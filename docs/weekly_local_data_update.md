# Fixed Market Data Update

This is the authoritative update procedure for the production dashboard. The machine-readable source split is [source_update_policy.json](../source_update_policy.json); do not maintain a second symbol list in an ad-hoc shell script.

## Normal Commands

Run from the local Mac after the U.S. close:

```bash
cd /Users/ruiyuma/Desktop/global-market-dashboard
source ~/anaconda3/bin/activate
python production_update.py
```

Run the full weekly OHLC refresh:

```bash
python production_update.py --weekly
```

Audit production without changing it:

```bash
python production_update.py --audit-only
```

The server-only daily timer remains useful when the Mac is offline. It updates every source reachable from Tencent Cloud, updates the sanitized quant curves, validates the rendered site, and performs a source audit.

## Codex Scheduled Windows

Both recurring jobs use the `America/Chicago` timezone and run Monday through Friday. They invoke the same canonical local command, `python production_update.py`, so source routing, privacy controls, local public-data fallbacks, validation, and auditing remain identical.

| Dallas time | Purpose | Required result checks |
|---|---|---|
| 06:00 | Asia-close refresh | Report China, Japan, and Korea equity latest dates; core FX latest dates; and the three tri-currency flow summaries. Before New York 16:00, a flow may be marked intraday only when all three legs share the same New York date. |
| 15:30 | U.S.-close refresh | Report the latest U.S. market date and the tri-currency daily summaries. At or after New York 16:00, the current common date is treated as a completed daily observation rather than intraday. |

The jobs are recurring trading-day updates, not weekly backfills. They must not run `git pull`, use `--weekly`, upload an entire cache directory, or weaken validation. On a market holiday, retaining the most recent common trading date is correct and must be stated in the result rather than relabeled as current.

## Source Split

### Server Daily

| Source | Symbols | Policy |
|---|---|---|
| WSCN | U.S. Treasury curve, core China Treasury tenors, core FX, Shanghai Composite; OHLC overlays for China 30Y, Japan 2Y/3Y/5Y/10Y/30Y, and Germany 2Y/10Y | Fetch daily; an empty response never replaces cache. A complete OHLC bar always wins over a same-date close-only observation. |
| Moscow Exchange ISS | `CNYRUB_TOM` official traded daily candles, inverted to `RUB/CNY` | Primary direct `RUB/CNY` history. Paginated back to 2019 and refreshed daily on the server. |
| ChinaMoney / ChinaBond CCDC | China 1M through 30Y curve | Official daily source and historical backfill. |
| Nikkei | `JP_EQUITY` | Preferred official Nikkei 225 daily CSV. |
| Japan MOF | Japan 1Y through 30Y | Official close-only historical anchor. WSCN supplies daily OHLC where configured; local Investing supplies weekly gap fills except Japan 30Y. |
| Trading Economics | Japan short-bill chart history/latest; Japan, Korea, Russia latest yield closes; Germany 3M/6M latest | Server-safe fallback. Close-only rows are explicit. |
| Bundesbank | Germany 1Y through 30Y except 3M/6M | Official history. |
| SMBS KORIBOR | Korea 1M/3M/6M | Money-market proxy, not a Korean government-bond yield. |
| Yahoo | Equity, FX, DXY, VIX, gold, oil series in the policy file | Server first; local only after an actual server error/empty response. |

`RUB/CNY` uses the inverted Moscow Exchange `CNYRUB_TOM` traded history when it spans at least 30 days and is no more than seven days behind the USD reference series. Yahoo `RUBCNY=X` is retained only as a cross-check. The `USDCNY/USDRUB` formula is a fallback when MOEX is missing or stale; any direct/formula difference remains visible as market basis in `source_audit` instead of automatically invalidating the official direct series. `RUB/JPY` still uses the 30-day-history and 2% formula-consistency guard because no equivalent official direct series is configured.

### Known Tencent Cloud Block

Investing.com returns `HTTP 403` from Tencent Cloud. This is not a `404` and is not retried from the server timer.

The server runs with `MARKET_SKIP_INVESTING=1` and records these rows as `degraded`, never as `ok`:

