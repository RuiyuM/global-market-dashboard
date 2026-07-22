#!/usr/bin/env python3
"""Regression tests for bounded incremental KORIBOR production refreshes."""

from __future__ import annotations

from datetime import date

import market_dashboard
import production_update
from fetch_japan_bond_ohlc import close_only_row


def test_production_koribor_patch_uses_oldest_requested_cache_with_overlap(monkeypatch, tmp_path) -> None:
    dashboard_data = tmp_path / "dashboard" / "data"
    monkeypatch.setattr(production_update, "ROOT", tmp_path)
    monkeypatch.setattr(production_update, "DASHBOARD_DATA", dashboard_data)
    for key, latest in (("KR_1M", "2026-07-20"), ("KR_3M", "2026-07-18"), ("KR_6M", "2026-07-20")):
        spec = next(spec for spec, source, _tenor in production_update.KOREA_BOND_SPECS if source == "smbs-koribor" and spec.key == key)
        market_dashboard.write_ohlc(
            dashboard_data / spec.cache_file,
            [close_only_row(latest, 3.0)],
        )
    calls: list[tuple[date, date]] = []

    def fake_koribor(start_day: date, end_day: date):
        calls.append((start_day, end_day))
        return {
            tenor: [close_only_row("2026-07-21", value)]
            for tenor, value in (("1M", 2.8), ("3M", 3.0), ("6M", 3.26))
        }

    monkeypatch.setattr(production_update, "fetch_smbs_koribor_rows_by_tenor", fake_koribor)

    patched, failures = production_update.patch_smbs_koribor(
        ["KR_1M", "KR_3M", "KR_6M"],
        date(2025, 1, 1),
        date(2026, 7, 21),
    )

    assert failures == []
    assert calls == [(date(2026, 7, 11), date(2026, 7, 21))]
    assert {item["key"] for item in patched} == {"KR_1M", "KR_3M", "KR_6M"}
