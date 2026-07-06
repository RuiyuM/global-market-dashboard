#!/usr/bin/env python3
"""Tests for FX volatility ranking drill-down details."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from market_dashboard import build_flow_sections, build_fx_cross_details, render_fx_rank_detail, render_html, us_close_effective_date


def row(day: int, close: float) -> dict[str, object]:
    return {"date": date(2026, 6, day), "open": close, "high": close, "low": close, "close": close}


def dated(month: int, day: int, close: float) -> dict[str, object]:
    return {"date": date(2026, month, day), "open": close, "high": close, "low": close, "close": close}


def test_build_fx_cross_details_derives_russia_cny_usd_jpy_pairs() -> None:
    details = build_fx_cross_details(
        {
            "CNY_BASE": [row(23, 1.0), row(24, 1.0)],
            "USDCNY": [row(23, 7.0), row(24, 7.1)],
            "JPYCNY": [row(23, 0.050), row(24, 0.052)],
            "RUBCNY": [row(23, 0.100), row(24, 0.090)],
        }
    )

    rub_rows = details["RU"]["rows"]
    assert [item["pair"] for item in rub_rows] == ["CNY/RUB", "USD/RUB", "JPY/RUB"]
    assert [item["name"] for item in rub_rows] == ["人民币/俄罗斯卢布", "美元/俄罗斯卢布", "日元/俄罗斯卢布"]
    assert rub_rows[0]["latest"] == 1.0 / 0.09
    assert rub_rows[1]["latest"] == 7.1 / 0.09
    assert rub_rows[2]["latest"] == 0.052 / 0.09
    assert rub_rows[0]["change"] > 0
    assert rub_rows[0]["pct_change"] > 0


def test_build_flow_sections_includes_exact_period_date_range() -> None:
    sections = build_flow_sections(
        {
            "USDCNY": [row(24, 7.0), row(25, 7.1), row(26, 7.2)],
            "JPYCNY": [row(24, 0.050), row(25, 0.051), row(26, 0.052)],
            "USDJPY": [row(24, 140.0), row(25, 141.0), row(26, 142.0)],
        }
    )

    periods = {item["period"]: item for item in sections[0]["periods"]}

    assert periods["当日"]["date_range"] == "2026-06-25 → 2026-06-26"
    assert periods["上日"]["date_range"] == "2026-06-24 → 2026-06-25"


def test_us_close_effective_date_uses_new_york_time_and_skips_weekends() -> None:
    ny = ZoneInfo("America/New_York")

    assert us_close_effective_date(datetime(2026, 6, 29, 15, 59, tzinfo=ny)) == date(2026, 6, 26)
    assert us_close_effective_date(datetime(2026, 6, 29, 16, 0, tzinfo=ny)) == date(2026, 6, 29)
    assert us_close_effective_date(datetime(2026, 6, 27, 12, 0, tzinfo=ny)) == date(2026, 6, 26)
    assert us_close_effective_date(datetime(2026, 6, 28, 12, 0, tzinfo=ny)) == date(2026, 6, 26)
    assert us_close_effective_date(datetime(2026, 6, 29, 19, 59, tzinfo=timezone.utc)) == date(2026, 6, 26)
    assert us_close_effective_date(datetime(2026, 6, 29, 20, 0, tzinfo=timezone.utc)) == date(2026, 6, 29)


def test_us_close_effective_date_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        us_close_effective_date(datetime(2026, 6, 29, 16, 0))


def test_build_flow_sections_weekend_daily_periods_use_prior_trading_days() -> None:
    us_close_date = us_close_effective_date(datetime(2026, 6, 28, 12, 0, tzinfo=ZoneInfo("America/New_York")))
    sections = build_flow_sections(
        {
            "USDCNY": [row(24, 7.0), row(25, 7.1), row(26, 7.2), row(29, 7.3)],
            "JPYCNY": [row(24, 0.050), row(25, 0.051), row(26, 0.052), row(29, 0.053)],
            "USDJPY": [row(24, 140.0), row(25, 141.0), row(26, 142.0), row(29, 143.0)],
        },
        us_close_date=us_close_date,
    )

    periods = {item["period"]: item for item in sections[0]["periods"]}

    assert periods["当日"]["date_range"] == "2026-06-25 → 2026-06-26"
    assert periods["上日"]["date_range"] == "2026-06-24 → 2026-06-25"
    assert "2026-06-29" not in periods["当日"]["date_range"]


def test_build_flow_sections_uses_us_calendar_week_windows() -> None:
    rows_by_key = {
        "USDCNY": [
            row(22, 7.0),
            row(23, 7.1),
            row(24, 7.2),
            row(25, 7.3),
            row(26, 7.4),
            row(29, 7.5),
            row(30, 7.6),
        ],
        "JPYCNY": [
            row(22, 0.050),
            row(23, 0.051),
            row(24, 0.052),
            row(25, 0.053),
            row(26, 0.054),
            row(29, 0.055),
            row(30, 0.056),
        ],
        "USDJPY": [
            row(22, 140.0),
            row(23, 141.0),
            row(24, 142.0),
            row(25, 143.0),
            row(26, 144.0),
            row(29, 145.0),
            row(30, 146.0),
        ],
    }

    sections = build_flow_sections(rows_by_key, us_close_date=date(2026, 6, 30))
    periods = {item["period"]: item for item in sections[0]["periods"]}

    assert periods["当周"]["date_range"] == "2026-06-29 → 2026-07-03"
    assert periods["上周"]["date_range"] == "2026-06-22 → 2026-06-26"
    assert {item["base_date"] for item in periods["当周"]["changes"]} == {"2026-06-29"}
    assert {item["latest_date"] for item in periods["当周"]["changes"]} == {"2026-06-30"}
    assert {item["base_date"] for item in periods["上周"]["changes"]} == {"2026-06-22"}
    assert {item["latest_date"] for item in periods["上周"]["changes"]} == {"2026-06-26"}


def test_build_flow_sections_uses_us_calendar_month_windows() -> None:
    rows_by_key = {
        "USDCNY": [dated(5, 1, 6.9), dated(5, 29, 7.0), dated(6, 1, 7.1), dated(6, 30, 7.2)],
        "JPYCNY": [dated(5, 1, 0.049), dated(5, 29, 0.050), dated(6, 1, 0.051), dated(6, 30, 0.052)],
        "USDJPY": [dated(5, 1, 139.0), dated(5, 29, 140.0), dated(6, 1, 141.0), dated(6, 30, 142.0)],
    }

    sections = build_flow_sections(rows_by_key, us_close_date=date(2026, 6, 30))
    periods = {item["period"]: item for item in sections[0]["periods"]}

    assert periods["当月"]["date_range"] == "2026-06-01 → 2026-06-30"
    assert periods["上月"]["date_range"] == "2026-05-01 → 2026-05-31"
    assert {item["base_date"] for item in periods["当月"]["changes"]} == {"2026-06-01"}
    assert {item["latest_date"] for item in periods["当月"]["changes"]} == {"2026-06-30"}
    assert {item["base_date"] for item in periods["上月"]["changes"]} == {"2026-05-01"}
    assert {item["latest_date"] for item in periods["上月"]["changes"]} == {"2026-05-29"}


def test_build_flow_sections_current_month_first_day_uses_previous_close_as_base() -> None:
    rows_by_key = {
        "USDCNY": [dated(6, 30, 7.0), dated(7, 1, 7.1)],
        "JPYCNY": [dated(6, 30, 0.050), dated(7, 1, 0.051)],
        "USDJPY": [dated(6, 30, 140.0), dated(7, 1, 141.0)],
    }

    sections = build_flow_sections(rows_by_key, us_close_date=date(2026, 7, 1))
    periods = {item["period"]: item for item in sections[0]["periods"]}

    assert periods["当月"]["date_range"] == "2026-07-01 → 2026-07-31"
    assert {item["base_date"] for item in periods["当月"]["changes"]} == {"2026-06-30"}
    assert {item["latest_date"] for item in periods["当月"]["changes"]} == {"2026-07-01"}
    assert periods["当月"]["result"]["best_route"]


def test_build_flow_sections_current_week_first_day_uses_previous_close_as_base() -> None:
    rows_by_key = {
        "USDCNY": [dated(7, 3, 7.0), dated(7, 6, 7.1)],
        "JPYCNY": [dated(7, 3, 0.050), dated(7, 6, 0.051)],
        "USDJPY": [dated(7, 3, 140.0), dated(7, 6, 141.0)],
    }

    sections = build_flow_sections(rows_by_key, us_close_date=date(2026, 7, 6))
    periods = {item["period"]: item for item in sections[0]["periods"]}

    assert periods["当周"]["date_range"] == "2026-07-06 → 2026-07-10"
    assert {item["base_date"] for item in periods["当周"]["changes"]} == {"2026-07-03"}
    assert {item["latest_date"] for item in periods["当周"]["changes"]} == {"2026-07-06"}
    assert periods["当周"]["result"]["best_route"]


def test_render_flow_period_dates_omit_year_in_visible_label() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": build_flow_sections(
                {
                    "USDCNY": [row(25, 7.1), row(26, 7.2)],
                    "JPYCNY": [row(25, 0.051), row(26, 0.052)],
                    "USDJPY": [row(25, 141.0), row(26, 142.0)],
                }
            ),
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert "<small>06-25 → 06-26</small>" in html
    assert "<small>2026-06-25 → 2026-06-26</small>" not in html


def test_render_flow_period_dates_aligns_mixed_source_dates_to_common_close() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": build_flow_sections(
                {
                    "USDCNY": [row(25, 7.1), row(26, 7.2)],
                    "JPYCNY": [row(25, 0.051), row(26, 0.052), row(29, 0.053)],
                    "USDJPY": [row(25, 141.0), row(26, 142.0), row(29, 143.0)],
                },
                us_close_date=date(2026, 6, 29),
            ),
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-29T00:00:00",
        }
    )

    assert "<small>06-25 → 06-26</small>" in html
    assert "06-25/26" not in html
    assert "06-26/29" not in html


def test_render_flow_period_dates_clips_to_us_close_date() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": build_flow_sections(
                {
                    "USDCNY": [row(25, 7.1), row(26, 7.2), row(29, 7.3)],
                    "JPYCNY": [row(25, 0.051), row(26, 0.052), row(29, 0.053)],
                    "USDJPY": [row(25, 141.0), row(26, 142.0), row(29, 143.0)],
                },
                us_close_date=date(2026, 6, 26),
            ),
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-29T00:00:00",
        }
    )

    assert "<small>06-25 → 06-26</small>" in html
    assert "<small>06-26 → 06-29</small>" not in html
    assert "<small>06-25/26 → 06-26/29</small>" not in html


def test_render_flow_summary_uses_best_route_path_not_strength_ranking() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [
                {
                    "name": "中日美",
                    "periods": [
                        {
                            "period": "当日",
                            "date_range": "2026-06-25 → 2026-06-26",
                            "changes": [],
                            "missing": [],
                            "result": {
                                "best_route": {
                                    "x": "日",
                                    "y": "美",
                                    "z": "中",
                                    "label": "日通过美多兑换中",
                                    "score": 0.0389,
                                    "status": "成立",
                                },
                                "ranking": ["日", "中", "美"],
                                "routes": [
                                    {
                                        "x": "日",
                                        "y": "美",
                                        "z": "中",
                                        "label": "日通过美多兑换中",
                                        "score": 0.0389,
                                        "status": "成立",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-29T00:00:00",
        }
    )

    assert "路径：日 &gt; 美 &gt; 中" in html
    assert "强弱：日 &gt; 中 &gt; 美" not in html


def test_build_fx_cross_details_includes_7d_and_30d_moves() -> None:
    details = build_fx_cross_details(
        {
            "CNY_BASE": [dated(5, 25, 1.0), row(17, 1.0), row(24, 1.0)],
            "USDCNY": [dated(5, 25, 7.0), row(17, 7.0), row(24, 7.0)],
            "JPYCNY": [dated(5, 25, 0.050), row(17, 0.050), row(24, 0.050)],
            "RUBCNY": [dated(5, 25, 0.100), row(17, 0.095), row(24, 0.090)],
        }
    )

    cny_rub = details["RU"]["rows"][0]

    assert cny_rub["pct_change_7d"] > 0
    assert cny_rub["pct_change_30d"] > 0
    assert cny_rub["change_7d_dates"] == {"base_date": "2026-06-17", "latest_date": "2026-06-24"}
    assert cny_rub["change_30d_dates"] == {"base_date": "2026-05-25", "latest_date": "2026-06-24"}


def test_render_fx_rank_detail_contains_click_drilldown_table() -> None:
    details = {
        "RU": {
            "country": "俄罗斯",
            "rows": [
                {
                    "pair": "CNY/RUB",
                    "name": "人民币/俄罗斯卢布",
                    "latest": 11.4949,
                    "change": 0.3385,
                    "pct_change": 3.03,
                    "pct_change_7d": 4.42,
                    "pct_change_30d": 10.15,
                    "range_7d": {"low": 11.06, "high": 11.50},
                    "range_30d": {"low": 10.28, "high": 12.59},
                }
            ],
        }
    }

    html = render_fx_rank_detail("RU", details)

    assert 'data-fx-rank-detail="RU"' in html
    assert "CNY/RUB" in html
    assert "人民币/俄罗斯卢布" in html
    assert "+3.03%" in html
    assert "7D涨跌" in html
    assert "+4.42%" in html
    assert "30D涨跌" in html
    assert "+10.15%" in html
