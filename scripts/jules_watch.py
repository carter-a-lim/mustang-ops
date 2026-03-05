#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / ".jules_watch_state.json"


def run(cmd, cwd=REPO_ROOT, check=True):
    p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), text=True, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}")
    return p


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"processed": {}, "updated_at": None}


def save_state(state):
    state["updated_at"] = int(time.time())
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def parse_ts(ts: str | None):
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def list_sessions(api_key):
    p = run(
        f"curl -sS 'https://jules.googleapis.com/v1alpha/sessions?pageSize=200' -H 'X-Goog-Api-Key: {api_key}'",
        check=True,
    )
    data = json.loads(p.stdout or "{}")
    return data.get("sessions", [])


def in_repo(session, repo_slug):
    src = (((session or {}).get("sourceContext") or {}).get("source") or "")
    return src.endswith(repo_slug)


def ensure_clean_main():
    run("git fetch origin", check=False)
    run("git checkout main")
    run("git reset --hard")


def apply_and_test(session_id, test_cmd):
    fd, patch_path = tempfile.mkstemp(prefix=f"jules_{session_id}_", suffix=".patch")
    os.close(fd)
    try:
        pull = run(f"jules remote pull --session {session_id}", check=False)
        patch = pull.stdout or ""
        Path(patch_path).write_text(patch)
        if not patch.strip():
            return {"status": "empty_patch"}

        branch = f"jules-watch-{session_id[:8]}"
        run(f"git checkout -B {branch} main")

        check = run(f"git apply --check {shlex.quote(patch_path)}", check=False)
        if check.returncode != 0:
            run("git checkout main", check=False)
            run(f"git branch -D {branch}", check=False)
            return {"status": "apply_conflict", "stderr": check.stderr[-2000:]}

        run(f"git apply {shlex.quote(patch_path)}")

        t = run(test_cmd, check=False)
        if t.returncode != 0:
            log = ((t.stdout or "") + "\n" + (t.stderr or ""))[-8000:]
            run("git checkout main", check=False)
            run(f"git branch -D {branch}", check=False)
            return {"status": "tests_failed", "test_log": log}

        run("git add -A")
        st = run("git status --porcelain", check=False)
        if not st.stdout.strip():
            run("git checkout main", check=False)
            run(f"git branch -D {branch}", check=False)
            return {"status": "no_changes"}

        msg = f"Auto-merge Jules session {session_id}"
        run(f"git commit -m {shlex.quote(msg)}")
        commit = run("git rev-parse HEAD").stdout.strip()

        run("git checkout main")
        run(f"git cherry-pick {commit}")
        push = run("git push", check=False)
        run(f"git branch -D {branch}", check=False)

        if push.returncode != 0:
            return {"status": "push_failed", "commit": commit, "stderr": push.stderr[-2000:]}
        return {"status": "merged", "commit": run("git rev-parse HEAD").stdout.strip()}
    finally:
        Path(patch_path).unlink(missing_ok=True)


def spawn_fix_session(session_id, repo_slug, reason):
    prompt = (
        f"Follow-up fix for Jules session {session_id}. "
        f"Resolve integration issues: {reason[:1200]}. "
        "Patch current main branch only, keep changes minimal, and ensure tests pass."
    )
    p = run(f"jules remote new --repo {repo_slug} --session {shlex.quote(prompt)}", check=False)
    if p.returncode != 0:
        return None
    for line in (p.stdout or "").splitlines():
        if line.strip().startswith("ID:"):
            return line.split(":", 1)[1].strip()
    return None


def watch_once(api_key, repo_slug, test_cmd, only_ids, max_age_hours):
    state = load_state()
    processed = state.setdefault("processed", {})

    sessions = [s for s in list_sessions(api_key) if in_repo(s, repo_slug)]
    now = datetime.now(timezone.utc)
    min_ts = now - timedelta(hours=max_age_hours)

    if only_ids:
        only = set(only_ids)
        sessions = [s for s in sessions if str(s.get("id")) in only]
    else:
        sessions = [s for s in sessions if (parse_ts(s.get("updateTime")) or now) >= min_ts]

    sessions.sort(key=lambda s: (s.get("updateTime") or ""), reverse=True)

    ensure_clean_main()

    changed = False
    for s in sessions:
        sid = str(s.get("id") or "")
        st = str(s.get("state") or "").upper()
        if not sid or sid in processed or st != "COMPLETED":
            continue

        result = apply_and_test(sid, test_cmd)
        rec = {"state": st, **result}
        if result.get("status") in {"tests_failed", "apply_conflict", "push_failed"}:
            fix_id = spawn_fix_session(sid, repo_slug, result.get("test_log") or result.get("stderr") or result.get("status"))
            if fix_id:
                rec["fix_session_id"] = fix_id

        processed[sid] = rec
        changed = True

    if changed:
        save_state(state)

    print(json.dumps({
        "repo": repo_slug,
        "scanned": len(sessions),
        "processed_total": len(processed),
        "recent_processed": dict(list(processed.items())[-5:])
    }, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="carter-a-lim/mustang-ops")
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-age-hours", type=int, default=6)
    ap.add_argument("--only-session", action="append", default=[])
    ap.add_argument(
        "--test-cmd",
        default=".venv/bin/python -m unittest tests/test_scrapers.py tests/test_autofill.py tests/test_metrics.py tests/test_calendar_events.py tests/test_auto_apply_orchestrator.py tests/test_question_filtering.py",
    )
    args = ap.parse_args()

    api_key = os.getenv("JULES_API_KEY")
    if not api_key:
        raise SystemExit("JULES_API_KEY is required")

    if args.once:
        watch_once(api_key, args.repo, args.test_cmd, args.only_session, args.max_age_hours)
        return

    while True:
        try:
            watch_once(api_key, args.repo, args.test_cmd, args.only_session, args.max_age_hours)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}))
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    main()
