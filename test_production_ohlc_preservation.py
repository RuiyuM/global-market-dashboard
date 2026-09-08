from argparse import Namespace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import market_dashboard as dashboard
import production_update as production


def candle(day, close, complete=True):
    return {"date": day, "open": close, "high": close + (0.1 if complete else 0),
            "low": close - (0.1 if complete else 0), "close": close}


def test_weekly_patch_preserves_newer_production_bar(monkeypatch, tmp_path):
    monkeypatch.setattr(production, "ROOT", tmp_path)
    monkeypatch.setattr(production, "DASHBOARD_DATA", tmp_path / "dashboard/data")
    monkeypatch.setattr(production, "LOCAL_DATA", tmp_path / "data")
    local = tmp_path / "dashboard/data/JP_2Y.csv"
    dashboard.write_ohlc(local, [candle("2026-09-04", 1.0), candle("2026-09-07", 1.2, False)])
    args = Namespace(server="root@example.invalid", server_dir="/opt/dashboard", ssh_key=Path("/key"))

    def download(command, **kwargs):
        manifest = Path(next(item.split("=", 1)[1] for item in command if item.startswith("--files-from=")))
        assert manifest.read_text().splitlines() == ["dashboard/data/JP_2Y.csv"]
        staging = Path(command[-1])
        dashboard.write_ohlc(staging / "dashboard/data/JP_2Y.csv", [
            candle("2026-09-07", 1.2, False), candle("2026-09-08", 1.3),
        ])

    monkeypatch.setattr(production, "run_command", download)
    production.sync_server_ohlc_caches(args, ["JP_2Y"])
    monkeypatch.setattr(production, "fetch_investing_html", lambda *a: "fixture")
    monkeypatch.setattr(production, "rows_from_investing_html", lambda html: [
        candle("2026-09-07", 1.21),
    ])
    monkeypatch.setattr(production, "write_investing_csv", lambda *a: None)
    patched, failures = production.patch_investing(
        ["JP_2Y"], {"investing_symbol_map": {"JP_2Y": "JP2Y"}},
        date(2026, 9, 1), date(2026, 9, 7),
    )
    assert not failures
    assert patched[0]["key"] == "JP_2Y"
    rows = dashboard.read_ohlc(local)
    assert [row["date"].isoformat() for row in rows] == ["2026-09-04", "2026-09-07", "2026-09-08"]
    assert rows[1]["close"] == 1.21
    assert rows[2]["close"] == 1.3
    assert dashboard.has_complete_ohlc(rows[2])


def test_no_candidates_do_not_download(monkeypatch):
    monkeypatch.setattr(production, "run_command", lambda *a, **kw: (_ for _ in ()).throw(AssertionError()))
    production.sync_server_ohlc_caches(SimpleNamespace(), [])
