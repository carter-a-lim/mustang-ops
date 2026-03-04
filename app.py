import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
USAGE_EVENTS_PATH = DATA_DIR / "usage_events.jsonl"
CHAT_SESSIONS_PATH = DATA_DIR / "chat_sessions.json"
JOB_PIPELINE_PATH = DATA_DIR / "job_pipeline.json"
ANSWER_MEMORY_PATH = DATA_DIR / "application_answer_memory.json"
ASSISTED_QUEUE_PATH = DATA_DIR / "assisted_apply_queue.json"
RESUME_TXT_PATH = DATA_DIR / "resume" / "latest_resume.txt"
RESUME_PROFILE_PATH = DATA_DIR / "resume_profile.json"

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
    "scrape_simplify_jobs": ROOT / "jobs" / "scrape_simplify_jobs.py",
    "auto_apply_orchestrator": ROOT / "jobs" / "auto_apply_orchestrator.py",
    "sync_gmail": ROOT / "jobs" / "sync_gmail.py",
}

app = FastAPI(title="Mustang Ops")
app.mount("/web", StaticFiles(directory=str(ROOT / "web")), name="web")
app.mount("/icons", StaticFiles(directory=str(ROOT / "web" / "icons")), name="icons")
if (ROOT / "node_modules").exists():
    app.mount("/node_modules", StaticFiles(directory=str(ROOT / "node_modules")), name="node_modules")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(ROOT / "web" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(ROOT / "web" / "sw.js", media_type="application/javascript")


class ChatBody(BaseModel):
    message: str
    session_id: str | None = None
    task_title: str | None = None


class CreateSessionBody(BaseModel):
    title: str | None = None


class RenameSessionBody(BaseModel):
    title: str


class AnswerMemoryEntry(BaseModel):
    question_type: str = Field(description="Short label, e.g. behavioral, motivation, strengths")
    prompt: str = Field(description="Original question prompt")
    answer: str = Field(description="Your preferred answer in your natural voice")
    tags: list[str] = Field(default_factory=list)


class AssistedQueueBuildBody(BaseModel):
    limit: int = 25
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    use_resume_fit: bool = True


class ResumeSyncBody(BaseModel):
    doc_id: str | None = None


class AutoApplyRunBody(BaseModel):
    stage: str = Field(default="all", pattern="^(prepare|enrich|draft|queue|submit|all)$")
    max: int = 10
    dry_run: bool = False


class ScrapeQuestionsBody(BaseModel):
    url: str | None = None
    html: str | None = None
    company: str
    title: str


class GenerateAnswersBody(BaseModel):
    company: str
    title: str
    questions: list[str]


class UpdateQueueItemBody(BaseModel):
    status: str


class AutofillExecuteBody(BaseModel):
    mode: str = Field(default="dry-run", pattern="^(dry-run|live)$")


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


def _read_json_file(path: Path, default: dict | list):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


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


def _load_answer_memory() -> dict:
    return _read_json_file(
        ANSWER_MEMORY_PATH,
        {
            "updated_at": None,
            "entries": [],
            "notes": "Store your best answers so assisted apply can match your voice.",
        },
    )


def _save_answer_memory(payload: dict) -> None:
    ANSWER_MEMORY_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def _keyword_match(text: str, include: list[str], exclude: list[str]) -> bool:
    low = text.lower()
    if include and not any(k.lower() in low for k in include):
        return False
    if exclude and any(k.lower() in low for k in exclude):
        return False
    return True


def _extract_resume_profile(text: str) -> dict:
    lower = text.lower()

    skill_terms = [
        "python",
        "javascript",
        "typescript",
        "react",
        "node.js",
        "node",
        "firebase",
        "supabase",
        "vercel",
        "git",
        "google cloud",
    ]
    skills = sorted({s for s in skill_terms if s in lower})

    grad_year = None
    m = re.search(r"class of\s*(20\d{2})", lower)
    if m:
        grad_year = int(m.group(1))

    work_auth = "unknown"
    if "u.s. citizen" in lower or "us citizen" in lower:
        work_auth = "us-citizen"

    return {
        "skills": skills,
        "grad_year": grad_year,
        "work_auth": work_auth,
    }


def _load_resume_profile() -> dict:
    if RESUME_PROFILE_PATH.exists():
        return _read_json_file(RESUME_PROFILE_PATH, {})

    if not RESUME_TXT_PATH.exists():
        return {"updated_at": None, "profile": {"skills": [], "grad_year": None, "work_auth": "unknown"}}

    text = RESUME_TXT_PATH.read_text(encoding="utf-8", errors="ignore")
    profile = _extract_resume_profile(text)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(RESUME_TXT_PATH),
        "profile": profile,
    }
    RESUME_PROFILE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def _fit_score_role(role: dict, profile: dict) -> tuple[int, list[str], str]:
    title = (role.get("title") or "").lower()
    location = (role.get("location") or "").lower()
    score = 35
    reasons: list[str] = []

    swe_terms = ["software", "backend", "frontend", "full stack", "developer", "engineer", "swe"]
    if any(t in title for t in swe_terms):
        score += 25
        reasons.append("Role aligns with software engineering path")

    role_skill_hints = {
        "python": ["python", "ml", "data"],
        "javascript": ["javascript", "js", "frontend", "web"],
        "typescript": ["typescript", "ts"],
        "react": ["react", "frontend"],
        "node": ["node", "backend", "api"],
    }

    matched_skills = 0
    profile_skills = [s.lower() for s in profile.get("skills", [])]
    for skill in profile_skills:
        hints = role_skill_hints.get(skill, [skill])
        if any(h in title for h in hints):
            matched_skills += 1
    if matched_skills:
        bump = min(25, matched_skills * 7)
        score += bump
        reasons.append(f"Skill overlap inferred from title ({matched_skills} signal{'s' if matched_skills != 1 else ''})")

    if "remote" in location:
        score += 5
        reasons.append("Remote-friendly location")

    if "citizenship" in title or "clearance" in title:
        if profile.get("work_auth") != "us-citizen":
            score -= 20
            reasons.append("Possible citizenship/clearance constraint")

    score = max(0, min(100, score))
    tier = "low-fit"
    if score >= 72:
        tier = "strong-fit"
    elif score >= 55:
        tier = "reach"

    return score, reasons, tier


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


