#!/usr/bin/env python3
"""Tests for server-safe global bond yield source parsers."""

from __future__ import annotations

from datetime import date

import fetch_global_bond_ohlc
from fetch_japan_bond_ohlc import close_only_row
from fetch_global_bond_ohlc import fetch_chinamoney_history_rows_by_tenor
from fetch_global_bond_ohlc import fetch_bundesbank_term_structure_rows
from fetch_global_bond_ohlc import rows_by_tenor_from_chinamoney_payload
from fetch_global_bond_ohlc import rows_by_tenor_from_smbs_koribor_html
from fetch_global_bond_ohlc import rows_from_bok_ecos_payload
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


def test_fetch_chinamoney_history_rows_skips_weekends(monkeypatch) -> None:
    calls: list[date] = []

    def fake_fetch(day: date):
        calls.append(day)
        return {"1M": close_only_row(day.isoformat(), 1.0 + len(calls))}

    monkeypatch.setattr(fetch_global_bond_ohlc, "fetch_chinamoney_rows_by_tenor_for_date", fake_fetch)

    rows = fetch_chinamoney_history_rows_by_tenor(date(2026, 6, 20), date(2026, 6, 23))

    assert calls == [date(2026, 6, 22), date(2026, 6, 23)]
    assert [row["date"] for row in rows["1M"]] == ["2026-06-22", "2026-06-23"]


def test_rows_by_tenor_from_smbs_koribor_html_decodes_daily_history() -> None:
    html = """
    <table><caption>Daily KORIBOR result</caption>
      <thead><tr><th>&nbsp;</th><th>1W</th><th>1M</th><th>2M</th><th>3M</th><th>6M</th><th>12M</th></tr></thead>
      <tbody>
        <script>d2('%_A3c%_A74%_A72%_A3e%_A3c%_A74%_A64%_A3e%_A32%_A30%_A32%_A36%_A2f%_A30%_A36%_A2f%_A32%_A36%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A74%_A64%_A3e%_A32%_A2e%_A35%_A30%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A74%_A64%_A3e%_A32%_A2e%_A36%_A38%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A74%_A64%_A3e%_A32%_A2e%_A38%_A35%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A74%_A64%_A3e%_A33%_A2e%_A30%_A31%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A74%_A64%_A3e%_A33%_A2e%_A32%_A33%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A74%_A64%_A3e%_A33%_A2e%_A36%_A35%_A3c%_A2f%_A74%_A64%_A3e%_A3c%_A2f%_A74%_A72%_A3e');</script>
        <tr><td>2026/06/25</td><td>2.50</td><td>2.68</td><td>2.84</td><td>3.00</td><td>3.21</td><td class='brr0'>3.64</td></tr>
      </tbody>
    </table>
    """

    rows = rows_by_tenor_from_smbs_koribor_html(html)

    assert [row["date"] for row in rows["1M"]] == ["2026-06-25", "2026-06-26"]
    assert rows["1M"][-1]["close"] == 2.68
    assert rows["3M"][-1]["close"] == 3.01
    assert rows["6M"][-1]["close"] == 3.23
    assert rows["12M"][-1]["source"] == "Seoul Money Brokerage Services KORIBOR fixing"


def test_rows_from_bok_ecos_payload_parses_daily_market_rates() -> None:
    payload = {
        "StatisticSearch": {
            "row": [
                {"TIME": "20260625", "DATA_VALUE": "2.65"},
                {"TIME": "20260626", "DATA_VALUE": "2.67"},
            ]
        }
    }

    rows = rows_from_bok_ecos_payload(payload)

    assert rows == [
        {
            "date": "2026-06-25",
            "timestamp": 1782345600,
            "open": 2.65,
            "high": 2.65,
            "low": 2.65,
            "close": 2.65,
        },
        {
            "date": "2026-06-26",
            "timestamp": 1782432000,
            "open": 2.67,
            "high": 2.67,
            "low": 2.67,
            "close": 2.67,
        },
    ]


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


def test_fetch_bundesbank_term_structure_rows_uses_bbsis_dataset(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return b'header,value,flag\n2026-06-26,2.51,\n'

    def fake_urlopen(request, timeout=0):
        seen["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr(fetch_global_bond_ohlc, "urlopen", fake_urlopen)

    rows = fetch_bundesbank_term_structure_rows("D.I.ZST.ZI.EUR.S1311.B.A604.R03XX.R.A.A._Z._Z.A")

    assert "/rest/data/BBSIS/" in seen["url"]
    assert rows[-1]["date"] == "2026-06-26"
    assert rows[-1]["close"] == 2.51


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
