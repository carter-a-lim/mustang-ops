import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ASSISTED_QUEUE_PATH = DATA_DIR / "assisted_apply_queue.json"
RESUME_PROFILE_PATH = DATA_DIR / "resume_profile.json"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def update_job_status(job_id: str, status: str, error_msg: str | None = None, attempt_info: dict | None = None) -> dict | None:
    if not ASSISTED_QUEUE_PATH.exists():
        return None

    try:
        data = json.loads(ASSISTED_QUEUE_PATH.read_text())
    except Exception:
        return None

    queue = data.get("queue", [])
    job = None
    for item in queue:
        if item.get("id") == job_id:
            item["status"] = status
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            if error_msg:
                item["last_error"] = error_msg

            if attempt_info:
                attempts = item.setdefault("attempts", [])
                attempts.append({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    **attempt_info
                })
                item["attempts"] = attempts[-10:] # Keep last 10

            job = item
            break

    if job:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        ASSISTED_QUEUE_PATH.write_text(json.dumps(data, indent=2) + "\n")
    return job


def get_job(job_id: str) -> dict | None:
    if not ASSISTED_QUEUE_PATH.exists():
        return None
    try:
        data = json.loads(ASSISTED_QUEUE_PATH.read_text())
    except Exception:
        return None
    for item in data.get("queue", []):
        if item.get("id") == job_id:
            return item
    return None


def get_fallback_data() -> dict:
    profile = {}
    if RESUME_PROFILE_PATH.exists():
        try:
            profile = json.loads(RESUME_PROFILE_PATH.read_text()).get("profile", {})
        except Exception:
            profile = {}

    return {
        "first_name": "Applicant",
        "last_name": "Mustang",
        "email": "mustang@example.com",
        "phone": "555-0100",
        "linkedin": "https://linkedin.com/in/mustang",
        "github": "https://github.com/mustang",
        "skills": profile.get("skills", ["python", "javascript"]),
        "grad_year": str(profile.get("grad_year", "2025")),
        "work_auth": profile.get("work_auth", "us-citizen"),
    }


