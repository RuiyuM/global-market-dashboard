# Server Deployment Runbook

This note records the deployment logic for the dashboard so the server state is not lost between turns.

For sources that the server cannot fetch directly, read [Weekly Local Data Update](weekly_local_data_update.md) before running a manual weekly backfill.

## Server And Repo

- Public site: `http://43.133.168.211/`
- Server app path: `/opt/global-market-dashboard`
- Static web root: `/opt/global-market-dashboard/dashboard`
- Main page: `/opt/global-market-dashboard/dashboard/index.html`
- Quant page: `/opt/global-market-dashboard/dashboard/quant_fund.html`
- Public quant snapshot: `/opt/global-market-dashboard/dashboard/quant_fund_snapshot.json`
- Private server config: `/opt/global-market-dashboard/.private/quant_fund.env`

Do not put private API keys, principal amounts, raw trades, positions, or account balances into GitHub, public HTML, or public snapshots.

## Normal Deployment

On the server:

```bash
cd /opt/global-market-dashboard
git pull --rebase origin main
python3 -m pytest test_market_dashboard_quant_fund.py test_quant_fund_snapshot.py -q
python3 market_dashboard.py --no-fetch
python3 validate_market_dashboard.py
```

If the generated HTML changed:

```bash
git status --short
git add market_dashboard.py test_market_dashboard_quant_fund.py dashboard/quant_fund.html
git commit -m "Describe the dashboard change"
git push origin main
```

If `git push` asks for credentials, enter them interactively in OrcaTerm. Do not paste tokens into tracked files or command history when avoidable.

## Daily Auto Update

The server update entry point is:

```bash
/opt/global-market-dashboard/update_market_dashboard.sh
```

That script runs:

```bash
python3 quant_fund_snapshot.py
python3 market_dashboard.py "$@"
```

The systemd service/timer from `install_server.sh` should run the same update flow daily, then run:

```bash
python3 /opt/global-market-dashboard/validate_market_dashboard.py
```

Check timer and logs:

```bash
systemctl status global-market-dashboard-update.service
systemctl list-timers global-market-dashboard-update.timer
journalctl -u global-market-dashboard-update.service -n 200 --no-pager
```

## Manual Post-Close Full Refresh

Use this when the daily server update runs, but some public market sources are blocked from Tencent Cloud.

1. Run the normal server update first:

```bash
cd /opt/global-market-dashboard
./update_market_dashboard.sh
python3 validate_market_dashboard.py
```

2. Inspect failures in `dashboard/latest_market_snapshot.json`. Common server-side failures seen on 2026-07-01:

```text
Yahoo 429: US_EQUITY, JP_EQUITY_YAHOO, DE_EQUITY, KR_EQUITY,
           KRWCNY, USDKRW, RUBCNY_YAHOO, RUBJPY_YAHOO, USDRUB_YAHOO,
           DXY, VIX, GOLD, USOIL
SMBS timeout: KR_1M
Investing 403 with fallback: Japan short bills, Korea bonds, Russia bonds/equity
```

3. Locally backfill the failed public series by following [Weekly Local Data Update](weekly_local_data_update.md). The expected local artifacts are:

```text
dashboard/data/<only failed or local-required symbols>.csv
data/<only refreshed Investing local files>.csv
```

4. Upload only public market data that was intentionally refreshed.

Do not rsync the full `dashboard/data/` directory after a partial local patch. That can overwrite newer server-generated WSCN, ChinaMoney, Nikkei, MOF, Bundesbank, SMBS, or Trading Economics rows with stale local cache.

```bash
cd /Users/ruiyuma/Desktop/global-market-dashboard
cat > /tmp/global_market_dashboard_upload_files.txt <<'EOF'
dashboard/data/JP_1M.csv
dashboard/data/RU_EQUITY.csv
EOF
rsync -avz --no-owner --no-group --chmod=D755,F644 \
  --files-from=/tmp/global_market_dashboard_upload_files.txt \
  -e "ssh -i '/Users/ruiyuma/Desktop/国债汇率/sol.pem' -o StrictHostKeyChecking=no" \
  ./ root@43.133.168.211:/opt/global-market-dashboard/
```

