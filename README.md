# PentAGI Gateway

Telegram ↔ PentAGI GraphQL bridge bot.

## Phase 1 — READ-ONLY

Commands:
- `/flows` — list PentAGI flows
- `/flow <id>` — flow detail
- `/tasks <flow_id>` — flow tasks
- `/providers` — LLM providers configured
- `/logs <flow_id>` — message logs
- `/help` — help message

## Setup

```bash
cp .env.example .env
# Edit .env with your tokens
pip install -r requirements.txt
python -m gateway.main
```
