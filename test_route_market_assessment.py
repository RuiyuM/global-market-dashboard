import pytest

from route_market_assessment import assess_route_market, attach_route_market_assessments


def market(*, mid=-2, long=-3, one=-0.25, five=-1.25, destination="US"):
    return {
        "destination": destination,
        "bond": {"status": "available", "groups": {
            "mid": {"status": "available", "change_bp": mid},
            "long": {"status": "available", "change_bp": long},
        }},
        "equity": {"status": "available", "label": "当地股指", "horizons": {
            "1": {"status": "available", "return_pct": one},
            "5": {"status": "available", "return_pct": five},
        }},
    }


def japan_flow(short, long, equity):
    return {"status": "published", "short_net": short, "long_net": long, "equity_net": equity,
            "week_start": "2026-11-08", "week_end": "2026-11-14"}


@pytest.mark.parametrize(("short", "long", "equity", "code"), [
    (1618, 6501, -2241, "debt"),
    (-15132, 13709, -1023, "neither"),
    (8747, 14817, 11293, "both"),
    (-11665, 462, 11822, "equity"),
    (20, -20, 0, "neither"),
])
def test_published_japan_data_classifies_net_investments(short, long, equity, code):
    route = market(one=1, five=-1, destination="JP")
    route["flow"] = japan_flow(short, long, equity)
    result = assess_route_market(route)
    assert result["kind"] == "official" and result["code"] == code
    assert "2026-11-08 至 2026-11-14" in [datum["value"] for datum in result["details"]]
    assert "国债和其他债券" in result["explanation"]
    if code == "debt":
        assert "+8,119 亿日元" in result["details"][0]["value"]
        assert "-2,241 亿日元" == result["details"][1]["value"]


@pytest.mark.parametrize(("mid", "long", "one", "five", "expected"), [
    (-1, -1, -0.2, -1, "debt"),
    (-0.99999999999, -1, -0.2, -1, "debt"),
    (2.6, 1.15, 0.2, 1, "equity"),
    (-4, -2, 0.2, 1, "both"),
    (5, 2, -0.2, -1, "neither"),
    (0.1, -0.1, 0.3, 0.8, "equity"),
    (0.1, -0.1, 0.0, 0.0, "neither"),
    (-4, 2, -0.2, -1, "mixed"),
    (-5, -0.5, 0.8, 1.2, "mixed"),
    (-4, -2, 0.2, -1, "mixed"),
    (-4, -2, -0.2, 1, "mixed"),
])
def test_price_judgment_checks_bond_agreement_and_stock_horizons(mid, long, one, five, expected):
    decision = assess_route_market(market(mid=mid, long=long, one=one, five=five))
    assert decision["kind"] == "price" and decision["code"] == expected
    assert "成交统计" in decision["explanation"]
    assert "后 5 日" in decision["details"][1]["value"]


def test_preliminary_price_result_uses_only_first_available_close():
    route = market()
    route["equity"]["horizons"]["5"] = {"status": "pending", "return_pct": None}
    decision = assess_route_market(route)
    assert decision["kind"] == "price" and decision["code"] == "debt"
    assert "目前仅按后 1 日初判" in decision["explanation"]
    assert "后 5 日待观察" in decision["details"][1]["value"]


def test_waiting_preserves_bond_evidence_and_expected_publication_date():
    route = market(destination="JP")
    route["equity"]["horizons"] = {"1": {"status": "pending", "return_pct": None}, "5": {"status": "pending"}}
    route["flow"] = {"status": "pending", "publication_date": "2026-11-27"}
    decision = assess_route_market(route)
    assert decision["kind"] == "waiting" and decision["code"] == "unknown"
    assert "净买入周报待发布" in decision["explanation"]
    assert route["flow"]["publication_date"] == "2026-11-27"
    assert "债价偏强" in decision["details"][0]["value"]
    assert decision["details"][1]["value"] == "等待后续股指收盘"


def test_unavailable_bond_data_never_implies_allocation_to_stocks():
    route = market(one=1, five=2)
    route["bond"] = {"status": "unavailable", "groups": {}}
    decision = assess_route_market(route)
    assert decision["kind"] == "waiting" and decision["code"] == "unknown"
    assert decision["details"][0]["value"] == "中长端数据不足"
    assert "+2%" in decision["details"][1]["value"]


def test_attach_covers_both_frequencies_and_retains_raw_evidence():
    one = market()
    two = market(destination="JP")
    two["flow"] = japan_flow(1, 1, 1)
    payload = {"groups": [{"daily": [{"routes": [one]}], "weekly": [{"routes": [two]}]}]}
    attach_route_market_assessments(payload)
    assert one["assessment"]["code"] == "debt"
    assert two["assessment"]["code"] == "both"
    assert two["flow"]["short_net"] == 1
