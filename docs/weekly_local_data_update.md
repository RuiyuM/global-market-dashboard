# Weekly Local Data Update

This document is the checklist to read before the weekly local update. Use it when a data source works locally but is blocked or unreliable from the Tencent Cloud server.

## Current Policy

The server should update every day from stable server-side sources first. Local weekly upload is only for symbols where the server cannot fetch complete OHLC history.

When doing a post-close refresh, run the server update first, then patch only the symbols that failed or returned stale data from local sources. This avoids replacing a working server pipeline with a local-only workflow.

### Finalized Source Split

Do not overwrite server-generated files for these sources unless validation explicitly says the series is stale:

| Source group | Server-updated symbols | Notes |
|---|---|---|
| WSCN | US Treasury tenors, core CN Treasury tenors, `USDCNY`, `JPYCNY`, `USDJPY`, `EURCNY`, `EURJPY`, `EURUSD`, `USDRUB`, `CN_EQUITY` | Server-first daily source. |
| ChinaMoney / ChinaBond CCDC | `CN_1M`, `CN_3M`, `CN_6M`, `CN_1Y`, `CN_2Y`, `CN_3Y`, `CN_5Y`, `CN_7Y`, `CN_10Y`, `CN_30Y` | Official China yield-curve source; 3M may include CCDC backfill. |
| Nikkei | `JP_EQUITY` | Preferred Japan equity source. Yahoo Nikkei is backup only. |
| Japan MOF + Trading Economics latest | `JP_1Y`, `JP_2Y`, `JP_3Y`, `JP_5Y`, `JP_7Y`, `JP_10Y`, `JP_30Y` | MOF is the historical anchor; TE only patches newest point when needed. |
| Bundesbank / Trading Economics latest | `DE_1Y`, `DE_2Y`, `DE_3Y`, `DE_5Y`, `DE_7Y`, `DE_10Y`, `DE_30Y`; `DE_3M`, `DE_6M` latest close | Bundesbank is preferred for German curve history. |
| SMBS KORIBOR | `KR_1M`, `KR_3M`, `KR_6M` | Short-end proxy, not a government-bond yield. |
| Server private env | Quant fund futures/options curves | Writes sanitized percent points only; no raw trades, balances, keys, or principal amounts. |

### Must Update Locally

| Symbol | Dataset | Reason | Normal cadence |
|---|---|---|---|
| `JP_1M` | Japan 1-month bill yield | No confirmed stable non-Investing daily history source. Server can only keep it alive with Trading Economics latest close. | Weekly |
| `RU_EQUITY` | Russia MOEX index | Investing.com is blocked from the server and no reliable Yahoo/official replacement has been verified. | Weekly |

### Optional Local OHLC Backfill

These can keep updating on the server, but the server-side fallback is close-only for recent days. Run local Investing backfill when complete OHLC candles matter.

| Symbol | Dataset | Server fallback |
|---|---|---|
| `JP_3M` | Japan 3-month bill yield | Trading Economics latest close; future replacement candidate: JBTS `TDB(3M)` |
| `JP_6M` | Japan 6-month bill yield | Trading Economics latest close; future replacement candidate: JBTS `TDB(6M)` |
| `KR_1Y` | Korea 1-year treasury yield | Trading Economics latest close; future replacement candidate: BOK ECOS `010190000` |
| `KR_2Y` | Korea 2-year treasury yield | Trading Economics latest close; future replacement candidate: BOK ECOS `010195000` |
| `KR_3Y` | Korea 3-year treasury yield | Trading Economics latest close; future replacement candidate: BOK ECOS `010200000` |
| `KR_5Y` | Korea 5-year treasury yield | Trading Economics latest close; future replacement candidate: BOK ECOS `010200001` |
| `KR_10Y` | Korea 10-year treasury yield | Trading Economics latest close; future replacement candidate: BOK ECOS `010210000` |
| `KR_30Y` | Korea 30-year treasury yield | Trading Economics latest close; future replacement candidate: BOK ECOS `010230000` |
| `RU_2Y` | Russia 2-year yield | Trading Economics latest close; future replacement candidate: Bank of Russia ZCYC 2Y |
| `RU_10Y` | Russia 10-year yield | Trading Economics latest close; future replacement candidate: Bank of Russia ZCYC 10Y |

