import unittest

from fetch_yahoo_us_ohlc import (
    build_chart_url,
    parse_sp500_tickers,
    rows_from_chart_response,
)


class YahooUsOhlcTests(unittest.TestCase):
    def test_build_chart_url_encodes_inclusive_date_range(self):
        url = build_chart_url("BRK.B", "2016-01-01", "2026-06-23")

        self.assertIn("https://query1.finance.yahoo.com/v8/finance/chart/BRK-B?", url)
        self.assertIn("period1=1451606400", url)
        self.assertIn("period2=1782259200", url)
        self.assertIn("interval=1d", url)
        self.assertIn("events=history", url)
        self.assertIn("includeAdjustedClose=true", url)

    def test_rows_from_chart_response_maps_ohlcv_and_adjusted_close(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL"},
                        "timestamp": [1777987800, 1778074200],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [203.5, None],
                                    "high": [207.25, 209.0],
                                    "low": [202.0, 204.5],
                                    "close": [206.1, 208.0],
                                    "volume": [51230000, 40210000],
                                }
                            ],
                            "adjclose": [{"adjclose": [205.7, 207.5]}],
                        },
                    }
                ],
                "error": None,
            }
        }

        rows = rows_from_chart_response(payload, "AAPL")

        self.assertEqual(
            rows,
            [
                {
                    "date": "2026-05-05",
                    "timestamp": 1777987800,
                    "symbol": "AAPL",
                    "open": 203.5,
                    "high": 207.25,
                    "low": 202.0,
                    "close": 206.1,
                    "adj_close": 205.7,
                    "volume": 51230000,
                }
            ],
        )

    def test_parse_sp500_tickers_extracts_symbols_and_converts_yahoo_dots(self):
        html = """
        <table id="constituents">
          <tr><th>Symbol</th><th>Security</th></tr>
          <tr><td><a href="/wiki/Apple_Inc.">AAPL</a></td><td>Apple Inc.</td></tr>
          <tr><td><a href="/wiki/Berkshire_Hathaway">BRK.B</a></td><td>Berkshire Hathaway</td></tr>
        </table>
        """

        self.assertEqual(parse_sp500_tickers(html), ["AAPL", "BRK-B"])


if __name__ == "__main__":
    unittest.main()
