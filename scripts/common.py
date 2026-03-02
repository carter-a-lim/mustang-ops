from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "logs" / "job_runs.jsonl"
CONTEXT_PATH = ROOT / "data" / "mustang_context.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def log_job(job: str, started_at: str, status: str, error: str | None = None, output_path: str | None = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "job": job,
        "started_at": started_at,
        "ended_at": utc_now(),
        "status": status,
        "error": error,
        "output_path": output_path,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")
