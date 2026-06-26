#!/usr/bin/env python3
"""Tests for the private quant-fund snapshot builder."""

from __future__ import annotations

from datetime import date, datetime, timezone

from quant_fund_snapshot import (
    aggregate_futures_trade_curve,
    build_options_percent_history,
    built_in_options_seed_points,
    default_quant_fund_snapshot,
    env_float,
)


def utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def test_futures_trades_are_rendered_as_percent_of_configured_base() -> None:
    trades = [
        {"time": utc_ms(2026, 4, 1), "realizedPnl": "30"},
        {"time": utc_ms(2026, 4, 1), "realizedPnl": "-10"},
        {"time": utc_ms(2026, 4, 2), "realizedPnl": "5"},
    ]

    curve = aggregate_futures_trade_curve(trades, base_usd=1000.0, start=date(2026, 4, 1))

    assert curve == [
        {"date": "2026-04-01", "pct": 2.0},
        {"date": "2026-04-02", "pct": 2.5},
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
    assert snapshot["futures"]["base_configured"] is False
    assert snapshot["options"]["base_configured"] is False
    assert "API_KEY" not in text
    assert "SECRET" not in text
    assert "BINANCE" not in text
    assert "BTCUSDT" not in text
    assert "USDT" not in text
    assert "USDC" not in text
    assert "option_usdt_value" not in text
    assert "futures_usdc" not in text
    assert "total_usdt_usdc" not in text
    assert "BTC-260" not in text


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
    assert "2500.051351" not in text
    assert "2412.401196" not in text
    assert "BTC-260" not in text
    assert "USDT" not in text
    assert "USDC" not in text
