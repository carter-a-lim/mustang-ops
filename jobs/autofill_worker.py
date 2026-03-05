import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ASSISTED_QUEUE_PATH = DATA_DIR / "assisted_apply_queue.json"
RESUME_PROFILE_PATH = DATA_DIR / "resume_profile.json"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def update_job_status(job_id: str, status: str, error_msg: str | None = None) -> dict | None:
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


def get_job_pipeline_record(company: str, title: str) -> dict | None:
    pipeline_path = DATA_DIR / "job_pipeline.json"
    if not pipeline_path.exists():
        return None
    try:
        data = json.loads(pipeline_path.read_text())
        for a in data.get("applications", []):
            if a.get("company", "").lower() == (company or "").lower() and a.get("title", "").lower() == (title or "").lower():
                return a
    except Exception:
        pass
    return None

def fill_form(page, data: dict, job: dict | None = None) -> None:
    mappings = {
        "first.*name|fname": data["first_name"],
        "last.*name|lname": data["last_name"],
        "email": data["email"],
        "phone|mobile": data["phone"],
        "linkedin": data["linkedin"],
        "github": data["github"],
    }

    import re

    field_map = []
    if job:
        pipeline_record = get_job_pipeline_record(job.get("company", ""), job.get("title", ""))
        if pipeline_record:
            field_map = pipeline_record.get("field_map", [])
            
    # Structured field map filling (if available)
    if field_map:
        for field in field_map:
            field_name = field.get("name")
            field_label = field.get("label")
            # Simple heuristic mapping for the extracted metadata
            val_to_fill = None
            for pattern, value in mappings.items():
                if (field_name and re.search(pattern, field_name, re.I)) or (field_label and re.search(pattern, field_label, re.I)):
                    val_to_fill = value
                    break
            
            if val_to_fill:
                try:
                    if field_name:
                        locators = page.locator(f'[name="{field_name}"]')
                        if locators.count() > 0:
                            locators.first.fill(val_to_fill)
                            continue
                except Exception:
                    pass
                
                try:
                    if field_label:
                        labels = page.get_by_label(field_label, exact=True)
                        if labels.count() > 0:
                            labels.first.fill(val_to_fill)
                            continue
                        labels = page.get_by_label(field_label)
                        if labels.count() > 0:
                            labels.first.fill(val_to_fill)
                            continue
                except Exception:
                    pass


    # Generic fallback mapping logic
    for pattern, value in mappings.items():
        filled = False
        try:
            placeholders = page.get_by_placeholder(re.compile(pattern, re.I))
            if placeholders.count() > 0:
                placeholders.first.fill(value)
                filled = True
        except Exception:
            pass

        if not filled:
            try:
                labels = page.get_by_label(re.compile(pattern, re.I))
                if labels.count() > 0:
                    labels.first.fill(value)
                    filled = True
            except Exception:
                pass

        if not filled:
            try:
                locators = page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="file"]):not([type="checkbox"]):not([type="radio"])')
                count = locators.count()
                for i in range(count):
                    loc = locators.nth(i)
                    id_val = loc.get_attribute("id") or ""
                    name_val = loc.get_attribute("name") or ""
                    placeholder_val = loc.get_attribute("placeholder") or ""
                    if re.search(pattern, id_val, re.I) or re.search(pattern, name_val, re.I) or re.search(pattern, placeholder_val, re.I):
                        loc.fill(value)
                        break
            except Exception:
                pass

    try:
        file_inputs = page.locator('input[type="file"]')
        if file_inputs.count() > 0:
            resume_path = DATA_DIR / "resume" / "latest_resume.txt"
            if resume_path.exists():
                file_inputs.first.set_input_files(str(resume_path))
    except Exception:
        pass


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

    log_artifact = {
        "job_id": args.job_id,
        "mode": args.mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_details": job,
        "outcome": "unknown",
        "error_classification": None,
        "screenshot_path": f"{args.job_id}_{args.mode}.png",
    }

    with sync_playwright() as p:
        browser = None
        try:
            headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            page.goto(apply_url, wait_until="networkidle", timeout=30000)
            fill_form(page, get_fallback_data(), job)

            screenshot_path = ARTIFACTS_DIR / f"{args.job_id}_{args.mode}.png"
            page.screenshot(path=str(screenshot_path), full_page=True)

            if args.mode == "live":
                if job.get("status") != "approved":
                    error_msg = "Must be approved before live submit"
                    update_job_status(args.job_id, "error", error_msg)
                    log_artifact["outcome"] = "error"
                    log_artifact["error_classification"] = "ApprovalGateError"
                    return

                submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Submit"), button:has-text("Apply")').first
                if submit_btn.count() > 0:
                    submit_btn.click(timeout=5000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    update_job_status(args.job_id, "submitted")
                    log_artifact["outcome"] = "submitted"
                else:
                    update_job_status(args.job_id, "error", "Submit button not found")
                    log_artifact["outcome"] = "error"
                    log_artifact["error_classification"] = "FormFillError"
            else:
                if job.get("status") != "approved":
                    update_job_status(args.job_id, "needs-approval")
                log_artifact["outcome"] = "dry-run-complete"

        except PlaywrightTimeoutError as exc:
            logging.error(f"TimeoutError: {exc}")
            update_job_status(args.job_id, "error", f"TimeoutError: {str(exc)}")
            log_artifact["outcome"] = "error"
            log_artifact["error_classification"] = "TimeoutError"
        except Exception as exc:
            logging.error(f"Exception: {exc}")
            update_job_status(args.job_id, "error", f"Error: {str(exc)}")
            log_artifact["outcome"] = "error"
            log_artifact["error_classification"] = "GeneralError"
        finally:
            log_artifact_path = ARTIFACTS_DIR / f"{args.job_id}_{args.mode}_log.json"
            log_artifact_path.write_text(json.dumps(log_artifact, indent=2) + "\n")
            if browser:
                browser.close()


if __name__ == "__main__":
    main()