### Local Backfill When Server Hits Yahoo 429

Tencent Cloud can occasionally get `429 Too Many Requests` from Yahoo. When that happens, refresh these public Yahoo series locally and upload the resulting `dashboard/data/*.csv` files:

```text
US_EQUITY JP_EQUITY_YAHOO DE_EQUITY KR_EQUITY
KRWCNY USDKRW RUBCNY_YAHOO RUBJPY_YAHOO USDRUB_YAHOO
DXY VIX GOLD USOIL
```

Use this local snippet:

```bash
cd /Users/ruiyuma/Desktop/global-market-dashboard
source ~/anaconda3/bin/activate
python - <<'PY'
from datetime import date, timedelta
from market_dashboard import YAHOO_SPECS, DASHBOARD_DATA, fetch_yahoo_ohlc, write_ohlc

keys = {
    "US_EQUITY", "JP_EQUITY_YAHOO", "DE_EQUITY", "KR_EQUITY",
    "KRWCNY", "USDKRW", "RUBCNY_YAHOO", "RUBJPY_YAHOO", "USDRUB_YAHOO",
    "DXY", "VIX", "GOLD", "USOIL",
}
end = date.today()
start = end - timedelta(days=540)
for spec in YAHOO_SPECS:
    if spec.key not in keys:
        continue
    rows = fetch_yahoo_ohlc(spec.symbol, start, end)
    if rows:
        write_ohlc(DASHBOARD_DATA / spec.cache_file, rows)
        print(spec.key, len(rows), rows[0]["date"], "->", rows[-1]["date"], rows[-1]["close"])
    else:
        print(spec.key, "EMPTY")
PY
```

## Weekly Local Procedure

Run this from a local network that can access Investing.com.

```bash
cd /Users/ruiyuma/Desktop/global-market-dashboard
source ~/anaconda3/bin/activate
python fetch_investing_bond_ohlc.py \
  JP1M JP3M JP6M KR1Y KR2Y KR3Y KR5Y KR10Y KR30Y RU2Y RU10Y RU_EQUITY \
  --start-date 2025-01-01 \
  --output-dir data
```

Then regenerate the dashboard locally:

```bash
python market_dashboard.py
python validate_market_dashboard.py
```

If the full local run stalls on the Korean SMBS/KORIBOR page, stop it and merge the already downloaded local Investing files into `dashboard/data` directly:

```bash
python - <<'PY'
from market_dashboard import (
    DASHBOARD_DATA,
    LOCAL_DATA,
    JAPAN_BOND_SPECS,
    KOREA_BOND_SPECS,
    INVESTING_SPECS,
    read_ohlc,
    merge_ohlc_rows,
    write_ohlc,
)

for spec, *_ in list(JAPAN_BOND_SPECS) + list(KOREA_BOND_SPECS):
    if not spec.local_file:
        continue
    src = LOCAL_DATA / spec.local_file
    dst = DASHBOARD_DATA / spec.cache_file
    if not src.exists():
        continue
    rows = read_ohlc(dst) if dst.exists() else []
    rows = merge_ohlc_rows(rows, read_ohlc(src))
    write_ohlc(dst, rows)
    print(spec.key, rows[-1]["date"] if rows else "")

for spec, investing_spec in INVESTING_SPECS:
    src = LOCAL_DATA / investing_spec.output_name
    dst = DASHBOARD_DATA / spec.cache_file
    if not src.exists():
        continue
    rows = read_ohlc(dst) if dst.exists() else []
    rows = merge_ohlc_rows(rows, read_ohlc(src))
    write_ohlc(dst, rows)
    print(spec.key, rows[-1]["date"] if rows else "")
PY
python market_dashboard.py --no-fetch
python validate_market_dashboard.py
```

Inspect the changed files before committing:

```bash
git status --short
git diff --stat
```

Only commit generated files that are intended public dashboard data. Do not commit private API keys, account values, raw private trade logs, or `.env` files.

## Publish To Server

After local validation, upload only the public files that were intentionally refreshed. Do not upload private API files, raw trade/account exports, or the whole `dashboard/data/` directory after a partial patch.

Full-directory rsync is intentionally avoided here. It can overwrite fresher server-generated WSCN/official data with stale local cache, and it can preserve local owner/group metadata that breaks later server writes.

