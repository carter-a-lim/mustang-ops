import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

ROOT = Path(__file__).resolve().parent
FALLBACK_CONTEXT = ROOT / "data" / "mustang_context.json"
CONTEXT_PATH = Path(os.getenv("MUSTANG_CONTEXT_PATH", str(FALLBACK_CONTEXT)))
if not CONTEXT_PATH.exists() and FALLBACK_CONTEXT.exists():
    CONTEXT_PATH = FALLBACK_CONTEXT

OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789")
OPENCLAW_TOKEN = os.getenv("OPENCLAW_TOKEN", "")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw:main")

JOBS = {
    "sync_canvas": ROOT / "jobs" / "sync_canvas.py",
    "morning_brief": ROOT / "jobs" / "morning_brief.py",
    "linkedin_scout": ROOT / "jobs" / "linkedin_scout.py",
    "token_sync": ROOT / "jobs" / "token_sync.py",
}

app = FastAPI(title="Mustang Ops")
app.mount("/web", StaticFiles(directory=str(ROOT / "web")), name="web")


class ChatBody(BaseModel):
    message: str


def read_context() -> dict:
    if not CONTEXT_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Context not found: {CONTEXT_PATH}")
    return json.loads(CONTEXT_PATH.read_text())


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/context")
def get_context():
    return read_context()


@app.post("/api/chat")
def chat(body: ChatBody):
    if not OPENCLAW_TOKEN:
        raise HTTPException(status_code=500, detail="OPENCLAW_TOKEN is missing")
    payload = {
        "model": OPENCLAW_MODEL,
        "messages": [{"role": "user", "content": body.message}],
    }
    res = requests.post(
        f"{OPENCLAW_BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=res.status_code, detail=res.text)
    data = res.json()
    return {"reply": data["choices"][0]["message"]["content"], "raw": data}


@app.post("/api/run/{job_name}")
def run_job(job_name: str):
    script = JOBS.get(job_name)
    if not script or not script.exists():
        raise HTTPException(status_code=404, detail="Unknown job")
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(["python3", str(script)], capture_output=True, text=True, cwd=str(ROOT))
    return {
        "job": job_name,
        "started_at": started,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
