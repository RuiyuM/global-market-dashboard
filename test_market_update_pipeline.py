#!/usr/bin/env python3
"""Regression tests for production source auditing and cache-safe updates."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import audit_market_sources
import market_dashboard
import production_update


def test_fetch_record_status_distinguishes_degraded_from_success() -> None:
    rows = [{"date": "2026-07-10"}]

    assert market_dashboard.fetch_record_status(rows) == "ok"
    assert market_dashboard.fetch_record_status(rows, "HTTP Error 403") == "degraded"
    assert market_dashboard.fetch_record_status([], "HTTP Error 429") == "error"
    assert market_dashboard.fetch_record_status([]) == "empty"


def test_merge_ohlc_rows_never_replaces_complete_bar_with_close_only() -> None:
    complete = {
        "date": "2026-07-13",
        "open": 2.737,
        "high": 2.802,
        "low": 2.733,
        "close": 2.780,
    }
    close_only = {
        "date": "2026-07-13",
        "open": 2.790,
        "high": 2.790,
        "low": 2.790,
        "close": 2.790,
    }

    assert market_dashboard.merge_ohlc_rows([complete], [close_only]) == [complete]
    assert market_dashboard.merge_ohlc_rows([close_only], [complete]) == [complete]


def test_empty_wscn_response_does_not_overwrite_cache(tmp_path, monkeypatch) -> None:
    spec = market_dashboard.SeriesSpec("TEST", "Test", "bond", "wscn", "TEST.OTC", "TEST.csv")
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "WSCN_SPECS", [spec])
    monkeypatch.setattr(market_dashboard, "MOEX_SPECS", [])
    monkeypatch.setattr(market_dashboard, "YAHOO_SPECS", [])
    monkeypatch.setattr(market_dashboard, "NIKKEI_SPECS", [])
    monkeypatch.setattr(market_dashboard, "CHINA_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "GERMANY_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "KOREA_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "INVESTING_SPECS", [])
    monkeypatch.setattr(market_dashboard, "fetch_wscn_ohlc", lambda *_args: [])
    cached = [{"date": "2026-07-09", "timestamp": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}]
    market_dashboard.write_ohlc(tmp_path / spec.cache_file, cached)

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=10, lookback_days=30, sleep_sec=0))

    assert records[0]["status"] == "empty"
    assert market_dashboard.read_ohlc(tmp_path / spec.cache_file)[-1]["date"].isoformat() == "2026-07-09"


def test_partial_wscn_response_merges_with_existing_history(tmp_path, monkeypatch) -> None:
    spec = market_dashboard.SeriesSpec("TEST", "Test", "equity", "wscn", "TEST.SS", "TEST.csv")
    cached = [
        {"date": "2026-07-16", "timestamp": 1, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        {"date": "2026-07-17", "timestamp": 2, "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5},
    ]
    incoming = [
        {"date": "2026-07-20", "timestamp": 3, "open": 101.5, "high": 103.0, "low": 101.0, "close": 102.5}
    ]
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "WSCN_SPECS", [spec])
    monkeypatch.setattr(market_dashboard, "MOEX_SPECS", [])
    monkeypatch.setattr(market_dashboard, "YAHOO_SPECS", [])
    monkeypatch.setattr(market_dashboard, "NIKKEI_SPECS", [])
    monkeypatch.setattr(market_dashboard, "CHINA_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "GERMANY_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "KOREA_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "INVESTING_SPECS", [])
    monkeypatch.setattr(market_dashboard, "fetch_wscn_ohlc", lambda *_args: incoming)
    market_dashboard.write_ohlc(tmp_path / spec.cache_file, cached)

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=10, lookback_days=30, sleep_sec=0))

    rows = market_dashboard.read_ohlc(tmp_path / spec.cache_file)
    assert records[0]["status"] == "ok"
    assert records[0]["rows"] == "3"
    assert [item["date"] for item in rows] == [date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20)]


def test_wscn_overlay_excludes_close_only_holiday_row(tmp_path, monkeypatch) -> None:
    spec = market_dashboard.SeriesSpec(
        "TEST_WSCN_OHLC", "Test overlay", "bond", "wscn-overlay", "TEST.OTC", "TEST.csv"
    )
    complete = {
        "date": "2026-07-17",
        "timestamp": 1,
        "open": 1.90,
        "high": 1.97,
        "low": 1.89,
        "close": 1.92,
    }
    holiday_close_only = {
        "date": "2026-07-20",
        "timestamp": 2,
        "open": 1.93,
        "high": 1.93,
        "low": 1.93,
        "close": 1.93,
    }
    monkeypatch.setattr(market_dashboard, "DASHBOARD_DATA", tmp_path)
    monkeypatch.setattr(market_dashboard, "WSCN_SPECS", [spec])
    monkeypatch.setattr(market_dashboard, "WSCN_OHLC_OVERLAY_TARGETS", {spec.key: "TEST"})
    monkeypatch.setattr(market_dashboard, "MOEX_SPECS", [])
    monkeypatch.setattr(market_dashboard, "YAHOO_SPECS", [])
    monkeypatch.setattr(market_dashboard, "NIKKEI_SPECS", [])
    monkeypatch.setattr(market_dashboard, "CHINA_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "GERMANY_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "KOREA_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "JAPAN_BOND_SPECS", [])
    monkeypatch.setattr(market_dashboard, "INVESTING_SPECS", [])
    monkeypatch.setattr(
        market_dashboard,
        "fetch_wscn_ohlc",
        lambda *_args: [complete, holiday_close_only],
    )
    market_dashboard.write_ohlc(tmp_path / spec.cache_file, [holiday_close_only])

    records = market_dashboard.fetch_all(SimpleNamespace(wscn_count=10, lookback_days=30, sleep_sec=0))

    assert records[0]["status"] == "ok"
    assert records[0]["latest"] == "2026-07-17"
    cached = market_dashboard.read_ohlc(tmp_path / spec.cache_file)
    assert len(cached) == 2
    assert cached[0]["date"] == date(2026, 7, 17)
    assert cached[0]["open"] == 1.90
    assert cached[0]["close"] == 1.92
    assert cached[1]["date"] == date(2026, 7, 20)
    assert not market_dashboard.has_complete_ohlc(cached[1])


def test_no_fetch_context_preserves_last_network_audit(tmp_path, monkeypatch) -> None:
    snapshot = tmp_path / "latest_market_snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-10T17:35:00-04:00",
                "last_fetch_at": "2026-07-10T17:34:00-04:00",
                "fetch_records": [{"key": "US_EQUITY", "status": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_dashboard, "SNAPSHOT_JSON", snapshot)

    records, last_fetch_at = market_dashboard.load_previous_fetch_context()

    assert records == [{"key": "US_EQUITY", "status": "ok"}]
    assert last_fetch_at == "2026-07-10T17:34:00-04:00"


def test_source_audit_accepts_expected_investing_degradation() -> None:
    snapshot = {
        "generated_at": "2026-07-10T17:35:00-04:00",
        "last_fetch_at": "2026-07-10T17:34:00-04:00",
        "fetch_mode": "network",
        "fetch_records": [
            {"key": "JP_1M", "status": "degraded", "latest": "2026-07-10", "error": "Investing.com history skipped"},
            {"key": "US_EQUITY", "status": "ok", "latest": "2026-07-10", "error": ""},
        ],
    }
    policy = {
        "server_blocked": {"investing.com": {"keys": ["JP_1M"]}},
        "yahoo_patch_on_failure": ["US_EQUITY"],
        "local_required": [],
    }

    report = audit_market_sources.audit_sources(
        snapshot,
        policy,
        now=datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc),
    )

    assert report["ok"] is True
    assert report["server_ok"] is True
    assert report["local_patch_candidates"] == []
    assert report["warnings"] == ["JP_1M: expected server degradation; fallback/cache active"]


def test_source_audit_routes_yahoo_failure_to_local_patch() -> None:
    snapshot = {
        "generated_at": "2026-07-10T17:35:00-04:00",
        "last_fetch_at": "2026-07-10T17:34:00-04:00",
        "fetch_mode": "network",
        "fetch_records": [
            {"key": "US_EQUITY", "status": "error", "latest": "", "error": "HTTP Error 429: Too Many Requests"},
        ],
    }
    policy = {
        "server_blocked": {},
        "yahoo_patch_on_failure": ["US_EQUITY"],
        "local_required": [],
    }

    report = audit_market_sources.audit_sources(
        snapshot,
        policy,
        now=datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc),
    )

    assert report["ok"] is False
    assert report["server_ok"] is True
    assert report["local_patch_candidates"] == ["US_EQUITY"]
    assert "HTTP Error 429" in report["errors"][0]


def test_source_audit_treats_optional_rubcny_yahoo_cross_check_as_warning() -> None:
    snapshot = {
        "generated_at": "2026-07-13T10:00:00-04:00",
        "last_fetch_at": "2026-07-13T09:59:00-04:00",
        "fetch_mode": "network",
        "fetch_records": [
            {"key": "RUBCNY_MOEX", "status": "ok", "latest": "2026-07-13", "error": ""},
            {"key": "RUBCNY_YAHOO", "status": "error", "latest": "", "error": "HTTP Error 429"},
        ],
    }
    policy = {
        "server_blocked": {},
        "yahoo_patch_on_failure": [],
        "smbs_patch_on_failure": [],
        "optional_sources": ["RUBCNY_YAHOO"],
        "local_required": [],
    }

    report = audit_market_sources.audit_sources(
        snapshot,
        policy,
        now=datetime(2026, 7, 13, 14, 1, tzinfo=timezone.utc),
    )

    assert report["ok"] is True
    assert report["local_patch_candidates"] == []
    assert report["warnings"] == [
        "RUBCNY_YAHOO: optional cross-check unavailable: status=error HTTP Error 429"
    ]


def test_current_local_patch_remediates_yahoo_server_failure() -> None:
    snapshot = {
        "generated_at": "2026-07-10T17:40:00-04:00",
        "last_fetch_at": "2026-07-10T17:34:00-04:00",
        "fetch_mode": "cache",
        "local_patch_report": {
            "patched_at": "2026-07-10T21:38:00+00:00",
            "keys": ["US_EQUITY"],
        },
        "fetch_records": [
            {"key": "US_EQUITY", "status": "error", "latest": "", "error": "HTTP Error 429"},
        ],
    }
    policy = {
        "server_blocked": {},
        "yahoo_patch_on_failure": ["US_EQUITY"],
        "local_required": [],
    }

    report = audit_market_sources.audit_sources(
        snapshot,
        policy,
        now=datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc),
    )

    assert report["ok"] is True
    assert report["server_ok"] is True
    assert report["patched_keys"] == ["US_EQUITY"]
    assert report["local_patch_candidates"] == []


def test_source_audit_routes_smbs_timeout_to_local_patch() -> None:
    snapshot = {
        "generated_at": "2026-07-13T10:00:00-04:00",
        "last_fetch_at": "2026-07-13T09:59:00-04:00",
        "fetch_mode": "network",
        "fetch_records": [
            {"key": "KR_1M", "status": "error", "latest": "", "error": "timed out"},
        ],
    }
    policy = {
        "server_blocked": {},
        "yahoo_patch_on_failure": [],
        "smbs_patch_on_failure": ["KR_1M"],
        "local_required": [],
    }

    report = audit_market_sources.audit_sources(
        snapshot,
        policy,
        now=datetime(2026, 7, 13, 14, 1, tzinfo=timezone.utc),
    )

    assert report["ok"] is False
    assert report["server_ok"] is True
    assert report["local_patch_candidates"] == ["KR_1M"]


def test_patch_smbs_koribor_writes_only_requested_public_series(tmp_path, monkeypatch) -> None:
    dashboard_data = tmp_path / "dashboard" / "data"
    monkeypatch.setattr(production_update, "ROOT", tmp_path)
    monkeypatch.setattr(production_update, "DASHBOARD_DATA", dashboard_data)
    monkeypatch.setattr(
        production_update,
        "fetch_smbs_koribor_rows_by_tenor",
        lambda *_args: {
            "1M": [
                {
                    "date": "2026-07-13",
                    "open": 2.68,
                    "high": 2.68,
                    "low": 2.68,
                    "close": 2.68,
                }
            ]
        },
    )

    patched, failures = production_update.patch_smbs_koribor(
        ["KR_1M"],
        date(2026, 7, 1),
        date(2026, 7, 13),
    )

    assert failures == []
    assert patched[0]["key"] == "KR_1M"
    assert patched[0]["files"] == ["dashboard/data/KR_1M.csv"]
    rows = market_dashboard.read_ohlc(dashboard_data / "KR_1M.csv")
    assert rows[-1]["date"] == date(2026, 7, 13)
    assert rows[-1]["close"] == 2.68


def test_patch_moex_index_writes_official_public_series(tmp_path, monkeypatch) -> None:
    dashboard_data = tmp_path / "dashboard" / "data"
    monkeypatch.setattr(production_update, "ROOT", tmp_path)
    monkeypatch.setattr(production_update, "DASHBOARD_DATA", dashboard_data)
    monkeypatch.setattr(
        production_update,
        "fetch_moex_index_ohlc",
        lambda *_args: [
            {
                "date": "2026-07-16",
                "timestamp": 1784160000,
                "open": 2072.9,
                "high": 2074.49,
                "low": 2020.34,
                "close": 2021.9,
                "volume": 0,
                "source_symbol": "IMOEX",
                "source": "Moscow Exchange ISS official index daily candles; local public-data patch",
            }
        ],
    )

    patched, failures = production_update.patch_moex_indices(
        ["RU_EQUITY"],
        {"local_source_overrides": {"RU_EQUITY": {"provider": "moex_iss", "symbol": "IMOEX"}}},
        date(2026, 7, 1),
        date(2026, 7, 17),
    )

    assert failures == []
    assert patched[0]["key"] == "RU_EQUITY"
    assert patched[0]["files"] == ["dashboard/data/RU_EQUITY.csv"]
    rows = market_dashboard.read_ohlc(dashboard_data / "RU_EQUITY.csv")
    assert rows[-1]["close"] == 2021.9
    assert "IMOEX,Moscow Exchange ISS official index daily candles" in (
        dashboard_data / "RU_EQUITY.csv"
    ).read_text(encoding="utf-8")


def test_upload_allowlist_rejects_private_or_unrelated_files() -> None:
    assert production_update.validate_public_upload_paths(
        ["dashboard/data/US_EQUITY.csv", "data/RU_EQUITY_INVESTING_1D_ohlc.csv", "dashboard/local_patch_report.json"]
    ) == ["dashboard/data/US_EQUITY.csv", "dashboard/local_patch_report.json", "data/RU_EQUITY_INVESTING_1D_ohlc.csv"]

    for path in [".private/quant_fund.env", "dashboard/quant_fund_snapshot.json", "../secret", "/tmp/key"]:
        try:
            production_update.validate_public_upload_paths([path])
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected upload path rejection: {path}")


def test_scheduled_summary_does_not_read_or_print_protected_quant_data(
    monkeypatch, capsys
) -> None:
    snapshot = {
        "generated_at": "2026-08-03T10:00:00-04:00",
        "series_status": [],
        "last_fetch_at": "2026-08-03T09:59:00-04:00",
        "fetch_mode": "network",
        "fetch_records": [],
    }

    def fake_download(_args, path):
        if path == "dashboard/quant_fund_snapshot.json":
            raise AssertionError("scheduled summary must not read protected quant snapshot")
        return snapshot

    monkeypatch.setattr(production_update, "download_json", fake_download)
    monkeypatch.setattr(
        production_update,
        "load_json",
        lambda _path: {
            "server_blocked": {},
            "yahoo_patch_on_failure": [],
            "smbs_patch_on_failure": [],
            "optional_sources": [],
            "local_required": [],
        },
    )

    production_update.print_final_summary(
        SimpleNamespace(redact_quant_summary=True)
    )

    output = capsys.readouterr().out
    assert "FINAL quant protected" in output
    assert "latest_pct" not in output
    assert "futures" not in output
    assert "options" not in output


def test_source_policy_keys_match_dashboard_and_investing_specs() -> None:
    policy = audit_market_sources.load_json(production_update.POLICY_PATH)
    dashboard_keys = set(production_update.dashboard_spec_map())
    blocked = {
        key
        for source in policy["server_blocked"].values()
        for key in source["keys"]
    }
    weekly = set(policy["local_weekly_ohlc"])
    required = set(policy["local_required"])
    overrides = set(policy["local_source_overrides"])
    mapped = set(policy["investing_symbol_map"])

    assert blocked == set(policy["server_fallbacks"])
    assert required <= weekly <= blocked
    assert weekly - overrides <= mapped <= dashboard_keys
    assert required <= overrides <= dashboard_keys
    assert set(policy["yahoo_patch_on_failure"]) <= dashboard_keys
    assert set(policy["smbs_patch_on_failure"]) <= dashboard_keys
    assert set(policy["optional_sources"]) <= dashboard_keys
    assert {
        policy["investing_symbol_map"][key]
        for key in mapped
    } <= set(production_update.INVESTING_BOND_SPECS)
    german_ohlc = {
        "DE_3M",
        "DE_6M",
        "DE_1Y",
        "DE_2Y",
        "DE_3Y",
        "DE_5Y",
        "DE_7Y",
        "DE_10Y",
        "DE_30Y",
    }
    assert {"JP_30Y", *german_ohlc} <= weekly
    assert {"JP_30Y", *german_ohlc} <= mapped
    assert "JP_30Y_INVESTING_ID_23903" in policy["ohlc_overlay_policy"]["rejected"]
    assert "JP_30Y_INVESTING_ID_23904" in policy["ohlc_overlay_policy"]["verified_local_gap_fills"]
    assert policy["ohlc_overlay_policy"]["wscn_daily"] == market_dashboard.WSCN_OHLC_OVERLAY_TARGETS
    for key in ("JP_30Y", *sorted(german_ohlc)):
        dashboard_spec = production_update.dashboard_spec_map()[key]
        investing_spec = production_update.INVESTING_BOND_SPECS[policy["investing_symbol_map"][key]]
        assert dashboard_spec.local_file == investing_spec.output_name
