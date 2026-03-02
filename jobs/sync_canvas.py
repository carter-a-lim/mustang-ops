import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_date(iso_ts: str | None) -> str | None:
    if not iso_ts:
        return None
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return None


def load_openclaw_canvas_env() -> tuple[str | None, str | None]:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        return None, None
    try:
        cfg = json.loads(cfg_path.read_text())
        env = cfg.get("skills", {}).get("entries", {}).get("canvas-lms", {}).get("env", {})
        return env.get("CANVAS_URL"), env.get("CANVAS_TOKEN")
    except Exception:
        return None, None


def canvas_get(base_url: str, token: str, path: str, params: dict | None = None):
    base = base_url.rstrip("/")
    q = f"?{urlencode(params)}" if params else ""
    url = f"{base}{path}{q}"
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    context_path = Path(os.getenv("MUSTANG_CONTEXT_PATH", "/home/ubuntu/mustang-ops/data/mustang_context.json"))
    fallback = Path(__file__).resolve().parents[1] / "data" / "mustang_context.json"
    if not context_path.exists() and fallback.exists():
        context_path = fallback

    context = json.loads(context_path.read_text()) if context_path.exists() else {}

    # resolve Canvas creds from env first, fallback to openclaw config skill env
    canvas_url = os.getenv("CANVAS_URL")
    canvas_token = os.getenv("CANVAS_TOKEN")
    if not (canvas_url and canvas_token):
        cfg_url, cfg_token = load_openclaw_canvas_env()
        canvas_url = canvas_url or cfg_url
        canvas_token = canvas_token or cfg_token

    deadlines = []
    events = []

    if canvas_url and canvas_token:
        now = datetime.now(timezone.utc)

        courses = canvas_get(
            canvas_url,
            canvas_token,
            "/api/v1/courses",
            {"enrollment_state": "active", "per_page": 50},
        )

        for c in courses:
            course_id = c.get("id")
            course_name = c.get("name", f"Course {course_id}")
            if not course_id:
                continue

            assignments = canvas_get(
                canvas_url,
                canvas_token,
                f"/api/v1/courses/{course_id}/assignments",
                {"per_page": 100},
            )

            for a in assignments:
                due_at = a.get("due_at")
                if not due_at:
                    continue
                try:
                    due_dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                except Exception:
                    continue
                if due_dt < now:
                    continue

                deadlines.append(
                    {
                        "id": f"canvas-{course_id}-{a.get('id')}",
                        "title": a.get("name", "Untitled Assignment"),
                        "task": a.get("name", "Untitled Assignment"),
                        "course": course_name,
                        "due_at": due_dt.isoformat(),
                        "date": due_dt.date().isoformat(),
                        "source": "canvas",
                        "confidence": 1.0,
                    }
                )

        # optional events feed
        try:
            upcoming = canvas_get(canvas_url, canvas_token, "/api/v1/users/self/upcoming_events", {"per_page": 50})
            for ev in upcoming:
                dt = ev.get("start_at") or ev.get("all_day_date")
                d = to_date(dt)
                if not d:
                    continue
                events.append(
                    {
                        "id": f"canvas-event-{ev.get('id')}",
                        "title": ev.get("title", "Canvas Event"),
                        "date": d,
                        "start_at": ev.get("start_at"),
                        "source": "canvas",
                    }
                )
        except Exception:
            pass

    deadlines.sort(key=lambda x: x.get("due_at", ""))

    context["deadlines"] = deadlines
    context["events"] = events
    context["updated_at"] = iso_now()
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(context, indent=2) + "\n")
    print(f"sync_canvas done: {len(deadlines)} deadlines, {len(events)} events")


if __name__ == "__main__":
    main()