def _call_openclaw(messages: list[dict[str, str]]) -> str:
    if not OPENCLAW_TOKEN:
        raise HTTPException(status_code=500, detail="OPENCLAW_TOKEN is missing")

    payload = {
        "model": OPENCLAW_MODEL,
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
        raise HTTPException(status_code=502, detail=f"OpenClaw upstream request failed: {exc}")

    if res.status_code >= 400:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    try:
        data = res.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="OpenClaw upstream returned invalid JSON")

    event = _usage_from_response(data)
    _append_usage_event(event)
    return data["choices"][0]["message"]["content"]


def _generate_draft_answers(company: str, role: str, questions: list[str]) -> dict[str, str]:
    profile_data = _load_resume_profile()
    profile = profile_data.get("profile", {})
    memory_data = _load_answer_memory()
    entries = memory_data.get("entries", [])

    context_lines = []
    if profile:
        skills = profile.get("skills", [])
        context_lines.append(f"Resume skills: {', '.join(skills)}")
        context_lines.append(f"Grad year: {profile.get('grad_year', 'Unknown')}")
        context_lines.append(f"Work auth: {profile.get('work_auth', 'Unknown')}")

    memory_context = ""
    if entries:
        memory_context = "Past answers for tone/context:\n"
        for e in entries[:5]:
            memory_context += f"- Q: {e.get('prompt')}\n  A: {e.get('answer')}\n"

    answers: dict[str, str] = {}
    for q in questions:
        prompt = (
            "Draft a concise, natural-sounding answer for this job application question.\n"
            f"Company: {company}\n"
            f"Role: {role}\n"
            f"Question: {q}\n"
        )
        if context_lines:
            prompt += "\nProfile details:\n" + "\n".join(context_lines)
        if memory_context:
            prompt += "\n" + memory_context
        prompt += "\nWrite only the final answer text."

        answers[q] = _call_openclaw([{"role": "user", "content": prompt}]).strip()

    return answers


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
                    "docs": f"https://github.com/openclaw/openclaw/tree/main/skills/{name}" if meta["source"] == "core" else "https://docs.openclaw.ai",
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
    return _read_json_file(p, {"updated_at": None, "repos": []})


