import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USAGE_EVENTS_PATH = DATA_DIR / "usage_events.jsonl"
CHAT_SESSIONS_PATH = DATA_DIR / "chat_sessions.json"
JOB_PIPELINE_PATH = DATA_DIR / "job_pipeline.json"

FALLBACK_CONTEXT = ROOT / "data" / "mustang_context.json"
CONTEXT_PATH = Path(os.getenv("MUSTANG_CONTEXT_PATH", str(FALLBACK_CONTEXT)))
if not CONTEXT_PATH.exists() and FALLBACK_CONTEXT.exists():
    CONTEXT_PATH = FALLBACK_CONTEXT

OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789")
OPENCLAW_TOKEN = os.getenv("OPENCLAW_TOKEN", "")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw:main")

# Optional cost estimation. Set in .env if you want dollar estimates.
# Example: 1.5 means $1.50 per 1M tokens.
COST_INPUT_PER_1M = float(os.getenv("MUSTANG_COST_INPUT_PER_1M", "0"))
COST_OUTPUT_PER_1M = float(os.getenv("MUSTANG_COST_OUTPUT_PER_1M", "0"))
LIMIT_5H_TOKENS = int(os.getenv("MUSTANG_LIMIT_5H_TOKENS", "200000"))
LIMIT_7D_TOKENS = int(os.getenv("MUSTANG_LIMIT_7D_TOKENS", "2000000"))

JOBS = {
    "sync_canvas": ROOT / "jobs" / "sync_canvas.py",
    "sync_github": ROOT / "jobs" / "sync_github.py",
    "sync_network": ROOT / "jobs" / "sync_network.py",
    "morning_brief": ROOT / "jobs" / "morning_brief.py",
    "linkedin_scout": ROOT / "jobs" / "linkedin_scout.py",
    "token_sync": ROOT / "jobs" / "token_sync.py",
}

app = FastAPI(title="Mustang Ops")
app.mount("/web", StaticFiles(directory=str(ROOT / "web")), name="web")


class ChatBody(BaseModel):
    message: str
    session_id: str | None = None


class CreateSessionBody(BaseModel):
    title: str | None = None


def read_context() -> dict:
    if not CONTEXT_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Context not found: {CONTEXT_PATH}")
    return json.loads(CONTEXT_PATH.read_text())


def _tail_lines(path: Path, n: int = 20) -> list[str]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(errors="ignore").replace("\x00", "")
        lines = ["".join(ch for ch in line if ch.isprintable() or ch.isspace()).strip() for line in raw.splitlines()]
        lines = [l for l in lines if l]
        return lines[-n:]
    except Exception:
        return []


def _agent_inbox() -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    items = []

    # Running background jobs related to Mustang Ops
    try:
        ps = subprocess.run(["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True, check=False)
        for line in ps.stdout.splitlines()[1:]:
            if "jobs/" in line and "python3" in line and "mustang-ops" in line:
                parts = line.strip().split(maxsplit=2)
                if len(parts) < 3:
                    continue
                pid, etimes, cmd = parts[0], parts[1], parts[2]
                items.append(
                    {
                        "type": "job",
                        "name": cmd.split("jobs/")[-1].split()[0],
                        "status": "running",
                        "pid": int(pid),
                        "seconds_running": int(etimes),
                        "summary": cmd,
                    }
                )
    except Exception:
        pass

    # Recent cron/server activity as monitor feed
    for source, file_name in (("cron", "logs/cron.log"), ("server", "logs/server.log")):
        lines = [l for l in _tail_lines(ROOT / file_name, 12) if l.strip()]
        for l in lines[-4:]:
            items.append(
                {
                    "type": source,
                    "name": source,
                    "status": "activity",
                    "summary": l[-180:],
                }
            )

    # Chat sessions recently active (treated as active threads)
    store = _load_chat_store()
    for s in store.get("sessions", [])[:12]:
        items.append(
            {
                "type": "session",
                "name": s.get("title", "Untitled"),
                "status": "idle",
                "updated_at": s.get("updated_at"),
                "summary": f"{len(s.get('messages', []))} messages",
                "id": s.get("id"),
            }
        )

    # newest first for session/activity, running jobs pinned first
    def _k(x):
        if x.get("status") == "running":
            return (0, x.get("seconds_running", 0))
        return (1, 0)

    items.sort(key=_k)
    return {"updated_at": now, "items": items[:40]}


def _load_chat_store() -> dict:
    if not CHAT_SESSIONS_PATH.exists():
        return {"sessions": []}
    try:
        return json.loads(CHAT_SESSIONS_PATH.read_text())
    except Exception:
        return {"sessions": []}


def _save_chat_store(store: dict) -> None:
    CHAT_SESSIONS_PATH.write_text(json.dumps(store, indent=2) + "\n")


def _find_session(store: dict, session_id: str) -> dict | None:
    for s in store.get("sessions", []):
        if s.get("id") == session_id:
            return s
    return None


def _usage_from_response(data: dict) -> dict:
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


def _append_usage_event(event: dict) -> None:
    with USAGE_EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _load_usage_events() -> list[dict]:
    if not USAGE_EVENTS_PATH.exists():
        return []
    events = []
    with USAGE_EVENTS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens / 1_000_000) * COST_INPUT_PER_1M + (completion_tokens / 1_000_000) * COST_OUTPUT_PER_1M


def _sum_events(events: list[dict]) -> dict:
    prompt = sum(int(e.get("prompt_tokens", 0)) for e in events)
    completion = sum(int(e.get("completion_tokens", 0)) for e in events)
    total = sum(int(e.get("total_tokens", 0)) for e in events)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "estimated_cost_usd": round(_estimate_cost(prompt, completion), 6),
    }