5. On the server, refresh quant fund from private env and re-render without another network fetch:

```bash
cd /opt/global-market-dashboard
chown -R root:root dashboard data
find dashboard data -type d -exec chmod 755 {} +
find dashboard data -type f -exec chmod 644 {} +
python3 quant_fund_snapshot.py
python3 market_dashboard.py --no-fetch
python3 validate_market_dashboard.py
```

6. Verify the public pages:

```bash
curl -fsS http://127.0.0.1/ -o /tmp/dashboard_home.html
curl -fsS http://127.0.0.1/quant_fund.html -o /tmp/quant.html
```

This procedure intentionally avoids storing private futures trades, API keys, principal amounts, or raw account balances on the server. Quant refresh should still leave only sanitized `{date, pct}` points in `dashboard/quant_fund_snapshot.json`.

## Quant Fund Privacy Rule

Goal: futures/options curves update automatically, but the server must not keep raw transaction details in public outputs.

Allowed public output:

```json
{
  "label": "期货",
  "status": "ok",
  "points": [
    {"date": "2026-04-23", "pct": -0.85}
  ],
  "latest_pct": -0.85
}
```

Forbidden in public HTML/snapshot:

- API keys or API env values
- principal amounts
- raw trade fields such as symbol, quote quantity, commission rows, order ids
- position strings
- account balance fields
- raw stablecoin labels or totals

The current sanitizer is enforced by:

```bash
python3 validate_market_dashboard.py
python3 -m pytest test_quant_fund_snapshot.py test_market_dashboard_quant_fund.py -q
```

## Quant Fund Env File

Private configuration lives only on the server:

```bash
mkdir -p /opt/global-market-dashboard/.private
chmod 700 /opt/global-market-dashboard/.private
vi /opt/global-market-dashboard/.private/quant_fund.env
chmod 600 /opt/global-market-dashboard/.private/quant_fund.env
```

Use environment variables for credentials and principal amounts. Do not commit this file.

Expected variable categories:

- futures API key and secret: Binance USD-M futures account used by the BTCUSDT futures trading script.
- option API key and secret: Binance options account used by the options account-status publisher.
- option-futures API key and secret: Binance USD-M futures account used by the options account-status publisher for its futures USDC component.
- futures symbol
- futures base capital
- options base capital
- optional start date
- optional local CSV path for one-time initialization

Important: `.private/` and generated snapshots are ignored by `.gitignore`.

Important credential rule:

- Futures API, options API, and option-futures API are three separate credential roles. Do not reuse one role for another.
- `BINANCE_FUTURES_API_KEY` / `BINANCE_FUTURES_API_SECRET` must be the futures trading API, the same account used by the local BTCUSDT futures trading code.
- `BINANCE_OPTION_API_KEY` / `BINANCE_OPTION_API_SECRET` must be the options account API, the same account used by `account_status_publisher/publish_account_status.py`.
- `BINANCE_OPTION_FUTURES_API_KEY` / `BINANCE_OPTION_FUTURES_API_SECRET` must be the futures-balance API used by the options account-status publisher. This is not the BTCUSDT futures trading API unless the publisher really uses the same account.
- The futures curve only reads futures trade/PnL data for `QUANT_FUND_SYMBOL`, normally `BTCUSDT`.
- The options curve reads option wallet value from `BINANCE_OPTION_API_*` and reads the stable futures balance component from `BINANCE_OPTION_FUTURES_API_*`.
- Never paste any API key into Git, public HTML, public JSON, shell history, or this document.

Local futures API reference:

```text
/Users/ruiyuma/Desktop/ML_TSF/jul_13/private/LTSF/Lorentzian_trading_Mao/2025_order_book_btc_shadow_ws_merge_add_bitget_htx_gate/LorentzianTrading_15_BTC.py
```

