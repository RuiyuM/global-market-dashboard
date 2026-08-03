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

The server-only daily timer remains useful when the Mac is offline. It runs at 16:10 New York time, after the U.S. close but before the 15:30 Dallas local orchestrator. It updates every source reachable from Tencent Cloud, updates the sanitized quant curves, validates the rendered site, and performs a source audit. When the Mac is available, the later local run remediates Yahoo 429 sources and remains the final production audit instead of being overwritten by a redundant server-only run.

## Codex Scheduled Windows

Both recurring jobs use the `America/Chicago` timezone and run Monday through Friday. They invoke the same canonical local command, `python production_update.py`, so source routing, privacy controls, local public-data fallbacks, validation, and auditing remain identical.

| Dallas time | Purpose | Required result checks |
|---|---|---|
| 06:00 | Asia-close refresh | Report China, Japan, and Korea equity latest dates; core FX latest dates; and the three tri-currency flow summaries. Before New York 16:00, replace `fx_flow_views.asia_intraday` only when all three triads are complete and every leg shares the same New York date. Report the captured New York date/time. |
| 15:30 | U.S.-close refresh | Report the latest U.S. market date and `fx_flow_views.closed`. At or after New York 16:00, the current common date is treated as a completed daily observation rather than intraday. Verify that the previously captured Asia-close view is still present and clickable; never overwrite it with the close calculation. |

The jobs are recurring trading-day updates, not weekly backfills. They must not run `git pull`, use `--weekly`, upload an entire cache directory, or weaken validation. On a market holiday, retaining the most recent common trading date is correct and must be stated in the result rather than relabeled as current.

Scheduled jobs must run through `scheduled_market_update_once.sh`, which always
enables `--redact-quant-summary`. Their command output and inbox reports must
never include futures or options percentages, quant snapshot contents, account
data, positions, principal, or credentials. The internal server updater may
continue refreshing the protected quant page. Every scheduled run must verify
that unauthenticated `quant_fund.html` and `quant_fund_snapshot.json` requests
return `401`, and that the public `latest_market_snapshot.json` has no
`quant_fund` key. Scheduled jobs do not authenticate to or inspect the protected
quant endpoints.

The public snapshot keeps both tri-currency views. `fx_flows` remains the backward-compatible result for the current run, while `fx_flow_views.closed` is rebuilt from completed New York sessions and `fx_flow_views.asia_intraday` is a retained morning snapshot. A partial morning update must preserve the previous valid Asia snapshot instead of publishing mixed-date legs. The dashboard defaults to the Asia view immediately after a complete morning capture and to the U.S.-close view after the close; users can switch between them without recomputation.

## Source Split

### Server Daily

| Source | Symbols | Policy |
|---|---|---|
| WSCN | U.S. Treasury curve, core China Treasury tenors, core FX, Shanghai Composite; OHLC overlays for China 30Y, Japan 2Y/3Y/5Y/10Y/30Y, and Germany 2Y/10Y | Fetch daily; an empty response never replaces cache. A complete OHLC bar always wins over a same-date close-only observation. |
| Moscow Exchange ISS | `CNYRUB_TOM` official traded daily candles, inverted to `RUB/CNY`; `IMOEX` official index candles | Primary direct `RUB/CNY` history is paginated back to 2019 and refreshed daily on the server. `IMOEX` is refreshed by the local public-data patch because Investing.com may challenge local automated requests. |
| ChinaMoney / ChinaBond CCDC | China 1M through 30Y curve | Official daily source and historical backfill. |
| Nikkei | `JP_EQUITY` | Preferred official Nikkei 225 daily CSV. |
| Japan MOF | Japan 1Y through 30Y | Official close-only historical anchor. WSCN supplies daily OHLC where configured; local Investing supplies weekly gap fills, including Japan 30Y through verified instrument ID `23904`. |
| Trading Economics | Japan short-bill chart history/latest; Japan, Korea, Russia latest yield closes; Germany 3M/6M latest | Server-safe fallback. Close-only rows are explicit; Germany 3M/6M also receive locally refreshed Investing OHLC. |
| Bundesbank | Germany 1Y through 30Y except 3M/6M | Official close history. Every listed German tenor receives locally refreshed Investing OHLC; Germany 2Y/10Y also use WSCN OHLC. |
| SMBS KORIBOR | Korea 1M/3M/6M | Money-market proxy, not a Korean government-bond yield. |
| Yahoo | Equity, FX, DXY, VIX, gold, oil series in the policy file | Server first; local only after an actual server error/empty response. |

