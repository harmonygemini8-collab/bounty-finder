"""Deep, per-issue analysis to decide which bounty is actually worth doing.

Where :mod:`scoring` gives a cheap first-pass ranking from search results, this
module pulls extra signals for a shortlist and produces a reasoned verdict:

    RECOMMEND  - legit, winnable, worth your time
    WATCH      - promising but has caveats (busy, unclear, slow maintainer)
    AVOID      - scam/farm, already solved, or someone is clearly ahead

Every verdict comes with human-readable ``reasons`` and ``red_flags`` so you
can sanity-check the machine, not blindly trust it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .models import Bounty
from .sources.github import GitHubSource

# Escrow-backed bounty platforms: a link to one of these is a strong signal the
# money is real and will actually be paid on merge.
_PLATFORM_PATTERNS = {
    "Algora": r"algora\.io",
    "BountyHub": r"bountyhub\.dev",
    "Polar": r"polar\.sh",
    "IssueHunt": r"issuehunt\.io",
    "Gitpay": r"gitpay\.me",
    "Boss.dev": r"\bboss\.dev\b",
}

# Repo-name hints for "bounty farm" aggregators (not real products to ship to).
_FARM_NAME_RE = re.compile(r"bounty|bounties|reward|airdrop|faucet|farm", re.I)

_CLAIM_RE = re.compile(
    r"\b(i(?:'| a)?m\s+(?:working|on it)|working on this|can i (?:be assigned|take|work)|"
    r"i(?:'| woul)d like to (?:work|take)|assign(?:ed)? to me|/attempt|i'll take)\b",
    re.I,
)
_ACCEPTANCE_RE = re.compile(
    r"acceptance criteria|steps to reproduce|expected behavior|- \[ \]|definition of done",
    re.I,
)


@dataclass
class Analysis:
    bounty: Bounty
    verdict: str = "WATCH"  # RECOMMEND / WATCH / AVOID
    worth_score: float = 0.0  # 0..100
    legitimacy: float = 0.0
    openness: float = 0.0  # 1 = wide open, 0 = crowded/taken
    finishability: float = 0.0
    maintainer: float = 0.0
    platforms: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)

    # raw signals kept for transparency / json output
    signals: dict = field(default_factory=dict)


def _detect_platforms(text: str) -> list[str]:
    found = []
    for name, pat in _PLATFORM_PATTERNS.items():
        if re.search(pat, text, re.I):
            found.append(name)
    return found


def _log_scale(value: float, cap: float) -> float:
    if value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(cap))


def _days_ago(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


class DeepAnalyzer:
    def __init__(self, gh: GitHubSource):
        self.gh = gh

    def analyze(self, bounty: Bounty) -> Analysis:
        a = Analysis(bounty=bounty)
        repo = self.gh.repo_stats(bounty.repo)
        comments = self.gh.issue_comments(bounty.repo, bounty.number)
        prs = self.gh.linked_prs(bounty.repo, bounty.number)

        text_blob = " ".join(
            [bounty.title, bounty.body] + [c.get("body") or "" for c in comments]
        )
        a.platforms = _detect_platforms(text_blob)

        self._legitimacy(a, repo)
        self._openness(a, comments, prs)
        self._finishability(a, repo)
        self._maintainer(a, repo, comments)
        self._verdict(a, repo, prs)
        return a

    # -- components ----------------------------------------------------------
    def _legitimacy(self, a: Analysis, repo: dict) -> None:
        b = a.bounty
        score = 0.3
        if a.platforms:
            score += 0.4
            a.reasons.append(f"Escrowed bounty platform detected: {', '.join(a.platforms)}")
        else:
            a.red_flags.append("No escrow platform link found — payment relies on trust")

        stars = repo.get("stars", 0)
        score += _log_scale(stars, 2000) * 0.3
        if stars >= 500:
            a.reasons.append(f"Established repo ({stars:,}★)")
        elif stars < 20:
            a.red_flags.append(f"Very low repo popularity ({stars}★)")

        if repo.get("archived"):
            score -= 0.4
            a.red_flags.append("Repo is archived (won't accept PRs)")
        if repo.get("fork"):
            score -= 0.1
            a.red_flags.append("Repo is a fork, not an upstream project")

        owner_slug = b.repo.split("/")[0]
        repo_slug = b.repo.split("/")[-1]
        if _FARM_NAME_RE.search(repo_slug) or _FARM_NAME_RE.search(owner_slug):
            if stars < 100:
                score -= 0.35
                a.red_flags.append("Looks like a 'bounty farm' aggregator repo, not a real product")

        created = repo.get("created_at")
        age = _days_ago(created)
        if age is not None and age < 30 and stars < 50:
            score -= 0.2
            a.red_flags.append(f"Repo created only {age}d ago with little traction")

        a.legitimacy = max(0.0, min(1.0, score))
        a.signals["stars"] = stars

    def _openness(self, a: Analysis, comments: list[dict], prs: list[dict]) -> None:
        b = a.bounty
        score = 1.0
        merged = [p for p in prs if p["merged"]]
        open_prs = [p for p in prs if p["state"] == "open" and not p["merged"]]

        if merged:
            score = 0.0
            a.red_flags.append(
                f"A linked PR (#{merged[0]['number']}) is already MERGED — likely solved"
            )
        if open_prs:
            score -= 0.5
            a.red_flags.append(
                f"{len(open_prs)} open PR(s) already attempting this "
                f"(e.g. #{open_prs[0]['number']} by {open_prs[0]['author'] or '?'})"
            )
        if b.assignees:
            score -= 0.4
            a.red_flags.append(f"Already assigned to {', '.join(b.assignees)}")

        claims = 0
        claimants = set()
        for c in comments:
            author = (c.get("user") or {}).get("login", "")
            if "bot" in author.lower():
                continue
            if _CLAIM_RE.search(c.get("body") or ""):
                claims += 1
                claimants.add(author)
        if claimants:
            score -= min(len(claimants), 5) * 0.12
            a.red_flags.append(f"{len(claimants)} people have publicly claimed/attempted it")

        a.openness = max(0.0, min(1.0, score))
        a.signals["open_prs"] = len(open_prs)
        a.signals["merged_prs"] = len(merged)
        a.signals["claimants"] = len(claimants)
        if a.openness >= 0.8 and not merged:
            a.reasons.append("Field looks open — no assignee, no competing PRs")

    def _finishability(self, a: Analysis, repo: dict) -> None:
        b = a.bounty
        labels = {label.lower() for label in b.labels}
        score = 0.5
        if labels & {"good first issue", "good-first-issue", "easy", "bug", "documentation"}:
            score += 0.25
            a.reasons.append("Scoped work (bug / good-first-issue / docs label)")
        if labels & {"epic", "research", "rfc"} or "enhancement" in labels and len(b.body) > 3000:
            score -= 0.25
            a.red_flags.append("Large / open-ended feature (epic / big enhancement)")
        if _ACCEPTANCE_RE.search(b.body or ""):
            score += 0.15
            a.reasons.append("Issue includes acceptance criteria / repro steps")
        else:
            a.red_flags.append("No clear acceptance criteria — scope is fuzzy")
        if len(b.body or "") > 6000:
            score -= 0.15
        a.finishability = max(0.0, min(1.0, score))

    def _maintainer(self, a: Analysis, repo: dict, comments: list[dict]) -> None:
        score = 0.4
        pushed = _days_ago(repo.get("pushed_at"))
        if pushed is not None:
            if pushed <= 14:
                score += 0.3
                a.reasons.append("Repo actively maintained (pushed within 2 weeks)")
            elif pushed >= 180:
                score -= 0.3
                a.red_flags.append(f"Repo looks stale (last push {pushed}d ago)")

        maintainer_here = any(
            (c.get("author_association") or "") in ("OWNER", "MEMBER", "COLLABORATOR")
            for c in comments
        )
        if maintainer_here:
            score += 0.3
            a.reasons.append("A maintainer is participating in the thread")
        else:
            a.red_flags.append("No maintainer has commented — approval/merge is uncertain")
        a.maintainer = max(0.0, min(1.0, score))

    def _verdict(self, a: Analysis, repo: dict, prs: list[dict]) -> None:
        b = a.bounty
        reward = _log_scale(b.amount_usd, 1000.0)
        worth = (
            reward * 0.30
            + a.legitimacy * 0.25
            + a.openness * 0.20
            + a.finishability * 0.15
            + a.maintainer * 0.10
        )
        a.worth_score = round(worth * 100, 1)

        if a.signals.get("merged_prs"):
            a.verdict = "AVOID"
        elif a.legitimacy < 0.4:
            a.verdict = "AVOID"
        elif a.openness < 0.3:
            a.verdict = "AVOID"
        elif a.worth_score >= 60 and a.legitimacy >= 0.55 and a.openness >= 0.6:
            a.verdict = "RECOMMEND"
        else:
            a.verdict = "WATCH"


def analyze_many(gh: GitHubSource, bounties: list[Bounty]) -> list[Analysis]:
    analyzer = DeepAnalyzer(gh)
    out = [analyzer.analyze(b) for b in bounties]
    return sorted(out, key=lambda x: x.worth_score, reverse=True)
