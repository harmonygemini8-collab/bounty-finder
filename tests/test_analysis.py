from datetime import datetime, timezone

from bounty_finder.analysis import DeepAnalyzer, _detect_platforms
from bounty_finder.models import Bounty


class FakeGH:
    """Stub GitHubSource returning canned data for deterministic tests."""

    def __init__(self, repo=None, comments=None, prs=None):
        self._repo = repo or {}
        self._comments = comments or []
        self._prs = prs or []

    def repo_stats(self, repo):
        return self._repo

    def issue_comments(self, repo, number, max_comments=100):
        return self._comments

    def linked_prs(self, repo, number):
        return self._prs


def _bounty(**kw):
    base = dict(source="github", repo="acme/widget", number=1, title="Fix bug",
                url="u", amount_usd=200.0, body="Steps to reproduce: ...")
    base.update(kw)
    return Bounty(**base)


def test_detect_platforms():
    assert "Algora" in _detect_platforms("see https://algora.io/bounty/x")
    assert "BountyHub" in _detect_platforms("bountyhub.dev/bounty/y")
    assert _detect_platforms("no links here") == []


def test_merged_pr_forces_avoid():
    gh = FakeGH(
        repo={"stars": 900, "pushed_at": datetime.now(timezone.utc)},
        prs=[{"number": 5, "state": "closed", "merged": True, "author": "bob"}],
    )
    a = DeepAnalyzer(gh).analyze(_bounty())
    assert a.verdict == "AVOID"
    assert a.openness == 0.0
    assert any("MERGED" in f for f in a.red_flags)


def test_low_legitimacy_farm_repo_avoid():
    gh = FakeGH(repo={"stars": 3, "pushed_at": datetime.now(timezone.utc)})
    b = _bounty(repo="someone/bounty-plaza", body="win rewards")
    a = DeepAnalyzer(gh).analyze(b)
    assert a.verdict == "AVOID"
    assert a.legitimacy < 0.4


def test_open_legit_issue_recommend():
    gh = FakeGH(
        repo={"stars": 1500, "pushed_at": datetime.now(timezone.utc),
              "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc)},
        comments=[{"user": {"login": "maint"}, "author_association": "OWNER",
                   "body": "thanks, PRs welcome"}],
        prs=[],
    )
    b = _bounty(
        amount_usd=500,
        labels=["bug"],
        body="Acceptance criteria: it should not crash. Steps to reproduce: run x.",
    )
    b.body += " https://algora.io/bounty/abc"
    a = DeepAnalyzer(gh).analyze(b)
    assert a.verdict == "RECOMMEND"
    assert "Algora" in a.platforms
    assert a.worth_score > 55


def test_assignee_reduces_openness():
    gh = FakeGH(repo={"stars": 800, "pushed_at": datetime.now(timezone.utc)})
    taken = DeepAnalyzer(gh).analyze(_bounty(assignees=["someone"]))
    free = DeepAnalyzer(gh).analyze(_bounty())
    assert free.openness > taken.openness


def test_claim_comments_reduce_openness():
    claims = [{"user": {"login": f"u{i}"}, "body": "I'd like to work on this"} for i in range(3)]
    gh = FakeGH(repo={"stars": 800, "pushed_at": datetime.now(timezone.utc)}, comments=claims)
    a = DeepAnalyzer(gh).analyze(_bounty())
    assert a.signals["claimants"] == 3
    assert a.openness < 1.0
