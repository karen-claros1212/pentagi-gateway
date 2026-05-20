# PentAGI Gateway

Telegram ↔ PentAGI GraphQL bridge with strict safety gates.

## Safety posture

Default mode is `READ_ONLY`. The Gateway never sends free text directly to PentAGI and the LLM/Brain never executes anything. All mutation requests are classified into structured intents, checked by policy, converted to a pending approval, and revalidated again at confirmation time.

Real Telegram is **NO-GO** until `TELEGRAM_BOT_TOKEN` is configured locally. Real mutations are **NO-GO** until deliberate `ASSISTED_EXECUTION` approval testing is performed.

## Modes

- `READ_ONLY`: read/list/report actions only. All mutations are blocked with: `Bloqueado: Gateway está en READ_ONLY. Esa acción requiere ASSISTED_EXECUTION y aprobación.`
- `REPORT_ONLY`: read/report only; no mutations.
- `ASSISTED_EXECUTION`: mutation requests create one-use approvals. Confirmation is required before execution.
- `LOCKED`: all governed actions are blocked.

`deleteFlow` is extra protected: it requires admin role, `DELETE_FLOW_ENABLED=true`, and `/confirm_delete <code>`. Normal `/confirm` cannot execute delete.

## Conversational operator model

PentAGI Gateway is a Telegram operator UI, not a command router. The intended path is:

`Telegram message → natural conversation → active flow context → policy → UI-equivalent action → response with buttons`

The Gateway mirrors the real PentAGI UI concepts: active flow context, providers, assistants/tasks, logs, live/event state and state-based actions. Buttons never bypass governance; callbacks are routed back through the same dispatcher and policy engine as text and commands.

Conversational examples:

- `hola` / `buenas` → natural operator introduction with buttons.
- `quién eres` → explains the PentAGI Gateway operator identity.
- `qué puedes hacer` → describes capabilities in human language before technical commands.
- Flow activity question with no active flow → offers flow selection instead of a technical error.
- Active flow running → shows a state summary and action buttons.
- Active flow waiting → asks for user input; in `READ_ONLY`, explains that sending input is blocked unless `ASSISTED_EXECUTION` plus approval is enabled.
- Active flow finished/stopped → offers report-oriented actions such as summary and findings.
- Sensitive actions → blocked in `READ_ONLY`; approval-gated in `ASSISTED_EXECUTION`.
- GraphQL/auth errors → safe human message with redaction, no traceback or token echo.

## Natural Language First

Natural language is the primary interface; commands are fallback. Offline deterministic examples:

- `muéstrame los flows` → list flows
- `abre este flow <id>` → bind active flow and show detail
- `qué está haciendo` → active flow status/summary
- `resume el flow` → active flow summary
- `qué encontró` → recent findings from tasks/logs
- `crea un flow...` → approval request, no direct execution
- `dile que continúe` → input approval for active flow
- `detén todo` → stop approval for active flow, or clarification
- `hola` / `buenas` → operator intro with inline menu
- `quién eres` → identity of the Gateway operator
- `qué puedes hacer` → capabilities in plain language
- ambiguous text → clarification
- delete/destructive text → blocked by default

## Commands fallback

Read/report:

- `/providers`
- `/flows`
- `/flow <id>`
- `/tasks <flow_id>`
- `/logs <flow_id>`
- `/terminal <flow_id>`
- `/bind <flow_id>`
- `/unbind`
- `/active`
- `/summary <flow_id>`
- `/report <flow_id>`

Controlled approval commands:

- `/create_flow <prompt>`
- `/send <text>`
- `/stop_flow <flow_id>`
- `/finish_flow <flow_id>`
- `/rename_flow <flow_id> <name>`
- `/delete_flow <flow_id>`
- `/confirm <code>`
- `/confirm_delete <code>`
- `/deny <code>`

Watcher skeleton:

- `/watch <flow_id>`
- `/unwatch <flow_id>`
- `/watch_status`

Subscriptions are disabled unless `PENTAGI_SUBSCRIPTIONS_ENABLED=true`.

## Environment

Copy `.env.example` to `.env` only on the host where secrets are managed. Do not commit `.env`.

Key variables:

```env
PENTAGI_BASE_URL=https://localhost:8443
PENTAGI_GRAPHQL_PATH=/api/v1/graphql
PENTAGI_API_TOKEN=REPLACE_ME
PENTAGI_VERIFY_TLS=false
PENTAGI_DEFAULT_PROVIDER=qwen

TELEGRAM_BOT_TOKEN=REPLACE_ME
TELEGRAM_ALLOWED_USERS=123456789
TELEGRAM_ALLOWED_CHATS=
TELEGRAM_INLINE_BUTTONS=true

GATEWAY_MODE=READ_ONLY
GATEWAY_SQLITE_PATH=./data/gateway.sqlite
GATEWAY_LOG_LEVEL=INFO

LLM_ENABLED=false
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=
LLM_MODEL=qwen

DELETE_FLOW_ENABLED=false
PENTAGI_SUBSCRIPTIONS_ENABLED=false
APPROVAL_TTL_SECONDS=300
NATURAL_LANGUAGE_FIRST=true
COMMANDS_AS_FALLBACK=true
```

## Local validation

All tests are offline/mocked and must not call real GraphQL or Telegram.

```bash
python3 -m compileall gateway
pytest -q
ruff check .
grep -RniE 'Bearer |PENTAGI_API_TOKEN=|TELEGRAM_BOT_TOKEN=|[0-9]{8,}:[A-Za-z0-9_-]{20,}' . --exclude-dir=.venv --exclude-dir=.git || true
```

## Host READ_ONLY smoke

Only run this on the host project path where `.env` already exists. It performs read-only health/listing only and must not print tokens.

```bash
cd /home/jesus/Proyectos/pentagi-gateway
. .venv/bin/activate
python - <<'PY'
import asyncio
from gateway.config import Settings
from gateway.pentagi.client import PentagiClient

async def main():
    s = Settings()
    if not s.pentagi_api_token:
        raise SystemExit("NO-GO: PENTAGI_API_TOKEN missing")
    if not s.telegram_bot_token or s.telegram_bot_token == "REPLACE_ME":
        print("Telegram blocker: TELEGRAM_BOT_TOKEN placeholder; real Telegram NO-GO.")
    c = PentagiClient(s.graphql_url, s.pentagi_api_token, s.pentagi_verify_tls)
    try:
        ok = await c.health_check()
        flows = await c.list_flows()
        print(f"READ_ONLY GraphQL smoke: health={ok}, flows_count={len(flows)}")
    finally:
        await c.close()

asyncio.run(main())
PY
```