def _read_meminfo_kb() -> tuple[int, int]:
    total = 0
    available = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
    except Exception:
        pass
    return total, available


def _node_version() -> str:
    try:
        out = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=2)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _system_stats() -> dict:
    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0

    mem_total_kb, mem_avail_kb = _read_meminfo_kb()
    mem_used_kb = max(mem_total_kb - mem_avail_kb, 0)
    mem_pct = (mem_used_kb / mem_total_kb * 100) if mem_total_kb else 0

    du = shutil.disk_usage("/")
    disk_pct = (du.used / du.total * 100) if du.total else 0

    return {
        "cpu": {
            "label": "CPU Load",
            "percent": round(min(100.0, max(0.0, (load1 / max(os.cpu_count() or 1, 1)) * 100)), 1),
            "detail": f"{(os.cpu_count() or 1)} cores · load1 {load1:.2f}",
        },
        "memory": {
            "label": "Memory",
            "percent": round(mem_pct, 1),
            "detail": f"{mem_used_kb/1024/1024:.1f}GB / {mem_total_kb/1024/1024:.1f}GB" if mem_total_kb else "n/a",
        },
        "system": {
            "label": "Active Node.js",
            "value": _node_version(),
            "detail": f"Disk {du.used/1024/1024/1024:.1f}GB / {du.total/1024/1024/1024:.1f}GB ({disk_pct:.0f}%)",
        },
    }


def _load_openclaw_config() -> dict:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text())
    except Exception:
        return {}


def _required_env_for_skill(skill_name: str) -> list[str]:
    required = {
        "github": ["GITHUB_TOKEN"],
        "gog": ["GOG_ACCOUNT", "GOG_KEYRING_PASSWORD"],
        "canvas-lms": ["CANVAS_URL", "CANVAS_TOKEN"],
        "tavily-search": ["TAVILY_API_KEY"],
    }
    return required.get(skill_name, [])


def _skill_group(skill_name: str) -> str:
    school = {"canvas-lms", "gog"}
    build = {"github", "coding", "clean-code", "playwright-mcp"}
    growth = {"growth-hacker", "tavily-search", "find-skills", "startup-agent"}
    ops = {"healthcheck", "self-improving-agent", "tmux", "clawhub"}

    if skill_name in school:
        return "School"
    if skill_name in build:
        return "Build"
    if skill_name in growth:
        return "Growth"
    if skill_name in ops:
        return "Ops"
    return "General"


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/context")
def get_context():
    return read_context()