@app.get("/api/network/metrics")
def get_network_metrics():
    jobs = get_network_jobs()
    queue = get_assisted_apply_queue()

    simplify_snapshot = _read_json_file(DATA_DIR / "simplify_software_internships.json", {"roles": []})
    ingest_total = len(simplify_snapshot.get("roles", [])) + len(jobs.get("roles", []))

    queue_items = queue.get("queue", [])
    queued_qualified = len([q for q in queue_items if q.get("status") in {"needs-review", "approved", "needs-approval", "drafted", "approval-queued"}])

    applications = jobs.get("applications", [])
    total_qualified = queued_qualified + len(applications)

    def _stage(app: dict[str, Any]) -> str:
        return str(app.get("stage") or app.get("status") or "").lower()

    total_submitted = len([a for a in applications if any(x in _stage(a) for x in ["applied", "submitted", "oa", "interview", "reject", "closed", "offer", "accept"])])
    waiting_response = len([a for a in applications if any(x in _stage(a) for x in ["applied", "submitted", "await", "waiting"])])

    interview = len([a for a in applications if "interview" in _stage(a)])
    oa = len([a for a in applications if "oa" in _stage(a) or "assessment" in _stage(a)])
    rejected = len([a for a in applications if any(x in _stage(a) for x in ["reject", "closed"])])
    accepted = len([a for a in applications if any(x in _stage(a) for x in ["offer", "accept"])])
    other = max(0, total_submitted - (interview + oa + rejected + accepted + waiting_response))

    return {
        "pipeline": {
            "ingest_total": ingest_total,
            "qualified": {
                "total": total_qualified,
                "currently_queued": queued_qualified,
            },
            "applications": {
                "total_submitted": total_submitted,
                "waiting_response": waiting_response,
            },
            "outcomes": {
                "interview": interview,
                "oa": oa,
                "rejected": rejected,
                "accepted": accepted,
                "other": other,
            },
        },
        "conversions": {
            "ingest_to_qualified_pct": round((total_qualified / max(ingest_total, 1)) * 100, 1),
            "qualified_to_submitted_pct": round((total_submitted / max(total_qualified, 1)) * 100, 1),
            "submitted_to_interview_pct": round((interview / max(total_submitted, 1)) * 100, 1),
        },
    }


@app.get("/api/network/jobs")
def get_network_jobs():
    base = _read_json_file(
        JOB_PIPELINE_PATH,
        {
            "updated_at": None,
            "roles": [],
            "applications": [],
            "outreach_targets": [],
        },
    )

    simplify_path = DATA_DIR / "simplify_software_internships.json"
    simplify = _read_json_file(
        simplify_path,
        {
            "fetched_at": None,
            "roles": [],
            "count": 0,
        },
    )

    simplify_roles = [
        {
            "company": r.get("company", ""),
            "title": r.get("role", ""),
            "location": r.get("location", ""),
            "status": "new",
            "age": r.get("age", ""),
            "apply_url": r.get("apply_url", ""),
            "source": "simplify",
        }
        for r in simplify.get("roles", [])
        if r.get("company") and r.get("role")
    ]

    existing_roles = base.get("roles", [])
    all_roles = simplify_roles + existing_roles

    return {
        **base,
        "updated_at": simplify.get("fetched_at") or base.get("updated_at"),
        "roles": all_roles,
        "sources": {
            "simplify": {
                "count": len(simplify_roles),
                "fetched_at": simplify.get("fetched_at"),
            },
            "manual": {
                "count": len(existing_roles),
                "updated_at": base.get("updated_at"),
            },
        },
    }


