"""Helpers for parsing bounty amounts out of free text."""

from __future__ import annotations

import re

# Matches things like "$1,340", "$50.00", "$1.5k", "1500 USD".
_DOLLAR_RE = re.compile(
    r"""
    (?:USD\s*)?              # optional leading USD
    \$\s?                    # dollar sign
    (\d{1,3}(?:,\d{3})+|\d+) # 1,340 or 1340
    (?:\.(\d{1,2}))?         # optional cents
    \s?(k|K)?                # optional thousands suffix
    """,
    re.VERBOSE,
)

_USD_SUFFIX_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s?(?:USD|usd)\b"
)


def parse_amounts(text: str) -> list[float]:
    """Return every dollar amount found in ``text`` (in USD)."""

    if not text:
        return []

    amounts: list[float] = []
    for m in _DOLLAR_RE.finditer(text):
        whole = m.group(1).replace(",", "")
        cents = m.group(2)
        value = float(whole)
        if cents:
            value += float(f"0.{cents}")
        if m.group(3):  # k / K suffix
            value *= 1000
        amounts.append(value)

    for m in _USD_SUFFIX_RE.finditer(text):
        amounts.append(float(m.group(1).replace(",", "")))

    return amounts


def best_amount(text: str) -> float:
    """Return the most likely bounty amount from ``text``.

    Heuristic: the largest amount mentioned. Bounty bots (BountyHub, Algora)
    report the running *total* as the largest figure, which is what a hunter
    ultimately cares about.
    """

    amounts = parse_amounts(text)
    return max(amounts) if amounts else 0.0
