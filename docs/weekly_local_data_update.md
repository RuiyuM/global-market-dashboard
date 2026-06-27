# Weekly Local Data Update

This document is the checklist to read before the weekly local update. Use it when a data source works locally but is blocked or unreliable from the Tencent Cloud server.

## Current Policy

The server should update every day from stable server-side sources first. Local weekly upload is only for symbols where the server cannot fetch complete OHLC history.

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

After committing and pushing the local data update:

```bash
git push origin main
ssh -i '/Users/ruiyuma/Desktop/国债汇率/sol.pem' root@43.133.168.211 \
  'cd /opt/global-market-dashboard && git pull --ff-only && python3 market_dashboard.py --no-fetch && python3 validate_market_dashboard.py'
```

## Server Daily Behavior

The server daily timer can still run normally:

- Investing.com may return `403 Forbidden`.
- `JP_1M` should remain populated by cached OHLC plus Trading Economics latest close.
- `RU_EQUITY` should remain on cached OHLC until local weekly data is uploaded.
- Korea bonds and Russia 2Y/10Y should keep updating via server-side close-only fallback.

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
