# Mustang Ops (Rebuilt)

Local-only dashboard + automation backend for your Mustang OS.

## Architecture

- **Host:** Oracle Ubuntu instance
- **Network:** local bind on `127.0.0.1:8080` (use SSH tunnel)
- **Brain:** OpenClaw Gateway at `http://127.0.0.1:18789/v1/chat/completions`
- **Memory:** `/home/ubuntu/mustang-ops/data/mustang_context.json` (fallback to repo `data/`)
- **Backend:** lightweight FastAPI app
- **Frontend:** single `web/index.html` with vanilla JS

## Setup

```bash
cd mustang-ops
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
npm install
cp .env.example .env
```

Set `OPENCLAW_TOKEN` inside `.env`.

## Run

```bash
uvicorn app:app --host 127.0.0.1 --port 8080
```

## SSH Tunnel (from your local machine)

```bash
ssh -L 8080:localhost:8080 ubuntu@<oracle-host>
```

Open: `http://localhost:8080`

## API Endpoints

- `GET /api/context` -> returns context JSON
- `GET /api/network/metrics` -> pipeline totals + conversion metrics
- `POST /api/chat` -> sends prompt to OpenClaw `/v1/chat/completions`
- `POST /api/run/{job_name}` -> runs one job script
- `POST /api/network/apply/scrape` -> scrape application questions (Greenhouse/Lever/Ashby/Workday + fallback)
- `POST /api/network/apply/generate` -> generate draft answers from resume + answer memory
- `PATCH /api/network/apply/queue/{job_id}` -> approve/reject/status updates for queue items
- `POST /api/network/apply/queue/{job_id}/execute` -> run Playwright autofill worker (`dry-run` or `live`)
- `POST /api/calendar/events` -> create calendar event via gog
- `DELETE /api/calendar/events/{event_id}` -> delete calendar event via gog

Valid jobs: `sync_canvas`, `morning_brief`, `linkedin_scout`, `token_sync`, `scrape_simplify_jobs`, `auto_apply_orchestrator`, `sync_gmail`

Calendar API uses:
- `GOG_ACCOUNT` (required)
- `GOG_CALENDAR_ID` (optional, defaults to `primary`)

## Auto-apply orchestration (semi-auto)

This repo includes `jobs/auto_apply_orchestrator.py` to coordinate application prep.

```bash
# Full pipeline (prepare -> enrich -> draft -> queue approval)
python3 jobs/auto_apply_orchestrator.py --stage all

# Just submit already-approved apps (max 3)
python3 jobs/auto_apply_orchestrator.py --stage submit --max 3

# Safe test run
python3 jobs/auto_apply_orchestrator.py --stage all --dry-run
```

State is written to `data/auto_apply_state.json`.

### API trigger endpoints

- `POST /api/auto-apply/run` with body:

```json
{ "stage": "all", "max": 25, "dry_run": false }
```

`stage` supports: `prepare | enrich | draft | queue | submit | all`

### n8n workflow templates

Import these in n8n:

- `deploy/n8n-workflow-auto-apply-scheduled.json`
- `deploy/n8n-workflow-auto-apply-approval.json`

After import:

1. In approval workflow, edit **Token OK?** and replace `change-me-strong-token`.
2. Activate both workflows.
3. Trigger approval submit via webhook (example):

```bash
curl -X POST "https://<your-n8n>/webhook/auto-apply-approve" \
  -H 'content-type: application/json' \
  -d '{"token":"change-me-strong-token","max":5}'
```


## Resume Generation Pipeline

Mustang Ops includes an end-to-end ATS-optimized resume generation pipeline:
- **Tailored Bullets:** Automatically selects the best-fitting resume bullets based on keyword overlap with the job description and the presence of impact metrics.
- **Strict Formatting:** Adheres to a single-column, plain HTML/PDF layout designed to pass through ATS systems perfectly.
- **Budgeting Guardrails:** Automatically drops the lowest-scored bullets until the resume fits strictly onto one page.
- **UI Integration:** One-click generation available directly in the Assisted Apply Queue dashboard.
