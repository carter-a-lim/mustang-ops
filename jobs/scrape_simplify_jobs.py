import csv
import json
import os
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import requests

SOURCE_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md"
SECTION_HEADER = "## 💻 Software Engineering Internship Roles"

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

JSON_PATH = DATA_DIR / "simplify_software_internships.json"
CSV_PATH = DATA_DIR / "simplify_software_internships.csv"

TIMEOUT_SECONDS = int(os.getenv("SIMPLIFY_FETCH_TIMEOUT_SECONDS", "45"))


def _clean_text(value: str) -> str:
    value = value.replace("<br>", ", ").replace("<br/>", ", ").replace("<br />", ", ")
    value = re.sub(r"<details>.*?<summary>(.*?)</summary>(.*?)</details>", r"\1: \2", value, flags=re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_first_link(value: str) -> str | None:
    match = re.search(r'href="([^"]+)"', value)
    if not match:
        return None
    return unescape(match.group(1))


def _extract_section(markdown: str) -> str:
    start = markdown.find(SECTION_HEADER)
    if start == -1:
        raise RuntimeError("Could not find software engineering section")

    next_header = markdown.find("\n## ", start + len(SECTION_HEADER))
    if next_header == -1:
        next_header = len(markdown)

    return markdown[start:next_header]


def _parse_rows(section: str) -> list[dict]:
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", section, flags=re.DOTALL)
    if not tbody_match:
        raise RuntimeError("Could not find internship table body")

    tbody = tbody_match.group(1)
    tr_blocks = re.findall(r"<tr>(.*?)</tr>", tbody, flags=re.DOTALL)

    rows: list[dict] = []
    current_company = ""

    for block in tr_blocks:
        tds = re.findall(r"<td>(.*?)</td>", block, flags=re.DOTALL)
        if len(tds) < 5:
            continue

        company_raw, role_raw, location_raw, application_raw, age_raw = tds[:5]

        company = _clean_text(company_raw)
        if company == "↳":
            company = current_company
        elif company:
            current_company = company

        role = _clean_text(role_raw)
        location = _clean_text(location_raw)
        age = _clean_text(age_raw)
        apply_url = _extract_first_link(application_raw)

        if not (company and role and apply_url):
            continue

        rows.append(
            {
                "company": company,
                "role": role,
                "location": location,
                "apply_url": apply_url,
                "age": age,
            }
        )

    return rows


def _write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company", "role", "location", "apply_url", "age"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    response = requests.get(SOURCE_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    section = _extract_section(response.text)
    rows = _parse_rows(section)

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "source": SOURCE_URL,
        "section": SECTION_HEADER,
        "fetched_at": now,
        "count": len(rows),
        "roles": rows,
    }

    JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_csv(rows, CSV_PATH)

    print(f"scrape_simplify_jobs done | rows={len(rows)} | json={JSON_PATH} | csv={CSV_PATH}")


if __name__ == "__main__":
    main()
