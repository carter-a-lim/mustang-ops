import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
USAGE_EVENTS_PATH = DATA_DIR / "usage_events.jsonl"

OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789")
OPENCLAW_TOKEN = os.getenv("OPENCLAW_TOKEN", "")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw:main")


def usage_from_response(data: dict) -> dict:
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    model = data.get("model") or OPENCLAW_MODEL
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def append_usage_event(event: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with USAGE_EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def call_openclaw(messages: list[dict[str, str]], model: str = None) -> str:
    if not OPENCLAW_TOKEN:
        raise ValueError("OPENCLAW_TOKEN is missing")

    payload = {
        "model": model or OPENCLAW_MODEL,
        "messages": messages,
    }
    try:
        res = requests.post(
            f"{OPENCLAW_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenClaw upstream request failed: {exc}")

    if res.status_code >= 400:
        raise RuntimeError(f"OpenClaw error {res.status_code}: {res.text}")

    try:
        data = res.json()
    except ValueError:
        raise RuntimeError("OpenClaw upstream returned invalid JSON")

    event = usage_from_response(data)
    append_usage_event(event)
    return data["choices"][0]["message"]["content"]
