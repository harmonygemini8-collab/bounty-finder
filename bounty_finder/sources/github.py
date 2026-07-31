"""Discover bounty issues via the GitHub REST search API.

Read-only: this module only issues GET requests. It never comments, assigns,
or otherwise mutates anything on GitHub.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Optional

import requests

from ..models import Bounty
from ..parsing import best_amount

API = "https://api.github.com"

# Labels commonly used to mark bounties across the ecosystem.
DEFAULT_LABEL_QUERIES = [
    'label:bounty',
    'label:"💎 Bounty"',
    'label:"💰 bounty"',
    'label:"💵 Bounty"',
    'label:"Bounty"',
]

# Repos that are pure bug-bounty write-ups / disclosure logs rather than code
# bounties. They pollute results, so they are skipped by default.
_NOISE_REPO_KEYWORDS = ("bug-bounty", "bugbounty", "security-disclosure")


def _token() -> Optional[str]:
    """Find a GitHub token from the environment or the gh CLI."""

    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


class GitHubSource:
    def __init__(self, token: Optional[str] = None, session: Optional[requests.Session] = None):
        self.token = token or _token()
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/vnd.github+json"})
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    # -- low level -----------------------------------------------------------
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = path if path.startswith("http") else f"{API}{path}"
        for attempt in range(4):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
                wait = max(reset - time.time(), 1)
                if wait > 120 or attempt == 3:
                    resp.raise_for_status()
                time.sleep(wait + 1)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    # -- public --------------------------------------------------------------
    def search(
        self,
        label_queries: Optional[Iterable[str]] = None,
        extra_qualifiers: str = "",
        max_results: int = 60,
        fetch_language: bool = True,
    ) -> list[Bounty]:
        label_queries = list(label_queries or DEFAULT_LABEL_QUERIES)
        seen: dict[str, Bounty] = {}
        lang_cache: dict[str, Optional[str]] = {}

        for lq in label_queries:
            q = f"{lq} is:issue is:open {extra_qualifiers}".strip()
            page = 1
            while len(seen) < max_results:
                data = self._get(
                    "/search/issues",
                    {"q": q, "per_page": 50, "page": page, "sort": "updated"},
                )
                items = data.get("items", [])
                if not items:
                    break
                for it in items:
                    b = self._to_bounty(it)
                    if b is None:
                        continue
                    key = f"{b.repo}#{b.number}"
                    if key not in seen:
                        seen[key] = b
                    if len(seen) >= max_results:
                        break
                if len(items) < 50:
                    break
                page += 1

        bounties = list(seen.values())
        if fetch_language:
            for b in bounties:
                if b.repo not in lang_cache:
                    lang_cache[b.repo] = self._repo_language(b.repo)
                b.language = lang_cache[b.repo]
        return bounties

    # -- helpers -------------------------------------------------------------
    def _to_bounty(self, item: dict) -> Optional[Bounty]:
        repo_url = item.get("repository_url", "")
        repo = "/".join(repo_url.split("/")[-2:]) if repo_url else "?"
        if any(k in repo.lower() for k in _NOISE_REPO_KEYWORDS):
            return None
        labels = [lbl["name"] for lbl in item.get("labels", [])]
        body = item.get("body") or ""
        title = item.get("title") or ""
        amount = best_amount(" ".join([title, body, " ".join(labels)]))
        return Bounty(
            source="github",
            repo=repo,
            number=item["number"],
            title=title,
            url=item.get("html_url", ""),
            amount_usd=amount,
            labels=labels,
            state=item.get("state", "open"),
            comments=item.get("comments", 0),
            reactions=(item.get("reactions") or {}).get("total_count", 0),
            assignees=[a["login"] for a in item.get("assignees", [])],
            created_at=_dt(item.get("created_at")),
            updated_at=_dt(item.get("updated_at")),
            body=body,
        )

    def _repo_language(self, repo: str) -> Optional[str]:
        try:
            data = self._get(f"/repos/{repo}")
            return data.get("language")
        except requests.HTTPError:
            return None

    def enrich_amount_from_comments(self, bounty: Bounty, max_comments: int = 100) -> None:
        """Refine the bounty amount by scanning bot comments (BountyHub/Algora).

        Only call this for a small shortlist; it costs one request per issue.
        """

        try:
            comments = self._get(
                f"/repos/{bounty.repo}/issues/{bounty.number}/comments",
                {"per_page": max_comments},
            )
        except requests.HTTPError:
            return
        best = bounty.amount_usd
        for c in comments if isinstance(comments, list) else []:
            author = (c.get("user") or {}).get("login", "").lower()
            text = c.get("body") or ""
            if "bot" in author or "bounty" in author or "algora" in author:
                best = max(best, best_amount(text))
        bounty.amount_usd = best

    def count_linked_prs(self, bounty: Bounty) -> None:
        """Best-effort count of open PRs referencing the issue (competition signal)."""

        try:
            data = self._get(
                "/search/issues",
                {"q": f'repo:{bounty.repo} is:pr is:open {bounty.number} in:body'},
            )
            bounty.linked_pr_count = min(data.get("total_count", 0), 50)
        except requests.HTTPError:
            bounty.linked_pr_count = 0


def _dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