Use that local script only to identify which futures API account should be configured on the server. Do not copy hardcoded key values into tracked files.

## Futures Curve Logic

`quant_fund_snapshot.py` builds the futures curve from raw trades in memory:

1. Fetch or load raw futures trades from the futures API account only.
2. Compute net daily realized PnL:

```text
net = realizedPnl - stable-asset commission
```

3. Accumulate net PnL by date.
4. Divide cumulative PnL by the futures base capital.
5. Write only `{date, pct}` points to `dashboard/quant_fund_snapshot.json`.

The raw trade list is not written by the dashboard pipeline. It should only exist in memory while `quant_fund_snapshot.py` runs, unless using a one-time private CSV import path outside the public repo.

If the website does not show a closed BTCUSDT trade that is visible in the trading UI, first check that the server's `BINANCE_FUTURES_API_KEY` is the same futures account as the local Lorentzian BTC script. Do not debug this by swapping in the options API.

## Options Curve Logic

`quant_fund_snapshot.py` builds the options curve from account totals in memory:

1. Fetch option wallet total using the options API account.
2. Fetch futures stable balance using the dedicated option-futures API account when needed for combined option account value.
3. Compute percent return against the options base capital.
4. Upsert only today's `{date, pct}` point into the public snapshot.

Raw account totals, stablecoin balances, and position strings are not written to public HTML/snapshot.

Reference implementation for the options account-status calculation:

```text
/Users/ruiyuma/Desktop/ML_TSF/jul_13/private/LTSF/account_status_publisher/publish_account_status.py
```

The dashboard should match that publisher's account split:

- option wallet value comes from the options account API.
- futures balance comes from the publisher's futures source, normally `Option_Strategy_mao/OptionTrading_DHSS.py`.
- Do not let the options curve read the BTCUSDT trading API balance, because that corrupts the options return percentage.

## One-Time Local Seed

If local or private historical data is needed to initialize the public percentage curve:

1. Run the conversion locally or on the server from a private path.
2. Produce only sanitized `{date, pct}` points.
3. Copy only the sanitized `quant_fund_snapshot.json` into `dashboard/`.
4. Run:

```bash
python3 market_dashboard.py --no-fetch
python3 validate_market_dashboard.py
```

Do not upload raw CSVs, position dumps, or account exports into the repo.

## OrcaTerm Notes

When using Tencent Cloud OrcaTerm:

- The visible terminal may require pressing Enter after paste.
- Chrome CDP/raw low-level input is blocked for OrcaTerm and should not be used.
- If browser automation cannot type into OrcaTerm, prepare the command in the local/browser clipboard and paste manually in OrcaTerm.
- Prefer short, verifiable command blocks over very long one-shot commands.

## Post-Deploy Verification

After deployment, refresh:

```text
http://43.133.168.211/quant_fund.html
```

Check page behavior:

- Quant cards are clickable.
- Detail panels are hidden by default and shown after click.
- Futures/options curves display percent values only.
- Stock index card says `coming soon in 2026 3季度末`.
- Futures latest value is not the old stale value.
- Large curve date axis shows all dates, not only start/end.

Run server checks:

```bash
cd /opt/global-market-dashboard
python3 -m pytest test_market_dashboard_quant_fund.py test_quant_fund_snapshot.py -q
python3 validate_market_dashboard.py
python3 - <<'PY'
from pathlib import Path
html = Path("dashboard/quant_fund.html").read_text(encoding="utf-8")
snapshot = Path("dashboard/quant_fund_snapshot.json").read_text(encoding="utf-8")
for marker in ["BTCUSDT", "USDT", "USDC", "base_configured", "trade_count", "commission", "quoteQty"]:
    print(marker, marker in html or marker in snapshot)
print("axis_date_count", html.count('class="quant-axis-date"'))
PY
```

All marker lines should be `False`; `axis_date_count` should be greater than zero when the large quant curve has data.
