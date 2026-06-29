#!/usr/bin/env python3
"""Tests for FX volatility ranking drill-down details."""

from __future__ import annotations

from datetime import date

from market_dashboard import build_flow_sections, build_fx_cross_details, render_fx_rank_detail, render_html


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