@app.get("/api/agents/inbox")
def agents_inbox():
    return _agent_inbox()


@app.get("/api/network/resume-profile")
def get_resume_profile():
    return _load_resume_profile()


@app.post("/api/network/resume/sync")
def sync_resume_from_docs(body: ResumeSyncBody):
    # If doc_id not provided, discover latest doc with "resume" in name.
    doc_id = body.doc_id
    account = os.getenv("GOG_ACCOUNT", "carter.limster@gmail.com")

    if not doc_id:
        search = subprocess.run(
            [
                "gog",
                "drive",
                "search",
                "name contains 'resume' or name contains 'Resume' or name contains 'CV'",
                "--max",
                "5",
                "--json",
                "--no-input",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "GOG_ACCOUNT": account},
            check=False,
        )
        if search.returncode != 0:
            raise HTTPException(status_code=500, detail=f"gog drive search failed: {search.stderr.strip()}")
        try:
            files = (json.loads(search.stdout) or {}).get("files", [])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to parse gog output: {exc}")
        docs = [f for f in files if f.get("mimeType") == "application/vnd.google-apps.document"]
        if not docs:
            raise HTTPException(status_code=404, detail="No resume Google Doc found")
        docs.sort(key=lambda x: x.get("modifiedTime", ""), reverse=True)
        doc_id = docs[0].get("id")

    RESUME_TXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    export = subprocess.run(
        [
            "gog",
            "docs",
            "export",
            doc_id,
            "--format",
            "txt",
            "--out",
            str(RESUME_TXT_PATH),
            "--no-input",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "GOG_ACCOUNT": account},
        check=False,
    )
    if export.returncode != 0:
        raise HTTPException(status_code=500, detail=f"gog docs export failed: {export.stderr.strip()}")

    text = RESUME_TXT_PATH.read_text(encoding="utf-8", errors="ignore")
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": f"gdoc:{doc_id}",
        "profile": _extract_resume_profile(text),
    }
    RESUME_PROFILE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


@app.get("/api/network/answer-memory")
def get_answer_memory():
    return _load_answer_memory()


