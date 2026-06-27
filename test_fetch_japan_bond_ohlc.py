#!/usr/bin/env python3
"""Tests for Japan bond yield source parsers."""

from __future__ import annotations

from fetch_japan_bond_ohlc import rows_by_tenor_from_mof_csv
from fetch_japan_bond_ohlc import row_from_tradingeconomics_quote_html


def test_rows_by_tenor_from_mof_csv_builds_close_only_ohlc() -> None:
    csv_text = """Interest Rate,,,,(Unit : %)
Date,1Y,2Y,3Y,5Y,30Y
2026/6/25,1.175,1.421,1.556,1.923,3.781
2026/6/26,1.180,1.404,1.621,1.876,3.520
"""

    rows = rows_by_tenor_from_mof_csv(csv_text)

    assert rows["3Y"][-1] == {
        "date": "2026-06-26",
        "timestamp": 1782432000,
        "open": 1.621,
        "high": 1.621,
        "low": 1.621,
        "close": 1.621,
    }
    assert rows["30Y"][0]["close"] == 3.781


def test_row_from_tradingeconomics_quote_html_parses_latest_summary() -> None:
    html = """
    <meta name="description" content="The yield on the Japan 1 Month Government Bond
    was 0.92% on June 26, 2026 according to over-the-counter interbank yield quotes." />
    """

    row = row_from_tradingeconomics_quote_html(html)

    assert row == {
        "date": "2026-06-26",
        "timestamp": 1782432000,
        "open": 0.92,
        "high": 0.92,
        "low": 0.92,
        "close": 0.92,
    }


def test_row_from_tradingeconomics_quote_html_parses_directional_summary() -> None:
    html = """
    <meta name="description" content="The yield on Japan 7 Year Bond Yield eased
    to 2.31% on June 26, 2026, marking a 0.02 percentage points decrease from
    the previous session." />
    """

    row = row_from_tradingeconomics_quote_html(html)

    assert row == {
        "date": "2026-06-26",
        "timestamp": 1782432000,
        "open": 2.31,
        "high": 2.31,
        "low": 2.31,
        "close": 2.31,
    }
