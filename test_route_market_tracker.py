from datetime import date
from math import log

import pytest

from route_market_tracker import build_route_market_tracker


def rows(quotes):
    return [{"date": day, "close": value} for day, value in quotes]


def fx_series(days):
    quotes = {"USDCNY": 7.0, "JPYCNY": 0.045, "USDJPY": 150.0, "EURCNY": 7.8,
              "EURUSD": 1.1, "RUBCNY": 0.08, "USDRUB": 95.0}
    return {
        key: rows((day, quote * (1 + (index + 1) / 100 * offset)) for offset, day in enumerate(days))
        for index, (key, quote) in enumerate(quotes.items())
    }


def route_for(snapshot, group, frequency, destination, signal=None):
    view = next(view for view in snapshot["groups"] if view["id"] == group)
    window = next(window for window in view[frequency] if signal in (None, window["signal_date"]))
    return next(route for route in window["routes"] if route["destination"] == destination)


def test_all_18_routes_are_selectable_and_scores_keep_their_signs_and_directions():
    data = fx_series(["2026-11-19", "2026-11-20", "2026-11-23"])
    # Germany has a missing direct leg on the current cutoff date.
    data["EURUSD"].pop(1)
    view = build_route_market_tracker(data, cutoff_date=date(2026, 11, 20), as_of_date=date(2026, 11, 23))
    assert sum(len(group["routes"]) for group in view["groups"]) == 18
    groups = {group["id"]: group for group in view["groups"]}
    assert groups["DE"]["daily"] == []
    assert groups["JP"]["daily"][0]["signal_date"] == "2026-11-20"
    routes = {route["id"]: route for route in groups["JP"]["daily"][0]["routes"]}
    selected = routes["US-CN-JP"]
    assert len(routes) == 6
    assert selected["label"] == "美→中→日"
    assert selected["score"] == pytest.approx(100 * (log(1.01) - log(1.02)))
    assert selected["direct"] == pytest.approx(100 * log(1.03))
    assert selected["residual"] == pytest.approx(selected["score"] - selected["direct"])
    assert routes["JP-CN-US"]["score"] == pytest.approx(-selected["score"])


def test_weekly_pairs_are_adjacent_completed_weeks_and_do_not_use_future_quotes():
    series = fx_series(["2026-10-30", "2026-11-03", "2026-11-06", "2026-11-20", "2026-11-26", "2026-11-27"])
    before = build_route_market_tracker(series, cutoff_date=date(2026, 11, 26), as_of_date=date(2026, 11, 26))
    complete = build_route_market_tracker(series, cutoff_date=date(2026, 11, 27), as_of_date=date(2026, 11, 27))
    assert [(w["base_date"], w["signal_date"]) for w in before["groups"][0]["weekly"]] == [
        ("2026-10-30", "2026-11-06"),
    ]
    assert [(w["base_date"], w["signal_date"]) for w in complete["groups"][0]["weekly"]] == [
        ("2026-11-20", "2026-11-27"),
        ("2026-10-30", "2026-11-06"),
    ]


def test_bond_then_stock_require_strictly_later_dates_and_frozen_tenors():
    series = fx_series(["2026-11-12", "2026-11-13"])
    # 3M has no signal-time observations. The 1Y/6M short basket established at the signal stays fixed.
    series["JP_3M"] = rows([("2026-11-17", 9.0)])
    series["JP_6M"] = rows([("2026-11-12", 1.0), ("2026-11-13", 1.1), ("2026-11-17", 1.4)])
    series["JP_1Y"] = rows([("2026-11-12", 1.2), ("2026-11-13", 1.2), ("2026-11-16", 1.3), ("2026-11-17", 1.5)])
    series["JP_2Y"] = rows([("2026-11-13", 1.6), ("2026-11-16", 1.5), ("2026-11-17", 1.5)])
    series["JP_10Y"] = rows([("2026-11-13", 2.1), ("2026-11-16", 2.0), ("2026-11-17", 1.9)])
    series["JP_EQUITY"] = rows([
        ("2026-11-13", 97), ("2026-11-17", 99), ("2026-11-18", 100), ("2026-11-19", 101),
        ("2026-11-20", 102), ("2026-11-23", 104), ("2026-11-24", 103), ("2026-11-25", 105),
    ])
    build = lambda day: build_route_market_tracker(series, cutoff_date=date(2026, 11, 13), as_of_date=day)
    pending = route_for(build(date(2026, 11, 16)), "JP", "daily", "JP")
    assert pending["bond"]["status"] == pending["equity"]["status"] == "pending"
    result = route_for(build(date(2026, 11, 20)), "JP", "daily", "JP")
    assert result["bond"]["base_date"] == "2026-11-13"
    assert result["bond"]["date"] == "2026-11-17"
    assert result["bond"]["groups"]["short"]["tenors"] == ["6M", "1Y"]
    assert result["bond"]["groups"]["short"]["change_bp"] == pytest.approx(30.0)
    assert result["equity"]["base_date"] == "2026-11-18"
    assert result["equity"]["horizons"]["1"]["return_pct"] == pytest.approx(1.0)
    assert result["equity"]["horizons"]["5"]["status"] == "pending"
    mature = route_for(build(date(2026, 11, 25)), "JP", "daily", "JP")
    assert mature["equity"]["horizons"]["5"]["date"] == "2026-11-25"
    assert mature["equity"]["horizons"]["5"]["return_pct"] == pytest.approx(5.0)


def test_russia_never_manufactures_a_short_end_or_mislabels_exhausted_future_data():
    data = fx_series(["2026-10-08", "2026-10-09"])
    data["RU_2Y"] = rows([("2026-10-09", 16.0), ("2026-10-12", 15.9)])
    data["RU_10Y"] = rows([("2026-10-09", 17.0), ("2026-10-12", 17.1)])
    data["RU_EQUITY"] = rows([("2026-10-13", 2000), ("2026-10-14", 1980), ("2026-11-13", 2200)])
    view = build_route_market_tracker(data, cutoff_date=date(2026, 10, 9), as_of_date=date(2026, 11, 20))
    route = route_for(view, "RU", "daily", "RU")
    assert route["bond"]["groups"]["short"] == {
        "status": "unavailable", "tenors": [], "base_yield": None, "yield": None, "change_bp": None,
    }
    assert route["bond"]["groups"]["mid"]["tenors"] == ["2Y"]
    assert route["bond"]["groups"]["long"]["tenors"] == ["10Y"]
    assert route["equity"]["horizons"]["1"]["return_pct"] == pytest.approx(-1.0)
    assert route["equity"]["horizons"]["5"]["status"] == "unavailable"


def test_a_short_only_curve_cannot_start_an_equity_outcome():
    series = fx_series(["2026-11-12", "2026-11-13"])
    series["JP_1Y"] = rows([("2026-11-13", 1.0), ("2026-11-16", 1.2)])
    series["JP_EQUITY"] = rows([("2026-11-17", 100), ("2026-11-18", 101)])
    tracker = build_route_market_tracker(series, cutoff_date=date(2026, 11, 13), as_of_date=date(2026, 11, 20))
    route = route_for(tracker, "JP", "daily", "JP")
    assert route["bond"]["status"] == "unavailable"
    assert route["equity"]["base_date"] is None
    assert route["equity"]["horizons"]["1"]["status"] == "unavailable"
