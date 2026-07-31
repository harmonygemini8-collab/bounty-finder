import json

from bounty_finder.models import Bounty
from bounty_finder.report import to_console, to_json, to_markdown


def _sample() -> list[Bounty]:
    b = Bounty(
        source="github", repo="microg/GmsCore", number=2843,
        title="[BOUNTY] WearOS Support", url="https://x/2843", amount_usd=1340.0,
        language="Java", labels=["bounty", "enhancement"],
    )
    b.score = 42.0
    b.score_breakdown = {"reward": 0.9, "tractability": 0.5, "competition": 0.8,
                          "activity": 1.0, "stack": 0.5}
    return [b]


def test_console_contains_repo():
    out = to_console(_sample(), top=5)
    assert "microg/GmsCore#2843" in out


def test_markdown_is_table():
    out = to_markdown(_sample(), top=5)
    assert out.startswith("# Bounty shortlist")
    assert "| # | Score |" in out


def test_json_roundtrips():
    out = to_json(_sample(), top=5)
    data = json.loads(out)
    assert data[0]["repo"] == "microg/GmsCore"
    assert data[0]["amount_usd"] == 1340.0


def test_empty_console():
    assert to_console([], top=5) == "No bounties found."
