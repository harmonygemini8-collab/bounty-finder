"""Command-line interface for bounty-finder."""

from __future__ import annotations

import argparse
import sys

from .analysis import analyze_many
from .report import (
    analyses_to_console,
    analyses_to_json,
    analyses_to_markdown,
    to_console,
    to_json,
    to_markdown,
)
from .scoring import ScoreConfig, ScoreWeights, rank
from .seeds import CURATED_LABELS, CURATED_ORGS
from .sources.algora import AlgoraSource
from .sources.github import DEFAULT_LABEL_QUERIES, GitHubSource


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bounty-finder",
        description=(
            "Discover and rank open bounty issues (read-only). "
            "Never comments, claims, or opens PRs on your behalf."
        ),
    )
    p.add_argument(
        "--min-amount", type=float, default=0.0,
        help="Only include bounties >= this USD amount (default: 0).",
    )
    p.add_argument(
        "--curated", action="store_true",
        help="Only search a seed list of high-star OSS projects known to pay "
             "bounties (skips the noisy generic label search).",
    )
    p.add_argument(
        "--min-stars", type=int, default=0,
        help="Drop bounties whose repo has fewer than this many stars.",
    )
    p.add_argument(
        "--max-age-days", type=int, default=0, metavar="DAYS",
        help="Only keep bounties opened within the last N days (0 = no limit). "
             "Great for catching FRESH bounties before the crowd piles on.",
    )
    p.add_argument(
        "--max-attempts", type=int, default=-1, metavar="N",
        help="With --deep: drop issues that already have more than N "
             "claimants/attempt PRs (e.g. 0 = only untouched bounties).",
    )
    p.add_argument(
        "--sort", choices=["worth", "fresh"], default="worth",
        help="Order results by worth score (default) or by freshness (newest first).",
    )
    p.add_argument(
        "--lang", action="append", default=[], metavar="LANGUAGE",
        help="Preferred repo language; repeatable (e.g. --lang Python --lang Go).",
    )
    p.add_argument(
        "--label", action="append", default=[], metavar="LABELQUERY",
        help="Override label search queries (repeatable). "
             f"Defaults: {', '.join(DEFAULT_LABEL_QUERIES)}",
    )
    p.add_argument(
        "--qualifiers", default="",
        help='Extra GitHub search qualifiers, e.g. "language:Python -label:wontfix".',
    )
    p.add_argument(
        "--max-fetch", type=int, default=60,
        help="Max issues to fetch from GitHub search before ranking (default: 60).",
    )
    p.add_argument(
        "--top", type=int, default=15,
        help="How many ranked candidates to display (default: 15).",
    )
    p.add_argument(
        "--enrich", type=int, default=10, metavar="N",
        help="Refine amount + competition for the top N via extra API calls "
             "(default: 10; 0 to disable).",
    )
    p.add_argument(
        "--deep", type=int, default=0, metavar="N",
        help="Run DEEP analysis on the top N candidates (legitimacy, competition, "
             "finishability, maintainer responsiveness) and output verdicts "
             "instead of the plain ranking. Costs ~3 API calls per issue.",
    )
    p.add_argument(
        "--algora-org", default=None,
        help="Also query Algora bounties for this org (best-effort).",
    )
    p.add_argument(
        "--no-language", action="store_true",
        help="Skip repo language lookups (faster).",
    )
    p.add_argument(
        "--format", choices=["console", "markdown", "json"], default="console",
    )
    p.add_argument("--output", "-o", help="Write output to this file instead of stdout.")
    # Weight overrides.
    p.add_argument("--w-reward", type=float, default=None)
    p.add_argument("--w-tractability", type=float, default=None)
    p.add_argument("--w-competition", type=float, default=None)
    p.add_argument("--w-activity", type=float, default=None)
    p.add_argument("--w-stack", type=float, default=None)
    return p


def _weights(args) -> ScoreWeights:
    w = ScoreWeights()
    for name in ("reward", "tractability", "competition", "activity", "stack"):
        val = getattr(args, f"w_{name}")
        if val is not None:
            setattr(w, name, val)
    return w


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    gh = GitHubSource()
    if not gh.token:
        print(
            "warning: no GitHub token found (set GITHUB_TOKEN or run 'gh auth login'); "
            "you will hit a low unauthenticated rate limit.",
            file=sys.stderr,
        )

    if args.curated:
        bounties = gh.search_orgs(
            orgs=CURATED_ORGS,
            label_queries=args.label or CURATED_LABELS,
            max_results=args.max_fetch,
            fetch_language=True,  # need stars for high-star filtering
        )
    else:
        bounties = gh.search(
            label_queries=args.label or None,
            extra_qualifiers=args.qualifiers,
            max_results=args.max_fetch,
            fetch_language=not args.no_language,
        )

    if args.algora_org:
        bounties += AlgoraSource().search(org=args.algora_org)

    if args.min_stars > 0:
        bounties = [b for b in bounties if (b.stars or 0) >= args.min_stars]

    if args.max_age_days > 0:
        bounties = [
            b for b in bounties
            if b.age_days is not None and b.age_days <= args.max_age_days
        ]

    config = ScoreConfig(weights=_weights(args), preferred_languages=args.lang)
    ranked = rank(bounties, config)

    # Enrich the current top-N, then re-rank (amount/competition may change).
    if args.enrich > 0:
        for b in ranked[: args.enrich]:
            if b.source == "github":
                gh.enrich_amount_from_comments(b)
                gh.count_linked_prs(b)
        ranked = rank(ranked, config)

    if args.min_amount > 0:
        ranked = [b for b in ranked if b.amount_usd >= args.min_amount]

    if args.sort == "fresh":
        ranked.sort(
            key=lambda b: b.created_at.timestamp() if b.created_at else 0, reverse=True
        )

    if args.deep > 0:
        candidates = [b for b in ranked if b.source == "github"][: args.deep]
        analyses = analyze_many(gh, candidates)
        if args.max_attempts >= 0:
            analyses = [a for a in analyses if a.attempts <= args.max_attempts]
        if args.sort == "fresh":
            analyses.sort(
                key=lambda a: a.bounty.created_at.timestamp() if a.bounty.created_at else 0,
                reverse=True,
            )
        deep_renderers = {
            "console": analyses_to_console,
            "markdown": analyses_to_markdown,
            "json": analyses_to_json,
        }
        text = deep_renderers[args.format](analyses, args.top)
    else:
        if args.max_attempts >= 0:
            print(
                "note: --max-attempts requires --deep to count attempts; ignoring.",
                file=sys.stderr,
            )
        renderers = {"console": to_console, "markdown": to_markdown, "json": to_json}
        text = renderers[args.format](ranked, args.top)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"Wrote output to {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
