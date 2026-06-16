# PMO BOT v206 Modular Core Extraction Package

This package includes both upgrades requested:

1. **v205.5 Pre-Extraction Hardening Patch**
   - Restores `/control` by removing the accidental `abort(404)`.
   - Adds broader admin protection for state-changing/report-writing POST routes.
   - Changes report/proof endpoints with a `record` parameter to default to `record=false`.
   - Adds dependency checks and a route-audit report.
   - Normalizes the main file to clean UTF-8.

2. **v206 Modular Core Extraction Foundation**
   - Adds `pmo_core` modules for storage, agent planning, hardening, settings, paths, environment, reporting, security, market data, execution guard, proof center, TradingView bridge, dashboard context, route registry, and payments.
   - Keeps the trading behavior compatibility-safe by leaving the full PMO Bot orchestration in `pmo_bot.py` while the new module boundaries are introduced.

## Install

Copy the entire `Python` folder contents into your PMO_BOT/Python folder, replacing `pmo_bot.py` and adding the `pmo_core` folder.

## Run checks

```powershell
python -m py_compile pmo_bot.py
python -m py_compile pmo_core\*.py
python pmo_bot.py --once
python pmo_bot.py
```

Live trading switches remain unchanged and locked by default.
