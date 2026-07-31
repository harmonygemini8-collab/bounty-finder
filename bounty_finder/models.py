"""Core data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Bounty:
    """A single bounty-bearing issue collected from a source."""

    source: str  # e.g. "github", "algora"
    repo: str  # "owner/name"
    number: int
    title: str
    url: str
    amount_usd: float  # best-effort parsed bounty amount; 0.0 if unknown
    labels: list[str] = field(default_factory=list)
    language: Optional[str] = None  # primary repo language, when known
    state: str = "open"
    comments: int = 0
    reactions: int = 0
    assignees: list[str] = field(default_factory=list)
    linked_pr_count: int = 0  # open PRs that appear to address the issue
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    body: str = ""

    # Filled in by the scorer.
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def age_days(self) -> Optional[int]:
        if self.created_at is None:
            return None
        now = datetime.now(timezone.utc)
        return (now - self.created_at).days

    @property
    def days_since_update(self) -> Optional[int]:
        if self.updated_at is None:
            return None
        now = datetime.now(timezone.utc)
        return (now - self.updated_at).days
