"""Rank bounties by expected value for a human bounty hunter.

The score combines:
  * reward          - larger bounties are worth more
  * tractability     - "bug" / "good first issue" are more finishable than
                       open-ended "epic"/"enhancement" mega-features
  * low competition  - assignees and linked PRs mean someone is likely ahead
  * activity         - recently active issues are more likely to still pay out
  * stack match      - repos in the user's languages are cheaper to tackle

Every component is normalized to 0..1 and combined with configurable weights.
The output is intentionally a *decision aid*, not an autopilot: a human reads
the shortlist and chooses what to actually claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Bounty

# Label hints. Values are tractability multipliers (higher = easier to finish).
_TRACTABLE_LABELS = {
    "good first issue": 1.0,
    "good-first-issue": 1.0,
    "easy": 0.9,
    "bug": 0.8,
    "documentation": 0.85,
    "help wanted": 0.7,
}
_HARD_LABELS = {
    "epic": 0.15,
    "enhancement": 0.5,
    "feature": 0.5,
    "research": 0.2,
    "rfc": 0.2,
}


@dataclass
class ScoreWeights:
    reward: float = 0.40
    tractability: float = 0.25
    competition: float = 0.20
    activity: float = 0.10
    stack: float = 0.05
    # Reward normalization: bounty that maps to a "full" reward score.
    reward_cap_usd: float = 1000.0


@dataclass
class ScoreConfig:
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    preferred_languages: list[str] = field(default_factory=list)


def _reward_component(amount: float, cap: float) -> float:
    if amount <= 0:
        return 0.0
    # Diminishing returns above the cap via log scaling.
    return min(1.0, math.log1p(amount) / math.log1p(cap))


def _tractability_component(b: Bounty) -> float:
    labels = [label.lower() for label in b.labels]
    best = 0.5  # neutral default
    for label in labels:
        if label in _TRACTABLE_LABELS:
            best = max(best, _TRACTABLE_LABELS[label])
        if label in _HARD_LABELS:
            best = min(best, _HARD_LABELS[label])
    # A very long body often signals a sprawling, ambiguous task.
    if len(b.body) > 4000:
        best *= 0.8
    return best


def _competition_component(b: Bounty) -> float:
    """1.0 = wide open, 0.0 = crowded."""

    score = 1.0
    if b.assignees:
        score -= 0.6  # someone is officially on it
    score -= min(b.linked_pr_count, 5) * 0.15  # open PRs already attempting it
    # Lots of comments can mean lots of interested hunters.
    score -= min(b.comments, 40) / 40.0 * 0.2
    return max(0.0, score)


def _activity_component(b: Bounty) -> float:
    d = b.days_since_update
    if d is None:
        return 0.5
    if d <= 14:
        return 1.0
    if d >= 365:
        return 0.1
    return max(0.1, 1.0 - (d - 14) / (365 - 14))


def _stack_component(b: Bounty, preferred: list[str]) -> float:
    if not preferred:
        return 0.5  # neutral when the user has no preference
    if not b.language:
        return 0.4
    return 1.0 if b.language.lower() in {p.lower() for p in preferred} else 0.2


def score_bounty(b: Bounty, config: ScoreConfig) -> Bounty:
    w = config.weights
    parts = {
        "reward": _reward_component(b.amount_usd, w.reward_cap_usd),
        "tractability": _tractability_component(b),
        "competition": _competition_component(b),
        "activity": _activity_component(b),
        "stack": _stack_component(b, config.preferred_languages),
    }
    total = (
        parts["reward"] * w.reward
        + parts["tractability"] * w.tractability
        + parts["competition"] * w.competition
        + parts["activity"] * w.activity
        + parts["stack"] * w.stack
    )
    b.score = round(total * 100, 1)
    b.score_breakdown = {k: round(v, 3) for k, v in parts.items()}
    return b


def rank(bounties: list[Bounty], config: ScoreConfig) -> list[Bounty]:
    for b in bounties:
        score_bounty(b, config)
    return sorted(bounties, key=lambda b: b.score, reverse=True)
