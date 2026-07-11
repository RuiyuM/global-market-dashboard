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

## Source Split

### Server Daily

| Source | Symbols | Policy |
|---|---|---|
| WSCN | U.S. Treasury curve, core China Treasury tenors, core FX, Shanghai Composite | Fetch daily; an empty response never replaces cache. |
| ChinaMoney / ChinaBond CCDC | China 1M through 30Y curve | Official daily source and historical backfill. |
| Nikkei | `JP_EQUITY` | Preferred official Nikkei 225 daily CSV. |
| Japan MOF | Japan 1Y through 30Y | Official historical anchor. |
| Trading Economics | Japan short-bill chart history/latest; Japan, Korea, Russia latest yield closes; Germany 3M/6M latest | Server-safe fallback. Close-only rows are explicit. |
| Bundesbank | Germany 1Y through 30Y except 3M/6M | Official history. |
| SMBS KORIBOR | Korea 1M/3M/6M | Money-market proxy, not a Korean government-bond yield. |
| Yahoo | Equity, FX, DXY, VIX, gold, oil series in the policy file | Server first; local only after an actual server error/empty response. |

### Known Tencent Cloud Block

Investing.com returned `HTTP 403` for all 12 configured requests in the verified 2026-07-11 server run. This is not a `404` and is not retried from the server timer.

The server runs with `MARKET_SKIP_INVESTING=1` and records these rows as `degraded`, never as `ok`:

```text
JP_1M JP_3M JP_6M
KR_1Y KR_2Y KR_3Y KR_5Y KR_10Y KR_30Y
RU_2Y RU_10Y RU_EQUITY
```

Japan 1M/3M/6M still receive Trading Economics chart history and latest data. Korea and Russia bonds retain their cached OHLC history and receive a Trading Economics latest close. `RU_EQUITY` has no confirmed server-safe replacement and is the only fixed local-required series.

### Local Fallback

`production_update.py` performs only these local actions:

- Refresh every Yahoo symbol whose server fetch record is `error`, `empty`, or unexpectedly degraded.
- Refresh `RU_EQUITY` from Investing.com on each local production run.
- With `--weekly`, refresh the public Investing OHLC list in `local_weekly_ohlc` from the policy file.
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
- Dashboard validation and unhandled source-audit failures must make systemd fail. Allowlisted Yahoo failures are reported as `SOURCE AUDIT FALLBACK` and keep the service successful while the validated cache remains fresh; the local orchestrator still patches those symbols.
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
