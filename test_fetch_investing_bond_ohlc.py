#!/usr/bin/env python3
"""Tests for Investing.com bond OHLC parsing."""

from __future__ import annotations

from fetch_investing_bond_ohlc import rows_from_html


def test_rows_from_html_parses_next_historical_data_store() -> None:
    html = """
    <script>
    self.__NEXT_DATA__ = {"props":{"pageProps":{"state":{
      "historicalDataStore":{
        "dateRange":{"startDate":"2026-05-27T00:00:00.000Z","endDate":"2026-06-27T00:00:00.000Z"},
        "timeFrame":"Daily",
        "historicalData":{"data":[
          {
            "rowDate":"Jun 26, 2026",
            "rowDateRaw":1782432000,
            "rowDateTimestamp":"2026-06-26T00:00:00Z",
            "last_closeRaw":"0.92000001668930",
            "last_openRaw":"0.91000002622604",
            "last_maxRaw":"0.92500001192093",
            "last_minRaw":"0.90499997138977"
          },
          {
            "rowDate":"Jun 25, 2026",
            "rowDateRaw":1782345600,
            "rowDateTimestamp":"2026-06-25T00:00:00Z",
            "last_closeRaw":"0.89999997615814",
            "last_openRaw":"0.90000000000000",
            "last_maxRaw":"0.90500000000000",
            "last_minRaw":"0.89000000000000"
          }
        ]}
      },
      "otherStore":{}
    }}}};
    </script>
    """

    rows = rows_from_html(html)

    assert rows == [
        {
            "date": "2026-06-25",
            "timestamp": 1782345600,
            "open": 0.9,
            "high": 0.905,
            "low": 0.89,
            "close": 0.89999997615814,
        },
        {
            "date": "2026-06-26",
            "timestamp": 1782432000,
            "open": 0.91000002622604,
            "high": 0.92500001192093,
            "low": 0.90499997138977,
            "close": 0.9200000166893,
        },
    ]
