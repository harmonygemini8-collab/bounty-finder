from bounty_finder.parsing import best_amount, parse_amounts


def test_parse_simple():
    assert parse_amounts("Bounty of $50.00 available") == [50.0]


def test_parse_thousands_separator():
    assert best_amount("[BOUNTY] WearOS Support [$1,340]") == 1340.0


def test_parse_k_suffix():
    assert best_amount("reward up to $1.5k") == 1500.0


def test_usd_suffix():
    assert best_amount("we offer 250 USD for this") == 250.0


def test_best_amount_takes_max():
    text = "starts at $50, now the total is $690"
    assert best_amount(text) == 690.0


def test_no_amount():
    assert best_amount("no money here") == 0.0
    assert parse_amounts("") == []
