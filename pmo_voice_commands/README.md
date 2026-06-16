# PMO Voice Command Packs

This folder keeps PMO BOT / PMO Desk Commander voice phrases separated by purpose so commands do not get mixed together.

PMO reads every `*.json` file in this folder automatically when a voice/text command is parsed. You do not need to edit `pmo_bot.py` to add normal command phrases.

## Rules

- Keep one category per file: status, reports, navigation, safe admin actions, blocked safety phrases.
- Do not put API keys, passwords, broker credentials, or admin tokens in this folder.
- Do not create voice commands that place orders, unlock live trading, disable risk controls, reveal secrets, or delete data.
- Voice commands map to registered Desk Commander tools only. The PMO backend firewall still decides whether the command is allowed.
- Admin/write tools still require the existing admin-token rules. Voice cannot bypass those rules.

## Add A Phrase

Open the matching JSON file and add another phrase to the `phrases` list:

```json
{
  "id": "status_overview",
  "tool": "get_pmo_status",
  "phrases": [
    "status",
    "how is pmo",
    "pmo bot status"
  ]
}
```

## Add A New Command

Use this shape:

```json
{
  "id": "my_command_name",
  "label": "My Command Name",
  "tool": "get_pmo_status",
  "intent": "tool",
  "confidence": 0.86,
  "phrases": ["my spoken phrase"],
  "examples": ["my spoken phrase"],
  "arguments": {}
}
```

## Test Commands

Use:

```powershell
Invoke-WebRequest -UseBasicParsing `
  -Uri "http://127.0.0.1:8091/api/ai/voice-commands" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"text":"what is missing","input_type":"voice"}'
```

## Current Safe Tool Names

- `get_pmo_status`
- `get_live_readiness`
- `get_safety_status`
- `refresh_connections`
- `run_switchboard_audit`
- `run_paper_proof`
- `refresh_watchlist`
- `run_backtest`
- `run_cobr_sim`
- `run_firewall_check`
- `run_pre_session_checklist`
- `explain_what_is_missing`
- `open_dashboard_section`
- `stop_voice`

Admin/write tools exist, but voice is not allowed to bypass the firewall.