@app.get("/api/skills")
def get_skills():
    workspace_skills_dir = ROOT.parent / "skills"
    user_skills_dir = Path.home() / ".agents" / "skills"
    core_skills_dir = Path.home() / ".npm-global" / "lib" / "node_modules" / "openclaw" / "skills"

    cfg = _load_openclaw_config()
    configured_entries = cfg.get("skills", {}).get("entries", {})

    discovered: dict[str, dict] = {}

    for skills_dir, source in ((workspace_skills_dir, "workspace"), (user_skills_dir, "user"), (core_skills_dir, "core")):
        if not skills_dir.exists():
            continue
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir() or not (d / "SKILL.md").exists():
                continue
            name = d.name
            discovered[name] = {
                "name": name,
                "source": source,
                "group": _skill_group(name),
                "required_env": _required_env_for_skill(name),
            }

    skills = []
    for name, meta in sorted(discovered.items(), key=lambda x: x[0].lower()):
        env_cfg = (configured_entries.get(name) or {}).get("env", {})
        required = meta["required_env"]
        missing = [k for k in required if not env_cfg.get(k)]

        if not required:
            readiness = "ready"
        elif missing:
            readiness = "needs-config"
        else:
            readiness = "ready"

        skills.append(
            {
                "name": name,
                "source": meta["source"],
                "group": meta["group"],
                "status": "installed",
                "readiness": readiness,
                "required_env": required,
                "missing_env": missing,
                "configured": len(missing) == 0,
                "usage": {
                    "last_used": None,
                    "runs_24h": 0,
                    "runs_7d": 0,
                    "success_rate": None,
                    "common_failure": None,
                },
                "actions": {
                    "docs": f"https://skills.sh/search?q={name}",
                    "test": f"Test {name}",
                    "update": f"Update {name}",
                },
            }
        )

    recommendations = [
        {
            "name": "linkedin-automation",
            "why": "Automate outreach + profile actions for your Network pipeline",
            "install": "npx skills add composiohq/awesome-claude-skills@linkedin-automation -g -y",
        },
        {
            "name": "gtm-prospecting",
            "why": "Rank high-value people to connect with from your field",
            "install": "npx skills add jforksy/claude-skills@gtm-prospecting -g -y",
        },
    ]

    health = {
        "total": len(skills),
        "ready": len([s for s in skills if s["readiness"] == "ready"]),
        "needs_config": len([s for s in skills if s["readiness"] == "needs-config"]),
    }

    return {"skills": skills, "health": health, "recommendations": recommendations}


@app.get("/api/github")
def get_github_snapshot():
    p = ROOT / "data" / "github_snapshot.json"
    if not p.exists():
        return {"updated_at": None, "repos": []}
    return json.loads(p.read_text())


@app.get("/api/network/jobs")
def get_network_jobs():
    if not JOB_PIPELINE_PATH.exists():
        return {
            "updated_at": None,
            "roles": [],
            "applications": [],
            "outreach_targets": [],
        }
    try:
        return json.loads(JOB_PIPELINE_PATH.read_text())
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid job pipeline data")


@app.get("/api/agents/inbox")
def agents_inbox():
    return _agent_inbox()


@app.get("/api/network")
def get_network():
    p = ROOT / "data" / "network_context.json"
    if not p.exists():
        return {
            "updated_at": None,
            "contacts": [],
            "interactions": [],
            "opportunities": [],
            "introductions": [],
            "summary": {"pending_followups": 0, "warm_leads": 0, "intros_available": 0, "reply_rate": 0},
        }
    return json.loads(p.read_text())


@app.get("/api/system/stats")
def system_stats():
    return _system_stats()


@app.get("/api/cron/list")
def cron_list():
    cron_path = ROOT / "config" / "crontab.txt"
    jobs = []
    if cron_path.exists():
        for line in cron_path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split(maxsplit=5)
            if len(parts) < 6:
                continue
            schedule = " ".join(parts[:5])
            command = parts[5]
            jobs.append({"schedule": schedule, "command": command})
    return {"jobs": jobs}


