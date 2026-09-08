import io
import json
from datetime import date, datetime

import pytest

import market_dashboard as dashboard


def fetch_payload(monkeypatch, timestamps, bars, **metadata):
    payload = {"chart": {"result": [{
        "meta": {"instrumentType": "CURRENCY", "exchangeTimezoneName": "Europe/London", **metadata},
        "timestamp": [int(datetime.fromisoformat(value).timestamp()) for value in timestamps],
        "indicators": {"quote": [{
            key: [bar[index] for bar in bars]
            for index, key in enumerate(("open", "high", "low", "close"))
        }]},
    }]}}
    monkeypatch.setattr(dashboard, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    return dashboard.fetch_yahoo_ohlc("KRW=X", date(2026, 1, 1), date(2026, 12, 31))


def test_currency_preserves_london_trading_dates_across_dst(monkeypatch):
    rows = fetch_payload(monkeypatch, [
        "2026-03-27T00:00:00+00:00",
        "2026-03-29T23:00:00+00:00",
        "2026-09-03T23:00:00+00:00",
        "2026-09-06T23:00:00+00:00",
        "2026-10-26T00:00:00+00:00",
    ], [(100, 102, 99, 101)] * 5)
    assert [r["date"] for r in rows] == [
        "2026-03-27", "2026-03-30", "2026-09-04", "2026-09-07", "2026-10-26",
    ]
    assert all(date.fromisoformat(r["date"]).weekday() < 5 for r in rows)


def test_currency_deduplicates_same_session_live_bar(monkeypatch):
    rows = fetch_payload(monkeypatch, [
        "2026-09-07T23:00:00+00:00", "2026-09-08T02:00:00+00:00",
    ], [(100, 102, 99, 101), (100, 103, 99, 102)])
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-09-08"
    assert rows[0]["high"] == 103
    assert rows[0]["close"] == 102


def test_currency_live_close_does_not_erase_existing_candle(monkeypatch):
    rows = fetch_payload(monkeypatch, [
        "2026-09-07T23:00:00+00:00", "2026-09-08T02:00:00+00:00",
    ], [(100, 103, 99, 102), (None, None, None, None)], regularMarketPrice=102)
    assert len(rows) == 1
    assert (rows[0]["high"], rows[0]["low"]) == (103, 99)


def test_currency_missing_timezone_fails_without_guessing(monkeypatch):
    with pytest.raises(ValueError, match="Missing Yahoo currency timezone"):
        fetch_payload(monkeypatch, ["2026-09-06T23:00:00+00:00"],
                      [(100, 102, 99, 101)], exchangeTimezoneName=None)


def test_non_currency_date_policy_is_unchanged(monkeypatch):
    rows = fetch_payload(monkeypatch, ["2026-09-04T00:00:00+00:00"],
                         [(100, 102, 99, 101)], instrumentType="INDEX",
                         exchangeTimezoneName="Asia/Seoul")
    assert rows[0]["date"] == "2026-09-04"
