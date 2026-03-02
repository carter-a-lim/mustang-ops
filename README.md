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
- `POST /api/chat` -> sends prompt to OpenClaw `/v1/chat/completions`
- `POST /api/run/{job_name}` -> runs one job script

Valid jobs: `sync_canvas`, `morning_brief`, `linkedin_scout`, `token_sync`, `scrape_simplify_jobs`
