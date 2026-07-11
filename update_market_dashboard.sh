#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 quant_fund_snapshot.py
python3 market_dashboard.py "$@"
python3 validate_market_dashboard.py
python3 audit_market_sources.py
