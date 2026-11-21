import csv
import io
from datetime import datetime

import pytest

import route_market_flow as flow


WEEK_OLD = "2026.11.1~11.7"
WEEK_AVAILABLE = "2026．11．8～11．14"
WEEK_FUTURE = "2026.11.15~11.21"
SCHEDULE_HTML = """<table>
<tr><th>Release Date</th><th>Subject</th></tr>
<tr><td>November 12, 2026</td><td>November 1 - 7, 2026</td></tr>
<tr><td>November 19, 2026</td><td>November 8 - 14, 2026</td></tr>
<tr><td>November 27, 2026</td><td>November 15 - 21, 2026</td></tr>
<tr><td>December 8, 2026</td><td>November, 2026</td></tr>
<tr><td>July 8, 2027</td><td>June 20 - 26, 2027 / June 27 - July 3, 2027</td></tr>
</table>"""


def mof_fixture(update="November 19, 2026", periods=(WEEK_OLD, WEEK_AVAILABLE)):
    rows = [[""] * 23 for _ in range(14)]
    rows[1][0] = "International Transactions in Securities (Weekly; based on reports from designated major investors)"
    rows[1][19] = f"Final Update  {update}"
    rows[4][19] = "Unit: 100 million Yen"
    rows[8][12] = "2. Portfolio Investment Liabilities"
    rows[11][12], rows[11][15], rows[11][19] = (
        "Equity and investment fund shares", "Long-term debt securities", "Short-term debt securities",
    )
    for column in (14, 17, 21, 22):
        rows[13][column] = "Net"
    for period in periods:
        rows.append([period, *["ignored"] * 11, "413,220", "415,461", "−2,241",
                     "60,244", "53,743", "6,501", "", "48,118", "46,500", "1,618", "5,878"])
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode("cp932")


def now(value="2026-11-21T03:15:00+00:00"):
    return datetime.fromisoformat(value)


def live_fixture(monkeypatch, *, csv_body=None, schedule=SCHEDULE_HTML):
    fixtures = {
        flow.MOF_CSV_URL: mof_fixture() if csv_body is None else csv_body,
        flow.MOF_SCHEDULE_URL: schedule.encode(),
    }
    monkeypatch.setattr(flow, "_download", fixtures.__getitem__)


def result_rows(data, *, instant=None):
    dates_and_destinations = (
        ("2026-11-13", "JP"), ("2026-11-20", "JP"), ("2026-11-20", "DE"),
        ("2026-09-18", "JP"), ("2026-11-27", "JP"),
    )
    windows = [
        {"signal_date": date, "routes": [{"destination": country}]} for date, country in dates_and_destinations
    ]
    payload = {"groups": [{"weekly": windows, "daily": []}]}
    flow.attach_route_market_flows(payload, data, now=instant or now())
    return [window["routes"][0]["flow"] for window in windows]


def test_verified_weekly_source_updates_pending_and_published(tmp_path, monkeypatch):
    live_fixture(monkeypatch)
    path = tmp_path / "portfolio.json"
    data = flow.load_route_market_flows(path, refresh=True, now=now())
    assert [record["status"] for record in data["fetch_records"]] == ["ok", "ok"]
    published, pending, unsupported, old_gap, unscheduled = result_rows(data)
    assert (published["status"], published["week_start"], published["week_end"]) == (
        "published", "2026-11-08", "2026-11-14",
    )
    assert published["publication_date"] == "2026-11-19"
    assert (published["long_net"], published["short_net"], published["equity_net"]) == (6501, 1618, -2241)
    assert (pending["status"], pending["publication_date"], pending["long_net"]) == ("pending", "2026-11-27", None)
    assert unsupported["status"] == old_gap["status"] == "unavailable"
    assert unsupported["source"] is None
    assert unscheduled["status"] == "pending"
    assert unscheduled["publication_date"] is None
    assert flow.load_route_market_flows(path, refresh=False, now=now()) == {**data, "fetch_records": []}


def test_mof_schedule_supports_combined_and_new_year_weeks():
    schedule = flow.parse_mof_schedule(
        '<table><tr><td>January 7, 2027</td>'
        '<td>December 20 - 26, 2026<br> / December 27 - January 2, 2027</td></tr></table>'
    )
    assert schedule == {"2026-12-26": "2027-01-07", "2027-01-02": "2027-01-07"}


def test_cache_is_preserved_when_source_rewinds_or_schedule_fails(tmp_path, monkeypatch):
    live_fixture(monkeypatch)
    path = tmp_path / "portfolio.json"
    before = flow.load_route_market_flows(path, refresh=True, now=now())
    original = path.read_bytes()
    live_fixture(monkeypatch, csv_body=mof_fixture("November 12, 2026", (WEEK_OLD,)), schedule="<html>Error</html>")
    after = flow.load_route_market_flows(path, refresh=True, now=now())
    assert [record["status"] for record in after["fetch_records"]] == ["degraded", "degraded"]
    assert after["weeks"] == before["weeks"]
    assert after["schedule"] == before["schedule"]
    assert path.read_bytes() == original


def test_due_week_is_unavailable_and_visible_to_audit_if_csv_lags(tmp_path, monkeypatch):
    live_fixture(monkeypatch)
    instant = now("2026-11-26T23:51:00+00:00")
    data = flow.load_route_market_flows(tmp_path / "portfolio.json", refresh=True, now=instant)
    assert data["fetch_records"][0]["status"] == "degraded"
    past_due = result_rows(data, instant=instant)[1]
    assert past_due["status"] == "unavailable"
    assert past_due["publication_date"] == "2026-11-27"


def test_actual_week_stays_pending_until_official_release(tmp_path, monkeypatch):
    live_fixture(monkeypatch, csv_body=mof_fixture("November 27, 2026", (WEEK_OLD, WEEK_AVAILABLE, WEEK_FUTURE)))
    instant = now("2026-11-26T23:49:00+00:00")
    data = flow.load_route_market_flows(tmp_path / "portfolio.json", refresh=True, now=instant)
    assert result_rows(data, instant=instant)[1]["status"] == "pending"


def test_invalid_numbers_headers_or_future_update_fail_closed(tmp_path, monkeypatch):
    bad = flow.decode_mof(mof_fixture()).replace('"6,501"', '"6,5010"')
    with pytest.raises(ValueError, match="flow number"):
        flow.parse_mof_csv(bad)
    with pytest.raises(ValueError):
        flow.parse_mof_csv("\n" * 25)
    live_fixture(monkeypatch, csv_body=mof_fixture("November 30, 2026"))
    data = flow.load_route_market_flows(tmp_path / "portfolio.json", refresh=True, now=now())
    assert data["weeks"] == {}
    assert data["fetch_records"][0]["status"] == "error"
    assert data["fetch_records"][1]["status"] == "ok"
