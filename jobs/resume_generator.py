import json
import logging
import re
import os
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
RESUME_PROFILE_PATH = DATA_DIR / "resume_profile.json"
STYLE_PROFILE_PATH = DATA_DIR / "application_style_profile.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def extract_keywords(text: str) -> set:
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return set(text.split())

def score_bullet(bullet: str, jd_keywords: set, has_metric: bool) -> int:
    score = 0
    if has_metric:
        score += 10
    bullet_words = extract_keywords(bullet)
    overlap = bullet_words.intersection(jd_keywords)
    score += len(overlap) * 5
    return score

def generate_resume_for_job(job_id: str, company: str, title: str, jd_text: str = "") -> dict:
    profile_data = _load_json(RESUME_PROFILE_PATH).get("profile", {})
    style_data = _load_json(STYLE_PROFILE_PATH)
    constraints = style_data.get("resume_constraints", {})
    max_bullets = constraints.get("max_bullets_per_role_or_project", 3)
    
    jd_keywords = extract_keywords(jd_text) or extract_keywords(company + " " + title)
    
    # 1. Selection Engine
    experiences = profile_data.get("experiences", [])
    selected_experiences = []
    
    for exp in experiences:
        bullets = []
        # Simulate breaking "impact" and "what_built" into bullets if needed, or if it's already a list.
        # But in resume_profile.json, "what_built" and "impact" are strings. Let's make bullets from them.
        raw_bullets = []
        if "bullets" in exp and isinstance(exp["bullets"], list):
            raw_bullets.extend(exp["bullets"])
        if "what_built" in exp:
            raw_bullets.append(exp["what_built"])
        if "impact" in exp:
            raw_bullets.append(exp["impact"])
            
        scored_bullets = []
        for b in raw_bullets:
            has_metric = bool(re.search(r'\d+%|\$\d+|\d+x|\d+\+', b))
            score = score_bullet(b, jd_keywords, has_metric)
            scored_bullets.append((score, b))
            
        scored_bullets.sort(key=lambda x: x[0], reverse=True)
        top_bullets = [b for _, b in scored_bullets[:max_bullets]]
        
        selected_experiences.append({
            "name": exp.get("name", ""),
            "type": exp.get("type", ""),
            "dates": exp.get("dates", ""),
            "bullets": top_bullets,
            "tech": exp.get("tech", [])
        })

    pdf_path = ARTIFACTS_DIR / f"{job_id}_resume.pdf"
    txt_path = ARTIFACTS_DIR / f"{job_id}_resume.txt"
    status = "failed"
    error_msg = None
    text_content = ""
    
    # Retry loop for strict one page
    max_retries = 3
    for attempt in range(max_retries):
        html_content = _render_html(profile_data, selected_experiences)
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content(html_content)
                
                # Check height (11in - 1in margins = 10in = 960px). Use 950px for safety.
                body_height = page.evaluate("document.body.scrollHeight")
                
                if body_height > 950 and constraints.get("one_page_strict", True):
                    logging.warning(f"Resume {job_id} exceeded one page (height: {body_height}px). Revising.")
                    browser.close()
                    
                    # Revise: find the lowest scored bullet and remove it
                    lowest_score = float('inf')
                    lowest_exp_idx = -1
                    lowest_bullet_idx = -1
                    
                    for i, exp in enumerate(selected_experiences):
                        for j, b in enumerate(exp['bullets']):
                            score = score_bullet(b, jd_keywords, bool(re.search(r'\d+%|\$\d+|\d+x|\d+\+', b)))
                            if score < lowest_score and len(exp['bullets']) > 1: # don't remove last bullet
                                lowest_score = score
                                lowest_exp_idx = i
                                lowest_bullet_idx = j
                                
                    if lowest_exp_idx != -1:
                        selected_experiences[lowest_exp_idx]['bullets'].pop(lowest_bullet_idx)
                        continue # try rendering again
                    else:
                        # Can't remove any more bullets, forced to fail
                        error_msg = "Constraint failed: cannot fit on one page"
                        break
                        
                # Success
                page.pdf(path=str(pdf_path), format="Letter", margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"})
                browser.close()
                status = "generated"
                
                # Generate text extract
                text_content = f"{profile_data.get('name', '')}\n{profile_data.get('email', '')}\n\n"
                for exp in selected_experiences:
                    text_content += f"{exp['name']} - {exp['type']} ({exp['dates']})\n"
                    for b in exp['bullets']:
                        text_content += f"- {b}\n"
                    text_content += "\n"
                txt_path.write_text(text_content, encoding="utf-8")
                break # Exit retry loop
                
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            logging.error(f"PDF generation failed: {e}")
            break

    return {
        "job_id": job_id,
        "status": status,
        "pdf_path": str(pdf_path),
        "txt_path": str(txt_path),
        "error": error_msg,
        "metadata": {
            "score": sum(score for exp in selected_experiences for score, _ in [(score_bullet(b, jd_keywords, bool(re.search(r'\d+%|\$\d+|\d+x|\d+\+', b))), b) for b in exp['bullets']]),
            "keywords_matched": list(jd_keywords.intersection(extract_keywords(text_content)))
        }
    }

def _render_html(profile: dict, experiences: list) -> str:
    # Single-column ATS-safe plain HTML
    name = profile.get("name", "Applicant")
    email = profile.get("email", "")
    phone = profile.get("phone", "")
    links = profile.get("links", {})
    linkedin = links.get("linkedin", "")
    
    contact_info = f"{email} | {phone} | {linkedin}"
    
    exp_html = ""
    for exp in experiences:
        tech_str = ", ".join(exp['tech']) if exp['tech'] else ""
        tech_html = f"<i>Tech: {tech_str}</i><br>" if tech_str else ""
        bullets_html = "".join(f"<li>{b}</li>" for b in exp['bullets'])
        
        exp_html += f"""
        <div class="experience">
            <div class="header">
                <strong>{exp['name']}</strong> - {exp['type']}
                <span class="dates">{exp['dates']}</span>
            </div>
            {tech_html}
            <ul>
                {bullets_html}
            </ul>
        </div>
        """
        
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.3; color: #000; margin: 0; padding: 0; }}
            h1 {{ font-size: 16pt; text-align: center; margin-bottom: 5px; }}
            .contact {{ text-align: center; font-size: 10pt; margin-bottom: 15px; }}
            h2 {{ font-size: 13pt; border-bottom: 1px solid #000; margin-top: 10px; margin-bottom: 5px; }}
            .experience {{ margin-bottom: 10px; }}
            .header {{ display: flex; justify-content: space-between; margin-bottom: 3px; }}
            .dates {{ font-style: italic; }}
            ul {{ margin-top: 3px; margin-bottom: 3px; padding-left: 20px; }}
            li {{ margin-bottom: 2px; }}
        </style>
    </head>
    <body>
        <h1>{name}</h1>
        <div class="contact">{contact_info}</div>
        
        <h2>Experience</h2>
        {exp_html}
    </body>
    </html>
    """

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        generate_resume_for_job(sys.argv[1], "TestCo", "Software Engineer", "React Node Python fast metrics")
