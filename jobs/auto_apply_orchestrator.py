#!/usr/bin/env python3
"""Auto-apply orchestration loop for Mustang Ops.

This is intentionally semi-automated:
- It prepares + enriches + drafts applications automatically.
- It requires explicit approval before submit.

Usage examples:
  python3 jobs/auto_apply_orchestrator.py --stage prepare
  python3 jobs/auto_apply_orchestrator.py --stage enrich
  python3 jobs/auto_apply_orchestrator.py --stage draft
  python3 jobs/auto_apply_orchestrator.py --stage queue
  python3 jobs/auto_apply_orchestrator.py --stage submit --max 3
  python3 jobs/auto_apply_orchestrator.py --stage all --dry-run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSISTED_QUEUE_PATH = DATA / "assisted_apply_queue.json"
AUTO_STATE_PATH = DATA / "auto_apply_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


@dataclass
class PipelineStats:
    prepared: int = 0
    enriched: int = 0
    drafted: int = 0
    queued_for_approval: int = 0
    submitted: int = 0


def load_state() -> dict[str, Any]:
    return load_json(
        AUTO_STATE_PATH,
        {
            "updated_at": None,
            "applications": [],
            "history": [],
        },
    )


def upsert_app(state: dict[str, Any], app_key: str, patch: dict[str, Any]) -> dict[str, Any]:
    apps = state.setdefault("applications", [])
    for item in apps:
        if item.get("key") == app_key:
            item.update(patch)
            item["updated_at"] = utc_now()
            return item

    created = {
        "key": app_key,
        "status": "new",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    created.update(patch)
    apps.append(created)
    return created


def log_event(state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
    history = state.setdefault("history", [])
    history.insert(
        0,
        {
            "ts": utc_now(),
            "type": event_type,
            "payload": payload,
        },
    )
    state["history"] = history[:1000]


def stage_prepare(state: dict[str, Any], stats: PipelineStats) -> None:
    queue = load_json(ASSISTED_QUEUE_PATH, {"queue": []}).get("queue", [])
    for role in queue:
        company = role.get("company", "")
        title = role.get("title", "")
        apply_url = role.get("apply_url", "")
        if not company or not title:
            continue

        key = f"{company}::{title}::{apply_url}".strip()
        existing = upsert_app(
            state,
            key,
            {
                "company": company,
                "title": title,
                "location": role.get("location"),
                "apply_url": apply_url,
                "source": role.get("source", "network"),
                "fit_score": role.get("fit_score", 0),
                "fit_tier": role.get("fit_tier", "unknown"),
                "status": "prepared",
            },
        )
        log_event(state, "prepared", {"key": key, "fit": existing.get("fit_score", 0)})
        stats.prepared += 1


def stage_enrich(state: dict[str, Any], stats: PipelineStats) -> None:
    for app in state.get("applications", []):
        if app.get("status") not in {"prepared", "enriched", "drafted", "approval-queued"}:
            continue

        if "enrichment" not in app:
            app["enrichment"] = {
                "company_signal": "unknown",
                "role_signal": "intern-friendly",
                "notes": [
                    "Add company-specific recent initiative.",
                    "Add one project bullet that maps to role stack.",
                ],
            }
            app["status"] = "enriched"
            app["updated_at"] = utc_now()
            log_event(state, "enriched", {"key": app.get("key")})
            stats.enriched += 1


def stage_draft(state: dict[str, Any], stats: PipelineStats) -> None:
    for app in state.get("applications", []):
        if app.get("status") not in {"enriched", "drafted", "approval-queued"}:
            continue
        if app.get("draft"):
            continue

        company = app.get("company", "this company")
        title = app.get("title", "this role")
        app["draft"] = {
            "resume_variant": "software_intern_v1",
            "cover_note": f"Hi {company} team — I’m excited to apply for {title}. "
            "I enjoy shipping fast, learning quickly, and owning real product outcomes.",
            "qa_checklist": [
                "Resume uploaded",
                "Phone/email fields validated",
                "Work authorization answered",
                "No placeholder text left",
            ],
        }
        app["status"] = "drafted"
        app["updated_at"] = utc_now()
        log_event(state, "drafted", {"key": app.get("key")})
        stats.drafted += 1


def stage_queue_for_approval(state: dict[str, Any], stats: PipelineStats) -> None:
    for app in state.get("applications", []):
        if app.get("status") != "drafted":
            continue
        app["status"] = "approval-queued"
        app["approval"] = {
            "decision": "pending",
            "requested_at": utc_now(),
            "review_channel": "discord:#chat-command-center",
        }
        app["updated_at"] = utc_now()
        log_event(state, "approval_queued", {"key": app.get("key")})
        stats.queued_for_approval += 1


def stage_submit(state: dict[str, Any], stats: PipelineStats, max_submit: int, dry_run: bool) -> None:
    submitted = 0
    for app in state.get("applications", []):
        if submitted >= max_submit:
            break
        approval = app.get("approval", {})
        if app.get("status") != "approval-queued" or approval.get("decision") != "approved":
            continue

        if dry_run:
            log_event(state, "submit_dry_run", {"key": app.get("key")})
            continue

        app["status"] = "submitted"
        app["submitted_at"] = utc_now()
        app["confirmation"] = {
            "ref": f"sim-{int(datetime.now().timestamp())}",
            "method": "simulated",
        }
        app["updated_at"] = utc_now()
        log_event(state, "submitted", {"key": app.get("key")})
        submitted += 1
        stats.submitted += 1


def run(stage: str, max_submit: int, dry_run: bool) -> dict[str, Any]:
    state = load_state()
    stats = PipelineStats()

    if stage in {"prepare", "all"}:
        stage_prepare(state, stats)
    if stage in {"enrich", "all"}:
        stage_enrich(state, stats)
    if stage in {"draft", "all"}:
        stage_draft(state, stats)
    if stage in {"queue", "all"}:
        stage_queue_for_approval(state, stats)
    if stage in {"submit", "all"}:
        stage_submit(state, stats, max_submit=max_submit, dry_run=dry_run)

    state["updated_at"] = utc_now()
    save_json(AUTO_STATE_PATH, state)

    summary = {
        "ok": True,
        "stage": stage,
        "dry_run": dry_run,
        "stats": {
            "prepared": stats.prepared,
            "enriched": stats.enriched,
            "drafted": stats.drafted,
            "queued_for_approval": stats.queued_for_approval,
            "submitted": stats.submitted,
        },
        "state_file": str(AUTO_STATE_PATH),
        "updated_at": state["updated_at"],
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mustang auto-apply orchestration stages")
    parser.add_argument(
        "--stage",
        choices=["prepare", "enrich", "draft", "queue", "submit", "all"],
        default="all",
    )
    parser.add_argument("--max", type=int, default=10, help="Max approved applications to submit")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform final submit writes")
    args = parser.parse_args()

    summary = run(stage=args.stage, max_submit=max(1, args.max), dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