`RUB/CNY` uses the inverted Moscow Exchange `CNYRUB_TOM` traded history when it spans at least 30 days and is no more than seven days behind the USD reference series. Yahoo `RUBCNY=X` is retained only as a cross-check. The `USDCNY/USDRUB` formula is a fallback when MOEX is missing or stale; any direct/formula difference remains visible as market basis in `source_audit` instead of automatically invalidating the official direct series. `RUB/JPY` still uses the 30-day-history and 2% formula-consistency guard because no equivalent official direct series is configured.

### Known Tencent Cloud Block

Investing.com returns `HTTP 403` from Tencent Cloud. This is not a `404` and is not retried from the server timer.

The server runs with `MARKET_SKIP_INVESTING=1` and records these rows as `degraded`, never as `ok`:

```text
JP_1M JP_3M JP_6M
JP_1Y JP_2Y JP_3Y JP_5Y JP_7Y JP_10Y JP_30Y
DE_3M DE_6M DE_1Y DE_2Y DE_3Y DE_5Y DE_7Y DE_10Y DE_30Y
KR_1Y KR_2Y KR_3Y KR_5Y KR_10Y KR_30Y
RU_2Y RU_10Y RU_EQUITY
```

Japan 2Y/3Y/5Y/10Y/30Y receive daily WSCN OHLC plus weekly local Investing gap fills. Japan 1Y/7Y retain MOF close anchors and cached local Investing OHLC. Germany 3M/6M/1Y/2Y/3Y/5Y/7Y/10Y/30Y receive weekly local Investing OHLC; the official Trading Economics or Bundesbank close series remains the anchor, and Germany 2Y/10Y additionally receive daily WSCN OHLC. Japan 1M/3M/6M still receive Trading Economics chart history and latest data. Korea and Russia bonds retain their cached OHLC history and receive a Trading Economics latest close. `RU_EQUITY` uses official Moscow Exchange ISS `IMOEX` daily candles and is the only fixed local-required series. Investing.com remains blocked on the server and is not required for this equity patch.

Japan 30Y must use Investing instrument ID `23904`. The old ID `23903` was a wrong-tenor mapping and ran roughly 33-37bp below the same-date Japan MOF 30Y curve. ID `23904` was cross-checked against MOF and WSCN before admission. Never restore `23903` or infer tenor identity from a filename alone.

Germany uses verified Investing IDs `23681`, `23682`, `23684`, `23685`, `23686`, `23688`, `23690`, `23693`, and `23696` for 3M through 30Y. Their same-date closes were cross-checked against Trading Economics or Deutsche Bundesbank before admission. Do not use WSCN `DE30YR.OTC`: despite its label, its close was roughly 115bp below the Bundesbank 30Y series and tracked the wrong curve level.

### Local Fallback

`production_update.py` performs only these local actions:

- Refresh every Yahoo symbol whose server fetch record is `error`, `empty`, or unexpectedly degraded.
- Refresh SMBS KORIBOR 1M/3M/6M locally only when the server records an actual timeout, error, or empty response.
- Refresh `RU_EQUITY` from the official Moscow Exchange ISS `IMOEX` candle endpoint on each local production run.
- With `--weekly`, refresh the public Investing OHLC list in `local_weekly_ohlc` from the policy file. This includes Japan 1Y/7Y, gap fills for Japan 2Y/3Y/5Y/10Y/30Y, and Germany 3M/6M/1Y/2Y/3Y/5Y/7Y/10Y/30Y.
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
- SMBS KORIBOR refreshes start from the oldest 1M/3M/6M cache date with a 7-day overlap and split requests into at most 31-day segments. Do not restore a single 540-day POST; it can time out even while the official endpoint is healthy.
- Do not use `git pull` as part of a data refresh. Code deployment and market-data refresh are separate operations.
- Futures percentage updates require an exact API anchor on the latest published trade date. Preserve every existing public point and append only later trade dates relative to that anchor; a disagreement in older overlap must never freeze otherwise valid new trades or rewrite history.

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
