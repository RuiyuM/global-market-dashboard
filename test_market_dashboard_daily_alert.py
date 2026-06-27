#!/usr/bin/env python3
"""Tests for the daily cross-market move alert."""

from __future__ import annotations

import math
from datetime import date, timedelta

from market_dashboard import SeriesSpec
from market_dashboard import build_daily_move_alert
from market_dashboard import render_html


def ohlc(day: date, close: float) -> dict[str, object]:
    return {"date": day, "open": close, "high": close, "low": close, "close": close}


def pct_rows(moves: list[float]) -> list[dict[str, object]]:
    start = date(2026, 5, 20)
    close = 100.0
    rows = [ohlc(start, close)]
    for index, move in enumerate(moves, start=1):
        close *= math.exp(move / 100)
        rows.append(ohlc(start + timedelta(days=index), close))
    return rows


def bp_rows(moves: list[float]) -> list[dict[str, object]]:
    start = date(2026, 5, 20)
    close = 4.0
    rows = [ohlc(start, close)]
    for index, move in enumerate(moves, start=1):
        close += move / 100
        rows.append(ohlc(start + timedelta(days=index), close))
    return rows


def spec(key: str, label: str, asset_class: str) -> SeriesSpec:
    return SeriesSpec(key, label, asset_class, "test", key, f"{key}.csv")


def test_daily_move_alert_always_shows_bond_and_fx_and_adds_equity_only_when_triggered() -> None:
    specs = {
        "US_EQUITY": spec("US_EQUITY", "标普500", "equity"),
        "US_10Y": spec("US_10Y", "美国10年国债", "bond"),
        "JPYCNY": spec("JPYCNY", "日元/人民币", "fx"),
    }
    series = {
        "US_EQUITY": pct_rows([0.1] * 24 + [0.8, 0.9, 1.0, 1.1, 1.2, 3.0]),
        "US_10Y": bp_rows([1.0] * 30),
        "JPYCNY": pct_rows([0.1] * 30),
    }

    alert = build_daily_move_alert(series, specs)

    assert alert["threshold_top_pct"] == 20.0
    assert [item["group"] for item in alert["items"]] == ["债券", "汇率", "股指"]
    assert alert["items"][0]["key"] == "US_10Y"
    assert alert["items"][1]["key"] == "JPYCNY"
    assert alert["items"][2]["key"] == "US_EQUITY"
    assert alert["items"][0]["warning"] is False
    assert alert["items"][1]["warning"] is False
    assert alert["items"][2]["warning"] is True
    assert alert["shown_count"] == 3


def test_daily_move_alert_omits_equity_when_today_is_not_top_20_percent() -> None:
    specs = {
        "US_EQUITY": spec("US_EQUITY", "标普500", "equity"),
        "US_10Y": spec("US_10Y", "美国10年国债", "bond"),
        "JPYCNY": spec("JPYCNY", "日元/人民币", "fx"),
    }
    series = {
        "US_EQUITY": pct_rows([1.0] * 30),
        "US_10Y": bp_rows([1.0] * 30),
        "JPYCNY": pct_rows([0.1] * 30),
    }

    alert = build_daily_move_alert(series, specs)

    assert [item["group"] for item in alert["items"]] == ["债券", "汇率"]
    assert alert["shown_count"] == 2
    assert all(item["warning"] is False for item in alert["items"])


def test_daily_alert_renders_before_volatility_ranking_with_fixed_and_conditional_items() -> None:
    html = render_html(
        {
            "countries": [],
            "daily_move_alert": {
                "window": "30D",
                "threshold_top_pct": 20.0,
                "shown_count": 3,
                "items": [
                    {
                        "key": "US_10Y",
                        "country": "美国",
                        "group": "债券",
                        "label": "美国10年国债",
                        "unit": "bp",
                        "move": 1.0,
                        "abs_move": 1.0,
                        "direction": "收益率跳升",
                        "rank": 30,
                        "sample_count": 30,
                        "top_pct": 100.0,
                        "warning": False,
                        "display_policy": "固定显示",
                        "latest_date": "2026-06-26",
                    },
                    {
                        "key": "JPYCNY",
                        "country": "日本",
                        "group": "汇率",
                        "label": "日元/人民币",
                        "unit": "pct",
                        "move": -0.2,
                        "abs_move": 0.2,
                        "direction": "下跌",
                        "rank": 10,
                        "sample_count": 30,
                        "top_pct": 33.3333333333,
                        "warning": False,
                        "display_policy": "固定显示",
                        "latest_date": "2026-06-26",
                    },
                    {
                        "key": "US_EQUITY",
                        "country": "美国",
                        "group": "股指",
                        "label": "标普500",
                        "unit": "pct",
                        "move": 3.0,
                        "abs_move": 3.0,
                        "direction": "上涨",
                        "rank": 1,
                        "sample_count": 30,
                        "top_pct": 3.3333333333,
                        "warning": True,
                        "display_policy": "触发显示",
                        "latest_date": "2026-06-26",
                    },
                ],
            },
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert html.find("每日异动") < html.find("波动率排名")
    assert html.count('class="daily-alert-card warning"') == 1
    assert html.count('class="daily-alert-card watch"') == 2
    assert "30D 日变化排名" in html
    assert "债券和汇率固定显示" in html
    assert "前 3.3%" in html
    assert 'class="daily-alert-card warning"' in html
    assert 'data-ohlc-key="US_10Y"' in html
    assert 'role="button"' in html
    assert 'tabindex="0"' in html
    assert '点击查看日线 OHLC' in html
    assert 'document.querySelectorAll(".daily-alert-card[data-ohlc-key]")' in html
