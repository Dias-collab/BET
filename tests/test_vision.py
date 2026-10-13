from decimal import Decimal

from bet_agent.models import Coupon
from bet_agent.olimp import OlimpBrowser, _decimal_from_text, normalize_text
from bet_agent.vision import _extract_json


def test_extract_json_from_model_noise():
    result = _extract_json('result: {"home_team":"Италия","away_team":"Бельгия"}')
    assert result["away_team"] == "Бельгия"


def test_total_labels():
    coupon = Coupon("Брентфорд", "Челси", "total", "over 2.5", shown_odds=Decimal("1.47"))
    assert OlimpBrowser._selection_labels(coupon) == ("Тотал", "2.5", "Больше")


def test_both_teams_labels():
    coupon = Coupon("Италия", "Бельгия", "both_teams_to_score", "yes")
    assert OlimpBrowser._selection_labels(coupon) == ("Обе забьют", "Да")


def test_normalize_team_names_and_dashes():
    assert normalize_text("Англия —  Испания") == "англия - испания"


def test_odd_is_last_number_in_labeled_tab():
    assert _decimal_from_text("П1 3.71") == Decimal("3.71")
    assert _decimal_from_text("X2 1,30") == Decimal("1.30")


def test_result_aliases():
    assert OlimpBrowser._result_key("ничья") == "X"
    assert OlimpBrowser._result_key("away") == "П2"


def test_total_number_with_comma():
    assert OlimpBrowser._selection_number("over 2,5") == "2.5"


def test_handicap_parts_with_side_and_sign():
    coupon = Coupon("Бельгия", "Франция", "handicap", "home +1,0")
    assert OlimpBrowser._handicap_parts(coupon) == ("Бельгия", "+1.0")
    coupon = Coupon("Бельгия", "Франция", "handicap", "Ф2 -1.5")
    assert OlimpBrowser._handicap_parts(coupon) == ("Франция", "-1.5")

