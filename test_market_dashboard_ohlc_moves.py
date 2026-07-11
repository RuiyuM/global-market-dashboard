#!/usr/bin/env python3
"""Tests for OHLC daily percent-move payloads."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import market_dashboard
from market_dashboard import COUNTRY_BOND_TENORS
from market_dashboard import CHINA_BOND_SPECS
from market_dashboard import CSS
from market_dashboard import GERMANY_BOND_SPECS
from market_dashboard import JAPAN_BOND_SPECS
from market_dashboard import JS
from market_dashboard import KOREA_BOND_SPECS
from market_dashboard import WSCN_SPECS
from market_dashboard import SeriesSpec
from market_dashboard import build_second_order_monitor
from market_dashboard import recent_ohlc_rows
from market_dashboard import render_html


def ohlc(day: int, close: float) -> dict[str, object]:
    return {
        "date": date(2026, 6, day),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }


def test_recent_ohlc_rows_adds_percent_move_from_previous_close() -> None:
    rows = [ohlc(1, 100), ohlc(2, 110), ohlc(3, 99)]

    recent = recent_ohlc_rows(rows, limit=2)

    assert [row["date"] for row in recent] == ["2026-06-02", "2026-06-03"]
    assert recent[0]["prev_close"] == 100
    assert recent[0]["change_pct"] == 10.0
    assert recent[1]["prev_close"] == 110
    assert recent[1]["change_pct"] == -10.0


def test_move_chart_keeps_rotated_date_labels_inside_svg_viewbox() -> None:
    assert "bottom: 84" in JS
    assert 'const dateLabelY = height - 30;' in JS
    assert 'rotate(-48 ${xx} ${dateLabelY})' in JS


def test_ohlc_panel_exposes_comparison_selector() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [
                {
                    "key": "US_10Y",
                    "country": "美国",
                    "group": "债券",
                    "label": "美国10年国债",
                    "unit": "pct",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [],
                }
            ],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert '<label class="ohlc-compare"' in html
    assert 'id="ohlc-compare-select"' in html
    assert '<option value="">无比较</option>' in html


def test_ohlc_panel_exposes_country_and_asset_picker() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [
                {
                    "key": "US_10Y",
                    "country": "美国",
                    "code": "US",
                    "group": "债券",
                    "label": "美国10年国债",
                    "unit": "bp",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [{"date": "2026-06-25", "open": 4, "high": 4, "low": 4, "close": 4}],
                }
            ],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert 'class="ohlc-picker"' in html
    assert 'id="ohlc-country-select"' in html
    assert 'id="ohlc-asset-select"' in html
    assert "const ohlcPickerGroups =" in JS
    assert "const syncOhlcPickers =" in JS
    assert "ohlcCountrySelect?.addEventListener" in JS
    assert "ohlcAssetSelect?.addEventListener" in JS


def test_ohlc_javascript_supports_comparison_normalization() -> None:
    assert 'const compareSelect = document.getElementById("ohlc-compare-select");' in JS
    assert "const comparisonFor = (primaryItem) =>" in JS
    assert "const normalizeOhlcSeries = (bars) =>" in JS
    assert "range_min" in JS
    assert "(number - rangeMin) / spread * 100" in JS
    assert "区间归一化 0-100" in JS


def test_move_chart_only_mentions_blue_compare_line_when_comparison_exists() -> None:
    assert "const moveCompareNote = compareItem ?" in JS
    assert "柱=主标的单日涨跌幅，蓝线=比较标的" not in JS


def test_ohlc_zoom_buttons_use_requested_direction() -> None:
    assert 'zoomInButton?.addEventListener("click", () => zoomChart(1));' in JS
    assert 'zoomOutButton?.addEventListener("click", () => zoomChart(-1));' in JS


def test_ohlc_supports_custom_range_and_exact_date_controls() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )
    assert 'id="ohlc-start-date"' in html
    assert 'id="ohlc-align-spread"' in html
    assert 'class="segmented ohlc-mode-group"' in html
    assert html.index('data-mode="ohlc"') < html.index('data-mode="move"')
    assert '<button type="button" class="ohlc-mode active" data-mode="ohlc">K线</button>' in html
    assert '<button type="button" class="ohlc-mode" data-mode="move">涨跌幅</button>' in html
    assert 'let chartMode = "ohlc";' in JS
    assert 'class="segmented ohlc-window-group"' in html
    assert 'class="chart-tools ohlc-chart-tools"' in html
    assert 'class="date-tools ohlc-date-tools"' in html
    assert '<label class="date-field ohlc-jump-field">快速查看 <input type="date" id="ohlc-jump-date"></label>' in html
    assert '<label>日期 <input type="date" id="ohlc-jump-date"></label>' not in html
    assert "@media (max-width: 640px)" in CSS
    assert ".ohlc-chart-tools { display: grid;" in CSS
    assert "#ohlc-range-label { grid-column: 1 / -1;" in CSS
    assert ".ohlc-jump-field," in CSS
    assert "const customRangeByKey = {};" in JS
    assert "const applyOhlcRange = () =>" in JS
    assert "const jumpToOhlcDate = () =>" in JS


def test_spread_calculator_is_separate_interactive_block() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [
                {
                    "key": "US_2Y",
                    "country": "美国",
                    "group": "债券",
                    "label": "美国2年国债",
                    "unit": "bp",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [{"date": "2026-06-25", "open": 4, "high": 4, "low": 4, "close": 4}],
                },
                {
                    "key": "US_10Y",
                    "country": "美国",
                    "group": "债券",
                    "label": "美国10年国债",
                    "unit": "bp",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [{"date": "2026-06-25", "open": 5, "high": 5, "low": 5, "close": 5}],
                },
            ],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert '<section class="panel spread-panel" id="spread-panel">' in html
    assert 'id="spread-country-select"' in html
    assert 'data-spread-window="1"' in html
    assert 'data-spread-window="7"' in html
    assert 'data-spread-window="30"' in html
    assert 'id="spread-start-date"' in html
    assert 'id="spread-exact-date"' in html
    assert 'id="spread-align-ohlc"' in html
    assert '<label>快速查看 <input type="date" id="spread-exact-date"></label>' in html
    assert '<label>日期 <input type="date" id="spread-exact-date"></label>' not in html
    assert 'id="spread-apply-range"' not in html
    assert 'id="spread-exact-button"' not in html
    assert ">查看日期</button>" not in html
    assert 'id="spread-tooltip"' in html
    assert 'id="spread-data"' in html
    assert "const buildSpreadRows = () =>" in JS
    assert "const renderSpread = () =>" in JS
    assert 'const spreadTooltip = document.getElementById("spread-tooltip");' in JS
    assert 'class="spread-hit"' in JS
    assert "spread-crosshair" in JS
    assert 'spreadStartInput?.addEventListener("change", setSpreadCustomMode);' in JS
    assert 'spreadExactDateInput?.addEventListener("change", setSpreadExactMode);' in JS
    assert "spread-positive-band" in JS
    assert "spread-negative-band" in JS
    assert "spread-long-line" in JS
    assert "spread-short-line" in JS


def test_spread_calculator_orders_long_and_short_by_selected_tenor() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [
                {
                    "key": "US_2Y",
                    "country": "美国",
                    "group": "债券",
                    "label": "美国2年国债",
                    "unit": "bp",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [{"date": "2026-06-25", "open": 4, "high": 4, "low": 4, "close": 4}],
                },
                {
                    "key": "US_10Y",
                    "country": "美国",
                    "group": "债券",
                    "label": "美国10年国债",
                    "unit": "bp",
                    "metrics": {},
                    "summary": {},
                    "ohlc": [{"date": "2026-06-25", "open": 5, "high": 5, "low": 5, "close": 5}],
                },
            ],
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    assert '"tenorMonths": 24' in html
    assert '"tenorMonths": 120' in html
    assert "const resolveSpreadLegs = () =>" in JS
    assert "firstMonths < secondMonths" in JS
    assert "longKey: secondKey" in JS
    assert "shortKey: firstKey" in JS


def test_ohlc_and_spread_ranges_can_be_aligned_bidirectionally() -> None:
    assert 'const alignOhlcToSpreadButton = document.getElementById("ohlc-align-spread");' in JS
    assert 'const alignSpreadToOhlcButton = document.getElementById("spread-align-ohlc");' in JS
    assert "const currentOhlcVisibleRange = () =>" in JS
    assert "const currentSpreadVisibleRange = () =>" in JS
    assert "const alignOhlcToSpread = () =>" in JS
    assert "const alignSpreadToOhlc = () =>" in JS
    assert 'alignOhlcToSpreadButton?.addEventListener("click", alignSpreadToOhlc);' in JS
    assert 'alignSpreadToOhlcButton?.addEventListener("click", alignOhlcToSpread);' in JS
    assert "customRangeByKey[key] = { start: range.start, end: range.end };" in JS
    assert "spreadStartInput.value = range.start;" in JS
    assert "spreadEndInput.value = range.end;" in JS
    assert "domainStart: start || selected[0]?.date || \"\"" in JS
    assert "renderSpreadChart(selection.rows, { domainStart: selection.domainStart, domainEnd: selection.domainEnd });" in JS
    assert "const domainStartMs = dateMs(domainStart);" in JS


def test_ohlc_and_spread_share_hover_date_crosshair() -> None:
    assert "let sharedHoverDate = null;" in JS
    assert "const setSharedHoverDate = (date) =>" in JS
    assert 'data-hover-date="${esc(bar.date)}"' in JS
    assert 'data-hover-date="${esc(row.date)}"' in JS
    assert "syncSharedCrosshairs();" in JS
    assert "setSharedHoverDate(bar.date);" in JS
    assert "setSharedHoverDate(row.date);" in JS
    assert "const crosshair = node.querySelector(\".candle-crosshair\");" in JS


def test_macro_indicators_feed_second_order_and_ohlc_picker() -> None:
    spec_keys = {spec.key for spec in market_dashboard.MACRO_SPECS}
    assert {"DXY", "VIX", "GOLD", "USOIL"} <= spec_keys

    specs = {spec.key: spec for spec in market_dashboard.MACRO_SPECS}
    series = {key: [ohlc(1, 100), ohlc(10, 105), ohlc(20, 110), ohlc(26, 108)] for key in spec_keys}
    rows = build_second_order_monitor(series, specs)

    macro_rows = [row for row in rows if row["country"] == "宏观指标"]
    assert [row["key"] for row in macro_rows] == ["DXY", "VIX", "GOLD", "USOIL"]
    assert all(row["group"] == "宏观" for row in macro_rows)
    assert all(row["unit"] == "pct" for row in macro_rows)

    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": macro_rows,
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )
    assert '<strong>宏观指标</strong>' in html
    assert 'class="country-toggle collapsed" data-country="宏观指标" aria-expanded="false"' in html
    assert '<span class="toggle-icon">▸</span><strong>宏观指标</strong>' in html
    macro_row_start = html.index('<tr class="derivative-row" data-country="宏观指标" data-ohlc-key="DXY"')
    macro_row_end = html.index(">", macro_row_start)
    assert " hidden" in html[macro_row_start:macro_row_end]
    assert 'data-country="宏观指标"' in html
    assert '"code": "MACRO"' in html
    assert '"country": "宏观指标"' in html


def test_expanded_wscn_bond_tenors_feed_second_order_and_spreads() -> None:
    spec_keys = {spec.key for spec in WSCN_SPECS}
    assert {
        "US_1M",
        "US_3M",
        "US_6M",
        "US_3Y",
        "US_5Y",
        "US_7Y",
        "US_30Y",
        "CN_3Y",
        "CN_5Y",
        "CN_7Y",
    } <= spec_keys
    assert {"US_20Y", "JP_30Y", "DE_30Y"}.isdisjoint(spec_keys)

    wanted_specs = {spec.key: spec for spec in WSCN_SPECS}
    wanted_specs.update({series_spec.key: series_spec for series_spec, _, _ in CHINA_BOND_SPECS})
    for key, label in [
        ("US_EQUITY", "标普500"),
        ("USDCNY", "美元/人民币"),
        ("CN_EQUITY", "上证综指"),
        ("CNY_BASE", "人民币基准"),
    ]:
        wanted_specs.setdefault(key, SeriesSpec(key, label, "test", "test", key, f"{key}.csv"))
    series = {
        key: [ohlc(1, 3.0), ohlc(10, 3.1), ohlc(20, 3.2)]
        for key in [
            "US_1M",
            "US_3M",
            "US_6M",
            "US_1Y",
            "US_2Y",
            "US_3Y",
            "US_5Y",
            "US_7Y",
            "US_10Y",
            "US_30Y",
            "CN_1M",
            "CN_3M",
            "CN_6M",
            "CN_1Y",
            "CN_2Y",
            "CN_3Y",
            "CN_5Y",
            "CN_7Y",
            "CN_10Y",
            "CN_30Y",
        ]
    }
    rows = build_second_order_monitor(series, wanted_specs)

    us_bonds = [row["key"] for row in rows if row["country"] == "美国" and row["group"] == "债券"]
    cn_bonds = [row["key"] for row in rows if row["country"] == "中国" and row["group"] == "债券"]
    assert us_bonds == ["US_1M", "US_3M", "US_6M", "US_1Y", "US_2Y", "US_3Y", "US_5Y", "US_7Y", "US_10Y", "US_30Y"]
    assert cn_bonds == ["CN_1M", "CN_3M", "CN_6M", "CN_1Y", "CN_2Y", "CN_3Y", "CN_5Y", "CN_7Y", "CN_10Y", "CN_30Y"]
    assert all(row["key"] != "US_20Y" for row in rows)

    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": rows,
            "fx_flows": [],
            "series_status": [],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )
    assert 'data-extra-bond-toggle="美国"' in html
    assert 'data-extra-bond-row="true"' in html
    assert '"tenor": "1M", "tenorMonths": 1, "key": "US_1M", "label": "美国1个月国债"' in html
    assert '"tenor": "30Y", "tenorMonths": 360, "key": "US_30Y", "label": "美国30年国债"' in html
    assert '"tenor": "7Y", "tenorMonths": 84, "key": "CN_7Y", "label": "中国7年国债"' in html
    assert '"tenor": "30Y", "tenorMonths": 360, "key": "CN_30Y", "label": "中国30年国债"' in html


def test_japan_extra_bond_tenors_use_server_safe_sources_not_stale_wscn() -> None:
    wscn_keys = {spec.key for spec in WSCN_SPECS}
    spec_by_key = {series_spec.key: series_spec for series_spec, _, _ in JAPAN_BOND_SPECS}

    assert {
        "JP_1M",
        "JP_3M",
        "JP_6M",
        "JP_3Y",
        "JP_5Y",
        "JP_7Y",
        "JP_30Y",
    } <= set(spec_by_key)
    assert {key: spec_by_key[key].source for key in ["JP_1M", "JP_3M", "JP_6M"]} == {
        "JP_1M": "investing+tradingeconomics",
        "JP_3M": "investing+tradingeconomics",
        "JP_6M": "investing+tradingeconomics",
    }
    assert {key: spec_by_key[key].source for key in ["JP_3Y", "JP_5Y", "JP_7Y", "JP_30Y"]} == {
        "JP_3Y": "mof+tradingeconomics",
        "JP_5Y": "mof+tradingeconomics",
        "JP_7Y": "mof+tradingeconomics",
        "JP_30Y": "mof+tradingeconomics",
    }
    assert {
        "JP_1M",
        "JP_3M",
        "JP_6M",
        "JP_3Y",
        "JP_5Y",
        "JP_7Y",
        "JP_30Y",
    }.isdisjoint(wscn_keys)
    assert COUNTRY_BOND_TENORS["JP"] == [
        ("1M", "JP_1M"),
        ("3M", "JP_3M"),
        ("6M", "JP_6M"),
        ("1Y", "JP_1Y"),
        ("2Y", "JP_2Y"),
        ("3Y", "JP_3Y"),
        ("5Y", "JP_5Y"),
        ("7Y", "JP_7Y"),
        ("10Y", "JP_10Y"),
        ("30Y", "JP_30Y"),
    ]


def test_japan_short_bills_merge_investing_history_with_tradingeconomics_latest(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec(
        "JP_1M",
        "日本1个月国债",
        "bond",
        "investing+tradingeconomics",
        "JP1MT=XX / GJGB1M",
        "JP_1M.csv",
        "JP1M_INVESTING_1D_ohlc.csv",
    )
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [(series_spec, "investing+tradingeconomics", "1M")])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "LOCAL_DATA", tmp_path / "empty-seed")
    monkeypatch.setattr(market_dashboard, "fetch_tradingeconomics_chart_rows", lambda slug, start, end: [])
    monkeypatch.setattr(market_dashboard, "fetch_investing_html", lambda spec, start, end: "<html></html>")
    monkeypatch.setattr(
        market_dashboard,
        "rows_from_investing_html",
        lambda html: [
            {"date": "2026-06-24", "timestamp": 1782259200, "open": 0.50, "high": 0.55, "low": 0.48, "close": 0.52},
            {"date": "2026-06-25", "timestamp": 1782345600, "open": 0.52, "high": 0.56, "low": 0.50, "close": 0.54},
        ],
    )
    monkeypatch.setattr(
        market_dashboard,
        "fetch_tradingeconomics_latest_row",
        lambda slug: {"date": "2026-06-26", "timestamp": 1782432000, "open": 0.55, "high": 0.57, "low": 0.54, "close": 0.56},
    )

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert records == [
        {
            "key": "JP_1M",
            "source": "investing+tradingeconomics",
            "symbol": "JP1MT=XX / GJGB1M",
            "status": "ok",
            "file": str(tmp_path / "JP_1M.csv"),
            "error": "",
            "rows": "3",
            "latest": "2026-06-26",
        }
    ]
    assert [row["date"].isoformat() for row in market_dashboard.read_ohlc(tmp_path / "JP_1M.csv")] == [
        "2026-06-24",
        "2026-06-25",
        "2026-06-26",
    ]
    assert "Trading Economics chart history + Investing.com historical table + Trading Economics latest yield page" in (tmp_path / "JP_1M.csv").read_text()


def test_japan_short_bills_use_te_chart_history_before_investing_window(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec(
        "JP_1M",
        "日本1个月国债",
        "bond",
        "investing+tradingeconomics",
        "JP1MT=XX / GJGB1M",
        "JP_1M.csv",
        "JP1M_INVESTING_1D_ohlc.csv",
    )
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [(series_spec, "investing+tradingeconomics", "1M")])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "LOCAL_DATA", tmp_path / "empty-seed")
    monkeypatch.setattr(
        market_dashboard,
        "fetch_tradingeconomics_chart_rows",
        lambda slug, start, end: [
            {"date": "2025-01-01", "timestamp": 1735689600, "open": 0.19, "high": 0.21, "low": 0.18, "close": 0.20},
            {"date": "2026-06-25", "timestamp": 1782345600, "open": 0.90, "high": 0.91, "low": 0.89, "close": 0.90},
        ],
    )
    monkeypatch.setattr(market_dashboard, "fetch_investing_html", lambda spec, start, end: "<html></html>")
    monkeypatch.setattr(
        market_dashboard,
        "rows_from_investing_html",
        lambda html: [
            {"date": "2026-06-25", "timestamp": 1782345600, "open": 0.52, "high": 0.56, "low": 0.50, "close": 0.54},
        ],
    )
    monkeypatch.setattr(market_dashboard, "fetch_tradingeconomics_latest_row", lambda slug: None)

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    rows = market_dashboard.read_ohlc(tmp_path / "JP_1M.csv")
    assert records[0]["rows"] == "2"
    assert [row["date"].isoformat() for row in rows] == ["2025-01-01", "2026-06-25"]
    assert rows[0]["close"] == 0.20
    assert rows[1]["open"] == 0.52
    assert rows[1]["high"] == 0.56
    assert rows[1]["low"] == 0.50
    assert rows[1]["close"] == 0.54


def test_japan_short_bills_request_extra_te_chart_history_for_ohlc_window(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec(
        "JP_1M",
        "日本1个月国债",
        "bond",
        "investing+tradingeconomics",
        "JP1MT=XX / GJGB1M",
        "JP_1M.csv",
        "JP1M_INVESTING_1D_ohlc.csv",
    )
    captured: dict[str, date] = {}
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "CHART_HISTORY_LIMIT", 10)
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [(series_spec, "investing+tradingeconomics", "1M")])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "LOCAL_DATA", tmp_path / "empty-seed")

    def fake_chart_rows(slug, start, end):
        captured["start"] = start
        captured["end"] = end
        return []

    monkeypatch.setattr(market_dashboard, "fetch_tradingeconomics_chart_rows", fake_chart_rows)
    monkeypatch.setattr(market_dashboard, "fetch_investing_html", lambda spec, start, end: "<html></html>")
    monkeypatch.setattr(market_dashboard, "rows_from_investing_html", lambda html: [])
    monkeypatch.setattr(market_dashboard, "fetch_tradingeconomics_latest_row", lambda slug: None)

    market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=7, sleep_sec=0))

    assert (captured["end"] - captured["start"]).days >= 20


def test_japan_short_bills_keep_investing_ohlc_when_te_has_same_date(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec(
        "JP_3M",
        "日本3个月国债",
        "bond",
        "investing+tradingeconomics",
        "JP3MT=XX / GJGB3M",
        "JP_3M.csv",
        "JP3M_INVESTING_1D_ohlc.csv",
    )
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [(series_spec, "investing+tradingeconomics", "3M")])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "LOCAL_DATA", tmp_path / "empty-seed")
    monkeypatch.setattr(market_dashboard, "fetch_tradingeconomics_chart_rows", lambda slug, start, end: [])
    monkeypatch.setattr(market_dashboard, "fetch_investing_html", lambda spec, start, end: "<html></html>")
    monkeypatch.setattr(
        market_dashboard,
        "rows_from_investing_html",
        lambda html: [
            {"date": "2026-06-26", "timestamp": 1782432000, "open": 0.91, "high": 0.95, "low": 0.90, "close": 0.942},
        ],
    )
    monkeypatch.setattr(
        market_dashboard,
        "fetch_tradingeconomics_latest_row",
        lambda slug: {"date": "2026-06-26", "timestamp": 1782432000, "open": 0.92, "high": 0.92, "low": 0.92, "close": 0.92},
    )

    market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    rows = market_dashboard.read_ohlc(tmp_path / "JP_3M.csv")
    assert rows[0]["open"] == 0.91
    assert rows[0]["high"] == 0.95
    assert rows[0]["low"] == 0.90
    assert rows[0]["close"] == 0.942


def test_japan_short_bills_fall_back_to_seed_when_investing_is_blocked(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec(
        "JP_1M",
        "日本1个月国债",
        "bond",
        "investing+tradingeconomics",
        "JP1MT=XX / GJGB1M",
        "JP_1M.csv",
        "JP1M_INVESTING_1D_ohlc.csv",
    )
    dashboard_dir = tmp_path / "dashboard-data"
    seed_dir = tmp_path / "seed-data"
    dashboard_dir.mkdir()
    seed_dir.mkdir()
    market_dashboard.write_ohlc(
        dashboard_dir / "JP_1M.csv",
        [
            {"date": "2026-06-26", "timestamp": 1782432000, "open": 0.55, "high": 0.57, "low": 0.54, "close": 0.56},
        ],
    )
    market_dashboard.write_ohlc(
        seed_dir / "JP1M_INVESTING_1D_ohlc.csv",
        [
            {"date": "2026-06-25", "timestamp": 1782345600, "open": 0.52, "high": 0.56, "low": 0.50, "close": 0.54},
        ],
    )
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [(series_spec, "investing+tradingeconomics", "1M")])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", dashboard_dir)
    monkeypatch.setattr(market_dashboard, "LOCAL_DATA", seed_dir)
    monkeypatch.setattr(market_dashboard, "fetch_tradingeconomics_chart_rows", lambda slug, start, end: [])
    monkeypatch.setattr(market_dashboard, "fetch_investing_html", lambda spec, start, end: (_ for _ in ()).throw(RuntimeError("HTTP Error 403: Forbidden")))
    monkeypatch.setattr(
        market_dashboard,
        "fetch_tradingeconomics_latest_row",
        lambda slug: {"date": "2026-06-26", "timestamp": 1782432000, "open": 0.55, "high": 0.57, "low": 0.54, "close": 0.56},
    )

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert records[0]["status"] == "degraded"
    assert records[0]["rows"] == "2"
    assert records[0]["latest"] == "2026-06-26"
    assert "Investing.com history failed: HTTP Error 403: Forbidden" in records[0]["error"]
    assert [row["date"].isoformat() for row in market_dashboard.read_ohlc(dashboard_dir / "JP_1M.csv")] == [
        "2026-06-25",
        "2026-06-26",
    ]


def test_korea_short_end_koribor_history_is_shared_across_tenors(monkeypatch, tmp_path) -> None:
    specs = [
        (SeriesSpec("KR_1M", "韩国1个月短端(KORIBOR)", "bond", "smbs-koribor", "SMBS:KORIBOR:1M", "KR_1M.csv"), "smbs-koribor", "1M"),
        (SeriesSpec("KR_3M", "韩国3个月短端(KORIBOR)", "bond", "smbs-koribor", "SMBS:KORIBOR:3M", "KR_3M.csv"), "smbs-koribor", "3M"),
        (SeriesSpec("KR_6M", "韩国6个月短端(KORIBOR)", "bond", "smbs-koribor", "SMBS:KORIBOR:6M", "KR_6M.csv"), "smbs-koribor", "6M"),
    ]
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "JAPAN_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "KOREA_BOND_SPECS", specs)
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    calls = []

    def fake_koribor(start, end):
        calls.append((start, end))
        return {
            "1M": [{"date": "2026-06-26", "timestamp": 1782432000, "open": 2.68, "high": 2.68, "low": 2.68, "close": 2.68}],
            "3M": [{"date": "2026-06-26", "timestamp": 1782432000, "open": 3.01, "high": 3.01, "low": 3.01, "close": 3.01}],
            "6M": [{"date": "2026-06-26", "timestamp": 1782432000, "open": 3.23, "high": 3.23, "low": 3.23, "close": 3.23}],
        }

    monkeypatch.setattr(market_dashboard, "fetch_smbs_koribor_rows_by_tenor", fake_koribor)

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert len(calls) == 1
    assert [record["key"] for record in records] == ["KR_1M", "KR_3M", "KR_6M"]
    assert [record["rows"] for record in records] == ["1", "1", "1"]
    assert market_dashboard.read_ohlc(tmp_path / "KR_3M.csv")[0]["close"] == 3.01


def test_korea_government_bonds_merge_investing_history_with_te_latest(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec(
        "KR_1Y",
        "韩国1年国债",
        "bond",
        "investing+tradingeconomics",
        "KR1YT=RR / KR:TE:1Y",
        "KR_1Y.csv",
        "KR1YR_INVESTING_1D_ohlc.csv",
    )
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "JAPAN_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "KOREA_BOND_SPECS", [(series_spec, "investing+tradingeconomics", "1Y")])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "LOCAL_DATA", tmp_path / "empty-seed")
    monkeypatch.setattr(market_dashboard, "fetch_investing_html", lambda spec, start, end: "<html></html>")
    monkeypatch.setattr(
        market_dashboard,
        "rows_from_investing_html",
        lambda html: [
            {"date": "2026-06-24", "timestamp": 1782259200, "open": 3.42, "high": 3.46, "low": 3.40, "close": 3.44},
            {"date": "2026-06-25", "timestamp": 1782345600, "open": 3.44, "high": 3.48, "low": 3.41, "close": 3.45},
        ],
    )
    monkeypatch.setattr(
        market_dashboard,
        "fetch_tradingeconomics_country_latest_row",
        lambda country_slug, slug: {"date": "2026-06-26", "timestamp": 1782432000, "open": 3.47, "high": 3.49, "low": 3.44, "close": 3.46},
    )

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert records == [
        {
            "key": "KR_1Y",
            "source": "investing+tradingeconomics",
            "symbol": "KR1YT=RR / KR:TE:1Y",
            "status": "ok",
            "file": str(tmp_path / "KR_1Y.csv"),
            "error": "",
            "rows": "3",
            "latest": "2026-06-26",
        }
    ]
    rows = market_dashboard.read_ohlc(tmp_path / "KR_1Y.csv")
    assert [row["date"].isoformat() for row in rows] == ["2026-06-24", "2026-06-25", "2026-06-26"]
    assert "Investing.com historical table + Trading Economics latest yield page" in (tmp_path / "KR_1Y.csv").read_text()


def test_investing_only_russia_bonds_use_cache_and_te_when_investing_is_blocked(monkeypatch, tmp_path) -> None:
    series_spec = SeriesSpec("RU_10Y", "俄罗斯10年国债", "bond", "investing", "RU10YT=RR", "RU_10Y.csv")
    investing_spec = market_dashboard.InvestingSpec(
        "RU10Y",
        "23974",
        "RU10YT=RR",
        "russia-10-year-bond-yield-historical-data",
        "Russia 10-Year Bond Yield Historical Data",
        "RU10YR_INVESTING_1D_ohlc.csv",
    )
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "CHINA_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "JAPAN_BOND_SPECS",
        "KOREA_BOND_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "INVESTING_SPECS", [(series_spec, investing_spec)])
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    market_dashboard.write_ohlc(
        tmp_path / "RU_10Y.csv",
        [
            {"date": "2026-06-23", "timestamp": 1782172800, "open": 15.70, "high": 15.70, "low": 15.70, "close": 15.70},
        ],
    )
    monkeypatch.setattr(
        market_dashboard,
        "fetch_investing_html",
        lambda spec, start, end: (_ for _ in ()).throw(RuntimeError("HTTP Error 403: Forbidden")),
    )
    monkeypatch.setattr(
        market_dashboard,
        "fetch_tradingeconomics_country_latest_row",
        lambda country_slug, slug: {"date": "2026-06-26", "timestamp": 1782432000, "open": 16.28, "high": 16.28, "low": 16.28, "close": 16.28},
    )

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert records[0]["status"] == "degraded"
    assert records[0]["rows"] == "2"
    assert records[0]["latest"] == "2026-06-26"
    assert "Investing.com history failed: HTTP Error 403: Forbidden" in records[0]["error"]
    rows = market_dashboard.read_ohlc(tmp_path / "RU_10Y.csv")
    assert [row["date"].isoformat() for row in rows] == ["2026-06-23", "2026-06-26"]
    assert rows[-1]["close"] == 16.28


def test_cross_checked_china_germany_korea_bond_tenors_are_configured() -> None:
    china_sources = {series_spec.key: series_spec.source for series_spec, _, _ in CHINA_BOND_SPECS}
    germany_sources = {series_spec.key: series_spec.source for series_spec, _, _ in GERMANY_BOND_SPECS}
    korea_sources = {series_spec.key: series_spec.source for series_spec, _, _ in KOREA_BOND_SPECS}

    assert {
        "CN_1M",
        "CN_3M",
        "CN_6M",
        "CN_1Y",
        "CN_2Y",
        "CN_3Y",
        "CN_5Y",
        "CN_7Y",
        "CN_10Y",
        "CN_30Y",
    } <= set(china_sources)
    assert set(china_sources.values()) == {"chinamoney"}
    assert COUNTRY_BOND_TENORS["CN"] == [
        ("1M", "CN_1M"),
        ("3M", "CN_3M"),
        ("6M", "CN_6M"),
        ("1Y", "CN_1Y"),
        ("2Y", "CN_2Y"),
        ("3Y", "CN_3Y"),
        ("5Y", "CN_5Y"),
        ("7Y", "CN_7Y"),
        ("10Y", "CN_10Y"),
        ("30Y", "CN_30Y"),
    ]

    assert germany_sources == {
        "DE_3M": "tradingeconomics",
        "DE_6M": "tradingeconomics",
        "DE_1Y": "bundesbank-term",
        "DE_2Y": "bundesbank",
        "DE_3Y": "bundesbank-term",
        "DE_5Y": "bundesbank",
        "DE_7Y": "bundesbank",
        "DE_10Y": "bundesbank",
        "DE_30Y": "bundesbank",
    }
    assert COUNTRY_BOND_TENORS["DE"] == [
        ("3M", "DE_3M"),
        ("6M", "DE_6M"),
        ("1Y", "DE_1Y"),
        ("2Y", "DE_2Y"),
        ("3Y", "DE_3Y"),
        ("5Y", "DE_5Y"),
        ("7Y", "DE_7Y"),
        ("10Y", "DE_10Y"),
        ("30Y", "DE_30Y"),
    ]


    assert korea_sources == {
        "KR_1M": "smbs-koribor",
        "KR_3M": "smbs-koribor",
        "KR_6M": "smbs-koribor",
        "KR_1Y": "investing+tradingeconomics",
        "KR_2Y": "investing+tradingeconomics",
        "KR_3Y": "investing+tradingeconomics",
        "KR_5Y": "investing+tradingeconomics",
        "KR_10Y": "investing+tradingeconomics",
        "KR_30Y": "investing+tradingeconomics",
    }
    assert {
        key: (spec.instrument_id, spec.source_symbol, spec.slug)
        for key, spec in market_dashboard.INVESTING_BOND_SPECS.items()
        if key in {"KR1Y", "KR2Y", "KR3Y", "KR5Y", "KR10Y", "KR30Y"}
    } == {
        "KR1Y": ("29294", "KR1YT=RR", "south-korea-1-year-bond-yield-historical-data"),
        "KR2Y": ("29295", "KR2YT=RR", "south-korea-2-year-bond-yield-historical-data"),
        "KR3Y": ("29296", "KR3YT=RR", "south-korea-3-year-bond-yield-historical-data"),
        "KR5Y": ("29298", "KR5YT=RR", "south-korea-5-year-bond-yield-historical-data"),
        "KR10Y": ("29292", "KR10YT=RR", "south-korea-10-year-bond-yield-historical-data"),
        "KR30Y": ("1052525", "KR30YT=RR", "south-korea-30-year-historical-data"),
    }
    assert COUNTRY_BOND_TENORS["KR"] == [
        ("1M", "KR_1M"),
        ("3M", "KR_3M"),
        ("6M", "KR_6M"),
        ("1Y", "KR_1Y"),
        ("2Y", "KR_2Y"),
        ("3Y", "KR_3Y"),
        ("5Y", "KR_5Y"),
        ("10Y", "KR_10Y"),
        ("30Y", "KR_30Y"),
    ]


def test_china_short_bills_backfill_from_lookback_when_cache_is_short(monkeypatch, tmp_path) -> None:
    cn_specs = [
        (SeriesSpec("CN_1M", "中国1个月国债", "bond", "chinamoney", "CFETS:CYCC000:1M", "CN_1M.csv"), "chinamoney", "1M"),
        (SeriesSpec("CN_3M", "中国3个月国债", "bond", "chinamoney", "CFETS:CYCC000:3M", "CN_3M.csv"), "chinamoney", "3M"),
    ]
    captured: dict[str, date] = {}
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "JAPAN_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "CHINA_BOND_SPECS", cn_specs)
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "today_utc", lambda: date(2026, 6, 26))

    short_cache = [
        {"date": (date(2026, 4, 28) + timedelta(days=offset)).isoformat(), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}
        for offset in range(60)
    ]
    market_dashboard.write_ohlc(tmp_path / "CN_1M.csv", short_cache)
    market_dashboard.write_ohlc(tmp_path / "CN_3M.csv", [{**row, "close": 1.2} for row in short_cache])

    def fake_chinamoney_history(start, end, sleep_sec):
        captured["start"] = start
        captured["end"] = end
        return {
            "1M": [{"date": "2026-03-28", "open": 0.9, "high": 0.9, "low": 0.9, "close": 0.9}],
            "3M": [{"date": "2026-03-28", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}],
        }

    monkeypatch.setattr(market_dashboard, "fetch_chinamoney_history_rows_by_tenor", fake_chinamoney_history)
    monkeypatch.setattr(market_dashboard, "fetch_chinabond_pbc_history_rows_by_tenor", lambda start, end, tenors, sleep_sec=0: {})

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert captured == {"start": date(2026, 3, 28), "end": date(2026, 6, 26)}
    assert [record["rows"] for record in records] == ["61", "61"]


def test_china_3m_merges_chinabond_history_with_chinamoney_recent(monkeypatch, tmp_path) -> None:
    cn_specs = [
        (SeriesSpec("CN_1M", "中国1个月国债", "bond", "chinamoney", "CFETS:CYCC000:1M", "CN_1M.csv"), "chinamoney", "1M"),
        (SeriesSpec("CN_3M", "中国3个月国债", "bond", "chinamoney", "CFETS:CYCC000:3M", "CN_3M.csv"), "chinamoney", "3M"),
    ]
    for name in [
        "WSCN_SPECS",
        "YAHOO_SPECS",
        "NIKKEI_SPECS",
        "JAPAN_BOND_SPECS",
        "GERMANY_BOND_SPECS",
        "KOREA_BOND_SPECS",
        "INVESTING_SPECS",
    ]:
        monkeypatch.setattr(market_dashboard, name, [])
    monkeypatch.setattr(market_dashboard, "CHINA_BOND_SPECS", cn_specs)
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "today_utc", lambda: date(2026, 6, 26))
    monkeypatch.setattr(
        market_dashboard,
        "fetch_chinabond_pbc_history_rows_by_tenor",
        lambda start, end, tenors, sleep_sec=0: {
            "3M": [{"date": "2025-01-02", "open": 1.5, "high": 1.5, "low": 1.5, "close": 1.5}],
        },
        raising=False,
    )
    monkeypatch.setattr(
        market_dashboard,
        "fetch_chinamoney_history_rows_by_tenor",
        lambda start, end, sleep_sec: {
            "1M": [{"date": "2026-06-26", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}],
            "3M": [{"date": "2026-06-26", "open": 1.2, "high": 1.2, "low": 1.2, "close": 1.2}],
        },
    )

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=500, lookback_days=90, sleep_sec=0))

    assert [record["rows"] for record in records] == ["1", "2"]
    rows = market_dashboard.read_ohlc(tmp_path / "CN_3M.csv")
    assert [row["date"].isoformat() for row in rows] == ["2025-01-02", "2026-06-26"]
    assert rows[0]["close"] == 1.5
    assert rows[1]["close"] == 1.2


def test_ohlc_comparison_legend_uses_inline_tspans_to_avoid_overlap() -> None:
    assert "const legendY = 18;" in JS
    assert "<tspan" in JS
    assert 'dx="16"' in JS
    assert '比较：${esc(compareItem.label)}' in JS
    assert "legendCompareY" not in JS
    assert 'x="${margin.left + 184}" y="16"' not in JS


def test_data_status_panel_defaults_collapsed() -> None:
    html = render_html(
        {
            "countries": [],
            "volatility_rankings": {"bond": [], "equity": [], "fx": []},
            "fx_rank_details": {},
            "second_order_monitor": [],
            "fx_flows": [],
            "series_status": [
                {
                    "key": "US_10Y",
                    "label": "美国10年国债",
                    "source": "WSCN",
                    "symbol": "US10YR.OTC",
                    "latest_date": "2026-06-26",
                    "latest": 4.25,
                    "stale": False,
                }
            ],
            "notes": [],
            "generated_at": "2026-06-26T00:00:00",
        }
    )

    opening = '<details class="panel status-panel">'
    assert opening in html
    assert "open" not in opening
    assert "<summary><span>数据状态</span>" in html
    assert '<table class="status-table">' in html
