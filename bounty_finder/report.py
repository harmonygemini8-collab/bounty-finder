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


# --------------------------------------------------------------------------
# Deep-analysis rendering
# --------------------------------------------------------------------------
_VERDICT_ICON = {"RECOMMEND": "✅", "WATCH": "🟡", "AVOID": "⛔"}


def analyses_to_console(analyses, top: int) -> str:
    rows = analyses[:top]
    if not rows:
        return "No bounties to analyze."
    out = []
    for i, a in enumerate(rows, 1):
        b = a.bounty
        icon = _VERDICT_ICON.get(a.verdict, "")
        out.append(
            f"{i}. {icon} {a.verdict}  worth={a.worth_score:<5} {_fmt_amount(b.amount_usd)}  "
            f"{b.repo}#{b.number}"
        )
        out.append(f"   {b.title}")
        out.append(f"   {b.url}")
        out.append(
            f"   legit={a.legitimacy:.2f} open={a.openness:.2f} "
            f"finishable={a.finishability:.2f} maintainer={a.maintainer:.2f}"
        )
        for r in a.reasons:
            out.append(f"   + {r}")
        for f in a.red_flags:
            out.append(f"   - {f}")
        out.append("")
    return "\n".join(out).rstrip()


def analyses_to_markdown(analyses, top: int) -> str:
    rows = analyses[:top]
    out = [
        "# Bounty deep-analysis",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{len(rows)} analyzed (read-only; verify before claiming)._",
        "",
        "| # | Verdict | Worth | Amount | Legit | Open | Finish | Maint. | Issue |",
        "|--:|:--------|------:|-------:|------:|-----:|-------:|-------:|:------|",
    ]
    for i, a in enumerate(rows, 1):
        b = a.bounty
        icon = _VERDICT_ICON.get(a.verdict, "")
        out.append(
            f"| {i} | {icon} {a.verdict} | {a.worth_score} | {_fmt_amount(b.amount_usd)} | "
            f"{a.legitimacy:.2f} | {a.openness:.2f} | {a.finishability:.2f} | "
            f"{a.maintainer:.2f} | [{b.repo}#{b.number}]({b.url})<br>{_escape(b.title)} |"
        )
    out += ["", "## Details", ""]
    for i, a in enumerate(rows, 1):
        b = a.bounty
        icon = _VERDICT_ICON.get(a.verdict, "")
        platforms = ", ".join(a.platforms) if a.platforms else "none detected"
        out.append(f"### {i}. {icon} {a.verdict} — [{b.repo}#{b.number}]({b.url})")
        out.append("")
        out.append(f"**{_escape(b.title)}** · {_fmt_amount(b.amount_usd)} · platform: {platforms}")
        out.append("")
        if a.reasons:
            out.append("**Reasons to do it**")
            out += [f"- {r}" for r in a.reasons]
            out.append("")
        if a.red_flags:
            out.append("**Red flags / caveats**")
            out += [f"- {f}" for f in a.red_flags]
            out.append("")
    out += [
        "---",
        "",
        "**Reminder:** this is a decision aid. Read the issue yourself, confirm "
        "the approach with the maintainer, and only claim what you will deliver.",
    ]
    return "\n".join(out)


def analyses_to_json(analyses, top: int) -> str:
    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    payload = []
    for a in analyses[:top]:
        d = asdict(a)
        # Bounty is nested; asdict already expanded it.
        payload.append(d)
    return json.dumps(payload, default=_default, indent=2)
