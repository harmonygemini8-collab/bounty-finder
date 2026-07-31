from datetime import datetime, timedelta, timezone

from bounty_finder.models import Bounty
from bounty_finder.scoring import ScoreConfig, ScoreWeights, rank, score_bounty


def _bounty(**kw) -> Bounty:
    base = dict(
        source="github", repo="o/r", number=1, title="t", url="u", amount_usd=100.0,
        updated_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return Bounty(**base)


def test_higher_amount_scores_higher():
    cfg = ScoreConfig()
    low = score_bounty(_bounty(amount_usd=50), cfg).score
    high = score_bounty(_bounty(amount_usd=800), cfg).score
    assert high > low


def test_assignee_reduces_competition_score():
    cfg = ScoreConfig()
    open_issue = score_bounty(_bounty(), cfg)
    taken = score_bounty(_bounty(assignees=["someone"]), cfg)
    assert open_issue.score_breakdown["competition"] > taken.score_breakdown["competition"]


def test_good_first_issue_more_tractable_than_epic():
    cfg = ScoreConfig()
    easy = score_bounty(_bounty(labels=["good first issue"]), cfg)
    hard = score_bounty(_bounty(labels=["epic"]), cfg)
    assert easy.score_breakdown["tractability"] > hard.score_breakdown["tractability"]


def test_stale_issue_lower_activity():
    cfg = ScoreConfig()
    fresh = score_bounty(_bounty(updated_at=datetime.now(timezone.utc)), cfg)
    old = score_bounty(
        _bounty(updated_at=datetime.now(timezone.utc) - timedelta(days=400)), cfg
    )
    assert fresh.score_breakdown["activity"] > old.score_breakdown["activity"]


def test_stack_match_prefers_language():
    cfg = ScoreConfig(preferred_languages=["Python"])
    match = score_bounty(_bounty(language="Python"), cfg)
    miss = score_bounty(_bounty(language="Rust"), cfg)
    assert match.score_breakdown["stack"] > miss.score_breakdown["stack"]


def test_rank_orders_by_score():
    cfg = ScoreConfig()
    items = [_bounty(number=1, amount_usd=10), _bounty(number=2, amount_usd=900)]
    ranked = rank(items, cfg)
    assert ranked[0].number == 2


def test_custom_weights_apply():
    cfg = ScoreConfig(weights=ScoreWeights(reward=1.0, tractability=0, competition=0,
                                           activity=0, stack=0))
    b = score_bounty(_bounty(amount_usd=1000), cfg)
    # With all weight on reward and amount at the cap, score should be ~100.
    assert b.score > 95
