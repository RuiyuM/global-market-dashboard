# Server Deployment Runbook

This note records the deployment logic for the dashboard so the server state is not lost between turns.

For sources that the server cannot fetch directly, read [Weekly Local Data Update](weekly_local_data_update.md) before running a manual weekly backfill.

## Server And Repo

- Public site: `https://43.133.168.211/`
- Server app path: `/opt/global-market-dashboard`
- Static web root: `/opt/global-market-dashboard/dashboard`
- Main page: `/opt/global-market-dashboard/dashboard/index.html`
- Quant page: `/opt/global-market-dashboard/dashboard/quant_fund.html`
- Public quant snapshot: `/opt/global-market-dashboard/dashboard/quant_fund_snapshot.json`
- Private quant config: `/opt/global-market-dashboard/.private/quant_fund.env`
- Private policy-news config: `/opt/global-market-dashboard/.private/policy_news.env`

Do not put private API keys, principal amounts, raw trades, positions, or account balances into GitHub, public HTML, or public snapshots.

## Normal Deployment

Code deployment is separate from market-data refresh. First commit and push only intentional code, tests, policy, and documentation from the local repository. Do not commit runtime cache churn merely to deploy code.

Then on the server:

```bash
cd /opt/global-market-dashboard
git pull --ff-only origin main
chown -R globaldash:globaldash /opt/global-market-dashboard
runuser -u globaldash -- python3 -m pytest -q
systemctl daemon-reload
systemctl start global-market-dashboard-update.service
```

If `git pull` reports an overlap with tracked runtime data, stop and inspect the conflicting paths. Do not reset or stash the whole server worktree blindly.

Verify deployment:

```bash
python3 validate_market_dashboard.py
python3 audit_market_sources.py
systemctl status global-market-dashboard-update.service --no-pager
```

## Daily Auto Update

The server update entry point is:

```bash
/opt/global-market-dashboard/update_market_dashboard.sh
```

That script runs:

```bash
python3 quant_fund_snapshot.py
python3 market_dashboard.py "$@"
python3 validate_market_dashboard.py
python3 audit_market_sources.py
```

The service runs as `globaldash`, loads policy-news credentials from the private environment file, and sets `MARKET_SKIP_INVESTING=1` because Investing.com is confirmed blocked from Tencent Cloud. The source audit treats those configured fallbacks as expected degradation. Allowlisted Yahoo errors produce `SOURCE AUDIT FALLBACK` while fresh cache continues serving; unhandled errors still fail the service.

Check timer and logs:

```bash
systemctl status global-market-dashboard-update.service
systemctl list-timers global-market-dashboard-update.timer
journalctl -u global-market-dashboard-update.service -n 200 --no-pager
```

## Manual Post-Close Full Refresh

Use the canonical local orchestrator; do not assemble a new rsync command from memory:

```bash
cd /Users/ruiyuma/Desktop/global-market-dashboard
source ~/anaconda3/bin/activate
python production_update.py
```

On the weekly OHLC refresh day:

```bash
python production_update.py --weekly
```

The orchestrator runs the server first, reads the machine policy, fetches only failed Yahoo and fixed local-required sources, uploads an allowlisted manifest, restores `globaldash` ownership, renders without another network fetch, and runs both validators. See [Fixed Market Data Update](weekly_local_data_update.md) for the exact source split.

Verify public pages after the command succeeds:

```bash
curl -fsS https://43.133.168.211/ -o /tmp/dashboard_home.html
curl -fsS https://43.133.168.211/quant_fund.html -o /tmp/quant.html
```

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

Policy-news credentials use a separate private file:

```bash
chown globaldash:globaldash /opt/global-market-dashboard/.private/policy_news.env
chmod 600 /opt/global-market-dashboard/.private/policy_news.env
```

The systemd drop-in may contain only `EnvironmentFile=/opt/global-market-dashboard/.private/policy_news.env`; it must not contain the key value itself. Rotate any key that has previously appeared in chat, a world-readable unit, shell history, or logs.

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
https://43.133.168.211/quant_fund.html
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

## SSH, Firewall, HTTPS, And Abuse Guard

The existing `root + sol.pem` workflow remains available, but root accepts public-key authentication only. The same authorized keys are installed for `lighthouse`, which has passwordless sudo and acts as the backup administrative path. The tracked SSH drop-in is `ops/ssh/00-dashboard-hardening.conf`; its early filename is intentional because OpenSSH uses the first value it reads.