Create an explicit upload list. For the weekly Investing backfill, start with:

```bash
cd /Users/ruiyuma/Desktop/global-market-dashboard
cat > /tmp/global_market_dashboard_upload_files.txt <<'EOF'
dashboard/data/JP_1M.csv
dashboard/data/JP_3M.csv
dashboard/data/JP_6M.csv
dashboard/data/KR_1Y.csv
dashboard/data/KR_2Y.csv
dashboard/data/KR_3Y.csv
dashboard/data/KR_5Y.csv
dashboard/data/KR_10Y.csv
dashboard/data/KR_30Y.csv
dashboard/data/RU_2Y.csv
dashboard/data/RU_10Y.csv
dashboard/data/RU_EQUITY.csv
data/JP1M_INVESTING_1D_ohlc.csv
data/JP3M_INVESTING_1D_ohlc.csv
data/JP6M_INVESTING_1D_ohlc.csv
data/KR1YR_INVESTING_1D_ohlc.csv
data/KR2YR_INVESTING_1D_ohlc.csv
data/KR3YR_INVESTING_1D_ohlc.csv
data/KR5YR_INVESTING_1D_ohlc.csv
data/KR10YR_INVESTING_1D_ohlc.csv
data/KR30YR_INVESTING_1D_ohlc.csv
data/RU2YR_INVESTING_1D_ohlc.csv
data/RU10YR_INVESTING_1D_ohlc.csv
data/RU_EQUITY_INVESTING_1D_ohlc.csv
EOF
```

If the server hit Yahoo 429, append only the failed or stale Yahoo files, for example:

```bash
cat >> /tmp/global_market_dashboard_upload_files.txt <<'EOF'
dashboard/data/US_EQUITY.csv
dashboard/data/DE_EQUITY.csv
dashboard/data/KRWCNY.csv
dashboard/data/USDKRW.csv
dashboard/data/DXY.csv
dashboard/data/VIX.csv
dashboard/data/GOLD.csv
dashboard/data/USOIL.csv
EOF
```

Then upload just those files:

```bash
rsync -avz --no-owner --no-group --chmod=D755,F644 \
  --files-from=/tmp/global_market_dashboard_upload_files.txt \
  -e "ssh -i '/Users/ruiyuma/Desktop/国债汇率/sol.pem' -o StrictHostKeyChecking=no" \
  ./ root@43.133.168.211:/opt/global-market-dashboard/
ssh -i '/Users/ruiyuma/Desktop/国债汇率/sol.pem' root@43.133.168.211 \
  'cd /opt/global-market-dashboard && chown -R root:root dashboard data && find dashboard data -type d -exec chmod 755 {} + && find dashboard data -type f -exec chmod 644 {} + && python3 quant_fund_snapshot.py && python3 market_dashboard.py --no-fetch && python3 validate_market_dashboard.py'
```

The server-side `quant_fund_snapshot.py` step uses the private server env and writes only sanitized percentage points.

## Server Daily Behavior

The server daily timer can still run normally:

- Investing.com may return `403 Forbidden`.
- `JP_1M` should remain populated by cached OHLC plus Trading Economics latest close.
- `RU_EQUITY` should remain on cached OHLC until local weekly data is uploaded.
- Korea bonds and Russia 2Y/10Y should keep updating via server-side close-only fallback.
- If SMBS/KORIBOR times out, `KR_1M` remains cached until a later successful run.

Check server status after weekly sync:

```bash
ssh -i '/Users/ruiyuma/Desktop/国债汇率/sol.pem' root@43.133.168.211 \
  'cd /opt/global-market-dashboard && systemctl is-active global-market-dashboard-update.timer && python3 validate_market_dashboard.py'
```

## Replacement Source Watchlist

These sources have been identified as candidates for reducing local weekly work:

- Japan `JP_3M` and `JP_6M`: JBTS historical main rate page, `TDB(3M)` and `TDB(6M)`.
- Korea `KR_1Y`, `KR_2Y`, `KR_3Y`, `KR_5Y`, `KR_10Y`, `KR_30Y`: BOK ECOS official daily market rates.
- Russia `RU_2Y` and `RU_10Y`: Bank of Russia official zero-coupon yield curve.

Do not replace an Investing series with a new source unless the dashboard source note makes the changed data definition explicit.
