import unittest

from fetch_wscn_ohlc import build_kline_url, next_page_timestamp, rows_from_response


class WscnOhlcTests(unittest.TestCase):
    def test_build_kline_url_encodes_chart_parameters(self):
        url = build_kline_url("JPYCNY.OTC", "1D", 100, 1780358400)

        self.assertIn("https://api-ddc-wscn.awtmt.com/market/kline?", url)
        self.assertIn("prod_code=JPYCNY.OTC", url)
        self.assertIn("tick_count=100", url)
        self.assertIn("period_type=86400", url)
        self.assertIn("fields=tick_at%2Copen_px%2Cclose_px%2Chigh_px%2Clow_px", url)
        self.assertIn("timestamp=1780358400", url)
        self.assertIn("adjust_price_type=forward", url)

    def test_rows_from_response_uses_returned_field_order(self):
        payload = {
            "code": 20000,
            "message": "OK",
            "data": {
                "fields": ["open_px", "close_px", "high_px", "low_px", "tick_at"],
                "candle": {
                    "JPYCNY.OTC": {
                        "lines": [
                            [0.043, 0.044, 0.045, 0.042, 1777939200],
                        ],
                    },
                },
            },
        }

        rows = rows_from_response(payload, "JPYCNY.OTC")

        self.assertEqual(
            rows,
            [
                {
                    "date": "2026-05-05",
                    "timestamp": 1777939200,
                    "open": 0.043,
                    "high": 0.045,
                    "low": 0.042,
                    "close": 0.044,
                }
            ],
        )

    def test_next_page_timestamp_uses_oldest_bar_as_exclusive_boundary(self):
        rows = [
            {"timestamp": 1780358400},
            {"timestamp": 1780272000},
        ]

        self.assertEqual(next_page_timestamp(rows), 1780272000)


if __name__ == "__main__":
    unittest.main()
