#!/usr/bin/env python3
"""Tests for the private quant-fund snapshot builder."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

import quant_fund_snapshot as qfs
from quant_fund_snapshot import (
    aggregate_futures_trade_curve,
    build_options_percent_history,
    built_in_options_seed_points,
    default_quant_fund_snapshot,
    env_date,
    env_float,
    fetch_futures_trades,
    load_futures_trades_csv,
    merge_retained_futures_rebuild,
    parse_futures_symbols,
    require_complete_futures_rebuild,
    require_lead_futures_context,
    update_options_percent_points,
)


def utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture(autouse=True)
def clear_optional_futures_symbols(monkeypatch) -> None:
    monkeypatch.delenv("QUANT_FUND_EXTRA_SYMBOLS", raising=False)
    monkeypatch.delenv("QUANT_FUND_EXTRA_SYMBOLS_START_DATE", raising=False)


def test_futures_trades_are_rendered_as_percent_of_configured_base() -> None:
    trades = [
        {"time": utc_ms(2026, 4, 1), "realizedPnl": "30", "commission": "1.5", "commissionAsset": "USDT"},
        {"time": utc_ms(2026, 4, 1), "realizedPnl": "-10", "commission": "0.5", "commissionAsset": "USDT"},
        {"time": utc_ms(2026, 4, 2), "realizedPnl": "5", "commission": "0.25", "commissionAsset": "USDT"},
    ]

    curve = aggregate_futures_trade_curve(trades, base_usd=1000.0, start=date(2026, 4, 1))

    assert curve == [
        {"date": "2026-04-01", "pct": 1.8},
        {"date": "2026-04-02", "pct": 2.275},
    ]


def test_futures_trades_csv_is_loaded_without_persisting_raw_trade_fields(tmp_path) -> None:
    source = tmp_path / "trades.csv"
    source.write_text(
        "datetime_utc,time,symbol,realizedPnl,quoteQty,commission\n"
        "2026-04-23T06:06:44+00:00,1776924404753,SYNTH,0,1,0.31\n"
        "2026-04-23T08:40:41+00:00,1776933641969,SYNTH,-3.6408,1,0.30\n",
        encoding="utf-8",
    )

    trades = load_futures_trades_csv(source)
    curve = aggregate_futures_trade_curve(trades, base_usd=100.0, start=date(2026, 4, 1))

    assert trades == [
        {"time": 1776924404753, "realizedPnl": 0.0, "commission": 0.31, "commissionAsset": ""},
        {"time": 1776933641969, "realizedPnl": -3.6408, "commission": 0.3, "commissionAsset": ""},
    ]
    assert curve == [{"date": "2026-04-23", "pct": -4.2508}]


def test_futures_trades_fetch_uses_valid_seven_day_windows(monkeypatch) -> None:
    calls = []

    def fake_signed_get(_base, _path, _api_key, _api_secret, params):
        calls.append((params["startTime"], params["endTime"]))
        return []

    monkeypatch.setattr(qfs, "signed_get", fake_signed_get)

    fetch_futures_trades("key", "secret", "BTCUSDT", date(2026, 6, 24), date(2026, 6, 26))

    assert calls == [
        (utc_ms(2026, 6, 24), utc_ms(2026, 6, 27) - 1000),
    ]


def test_futures_trades_fetch_splits_long_ranges_at_seven_days(monkeypatch) -> None:
    calls = []

    def fake_signed_get(_base, _path, _api_key, _api_secret, params):
        calls.append((params["startTime"], params["endTime"]))
        return []

    monkeypatch.setattr(qfs, "signed_get", fake_signed_get)

    fetch_futures_trades("key", "secret", "BTCUSDT", date(2026, 4, 1), date(2026, 4, 10))

    assert calls == [
        (utc_ms(2026, 4, 1), utc_ms(2026, 4, 8) - 1),
        (utc_ms(2026, 4, 8), utc_ms(2026, 4, 11) - 1000),
    ]


def test_futures_source_requires_lead_trader_and_symbol_whitelist(monkeypatch) -> None:
    calls = []

    def fake_signed_get(_base, path, _api_key, _api_secret, _params=None):
        calls.append(path)
        if path.endswith("/userStatus"):
            return {"success": True, "data": {"isLeadTrader": True}}
        return {"success": True, "data": [{"symbol": "BTCUSDT"}]}

    monkeypatch.setattr(qfs, "signed_get", fake_signed_get)

    require_lead_futures_context("lead-key", "lead-secret", "BTCUSDT")

    assert calls == [
        "/sapi/v1/copyTrading/futures/userStatus",
        "/sapi/v1/copyTrading/futures/leadSymbol",
    ]


def test_futures_source_requires_every_configured_symbol(monkeypatch) -> None:
    def fake_signed_get(_base, path, _api_key, _api_secret, _params=None):
        if path.endswith("/userStatus"):
            return {"success": True, "data": {"isLeadTrader": True}}
        return {"success": True, "data": [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]}

    monkeypatch.setattr(qfs, "signed_get", fake_signed_get)

    require_lead_futures_context("lead-key", "lead-secret", ["BTCUSDT", "ETHUSDT"])


def test_futures_symbols_are_normalized_and_deduplicated() -> None:
    assert parse_futures_symbols("btcusdt", " ethusdt, BTCUSDT,ethusdt ") == ["BTCUSDT", "ETHUSDT"]


def test_futures_source_rejects_regular_futures_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        qfs,
        "signed_get",
        lambda *_args, **_kwargs: {"success": True, "data": {"isLeadTrader": False}},
    )

    with pytest.raises(ValueError, match="not a lead-trading portfolio"):
        require_lead_futures_context("regular-key", "regular-secret", "BTCUSDT")


def test_complete_futures_rebuild_accepts_full_history_and_value_revisions() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.8529},
        {"date": "2026-06-22", "pct": -0.8969},
        {"date": "2026-06-24", "pct": 2.9086},
    ]
    rebuilt = [
        {"date": "2026-04-23", "pct": -0.8528},
        {"date": "2026-06-22", "pct": -0.8968},
        {"date": "2026-06-24", "pct": 2.9087},
        {"date": "2026-06-29", "pct": 1.7729},
    ]

    assert require_complete_futures_rebuild(existing, rebuilt) is None


def test_complete_futures_rebuild_rejects_missing_existing_dates() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.8529},
        {"date": "2026-06-24", "pct": 2.9086},
        {"date": "2026-06-29", "pct": 1.7728},
    ]

    with pytest.raises(ValueError, match="incomplete futures API rebuild"):
        require_complete_futures_rebuild(
            existing,
            [
                {"date": "2026-04-23", "pct": -0.8529},
                {"date": "2026-06-29", "pct": 1.7728},
            ],
        )


def test_complete_futures_rebuild_rejects_empty_history() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.8529},
        {"date": "2026-06-24", "pct": 2.9086},
    ]

    with pytest.raises(ValueError, match="empty futures API rebuild"):
        require_complete_futures_rebuild(existing, [])


def test_retained_futures_rebuild_preserves_prefix_and_reanchors_window() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.5},
        {"date": "2026-05-12", "pct": 1.0},
        {"date": "2026-05-14", "pct": 1.5},
        {"date": "2026-06-01", "pct": 2.0},
    ]
    retained_window = [
        {"date": "2026-05-14", "pct": 0.5},
        {"date": "2026-06-01", "pct": 1.0},
        {"date": "2026-08-14", "pct": 1.25},
    ]

    assert merge_retained_futures_rebuild(existing, retained_window) == [
        {"date": "2026-04-23", "pct": -0.5},
        {"date": "2026-05-12", "pct": 1.0},
        {"date": "2026-05-14", "pct": 1.5},
        {"date": "2026-06-01", "pct": 2.0},
        {"date": "2026-08-14", "pct": 2.25},
    ]


def test_retained_futures_rebuild_rejects_overlap_value_mismatch() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.5},
        {"date": "2026-05-12", "pct": 1.0},
        {"date": "2026-05-14", "pct": 1.8},
    ]
    retained_window = [{"date": "2026-05-14", "pct": 0.5}]

    with pytest.raises(ValueError, match="overlap mismatch"):
        merge_retained_futures_rebuild(existing, retained_window)


def test_retained_futures_rebuild_rejects_missing_overlap_date() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.5},
        {"date": "2026-05-12", "pct": 1.0},
        {"date": "2026-05-14", "pct": 1.5},
        {"date": "2026-05-20", "pct": 1.7},
    ]
    retained_window = [
        {"date": "2026-05-14", "pct": 0.5},
        {"date": "2026-08-14", "pct": 1.0},
    ]

    with pytest.raises(ValueError, match="incomplete futures retained-window rebuild"):
        merge_retained_futures_rebuild(existing, retained_window)


def test_options_total_is_rendered_as_percent_of_configured_base() -> None:
    history = [
        {"date": "2026-04-01", "total": 10000.0},
        {"date": "2026-04-02", "total": 10200.0},
        {"date": "2026-04-03", "total": 9900.0},
    ]

    curve = build_options_percent_history(history, base_usd=10000.0)

    assert curve == [
        {"date": "2026-04-01", "pct": 0.0},
        {"date": "2026-04-02", "pct": 2.0},
        {"date": "2026-04-03", "pct": -1.0},
    ]


def test_options_rebase_preserves_history_and_scales_only_new_pnl() -> None:
    history = [
        {"date": "2026-07-15", "pct": 1.25},
        {"date": "2026-07-16", "pct": 2.0},
    ]

    funding_day = update_options_percent_points(
        history,
        day=date(2026, 7, 16),
        total=10000.0,
        base_usd=10000.0,
        rebase_date=date(2026, 7, 16),
        rebase_total_usd=10000.0,
    )
    next_day = update_options_percent_points(
        funding_day,
        day=date(2026, 7, 17),
        total=10100.0,
        base_usd=10000.0,
        rebase_date=date(2026, 7, 16),
        rebase_total_usd=10000.0,
    )

    assert funding_day == history
    assert next_day == [
        {"date": "2026-07-15", "pct": 1.25},
        {"date": "2026-07-16", "pct": 2.0},
        {"date": "2026-07-17", "pct": 3.0},
    ]


def test_options_rebase_rejects_missing_public_anchor() -> None:
    with pytest.raises(ValueError, match="missing public options rebase anchor"):
        update_options_percent_points(
            [],
            day=date(2026, 7, 17),
            total=10100.0,
            base_usd=10000.0,
            rebase_date=date(2026, 7, 16),
            rebase_total_usd=10000.0,
        )


def test_default_snapshot_is_public_and_sanitized() -> None:
    snapshot = default_quant_fund_snapshot()
    text = str(snapshot)

    assert snapshot["futures"]["label"] == "期货"
    assert snapshot["options"]["label"] == "期权"
    assert snapshot["futures"]["status"] == "missing_base"
    assert "base_configured" not in text
    assert "trade_count" not in text
    assert "API_KEY" not in text
    assert "SECRET" not in text
    assert "BINANCE" not in text
    assert "BTCUSDT" not in text
    assert "USDT" not in text
    assert "USDC" not in text


def test_api_futures_update_writes_only_public_percent_points(monkeypatch, tmp_path) -> None:
    for name in [
        "QUANT_FUND_OPTIONS_BASE_USD",
        "BINANCE_OPTION_API_KEY",
        "BINANCE_OPTION_API_SECRET",
        "QUANT_FUND_FUTURES_TRADES_CSV",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QUANT_FUND_START_DATE", "2026-04-01")
    monkeypatch.setenv("QUANT_FUND_FUTURES_BASE_USD", "1000")
    monkeypatch.setenv("QUANT_FUND_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_SECRET", "test-secret")
    monkeypatch.setattr(qfs, "load_existing_public_snapshot", lambda: {})
    monkeypatch.setattr(qfs, "require_lead_futures_context", lambda *_args: None)
    monkeypatch.setattr(
        qfs,
        "fetch_futures_trades",
        lambda *_args, **_kwargs: [
            {
                "time": utc_ms(2026, 4, 1),
                "symbol": "BTCUSDT",
                "orderId": "raw-order",
                "quoteQty": "1000",
                "realizedPnl": "30",
                "commission": "1.5",
                "commissionAsset": "USDT",
            },
            {
                "time": utc_ms(2026, 4, 2),
                "symbol": "BTCUSDT",
                "id": "raw-trade",
                "quoteQty": "900",
                "realizedPnl": "-10",
                "commission": "0.5",
                "commissionAsset": "USDT",
            },
        ],
    )

    snapshot = qfs.build_snapshot()
    out = tmp_path / "quant_fund_snapshot.json"
    qfs.write_public_snapshot(snapshot, out)
    text = out.read_text(encoding="utf-8")

    assert snapshot["futures"]["status"] == "ok"
    assert snapshot["futures"]["points"] == [
        {"date": "2026-04-01", "pct": 2.85},
        {"date": "2026-04-02", "pct": 1.8},
    ]
    assert snapshot["futures"]["latest_pct"] == 1.8
    for marker in [
        "BTCUSDT",
        "USDT",
        "orderId",
        "raw-order",
        "raw-trade",
        "quoteQty",
        "commission",
        "commissionAsset",
        "realizedPnl",
        "test-key",
        "test-secret",
    ]:
        assert marker not in text


def test_api_futures_update_combines_extra_symbol_from_effective_date(monkeypatch) -> None:
    for name in [
        "QUANT_FUND_OPTIONS_BASE_USD",
        "BINANCE_OPTION_API_KEY",
        "BINANCE_OPTION_API_SECRET",
        "QUANT_FUND_FUTURES_TRADES_CSV",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QUANT_FUND_START_DATE", "2026-04-01")
    monkeypatch.setenv("QUANT_FUND_FUTURES_BASE_USD", "1000")
    monkeypatch.setenv("QUANT_FUND_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("QUANT_FUND_EXTRA_SYMBOLS", "ETHUSDT")
    monkeypatch.setenv("QUANT_FUND_EXTRA_SYMBOLS_START_DATE", "2026-08-22")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_SECRET", "test-secret")
    monkeypatch.setattr(qfs, "load_existing_public_snapshot", lambda: {})
    checked_symbols = []
    calls = []

    def fake_context(_key, _secret, symbols):
        checked_symbols.extend(symbols)

    def fake_fetch(_key, _secret, symbol, start, _end):
        calls.append((symbol, start))
        if symbol == "BTCUSDT":
            return [
                {
                    "time": utc_ms(2026, 4, 1),
                    "realizedPnl": "10",
                    "commission": "0",
                    "commissionAsset": "USDT",
                }
            ]
        return [
            {
                "time": utc_ms(2026, 8, 22),
                "realizedPnl": "20",
                "commission": "0",
                "commissionAsset": "USDT",
            }
        ]

    monkeypatch.setattr(qfs, "require_lead_futures_context", fake_context)
    monkeypatch.setattr(qfs, "fetch_futures_trades", fake_fetch)

    snapshot = qfs.build_snapshot()

    assert checked_symbols == ["BTCUSDT", "ETHUSDT"]
    assert calls == [("BTCUSDT", date(2026, 4, 1)), ("ETHUSDT", date(2026, 8, 22))]
    assert snapshot["futures"]["status"] == "ok"
    assert snapshot["futures"]["points"] == [
        {"date": "2026-04-01", "pct": 1.0},
        {"date": "2026-08-22", "pct": 3.0},
    ]
    assert "BTCUSDT" not in str(snapshot)
    assert "ETHUSDT" not in str(snapshot)


def test_api_futures_update_rebuilds_full_history_from_configured_start(monkeypatch) -> None:
    for name in [
        "QUANT_FUND_OPTIONS_BASE_USD",
        "BINANCE_OPTION_API_KEY",
        "BINANCE_OPTION_API_SECRET",
        "QUANT_FUND_FUTURES_TRADES_CSV",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QUANT_FUND_START_DATE", "2026-04-01")
    monkeypatch.setenv("QUANT_FUND_FUTURES_BASE_USD", "1000")
    monkeypatch.setenv("QUANT_FUND_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_SECRET", "test-secret")
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {
            "futures": {
                "points": [
                    {"date": "2026-04-23", "pct": -0.8},
                    {"date": "2026-06-24", "pct": 2.9},
                    {"date": "2026-06-29", "pct": 2.8},
                ]
            }
        },
    )
    calls = []

    def fake_fetch(_key, _secret, _symbol, start, end):
        calls.append((start, end))
        return [
            {
                "time": utc_ms(2026, 4, 23),
                "realizedPnl": "-7",
                "commission": "1",
                "commissionAsset": "USDT",
            },
            {
                "time": utc_ms(2026, 6, 24),
                "realizedPnl": "38",
                "commission": "1",
                "commissionAsset": "USDT",
            },
            {
                "time": utc_ms(2026, 6, 29),
                "realizedPnl": "-10",
                "commission": "1",
                "commissionAsset": "USDT",
            }
        ]

    monkeypatch.setattr(qfs, "fetch_futures_trades", fake_fetch)
    monkeypatch.setattr(qfs, "require_lead_futures_context", lambda *_args: None)

    snapshot = qfs.build_snapshot()

    assert calls[0][0] == date(2026, 4, 1)
    assert snapshot["futures"]["status"] == "ok"
    assert snapshot["futures"]["points"] == [
        {"date": "2026-04-23", "pct": -0.8},
        {"date": "2026-06-24", "pct": 2.9},
        {"date": "2026-06-29", "pct": 1.8},
    ]


def test_api_futures_update_preserves_public_curve_when_rebuild_is_incomplete(monkeypatch) -> None:
    for name in [
        "QUANT_FUND_OPTIONS_BASE_USD",
        "BINANCE_OPTION_API_KEY",
        "BINANCE_OPTION_API_SECRET",
        "QUANT_FUND_FUTURES_TRADES_CSV",
    ]:
        monkeypatch.delenv(name, raising=False)
    existing = [
        {"date": "2026-04-23", "pct": -0.8},
        {"date": "2026-06-24", "pct": 2.9},
    ]
    monkeypatch.setenv("QUANT_FUND_START_DATE", "2026-04-01")
    monkeypatch.setenv("QUANT_FUND_FUTURES_BASE_USD", "1000")
    monkeypatch.setenv("QUANT_FUND_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_SECRET", "test-secret")
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {"futures": {"points": existing}},
    )
    monkeypatch.setattr(qfs, "require_lead_futures_context", lambda *_args: None)
    monkeypatch.setattr(
        qfs,
        "fetch_futures_trades",
        lambda *_args, **_kwargs: [
            {
                "time": utc_ms(2026, 6, 24),
                "realizedPnl": "29",
                "commission": "0",
                "commissionAsset": "USDT",
            }
        ],
    )

    snapshot = qfs.build_snapshot()

    assert snapshot["futures"]["status"] == "error"
    assert snapshot["futures"]["error"] == "ValueError"
    assert snapshot["futures"]["points"] == existing


def test_api_options_update_uses_dedicated_option_futures_credentials(monkeypatch, tmp_path) -> None:
    for name in ["QUANT_FUND_FUTURES_BASE_USD", "QUANT_FUND_FUTURES_TRADES_CSV", "QUANT_FUND_SYMBOL"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_DATE", raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD", raising=False)
    monkeypatch.setenv("QUANT_FUND_START_DATE", "2026-04-01")
    monkeypatch.setenv("QUANT_FUND_OPTIONS_BASE_USD", "1000")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_KEY", "lead-futures-key")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_SECRET", "lead-futures-secret")
    monkeypatch.setenv("BINANCE_OPTION_API_KEY", "test-option-key")
    monkeypatch.setenv("BINANCE_OPTION_API_SECRET", "test-option-secret")
    monkeypatch.setenv("BINANCE_OPTION_FUTURES_API_KEY", "option-futures-key")
    monkeypatch.setenv("BINANCE_OPTION_FUTURES_API_SECRET", "option-futures-secret")
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {"options": {"points": [{"date": "2026-04-01", "pct": -1.0}]}},
    )
    monkeypatch.setattr(qfs, "fetch_option_wallet_total", lambda *_args, **_kwargs: 910.0)
    balance_calls = []

    def fake_futures_stable_balance(api_key, api_secret):
        balance_calls.append((api_key, api_secret))
        return 110.0

    monkeypatch.setattr(qfs, "fetch_futures_stable_balance", fake_futures_stable_balance)

    snapshot = qfs.build_snapshot()
    out = tmp_path / "quant_fund_snapshot.json"
    qfs.write_public_snapshot(snapshot, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    text = json.dumps(payload, ensure_ascii=False)

    assert payload["options"]["status"] == "ok"
    assert balance_calls == [("option-futures-key", "option-futures-secret")]
    assert payload["options"]["points"][0] == {"date": "2026-04-01", "pct": -1.0}
    assert payload["options"]["points"][-1]["pct"] == 2.0
    assert payload["options"]["latest_pct"] == 2.0
    for marker in [
        "USDT",
        "USDC",
        "option_usdt_value",
        "futures_usdc",
        "total_usdt_usdc",
        "option_positions",
        "futures_positions",
        "lead-futures-key",
        "lead-futures-secret",
        "test-option-key",
        "test-option-secret",
        "option-futures-key",
        "option-futures-secret",
        "910.0",
        "110.0",
        "1020.0",
    ]:
        assert marker not in text
    assert "option_usdt_value" not in text
    assert "futures_usdc" not in text
    assert "total_usdt_usdc" not in text


def test_api_options_rebase_chain_links_without_changing_history(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
            return value if tz is not None else value.replace(tzinfo=None)

    for name in ["QUANT_FUND_FUTURES_BASE_USD", "QUANT_FUND_FUTURES_TRADES_CSV", "QUANT_FUND_SYMBOL"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QUANT_FUND_OPTIONS_BASE_USD", "1000")
    monkeypatch.setenv("QUANT_FUND_OPTIONS_REBASE_DATE", "2026-07-16")
    monkeypatch.setenv("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD", "1000")
    monkeypatch.setenv("BINANCE_OPTION_API_KEY", "test-option-key")
    monkeypatch.setenv("BINANCE_OPTION_API_SECRET", "test-option-secret")
    monkeypatch.setenv("BINANCE_OPTION_FUTURES_API_KEY", "option-futures-key")
    monkeypatch.setenv("BINANCE_OPTION_FUTURES_API_SECRET", "option-futures-secret")
    monkeypatch.setattr(qfs, "datetime", FixedDateTime)
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {
            "options": {
                "points": [
                    {"date": "2026-07-15", "pct": 1.25},
                    {"date": "2026-07-16", "pct": 2.0},
                ]
            }
        },
    )
    monkeypatch.setattr(qfs, "fetch_option_wallet_total", lambda *_args, **_kwargs: 900.0)
    monkeypatch.setattr(qfs, "fetch_futures_stable_balance", lambda *_args, **_kwargs: 110.0)

    snapshot = qfs.build_snapshot()

    assert snapshot["options"]["status"] == "ok"
    assert snapshot["options"]["points"] == [
        {"date": "2026-07-15", "pct": 1.25},
        {"date": "2026-07-16", "pct": 2.0},
        {"date": "2026-07-17", "pct": 3.0},
    ]
    assert "rebase" not in json.dumps(snapshot, ensure_ascii=False).lower()


def test_incomplete_options_rebase_config_preserves_existing_curve(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_FUND_OPTIONS_BASE_USD", "1000")
    monkeypatch.setenv("QUANT_FUND_OPTIONS_REBASE_DATE", "2026-07-16")
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD", raising=False)
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {"options": {"points": [{"date": "2026-07-16", "pct": 2.0}]}},
    )

    snapshot = qfs.build_snapshot()

    assert snapshot["options"]["status"] == "rebase_config_error"
    assert snapshot["options"]["points"] == [{"date": "2026-07-16", "pct": 2.0}]


def test_api_options_update_does_not_reuse_trading_futures_credentials(monkeypatch) -> None:
    for name in ["QUANT_FUND_FUTURES_BASE_USD", "QUANT_FUND_FUTURES_TRADES_CSV", "QUANT_FUND_SYMBOL"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("BINANCE_OPTION_FUTURES_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_OPTION_FUTURES_API_SECRET", raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_DATE", raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD", raising=False)
    monkeypatch.setenv("QUANT_FUND_OPTIONS_BASE_USD", "1000")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_KEY", "lead-futures-key")
    monkeypatch.setenv("BINANCE_LEAD_FUTURES_API_SECRET", "lead-futures-secret")
    monkeypatch.setenv("BINANCE_OPTION_API_KEY", "test-option-key")
    monkeypatch.setenv("BINANCE_OPTION_API_SECRET", "test-option-secret")
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {"options": {"points": [{"date": "2026-06-26", "pct": -3.5040}]}},
    )

    def fail_if_trading_futures_credentials_are_reused(*_args, **_kwargs):
        raise AssertionError("options curve must not reuse trading futures credentials")

    monkeypatch.setattr(qfs, "fetch_futures_stable_balance", fail_if_trading_futures_credentials_are_reused)

    snapshot = qfs.build_snapshot()

    assert snapshot["options"]["status"] == "stale"
    assert snapshot["options"]["points"] == [{"date": "2026-06-26", "pct": -3.504}]


def test_option_wallet_total_uses_sapi_options_wallet(monkeypatch) -> None:
    calls = []

    def fake_signed_get(base, path, api_key, api_secret, params=None):
        calls.append((base, path, api_key, api_secret, params))
        return [
            {"walletName": "Spot", "balance": "100"},
            {"walletName": "Options", "balance": "2450.5"},
        ]

    monkeypatch.setattr(qfs, "signed_get", fake_signed_get)

    assert qfs.fetch_option_wallet_total("option-key", "option-secret") == 2450.5
    assert calls == [
        (
            qfs.SAPI_BASE,
            "/sapi/v1/asset/wallet/balance",
            "option-key",
            "option-secret",
            {"quoteAsset": "USDT"},
        )
    ]


def test_futures_stable_balance_matches_options_publisher_usdc_only(monkeypatch) -> None:
    def fake_signed_get(base, path, api_key, api_secret, params=None):
        return [
            {"asset": "USDT", "balance": "4000", "crossUnPnl": "0"},
            {"asset": "USDC", "balance": "496", "crossUnPnl": "4"},
        ]

    monkeypatch.setattr(qfs, "signed_get", fake_signed_get)

    assert qfs.fetch_futures_stable_balance("futures-key", "futures-secret") == 500.0


def test_base_usd_has_no_repository_default(monkeypatch) -> None:
    monkeypatch.delenv("QUANT_FUND_FUTURES_BASE_USD", raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_BASE_USD", raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_DATE", raising=False)
    monkeypatch.delenv("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD", raising=False)

    assert env_float("QUANT_FUND_FUTURES_BASE_USD") is None
    assert env_float("QUANT_FUND_OPTIONS_BASE_USD") is None
    assert env_date("QUANT_FUND_OPTIONS_REBASE_DATE") is None
    assert env_float("QUANT_FUND_OPTIONS_REBASE_TOTAL_USD") is None


def test_options_seed_points_are_percent_only_without_raw_amounts() -> None:
    points = built_in_options_seed_points()
    text = str(points)

    assert points == [
        {"date": "2026-06-22", "pct": 0.0021},
        {"date": "2026-06-23", "pct": -0.3457},
        {"date": "2026-06-24", "pct": 0.4213},
        {"date": "2026-06-25", "pct": -1.1163},
        {"date": "2026-06-26", "pct": -3.5040},
    ]
    assert "USDT" not in text
    assert "USDC" not in text
