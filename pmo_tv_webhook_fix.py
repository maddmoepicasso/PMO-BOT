"""PMO TradingView webhook setup helper.

Run:
    python pmo_tv_webhook_fix.py

This prints the current PMO TradingView alert checklist and JSON payload
templates. It does not print private webhook secrets.
"""

from __future__ import annotations


PINE_STRATEGY_PAYLOAD = """{
  "ticker": "{{ticker}}",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "contracts": {{strategy.order.contracts}},
  "price": {{strategy.order.price}},
  "close": {{close}},
  "open": {{open}},
  "high": {{high}},
  "low": {{low}},
  "volume": {{volume}},
  "time": "{{time}}",
  "timenow": "{{timenow}}",
  "interval": "{{interval}}",
  "exchange": "{{exchange}}",
  "bar_index": {{bar_index}},
  "secret": "YOUR_WEBHOOK_SECRET_HERE"
}"""


PINE_INDICATOR_BUY_PAYLOAD = """{
  "ticker": "{{ticker}}",
  "symbol": "{{ticker}}",
  "action": "BUY",
  "price": {{close}},
  "close": {{close}},
  "open": {{open}},
  "high": {{high}},
  "low": {{low}},
  "volume": {{volume}},
  "time": "{{time}}",
  "timenow": "{{timenow}}",
  "interval": "{{interval}}",
  "exchange": "{{exchange}}",
  "bar_index": {{bar_index}},
  "secret": "YOUR_WEBHOOK_SECRET_HERE"
}"""


PINE_INDICATOR_SELL_PAYLOAD = PINE_INDICATOR_BUY_PAYLOAD.replace('"BUY"', '"SELL"')


def main() -> None:
    line = "=" * 72
    print(line)
    print("PMO TradingView Webhook Fix Kit")
    print(line)
    print(
        """
Root fixes:
  1. TradingView trigger must be: Once Per Bar Close
  2. Payload must include price or close with {{close}}
  3. Payload should include bar_index for same-bar deduplication
  4. Use HTTP 200 duplicate responses so TradingView does not retry storms
  5. PMO accepts both /tradingview and /api/tv-alert

Webhook URLs:
  Local: http://127.0.0.1:8091/tradingview
  Alias: http://127.0.0.1:8091/api/tv-alert
  Public/ngrok: https://YOUR-NGROK-DOMAIN/api/tv-alert

TradingView alert settings:
  Condition: your PMO condition
  Trigger: Once Per Bar Close
  Webhook URL: one of the URLs above
  Message: paste one JSON payload below
"""
    )
    print(line)
    print("Strategy payload")
    print(line)
    print(PINE_STRATEGY_PAYLOAD)
    print(line)
    print("Indicator BUY payload")
    print(line)
    print(PINE_INDICATOR_BUY_PAYLOAD)
    print(line)
    print("Indicator SELL payload")
    print(line)
    print(PINE_INDICATOR_SELL_PAYLOAD)
    print(line)
    print(
        """
PowerShell local test pattern:
  $payload = @{ ticker="NVDA"; action="BUY"; price=212.50; close=212.50;
    open=211.00; high=213.00; low=210.50; volume=125000; interval="5";
    exchange="NASDAQ"; time="2026-06-16T10:00:00Z"; timenow="2026-06-16T10:00:00Z";
    bar_index=42; secret="YOUR_WEBHOOK_SECRET_HERE" } | ConvertTo-Json

  Invoke-RestMethod -Uri "http://127.0.0.1:8091/api/tv-alert" `
    -Method POST -ContentType "application/json" -Body $payload
"""
    )


if __name__ == "__main__":
    main()
