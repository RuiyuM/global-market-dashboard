# Global Market Dashboard

Static dashboard for monitoring U.S., China, Japan, Germany, Russia, and Korea across:

- 2Y and 10Y bond yields
- Equity indices
- FX versus CNY
- 1D, 7D, 14D, 30D changes
- Weekly average volatility
- First/second derivative monitor with clickable OHLC visualization
- Three-currency FX flow routes: 中日美, 中德美, 中俄美

The generated site is a static file under `dashboard/index.html`, so it can be hosted by Nginx and accessed by server IP without a domain.

## Local Update

```bash
./update_market_dashboard.sh
python3 validate_market_dashboard.py
open dashboard/index.html
```

## One-Command Server Deploy

On a fresh Ubuntu/Debian/OpenCloudOS/CentOS/RHEL server:

```bash
curl -fsSL https://raw.githubusercontent.com/RuiyuM/global-market-dashboard/main/install_server.sh | sudo bash
```

After installation, open:

```text
http://YOUR_SERVER_IP/
```

Use your real public IP in a browser address bar. Do not run `http://...` as a shell command.

No domain is required.

## What The Installer Does

- Installs `git`, `python3`, `curl`, and `nginx`
- Clones this repo to `/opt/global-market-dashboard`
- Runs an initial dashboard update and validation
- Configures Nginx to serve `/opt/global-market-dashboard/dashboard`
- Creates a systemd timer to update the dashboard daily

## Operations

Manual update:

```bash
sudo systemctl start global-market-dashboard-update.service
```

Check update status:

```bash
systemctl status global-market-dashboard-update.service
systemctl list-timers global-market-dashboard-update.timer
```

View logs:

```bash
journalctl -u global-market-dashboard-update.service -n 200 --no-pager
```