@app.get("/api/usage/summary")
def usage_summary():
    now = datetime.now(timezone.utc)
    events = _load_usage_events()

    events_with_dt = []
    for e in events:
        try:
            dt = datetime.fromisoformat(e.get("ts"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        events_with_dt.append((dt, e))

    last_5h_cutoff = now - timedelta(hours=5)
    last_7d_cutoff = now - timedelta(days=7)

    last_5h_events = [e for dt, e in events_with_dt if dt >= last_5h_cutoff]
    last_7d_events = [e for dt, e in events_with_dt if dt >= last_7d_cutoff]

    daily = {}
    for dt, e in events_with_dt:
        if dt < last_7d_cutoff:
            continue
        day = dt.date().isoformat()
        daily.setdefault(day, []).append(e)

    daily_buckets = []
    for day in sorted(daily.keys()):
        sums = _sum_events(daily[day])
        sums["date"] = day
        daily_buckets.append(sums)

    last_5h = _sum_events(last_5h_events)
    last_7d = _sum_events(last_7d_events)

    limit_5h = max(LIMIT_5H_TOKENS, 1)
    limit_7d = max(LIMIT_7D_TOKENS, 1)

    return {
        "pricing": {
            "input_per_1m": COST_INPUT_PER_1M,
            "output_per_1m": COST_OUTPUT_PER_1M,
            "cost_estimation_enabled": COST_INPUT_PER_1M > 0 or COST_OUTPUT_PER_1M > 0,
        },
        "limits": {
            "last_5h_tokens": limit_5h,
            "last_7d_tokens": limit_7d,
        },
        "windows": {
            "last_5h": {
                **last_5h,
                "percent_used": round((last_5h["total_tokens"] / limit_5h) * 100, 2),
                "percent_remaining": round(max(0.0, 100 - (last_5h["total_tokens"] / limit_5h) * 100), 2),
            },
            "last_7d": {
                **last_7d,
                "percent_used": round((last_7d["total_tokens"] / limit_7d) * 100, 2),
                "percent_remaining": round(max(0.0, 100 - (last_7d["total_tokens"] / limit_7d) * 100), 2),
            },
        },
        "daily_last_7d": daily_buckets,
        "event_count": len(events_with_dt),
    }


@app.get("/api/chat/sessions")
def list_chat_sessions():
    store = _load_chat_store()
    sessions = store.get("sessions", [])
    sessions = sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
    return {
        "sessions": [
            {
                "id": s.get("id"),
                "title": s.get("title", "Untitled"),
                "updated_at": s.get("updated_at"),
                "created_at": s.get("created_at"),
                "message_count": len(s.get("messages", [])),
            }
            for s in sessions
        ]
    }


@app.post("/api/chat/sessions")
def create_chat_session(body: CreateSessionBody):
    now = datetime.now(timezone.utc).isoformat()
    sid = str(uuid.uuid4())
    session = {
        "id": sid,
        "title": (body.title or "New Chat").strip() or "New Chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    store = _load_chat_store()
    store.setdefault("sessions", []).append(session)
    _save_chat_store(store)
    return session


@app.get("/api/chat/sessions/{session_id}")
def get_chat_session(session_id: str):
    store = _load_chat_store()
    session = _find_session(store, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/chat")
def chat(body: ChatBody):
    if not OPENCLAW_TOKEN:
        raise HTTPException(status_code=500, detail="OPENCLAW_TOKEN is missing")

    store = _load_chat_store()
    session = None
    messages = []

    if body.session_id:
        session = _find_session(store, body.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        for m in session.get("messages", [])[-30:]:
            role = m.get("role")
            content = m.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": body.message})

    payload = {
        "model": OPENCLAW_MODEL,
        "messages": messages,
    }
    res = requests.post(
        f"{OPENCLAW_BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if res.status_code >= 400:
        raise HTTPException(status_code=res.status_code, detail=res.text)
    data = res.json()

    event = _usage_from_response(data)
    _append_usage_event(event)
    reply = data["choices"][0]["message"]["content"]

    if session is not None:
        now = datetime.now(timezone.utc).isoformat()
        session.setdefault("messages", []).append({"role": "user", "content": body.message, "ts": now})
        session.setdefault("messages", []).append({"role": "assistant", "content": reply, "ts": now})
        session["updated_at"] = now
        if session.get("title", "New Chat") in ("", "New Chat"):
            session["title"] = body.message[:48]
        _save_chat_store(store)

    return {
        "reply": reply,
        "raw": data,
        "usage": event,
        "session_id": body.session_id,
    }


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
