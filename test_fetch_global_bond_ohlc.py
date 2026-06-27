#!/usr/bin/env python3
"""Tests for server-safe global bond yield source parsers."""

from __future__ import annotations

from fetch_global_bond_ohlc import rows_by_tenor_from_chinamoney_payload
from fetch_global_bond_ohlc import rows_from_bundesbank_csv
from fetch_global_bond_ohlc import row_from_tradingeconomics_quote_html


def test_rows_by_tenor_from_chinamoney_payload_extracts_key_curve_terms() -> None:
    payload = """
    {
      "data": {
        "dataXml": "<?xml version='1.0' encoding='UTF-8'?><chart><xaxis><value xid='1'>0.083</value><value xid='4'>0.25</value><value xid='7'>0.5</value><value xid='13'>1</value><value xid='23'>2</value><value xid='33'>3</value><value xid='53'>5</value><value xid='73'>7</value><value xid='103'>10</value><value xid='303'>30</value></xaxis><graphs><graph gid='0'><value xid='1'>0.9585</value><value xid='4'>1.0581</value><value xid='7'>1.0902</value><value xid='13'>1.1353</value><value xid='23'>1.2462</value><value xid='33'>1.2886</value><value xid='53'>1.4355</value><value xid='73'>1.5658</value><value xid='103'>1.7322</value><value xid='303'>2.2196</value></graph></graphs></chart>"
      }
    }
    """

    rows = rows_by_tenor_from_chinamoney_payload(payload, "2026-06-26")

    assert rows["1M"]["close"] == 0.9585
    assert rows["3M"]["close"] == 1.0581
    assert rows["6M"]["close"] == 1.0902
    assert rows["30Y"] == {
        "date": "2026-06-26",
        "timestamp": 1782432000,
        "open": 2.2196,
        "high": 2.2196,
        "low": 2.2196,
        "close": 2.2196,
    }


def test_rows_from_bundesbank_csv_skips_missing_weekends() -> None:
    csv_text = """\
"",BBSSY.D.REN.EUR.A610.000000WT0202.A,BBSSY.D.REN.EUR.A610.000000WT0202.A_FLAGS
"",Daily yield of the current (two-year) Federal Treasury notes,
2026-06-25,2.53,
2026-06-26,2.51,
2026-06-27,.,No value available
"""

    rows = rows_from_bundesbank_csv(csv_text)

    assert rows[-1] == {
        "date": "2026-06-26",
        "timestamp": 1782432000,
        "open": 2.51,
        "high": 2.51,
        "low": 2.51,
        "close": 2.51,
    }
    assert len(rows) == 2


def test_row_from_tradingeconomics_quote_html_handles_non_japan_country() -> None:
    html = """
    <meta name="description" content="The yield on Germany 3 Month Bond Yield held
    steady at 2.27% on June 26, 2026. Over the past month, the yield has edged up." />
    """

    row = row_from_tradingeconomics_quote_html(html)

    assert row == {
        "date": "2026-06-26",
        "timestamp": 1782432000,
        "open": 2.27,
        "high": 2.27,
        "low": 2.27,
        "close": 2.27,
    }