```text
JP_1M JP_3M JP_6M
JP_1Y JP_2Y JP_3Y JP_5Y JP_7Y JP_10Y
KR_1Y KR_2Y KR_3Y KR_5Y KR_10Y KR_30Y
RU_2Y RU_10Y RU_EQUITY
```

Japan 2Y/3Y/5Y/10Y receive daily WSCN OHLC and Japan 30Y receives WSCN OHLC without an Investing fill. Japan 1Y/7Y retain MOF close anchors and cached local Investing OHLC. Japan 1M/3M/6M still receive Trading Economics chart history and latest data. Korea and Russia bonds retain their cached OHLC history and receive a Trading Economics latest close. `RU_EQUITY` has no confirmed server-safe replacement and is the only fixed local-required series.

Do not use the configured Investing `JP30Y` response as Japan 30Y. Cross-checking showed it roughly 33-37bp below the same-date Japan MOF 30Y curve while WSCN stayed within roughly 5-8bp; the Investing mapping is therefore rejected for production.

### Local Fallback

`production_update.py` performs only these local actions:

- Refresh every Yahoo symbol whose server fetch record is `error`, `empty`, or unexpectedly degraded.
- Refresh SMBS KORIBOR 1M/3M/6M locally only when the server records an actual timeout, error, or empty response.
- Refresh `RU_EQUITY` from Investing.com on each local production run.
- With `--weekly`, refresh the public Investing OHLC list in `local_weekly_ohlc` from the policy file. This includes Japan 1Y/7Y and gap fills for Japan 2Y/3Y/5Y/10Y, but explicitly excludes Japan 30Y.
- Upload only files produced successfully in that run.

An empty response, exception, or incoming dataset older than the local cache is rejected. A required local failure stops the run before deployment.

## Update Sequence

1. Start `global-market-dashboard-update.service` on the server.
2. Download `latest_market_snapshot.json` and audit `fetch_records` against the policy file.
3. Fetch only required local fallbacks.
4. Generate `dashboard/local_patch_report.json` containing public symbols, dates, and no credentials.
5. Upload an explicit `--files-from` manifest. Full-directory rsync is forbidden.
6. Restore `globaldash:globaldash` ownership on runtime data.
7. Rebuild with `--no-fetch`; this preserves the server fetch audit and attaches the current local patch report.
8. Run dashboard validation and source audit again.

## Failure Rules

- `update_market_dashboard.sh` is the single server entry point. It runs quant refresh, market fetch/render, dashboard validation, and source audit.
- Dashboard validation and unhandled source-audit failures must make systemd fail. Allowlisted Yahoo or SMBS KORIBOR failures are reported as `SOURCE AUDIT FALLBACK` and keep the service successful while the validated cache remains fresh; the local orchestrator still patches those symbols.
- Runtime files must stay writable by `globaldash`. Never run `chown -R root:root dashboard data`.
- A no-fetch render must retain `fetch_records` and `last_fetch_at`; otherwise the original 403/429 evidence is lost.
- Expected Investing degradation may warn but does not fail while its fallback/cache remains usable.
- Yahoo `429` is intermittent. Patch only failed Yahoo keys; do not overwrite working official/WSCN files.
- Do not use `git pull` as part of a data refresh. Code deployment and market-data refresh are separate operations.

## Privacy Boundary

Allowed uploads:

```text
dashboard/data/*.csv
data/*_INVESTING_1D_ohlc.csv
dashboard/local_patch_report.json
```

Forbidden uploads include `.private/`, `.env`, API keys, raw futures trades, option positions, account balances, principal amounts, and quant API responses. `production_update.py` enforces this allowlist before rsync. The public quant output remains sanitized `{date, pct}` points only.

## Verification

On the server:

```bash
cd /opt/global-market-dashboard
python3 validate_market_dashboard.py
python3 audit_market_sources.py
systemctl is-active global-market-dashboard-update.timer
systemctl status global-market-dashboard-update.service --no-pager
```

Expected result: validation passes, source audit passes with only known Investing degradation warnings, the timer is active, runtime files are owned by `globaldash`, and `last_fetch_at` reflects the latest network run.
