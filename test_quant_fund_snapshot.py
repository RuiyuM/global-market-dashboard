#!/usr/bin/env python3
"""Tests for the private quant-fund snapshot builder."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import quant_fund_snapshot as qfs
from quant_fund_snapshot import (
    aggregate_futures_trade_curve,
    build_options_percent_history,
    built_in_options_seed_points,
    default_quant_fund_snapshot,
    env_float,
    load_futures_trades_csv,
    merge_percent_points,
)


def utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


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


def test_futures_api_update_appends_to_existing_public_curve_without_resetting() -> None:
    existing = [
        {"date": "2026-04-23", "pct": -0.8529},
        {"date": "2026-06-22", "pct": -0.8969},
        {"date": "2026-06-24", "pct": 2.9086},
    ]
    api_curve = [
        {"date": "2026-06-24", "pct": -0.1976},
        {"date": "2026-06-25", "pct": -0.3966},
        {"date": "2026-06-26", "pct": 7.1930},
    ]

    merged = merge_percent_points(existing, api_curve)

    assert merged == [
        {"date": "2026-04-23", "pct": -0.8529},
        {"date": "2026-06-22", "pct": -0.8969},
        {"date": "2026-06-24", "pct": 2.9086},
        {"date": "2026-06-25", "pct": 2.7096},
        {"date": "2026-06-26", "pct": 10.2992},
    ]


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
    monkeypatch.setenv("BINANCE_FUTURES_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_FUTURES_API_SECRET", "test-secret")
    monkeypatch.setattr(qfs, "load_existing_public_snapshot", lambda: {})
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


def test_api_options_update_writes_only_public_percent_points(monkeypatch, tmp_path) -> None:
    for name in ["QUANT_FUND_FUTURES_BASE_USD", "QUANT_FUND_FUTURES_TRADES_CSV", "QUANT_FUND_SYMBOL"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("QUANT_FUND_START_DATE", "2026-04-01")
    monkeypatch.setenv("QUANT_FUND_OPTIONS_BASE_USD", "1000")
    monkeypatch.setenv("BINANCE_FUTURES_API_KEY", "test-futures-key")
    monkeypatch.setenv("BINANCE_FUTURES_API_SECRET", "test-futures-secret")
    monkeypatch.setenv("BINANCE_OPTION_API_KEY", "test-option-key")
    monkeypatch.setenv("BINANCE_OPTION_API_SECRET", "test-option-secret")
    monkeypatch.setattr(
        qfs,
        "load_existing_public_snapshot",
        lambda: {"options": {"points": [{"date": "2026-04-01", "pct": -1.0}]}},
    )
    monkeypatch.setattr(qfs, "fetch_option_wallet_total", lambda *_args, **_kwargs: 910.0)
    monkeypatch.setattr(qfs, "fetch_futures_stable_balance", lambda *_args, **_kwargs: 110.0)

    snapshot = qfs.build_snapshot()
    out = tmp_path / "quant_fund_snapshot.json"
    qfs.write_public_snapshot(snapshot, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    text = json.dumps(payload, ensure_ascii=False)

    assert payload["options"]["status"] == "ok"
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
        "test-futures-key",
        "test-futures-secret",
        "test-option-key",
        "test-option-secret",
        "910.0",
        "110.0",
        "1020.0",
    ]:
        assert marker not in text
    assert "option_usdt_value" not in text
    assert "futures_usdc" not in text
    assert "total_usdt_usdc" not in text


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

    assert env_float("QUANT_FUND_FUTURES_BASE_USD") is None
    assert env_float("QUANT_FUND_OPTIONS_BASE_USD") is None


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
