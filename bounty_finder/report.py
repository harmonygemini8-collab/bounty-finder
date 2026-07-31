"""Render ranked bounties as a console table, markdown, or JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from .models import Bounty


def _fmt_amount(a: float) -> str:
    return f"${a:,.0f}" if a else "—"


def to_console(bounties: list[Bounty], top: int) -> str:
    rows = bounties[:top]
    if not rows:
        return "No bounties found."
    lines = []
    header = f"{'#':>2}  {'SCORE':>5}  {'AMOUNT':>8}  {'LANG':<12}  {'COMP':>4}  ISSUE"
    lines.append(header)
    lines.append("-" * max(len(header), 80))
    for i, b in enumerate(rows, 1):
        comp = b.score_breakdown.get("competition", 0)
        comp_flag = "open" if comp >= 0.7 else ("busy" if comp >= 0.3 else "HOT")
        title = (b.title[:48] + "…") if len(b.title) > 49 else b.title
        lines.append(
            f"{i:>2}  {b.score:>5.1f}  {_fmt_amount(b.amount_usd):>8}  "
            f"{(b.language or '?'):<12}  {comp_flag:>4}  {b.repo}#{b.number} {title}"
        )
        lines.append(f"      {b.url}")
    return "\n".join(lines)


def to_markdown(bounties: list[Bounty], top: int) -> str:
    rows = bounties[:top]
    out = [
        "# Bounty shortlist",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{len(rows)} candidates (read-only; claim manually)._",
        "",
        "| # | Score | Amount | Lang | Competition | Age (d) | Issue |",
        "|--:|------:|-------:|:-----|:------------|--------:|:------|",
    ]
    for i, b in enumerate(rows, 1):
        comp = b.score_breakdown.get("competition", 0)
        comp_flag = "🟢 open" if comp >= 0.7 else ("🟡 busy" if comp >= 0.3 else "🔴 crowded")
        age = b.age_days if b.age_days is not None else "?"
        out.append(
            f"| {i} | {b.score:.1f} | {_fmt_amount(b.amount_usd)} | "
            f"{b.language or '?'} | {comp_flag} | {age} | "
            f"[{b.repo}#{b.number}]({b.url})<br>{_escape(b.title)} |"
        )
    out += ["", "## Score breakdown", ""]
    for i, b in enumerate(rows, 1):
        bd = ", ".join(f"{k}={v}" for k, v in b.score_breakdown.items())
        out.append(f"{i}. **{b.repo}#{b.number}** ({b.score:.1f}) — {bd}")
    out += [
        "",
        "---",
        "",
        "**How to use this list:** review the top candidates, open the issue, "
        "and if it genuinely fits your skills, leave a *genuine* comment asking "
        "to be assigned and confirm the approach with the maintainer before "
        "coding. Do not mass-comment — that gets accounts banned and PRs "
        "rejected.",
    ]
    return "\n".join(out)


def to_json(bounties: list[Bounty], top: int) -> str:
    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    return json.dumps([asdict(b) for b in bounties[:top]], default=_default, indent=2)


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
