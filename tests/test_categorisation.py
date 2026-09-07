"""
Tests for merchant-substring categorisation rules.
"""

from categorisation.rules import categorise, load_rules


def test_known_merchants_match_expected_categories():
    rules = load_rules()
    assert categorise("TESCO STORES 1234 BELFAST", rules) == "groceries"
    assert categorise("NETFLIX.COM", rules) == "subscriptions"
    assert categorise("DELIVEROO*ORDER 88213", rules) == "dining_out"
    assert categorise("POWER NI ONLINE PAYMENT", rules) == "utilities"


def test_matching_is_case_insensitive():
    rules = load_rules()
    assert categorise("tesco stores belfast", rules) == "groceries"
    assert categorise("Costa Coffee", rules) == "dining_out"


def test_unmatched_description_returns_none():
    rules = load_rules()
    assert categorise("SOME RANDOM MERCHANT XYZ 999", rules) is None


def test_first_matching_rule_wins_when_rules_could_overlap():
    # "uber" appears in transport; make sure a transport-tagged rule higher
    # in the file takes precedence over anything appearing later that
    # might also match the same substring.
    rules = load_rules()
    assert categorise("UBER *TRIP HELP.UBER.COM", rules) == "transport"