Install and verify SSH hardening without closing the active session:

```bash
install -m 600 -o root -g root \
  /opt/global-market-dashboard/ops/ssh/00-dashboard-hardening.conf \
  /etc/ssh/sshd_config.d/00-dashboard-hardening.conf
sshd -t
systemctl reload sshd
sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|logingracetime|x11forwarding) '
```

Expected effective SSH state: root key login remains enabled as `without-password`, password login is disabled, `MaxAuthTries` is 3, and X11 forwarding is disabled. Always test fresh `root` and `lighthouse` key sessions before ending the current session.

Firewalld is enabled and its public zone permits only `ssh`, `http`, `https`, and the platform's `dhcpv6-client` helper. There must be no explicit FTP, `8888`, or `39000-40000` port ranges and forwarding must remain disabled:

```bash
firewall-cmd --zone=public --list-all
systemctl is-enabled firewalld
systemctl is-active firewalld
```

The server uses a publicly trusted Let's Encrypt IP-address certificate. IP certificates use the `shortlived` profile and expire after roughly six days, so the tracked `dashboard-certbot-renew.timer` checks twice daily. Certbot lives in `/opt/certbot`, the certificate lineage is `/etc/letsencrypt/live/43.133.168.211`, and the deploy hook validates and reloads Nginx.

Install the tracked renewal units and hook:

```bash
install -m 755 ops/certbot/reload-nginx.sh /usr/local/sbin/dashboard-certbot-reload-nginx
install -m 644 ops/systemd/dashboard-certbot-renew.service /etc/systemd/system/dashboard-certbot-renew.service
install -m 644 ops/systemd/dashboard-certbot-renew.timer /etc/systemd/system/dashboard-certbot-renew.timer
systemctl daemon-reload
systemctl enable --now dashboard-certbot-renew.timer
```

Test the complete ACME renewal path after any certificate or Nginx change:

```bash
/opt/certbot/bin/certbot renew --dry-run --no-random-sleep-on-renew \
  --cert-name 43.133.168.211 \
  --deploy-hook /usr/local/sbin/dashboard-certbot-reload-nginx
```

The production config is tracked at `ops/nginx/global-market-dashboard.conf`. Render `__APP_DIR__` to the actual app path before installing it. Do not restore the old static-site fallback `try_files $uri $uri/ /index.html`; unknown scanner paths must return a small `404` instead of the multi-megabyte dashboard.

The tracked config provides:

- gzip for HTML, JSON, JavaScript, CSS, and SVG;
- per-IP request and connection limits with HTTP `429` on excess;
- GET/HEAD-only public access;
- hidden-file denial and browser security headers;
- TLS 1.2/1.3 with a trusted IP certificate and HSTS;
- conservative timeouts without blocking ordinary dashboard use.

Deploy and verify on OpenCloudOS:

```bash
sed \
  -e 's|__APP_DIR__|/opt/global-market-dashboard|g' \
  -e 's|__PUBLIC_IP__|43.133.168.211|g' \
  /opt/global-market-dashboard/ops/nginx/global-market-dashboard.conf \
  >/etc/nginx/conf.d/global-market-dashboard.conf
nginx -t
systemctl reload nginx
curl -sSI http://43.133.168.211/
curl -sSI -H 'Accept-Encoding: gzip' https://43.133.168.211/
curl -sSI https://43.133.168.211/admin
```

HTTP `/` must redirect to HTTPS, the HTTPS response must include `Content-Encoding: gzip` and the security headers, and the HTTPS unknown path must return `404`, not `200` and not the dashboard body. A few scanner requests in the access log are normal; only call it an active attack when request/concurrency/error rates materially rise, not merely because probe paths appear.

## Policy News Refresh

The weekly OpenAI-classified news cache is private-credential backed but the resulting headlines are public. A cached render must retain the latest classified news instead of reverting to examples.

To refresh only the policy-news radar while preserving market CSVs:

```bash
runuser -u globaldash -- bash -c \
  'set -a; source /opt/global-market-dashboard/.private/policy_news.env; set +a; cd /opt/global-market-dashboard; python3 market_dashboard.py --no-fetch --force-policy-news-refresh'
python3 validate_market_dashboard.py
```

Never put the key value in the command line, Git, service unit, logs, or dashboard output. After a refresh, inspect all six regions for wrong-country headlines and impossible policy actions. Federal Reserve year sections must stop at the next official table heading so older rows cannot be assigned to a newer year.
