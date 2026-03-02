# Mustang Ops

Personal operator stack for startup + school + coding workflows.

## Modules

1. **Chat Command Center** (Open WebUI)
2. **Mustang Context** (`data/mustang_context.json`)
3. **Intelligence & Outreach** (jobs + queue)
4. **Build & Ship Panel** (GitHub + infra checks)
5. **Skill Inventory** (installed skills status)
6. **Heartbeat/Cron Layer** (scheduled automation)

## Quick Start

```bash
cd mustang-ops
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/init_context.py
python scripts/validate_context.py
```

## Jobs

Run a job manually:

```bash
python jobs/sync_canvas.py
python jobs/morning_brief.py
python jobs/linkedin_scout.py
python jobs/token_sync.py
```

Each job appends run metadata to `logs/job_runs.jsonl`.

## Cron

Install cron entries from `config/crontab.txt`:

```bash
crontab config/crontab.txt
```

## Data Contracts

- `schemas/mustang_context.schema.json`
- `schemas/job_run.schema.json`

## GitHub Repo Expectations

- Keep secrets in `.env` only
- Keep `data/` private and local by default
- Commit code + schemas, never API keys/tokens