@app.post("/api/network/answer-memory")
def add_answer_memory(entry: AnswerMemoryEntry):
    data = _load_answer_memory()
    entries = data.get("entries", [])
    entries.insert(
        0,
        {
            "question_type": entry.question_type,
            "prompt": entry.prompt,
            "answer": entry.answer,
            "tags": entry.tags,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    data["entries"] = entries[:300]
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_answer_memory(data)
    return {"ok": True, "count": len(data["entries"])}


@app.post("/api/network/apply/prepare")
def prepare_assisted_apply_queue(body: AssistedQueueBuildBody):
    jobs = get_network_jobs()
    roles = jobs.get("roles", [])
    include = body.include_keywords or []
    exclude = body.exclude_keywords or []
    resume_payload = _load_resume_profile() if body.use_resume_fit else {"profile": {"skills": []}}
    profile = resume_payload.get("profile", {})

    candidates = []
    for role in roles:
        title = role.get("title", "")
        company = role.get("company", "")
        location = role.get("location", "")
        text = f"{company} {title} {location}"
        if not _keyword_match(text, include, exclude):
            continue

        fit_score, fit_reasons, fit_tier = _fit_score_role(role, profile) if body.use_resume_fit else (60, ["Keyword match"], "reach")
        if fit_tier == "low-fit":
            continue

        candidates.append(
            {
                "id": str(uuid.uuid4()),
                "company": company,
                "title": title,
                "location": location,
                "apply_url": role.get("apply_url", ""),
                "source": role.get("source", "network"),
                "status": "needs-review",
                "fit_score": fit_score,
                "fit_tier": fit_tier,
                "fit_reasons": fit_reasons,
                "questions_needed": [
                    "Why this company?",
                    "Tell us about yourself",
                    "Relevant project highlight",
                ],
            }
        )

    candidates.sort(key=lambda x: x.get("fit_score", 0), reverse=True)
    queue = candidates[: max(1, min(body.limit, 200))]

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(queue),
        "filters": {
            "include_keywords": include,
            "exclude_keywords": exclude,
            "limit": body.limit,
            "use_resume_fit": body.use_resume_fit,
        },
        "resume_profile": profile,
        "queue": queue,
    }
    ASSISTED_QUEUE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


@app.get("/api/network/apply/queue")
def get_assisted_apply_queue():
    return _read_json_file(
        ASSISTED_QUEUE_PATH,
        {
            "updated_at": None,
            "count": 0,
            "filters": {},
            "queue": [],
        },
    )


@app.patch("/api/network/apply/queue/{job_id}")
def update_assisted_apply_queue_item(job_id: str, body: UpdateQueueItemBody):
    data = get_assisted_apply_queue()
    queue = data.get("queue", [])

    found = False
    for item in queue:
        if item.get("id") == job_id:
            item["status"] = body.status
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Queue item not found")

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    ASSISTED_QUEUE_PATH.write_text(json.dumps(data, indent=2) + "\n")
    return {"ok": True, "job_id": job_id, "status": body.status}


@app.post("/api/network/apply/queue/{job_id}/execute")
def execute_autofill(job_id: str, body: AutofillExecuteBody, background_tasks: BackgroundTasks):
    data = get_assisted_apply_queue()
    queue = data.get("queue", [])

    job_item = next((item for item in queue if item.get("id") == job_id), None)
    if not job_item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    script_path = ROOT / "jobs" / "autofill_worker.py"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="autofill worker not found")

    def _spawn_worker() -> None:
        subprocess.Popen(["python3", str(script_path), job_id, body.mode], cwd=str(ROOT))

    background_tasks.add_task(_spawn_worker)
    return {"ok": True, "job_id": job_id, "mode": body.mode, "status": "started"}


