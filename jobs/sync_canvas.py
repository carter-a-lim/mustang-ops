import json
import os
import re
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from pypdf import PdfReader
except Exception:  # optional dependency at runtime
    PdfReader = None

KEYWORDS = ["midterm", "final", "quiz", "exam", "assignment", "lab", "project", "homework"]
MONTH_MAP = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_date(iso_ts: str | None) -> str | None:
    if not iso_ts:
        return None
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return None


def text_clean(s: str | None) -> str:
    s = unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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
    req = Request(f"{base}{path}{q}", headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def infer_year(month: int, now: datetime) -> int:
    # school-year friendly heuristic: dates far in past shift to next year
    y = now.year
    candidate = datetime(y, month, 1, tzinfo=timezone.utc)
    if candidate.month < now.month - 3:
        return y + 1
    return y


def event_from_match(course_id: int, course_name: str, title: str, source: str, month: int, day: int, now: datetime):
    year = infer_year(month, now)
    try:
        d = datetime(year, month, day, tzinfo=timezone.utc).date()
    except Exception:
        return None
    return {
        "id": f"{source}-{course_id}-{month:02d}-{day:02d}-{abs(hash(title)) % 10000}",
        "title": title,
        "course": course_name,
        "date": d.isoformat(),
        "source": source,
    }


def extract_keyword_dates(course_id: int, course_name: str, text: str, source: str, now: datetime):
    out = []
    lower = text.lower()

    # Month name dates with nearby keyword context
    for m in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b", text, flags=re.I):
        month = MONTH_MAP[m.group(1).lower()[:3]]
        day = int(m.group(2))
        start = max(0, m.start() - 80)
        end = min(len(lower), m.end() + 80)
        window = lower[start:end]
        if any(k in window for k in KEYWORDS):
            title = text[max(0, m.start()-30):min(len(text), m.end()+60)].strip()
            ev = event_from_match(course_id, course_name, title, source, month, day, now)
            if ev:
                out.append(ev)

    # Slash dates only when keyword appears nearby to reduce false positives
    for m in re.finditer(r"\b(\d{1,2})\/(\d{1,2})\b", text):
        month = int(m.group(1))
        day = int(m.group(2))
        start = max(0, m.start() - 80)
        end = min(len(lower), m.end() + 80)
        window = lower[start:end]
        if any(k in window for k in KEYWORDS):
            title = text[max(0, m.start()-30):min(len(text), m.end()+60)].strip()
            ev = event_from_match(course_id, course_name, title, source, month, day, now)
            if ev:
                out.append(ev)

    return out


def extract_pdf_text(file_url: str, token: str) -> str:
    if PdfReader is None:
        return ""
    try:
        req = Request(file_url, headers={"Authorization": f"Bearer {token}"})
        with urlopen(req, timeout=45) as r:
            data = r.read()
        reader = PdfReader(BytesIO(data))
        pages = []
        for p in reader.pages[:12]:
            pages.append(p.extract_text() or "")
        return text_clean(" ".join(pages))
    except Exception:
        return ""


def main() -> None:
    context_path = Path(os.getenv("MUSTANG_CONTEXT_PATH", "/home/ubuntu/mustang-ops/data/mustang_context.json"))
    fallback = Path(__file__).resolve().parents[1] / "data" / "mustang_context.json"
    if not context_path.exists() and fallback.exists():
        context_path = fallback

    context = json.loads(context_path.read_text()) if context_path.exists() else {}

    canvas_url = os.getenv("CANVAS_URL")
    canvas_token = os.getenv("CANVAS_TOKEN")
    if not (canvas_url and canvas_token):
        cfg_url, cfg_token = load_openclaw_canvas_env()
        canvas_url = canvas_url or cfg_url
        canvas_token = canvas_token or cfg_token

    deadlines, events = [], []

    if canvas_url and canvas_token:
        now = datetime.now(timezone.utc)
        courses = canvas_get(canvas_url, canvas_token, "/api/v1/courses", {"enrollment_state": "active", "per_page": 50})

        for c in courses:
            cid = c.get("id")
            cname = c.get("name", f"Course {cid}")
            if not cid:
                continue

            # Assignments with explicit due dates (best source)
            try:
                assignments = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}/assignments", {"per_page": 100})
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
                    deadlines.append({
                        "id": f"canvas-{cid}-{a.get('id')}",
                        "title": a.get("name", "Untitled Assignment"),
                        "task": a.get("name", "Untitled Assignment"),
                        "course": cname,
                        "due_at": due_dt.isoformat(),
                        "date": due_dt.date().isoformat(),
                        "source": "canvas",
                        "confidence": 1.0,
                    })
            except Exception:
                pass

            # Syllabus page/body
            try:
                detail = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}", {"include[]": "syllabus_body"})
                body = text_clean(detail.get("syllabus_body"))
                if body:
                    events.extend(extract_keyword_dates(cid, cname, body, "canvas-syllabus", now))
            except Exception:
                pass

            # Pages content
            try:
                pages = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}/pages", {"per_page": 50})
                for p in pages:
                    page_url = p.get("url")
                    if not page_url:
                        continue
                    page = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}/pages/{page_url}")
                    text = text_clean((page.get("title") or "") + " " + (page.get("body") or ""))
                    events.extend(extract_keyword_dates(cid, cname, text, "canvas-page", now))
            except Exception:
                pass

            # Modules + items (titles often contain quizzes/exams)
            try:
                modules = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}/modules", {"include[]": "items", "per_page": 100})
                for m in modules:
                    mtext = text_clean(m.get("name"))
                    events.extend(extract_keyword_dates(cid, cname, mtext, "canvas-module", now))
                    for it in m.get("items") or []:
                        itext = text_clean((it.get("title") or "") + " " + (it.get("type") or ""))
                        events.extend(extract_keyword_dates(cid, cname, itext, "canvas-module-item", now))
            except Exception:
                pass

            # Files by name + optional PDF text mining (syllabi / schedules / exam docs)
            try:
                files = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}/files", {"per_page": 100})
                for f in files:
                    name = (f.get("display_name") or f.get("filename") or "")
                    ftext = text_clean(name)
                    events.extend(extract_keyword_dates(cid, cname, ftext, "canvas-file", now))

                    lower_name = name.lower()
                    should_parse_pdf = (
                        lower_name.endswith(".pdf")
                        and any(k in lower_name for k in ["syllabus", "schedule", "calendar", "midterm", "final", "exam", "quiz", "assignment", "lab", "project"])
                    )
                    file_url = f.get("url")
                    if should_parse_pdf and file_url:
                        pdf_text = extract_pdf_text(file_url, canvas_token)
                        if pdf_text:
                            events.extend(extract_keyword_dates(cid, cname, pdf_text, "canvas-pdf", now))
            except Exception:
                pass

            # Announcements / discussion topics sometimes include exam dates
            try:
                anns = canvas_get(canvas_url, canvas_token, "/api/v1/announcements", {"context_codes[]": f"course_{cid}", "per_page": 50})
                for a in anns:
                    text = text_clean((a.get("title") or "") + " " + (a.get("message") or ""))
                    events.extend(extract_keyword_dates(cid, cname, text, "canvas-announcement", now))
            except Exception:
                pass

            try:
                topics = canvas_get(canvas_url, canvas_token, f"/api/v1/courses/{cid}/discussion_topics", {"per_page": 50})
                for t in topics:
                    text = text_clean((t.get("title") or "") + " " + (t.get("message") or ""))
                    events.extend(extract_keyword_dates(cid, cname, text, "canvas-discussion", now))
            except Exception:
                pass

            # User-confirmed CSC-202 overrides from screenshot
            if "CSC-202" in cname:
                y = now.year
                for item_id, task, due_dt in [
                    ("csc202-lab-4", "Lab 4", datetime(y, 2, 20, 23, 59, tzinfo=timezone.utc)),
                    ("csc202-quiz-6", "Quiz 6", datetime(y, 2, 25, 23, 59, tzinfo=timezone.utc)),
                    ("csc202-assignment-4", "Assignment 4", datetime(y, 2, 27, 23, 59, tzinfo=timezone.utc)),
                    ("csc202-assignment-5", "Assignment 5", datetime(y, 3, 13, 23, 59, tzinfo=timezone.utc)),
                ]:
                    deadlines.append({
                        "id": item_id,
                        "title": task,
                        "task": task,
                        "course": cname,
                        "due_at": due_dt.isoformat(),
                        "date": due_dt.date().isoformat(),
                        "source": "canvas-syllabus-user-confirmed",
                        "confidence": 0.95,
                    })

        # Upcoming calendar events feed
        try:
            upcoming = canvas_get(canvas_url, canvas_token, "/api/v1/users/self/upcoming_events", {"per_page": 50})
            for ev in upcoming:
                dt = ev.get("start_at") or ev.get("all_day_date")
                d = to_date(dt)
                if not d:
                    continue
                events.append({
                    "id": f"canvas-event-{ev.get('id')}",
                    "title": ev.get("title", "Canvas Event"),
                    "course": ev.get("context_name", "General"),
                    "date": d,
                    "start_at": ev.get("start_at"),
                    "source": "canvas",
                })
        except Exception:
            pass

    # de-dupe + sort deadlines
    duniq = {d.get("id", f"d-{i}"): d for i, d in enumerate(deadlines)}
    deadlines = sorted(duniq.values(), key=lambda x: x.get("due_at", ""))

    # keep upcoming-ish events only and de-dupe
    today = datetime.now(timezone.utc).date()
    euniq = {}
    for i, e in enumerate(events):
        d = e.get("date")
        if not d:
            continue
        try:
            if datetime.fromisoformat(d).date() < today:
                continue
        except Exception:
            continue
        euniq[e.get("id", f"e-{i}")] = e
    events = sorted(euniq.values(), key=lambda x: x.get("date", ""))

    context["deadlines"] = deadlines
    context["events"] = events
    context["updated_at"] = iso_now()
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(context, indent=2) + "\n")

    print(f"sync_canvas done: {len(deadlines)} deadlines, {len(events)} events")


if __name__ == "__main__":
    main()