def fill_form(page, data: dict) -> None:
    import re

    # Layer 1: Specific field mappings with multiple selector strategies
    field_specs = [
        {"key": "first_name", "patterns": ["first name", "fname", "given name"], "value": data.get("first_name")},
        {"key": "last_name", "patterns": ["last name", "lname", "family name", "surname"], "value": data.get("last_name")},
        {"key": "email", "patterns": ["email", "e-mail"], "value": data.get("email")},
        {"key": "phone", "patterns": ["phone", "mobile", "contact number", "tel"], "value": data.get("phone")},
        {"key": "linkedin", "patterns": ["linkedin"], "value": data.get("linkedin")},
        {"key": "github", "patterns": ["github"], "value": data.get("github")},
        {"key": "website", "patterns": ["website", "portfolio"], "value": data.get("website") or data.get("github")},
    ]

    for spec in field_specs:
        if not spec["value"]:
            continue

        found = False
        # Strategy A: Label matching (ARIA and associated labels)
        for pattern in spec["patterns"]:
            try:
                loc = page.get_by_label(pattern, exact=False)
                if loc.count() > 0:
                    loc.first.fill(spec["value"])
                    logging.info(f"Filled {spec['key']} via label: {pattern}")
                    found = True
                    break
            except Exception:
                pass
        if found: continue

        # Strategy B: Placeholder matching
        for pattern in spec["patterns"]:
            try:
                loc = page.get_by_placeholder(pattern, exact=False)
                if loc.count() > 0:
                    loc.first.fill(spec["value"])
                    logging.info(f"Filled {spec['key']} via placeholder: {pattern}")
                    found = True
                    break
            except Exception:
                pass
        if found: continue

        # Strategy C: Attribute regex (id, name, data-automation-id)
        regex_pattern = "|".join(spec["patterns"])
        locators = page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="file"]):not([type="checkbox"]):not([type="radio"]), textarea')
        for i in range(locators.count()):
            loc = locators.nth(i)
            for attr in ["id", "name", "data-automation-id", "aria-label"]:
                val = loc.get_attribute(attr) or ""
                if re.search(regex_pattern, val, re.I):
                    loc.fill(spec["value"])
                    logging.info(f"Filled {spec['key']} via {attr}: {val}")
                    found = True
                    break
            if found: break

    # Layer 2: Resume upload with robust detection
    try:
        file_inputs = page.locator('input[type="file"]')
        resume_found = False
        resume_path = DATA_DIR / "resume" / "latest_resume.txt"

        if resume_path.exists():
            for i in range(file_inputs.count()):
                loc = file_inputs.nth(i)
                attrs = (loc.get_attribute("id") or "") + (loc.get_attribute("name") or "") + (loc.get_attribute("aria-label") or "")
                if re.search(r"resume|cv", attrs, re.I):
                    loc.set_input_files(str(resume_path))
                    logging.info("Uploaded resume via keyword-matched file input")
                    resume_found = True
                    break

            if not resume_found and file_inputs.count() > 0:
                file_inputs.first.set_input_files(str(resume_path))
                logging.info("Uploaded resume via fallback (first file input)")
    except Exception as e:
        logging.warning(f"Resume upload failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Autofill Application Worker")
    parser.add_argument("job_id")
    parser.add_argument("mode", choices=["dry-run", "live"])
    args = parser.parse_args()

    job = get_job(args.job_id)
    if not job:
        print(f"Job {args.job_id} not found")
        sys.exit(1)

    apply_url = job.get("apply_url")
    if not apply_url:
        update_job_status(args.job_id, "error", "Missing apply_url")
        sys.exit(1)

    max_retries = 3
    attempt = 0
    success = False

    while attempt < max_retries and not success:
        attempt += 1
        attempt_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_a{attempt}"
        logging.info(f"Starting attempt {attempt}/{max_retries} for job {args.job_id} ({args.mode})")

        with sync_playwright() as p:
            browser = None
            try:
                headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()

                # Classification: NAVIGATION_FAILED
                try:
                    page.goto(apply_url, wait_until="networkidle", timeout=30000)
                except Exception as e:
                    logging.error(f"Navigation failed: {e}")
                    raise Exception(f"NAVIGATION_FAILED: {e}")

                fill_form(page, get_fallback_data())

                # Classification: ARTIFACT_FAILED (non-fatal for the run)
                job_artifacts_dir = ARTIFACTS_DIR / args.job_id
                job_artifacts_dir.mkdir(parents=True, exist_ok=True)
                try:
                    screenshot_path = job_artifacts_dir / f"{attempt_id}_{args.mode}.png"
                    page.screenshot(path=str(screenshot_path), full_page=True)

                    html_path = job_artifacts_dir / f"{attempt_id}_{args.mode}.html"
                    html_path.write_text(page.content(), encoding="utf-8")
                except Exception as e:
                    logging.warning(f"Failed to save artifacts: {e}")

                if args.mode == "live":
                    # Re-verify approval status from file
                    fresh_job = get_job(args.job_id)
                    if not fresh_job or fresh_job.get("status") != "approved":
                        raise Exception("UNAPPROVED_SUBMIT_ATTEMPT: Job status must be 'approved' for live submission")

                    submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Submit"), button:has-text("Apply")').first
                    if submit_btn.count() > 0:
                        submit_btn.click(timeout=5000)
                        page.wait_for_load_state("networkidle", timeout=10000)
                        update_job_status(
                            args.job_id,
                            "submitted",
                            attempt_info={
                                "attempt": attempt,
                                "mode": args.mode,
                                "status": "success",
                                "artifacts": {
                                    "screenshot": str(job_artifacts_dir / f"{attempt_id}_{args.mode}.png"),
                                    "html": str(job_artifacts_dir / f"{attempt_id}_{args.mode}.html")
                                }
                            }
                        )
                        success = True
                    else:
                        raise Exception("SELECTOR_NOT_FOUND: Submit button not found")
                else:
                    # Dry-run success
                    new_status = "needs-approval" if job.get("status") != "approved" else job.get("status")
                    update_job_status(
                        args.job_id,
                        new_status,
                        attempt_info={
                            "attempt": attempt,
                            "mode": args.mode,
                            "status": "success",
                            "artifacts": {
                                "screenshot": str(job_artifacts_dir / f"{attempt_id}_{args.mode}.png"),
                                "html": str(job_artifacts_dir / f"{attempt_id}_{args.mode}.html")
                            }
                        }
                    )
                    success = True

            except Exception as exc:
                error_msg = str(exc)
                logging.error(f"Attempt {attempt} failed: {error_msg}")

                error_code = "UNKNOWN_ERROR"
                if ":" in error_msg:
                    error_code = error_msg.split(":")[0]

                update_job_status(
                    args.job_id,
                    "error",
                    error_msg,
                    attempt_info={
                        "attempt": attempt,
                        "mode": args.mode,
                        "status": "failed",
                        "error_code": error_code,
                        "error_message": error_msg,
                        "artifacts": {
                            "screenshot": str(job_artifacts_dir / f"{attempt_id}_{args.mode}.png") if 'job_artifacts_dir' in locals() else None,
                            "html": str(job_artifacts_dir / f"{attempt_id}_{args.mode}.html") if 'job_artifacts_dir' in locals() else None
                        }
                    }
                )

                # If it's an unapproved attempt, don't retry
                if "UNAPPROVED_SUBMIT_ATTEMPT" in error_msg:
                    break

                if attempt < max_retries:
                    import time
                    time.sleep(2 ** attempt) # Exponential backoff
            finally:
                if browser:
                    browser.close()


if __name__ == "__main__":
    main()