@app.post("/api/network/apply/scrape")
def scrape_application_questions(body: ScrapeQuestionsBody):
    from scrapers import extract_questions_from_html, fetch_html

    html_content = body.html or ""
    if not html_content and body.url:
        html_content = fetch_html(body.url)

    if not html_content:
        raise HTTPException(status_code=400, detail="Must provide url or html to scrape")

    questions = extract_questions_from_html(html_content, body.url or "")

    try:
        data = _read_json_file(JOB_PIPELINE_PATH, {})
        applications = data.get("applications", [])

        app_record = None
        for a in applications:
            if a.get("company", "").lower() == body.company.lower() and a.get("title", "").lower() == body.title.lower():
                app_record = a
                break

        if not app_record:
            app_record = {
                "company": body.company,
                "title": body.title,
                "stage": "Draft",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            applications.append(app_record)

        app_record["questions"] = questions
        data["applications"] = applications
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        JOB_PIPELINE_PATH.write_text(json.dumps(data, indent=2) + "\n")
    except Exception:
        pass

    return {"questions": questions}


@app.post("/api/network/apply/generate")
def generate_application_answers(body: GenerateAnswersBody):
    if not body.questions:
        return {"answers": {}}

    answers = _generate_draft_answers(body.company, body.title, body.questions)

    try:
        data = _read_json_file(JOB_PIPELINE_PATH, {})
        applications = data.get("applications", [])
        for a in applications:
            if a.get("company", "").lower() == body.company.lower() and a.get("title", "").lower() == body.title.lower():
                a["draft_answers"] = answers
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                JOB_PIPELINE_PATH.write_text(json.dumps(data, indent=2) + "\n")
                break
    except Exception:
        pass

    return {"answers": answers}


@app.get("/api/network")
def get_network():
    p = ROOT / "data" / "network_context.json"
    return _read_json_file(
        p,
        {
            "updated_at": None,
            "contacts": [],
            "interactions": [],
            "opportunities": [],
            "introductions": [],
            "summary": {"pending_followups": 0, "warm_leads": 0, "intros_available": 0, "reply_rate": 0},
        },
    )


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

    # Rolling-window reset hints ("when oldest included usage expires")
    reset_5h_at = None
    reset_7d_at = None
    if last_5h_events:
        oldest_5h = min(dt for dt, e in events_with_dt if dt >= last_5h_cutoff)
        reset_5h_at = (oldest_5h + timedelta(hours=5)).isoformat()
    if last_7d_events:
        oldest_7d = min(dt for dt, e in events_with_dt if dt >= last_7d_cutoff)
        reset_7d_at = (oldest_7d + timedelta(days=7)).isoformat()

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
                "tokens_remaining": max(0, limit_5h - last_5h["total_tokens"]),
                "reset_at": reset_5h_at,
                "active_window": bool(last_5h_events),
            },
            "last_7d": {
                **last_7d,
                "percent_used": round((last_7d["total_tokens"] / limit_7d) * 100, 2),
                "percent_remaining": round(max(0.0, 100 - (last_7d["total_tokens"] / limit_7d) * 100), 2),
                "tokens_remaining": max(0, limit_7d - last_7d["total_tokens"]),
                "reset_at": reset_7d_at,
                "active_window": bool(last_7d_events),
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


@app.patch("/api/chat/sessions/{session_id}")
def rename_chat_session(session_id: str, body: RenameSessionBody):
    store = _load_chat_store()
    session = _find_session(store, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    session["title"] = title[:80]
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_chat_store(store)
    return {"ok": True, "id": session_id, "title": session["title"]}


@app.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str):
    store = _load_chat_store()
    sessions = store.get("sessions", [])
    new_sessions = [s for s in sessions if s.get("id") != session_id]
    if len(new_sessions) == len(sessions):
        raise HTTPException(status_code=404, detail="Session not found")
    store["sessions"] = new_sessions
    _save_chat_store(store)
    return {"ok": True, "deleted": session_id}


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
    try:
        res = requests.post(
            f"{OPENCLAW_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENCLAW_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenClaw upstream request failed: {exc}")

    if res.status_code >= 400:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    try:
        data = res.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="OpenClaw upstream returned invalid JSON")

    event = _usage_from_response(data)
    _append_usage_event(event)
    reply = data["choices"][0]["message"]["content"]

    if session is not None:
        now = datetime.now(timezone.utc).isoformat()
        session.setdefault("messages", []).append({"role": "user", "content": body.message, "ts": now})
        session.setdefault("messages", []).append({"role": "assistant", "content": reply, "ts": now})
        session["updated_at"] = now
        if body.task_title:
            session["title"] = body.task_title[:80]
        elif session.get("title", "New Chat") in ("", "New Chat"):
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


@app.post("/api/auto-apply/run")
def run_auto_apply(body: AutoApplyRunBody):
    script = JOBS.get("auto_apply_orchestrator")
    if not script or not script.exists():
        raise HTTPException(status_code=404, detail="Auto apply orchestrator not found")

    cmd = [
        "python3",
        str(script),
        "--stage",
        body.stage,
        "--max",
        str(max(1, min(body.max, 500))),
    ]
    if body.dry_run:
        cmd.append("--dry-run")

    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))

    parsed: dict[str, Any] | None = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except Exception:
            parsed = None

    return {
        "job": "auto_apply_orchestrator",
        "started_at": started,
        "cmd": cmd,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "result": parsed,
    }
