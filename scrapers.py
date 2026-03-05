import re
from html.parser import HTMLParser


class GreenhouseParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_label = False
        self.current_label: list[str] = []
        self.questions: list[str] = []
        self.is_field = False
        self.div_depth = 0
        self.field_div_depth = -1

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag == "div":
            self.div_depth += 1
            if "field" in (attr_dict.get("class") or ""):
                self.is_field = True
                self.field_div_depth = self.div_depth

        if tag == "label" and self.is_field:
            self.in_label = True
            self.current_label = []

    def handle_endtag(self, tag):
        if tag == "label" and self.in_label:
            self.in_label = False
            text = "".join(self.current_label).strip()
            text = re.sub(r"\s+", " ", text).strip("* \n")
            if text and not _is_noise(text):
                self.questions.append(text)
            self.current_label = []

        if tag == "div":
            if self.is_field and self.div_depth == self.field_div_depth:
                self.is_field = False
                self.field_div_depth = -1
            self.div_depth -= 1

    def handle_data(self, data):
        if self.in_label:
            self.current_label.append(data)


class LeverParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_question = False
        self.target_depth = -1
        self.current_depth = 0
        self.current_text: list[str] = []
        self.questions: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.current_depth += 1
        attr_dict = dict(attrs)
        cls = attr_dict.get("class") or ""
        if ("application-question" in cls or "application-label" in cls) and not self.in_question:
            self.in_question = True
            self.target_depth = self.current_depth
            self.current_text = []

    def handle_endtag(self, tag):
        if self.in_question and self.current_depth == self.target_depth:
            self.in_question = False
            text = "".join(self.current_text).strip()
            text = re.sub(r"\s+", " ", text).strip("* \n")
            if text and not _is_noise(text):
                self.questions.append(text)
            self.current_text = []
            self.target_depth = -1
        self.current_depth -= 1

    def handle_data(self, data):
        if self.in_question:
            self.current_text.append(data)


class SmartRecruitersParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_label = False
        self.current_label: list[str] = []
        self.questions: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = (attr_dict.get("class") or "").lower()
        if tag == "label" or "question" in cls or "label" in cls:
            self.in_label = True
            self.current_label = []

    def handle_endtag(self, tag):
        if self.in_label:
            text = "".join(self.current_label).strip()
            text = re.sub(r"\s+", " ", text).strip("* \n")
            if text and not _is_noise(text):
                self.questions.append(text)
            self.in_label = False
            self.current_label = []

    def handle_data(self, data):
        if self.in_label:
            self.current_label.append(data)


class ICIMSParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_label = False
        self.current_label: list[str] = []
        self.questions: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = (attr_dict.get("class") or "").lower()
        if tag in ["label", "dt", "span"] and ("label" in cls or "field" in cls):
            self.in_label = True
            self.current_label = []

    def handle_endtag(self, tag):
        if self.in_label:
            text = "".join(self.current_label).strip()
            text = re.sub(r"\s+", " ", text).strip("* \n")
            if text and not _is_noise(text):
                self.questions.append(text)
            self.in_label = False
            self.current_label = []

    def handle_data(self, data):
        if self.in_label:
            self.current_label.append(data)


def _normalize_question(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().strip("* ")
    return text


def _is_noise(text: str) -> bool:
    clean = text.lower().replace("*", "").strip()
    if not clean or len(clean) < 6:
        return True
    ignore = {
        "resume",
        "cv",
        "resume/cv",
        "cover letter",
        "first name",
        "last name",
        "full name",
        "email",
        "phone",
        "company",
        "school",
        "degree",
        "discipline",
        "linkedin profile",
        "website",
        "portfolio",
        "portfolio url",
        "github",
        "github url",
        "start date",
        "upload",
        "job location",
        "posted date",
        "category",
        "employment type",
        "hiring company",
        "attach",
        "attach resume",
        "attach cover letter",
        "enter manually",
        "upload",
        "upload resume",
    }
    return clean in ignore


def _extract_with_regex(html: str) -> list[str]:
    out: list[str] = []
    patterns = [
        r"<label[^>]*>(.*?)</label>",
        r"<legend[^>]*>(.*?)</legend>",
        r"aria-label=[\"']([^\"']+)[\"']",
        r"placeholder=[\"']([^\"']+\?)[\"']",
    ]
    for pat in patterns:
        for m in re.findall(pat, html, flags=re.I | re.S):
            t = re.sub(r"<[^>]+>", "", m)
            t = _normalize_question(t)
            if not _is_noise(t):
                out.append(t)
    return out


def _extract_ashby(html: str) -> list[str]:
    out = _extract_with_regex(html)
    for m in re.findall(r">\s*([^<\n\r]{12,160}\?)\s*<", html, flags=re.I):
        t = _normalize_question(m)
        if not _is_noise(t):
            out.append(t)
    for m in re.findall(r'data-testid=[\"\'][^\"\']*question[^\"\']*[\"\'][^>]*>(.*?)<', html, flags=re.I | re.S):
        t = _normalize_question(re.sub(r"<[^>]+>", "", m))
        if not _is_noise(t):
            out.append(t)
    return out


def _extract_workday(html: str) -> list[str]:
    out = _extract_with_regex(html)
    patterns = [
        r'data-automation-id=[\"\'][^\"\']*(?:question|label|prompt)[^\"\']*[\"\'][^>]*>(.*?)<',
        r'aria-labelledby=[\"\'][^\"\']*[\"\'][^>]*>(.*?)<',
    ]
    for pat in patterns:
        for m in re.findall(pat, html, flags=re.I | re.S):
            t = _normalize_question(re.sub(r"<[^>]+>", "", m))
            if not _is_noise(t):
                out.append(t)
    return out


def _calculate_confidence(questions: list[str], source: str, html: str) -> float:
    if not questions:
        return 0.0
    score = 0.5
    markers = {
        "greenhouse": ["greenhouse", "field"],
        "lever": ["lever", "application-question"],
        "ashby": ["ashby"],
        "workday": ["workday", "data-automation-id"],
        "smartrecruiters": ["smartrecruiters"],
        "icims": ["icims"],
    }
    html_l = html.lower()
    for mk in markers.get(source, []):
        if mk in html_l:
            score += 0.1
    if 2 <= len(questions) <= 15:
        score += 0.2
    elif len(questions) > 15:
        score += 0.1
    return min(1.0, score)


def playwright_fallback_extract(url: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"questions": [], "field_map": [], "source": "playwright_fallback", "confidence": 0.0, "error": "Playwright not installed"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)

            script = """
            () => {
                const results = [];
                const inputs = document.querySelectorAll('input, select, textarea');
                inputs.forEach(el => {
                    const tag = el.tagName.toLowerCase();
                    const type = tag === 'input' ? el.type : tag;
                    if (['hidden', 'submit', 'button'].includes(type)) return;
                    
                    let labelText = '';
                    if (el.id) {
                        const labelEl = document.querySelector(`label[for="${el.id}"]`);
                        if (labelEl) labelText = labelEl.innerText;
                    }
                    if (!labelText && el.closest('label')) {
                        labelText = el.closest('label').innerText;
                    }
                    if (!labelText) {
                        labelText = el.getAttribute('aria-label') || el.placeholder || '';
                    }

                    let opts = [];
                    if (tag === 'select') {
                        opts = Array.from(el.querySelectorAll('option')).map(o => o.value).filter(v => v);
                    }

                    results.push({
                        label: labelText.trim(),
                        name: el.name || el.id || '',
                        type: type,
                        required: el.required || el.hasAttribute('aria-required') || false,
                        options: opts
                    });
                });
                return results;
            }
            """
            fields = page.evaluate(script)
            browser.close()

            filtered_fields = []
            questions = []
            for f in fields:
                q = _normalize_question(f['label'])
                if q and not _is_noise(q):
                    f['label'] = q
                    filtered_fields.append(f)
                    if q not in questions:
                        questions.append(q)

            return {
                "questions": questions,
                "field_map": filtered_fields,
                "source": "playwright_fallback",
                "confidence": 0.9,
                "error": None
            }
    except Exception as exc:
        return {
            "questions": [],
            "field_map": [],
            "source": "playwright_fallback",
            "confidence": 0.0,
            "error": str(exc)
        }

def extract_questions_from_html(html: str, url: str = "", threshold: float = 0.65) -> dict:
    html_lower = html.lower()
    url_lower = (url or "").lower()

    questions: list[str] = []
    source = "generic"
    error = None

    try:
        if "boards.greenhouse.io" in url_lower or "greenhouse" in html_lower or 'class="field"' in html_lower:
            source = "greenhouse"
            p = GreenhouseParser()
            p.feed(html)
            questions = p.questions
        elif "jobs.lever.co" in url_lower or "application-question" in html_lower:
            source = "lever"
            p = LeverParser()
            p.feed(html)
            questions = p.questions
        elif "ashbyhq" in url_lower or "ashby" in html_lower:
            source = "ashby"
            questions = _extract_ashby(html)
        elif "workday" in url_lower or "myworkdayjobs" in url_lower:
            source = "workday"
            questions = _extract_workday(html)
        elif "smartrecruiters" in url_lower:
            source = "smartrecruiters"
            p = SmartRecruitersParser()
            p.feed(html)
            questions = p.questions
        elif "icims" in url_lower:
            source = "icims"
            p = ICIMSParser()
            p.feed(html)
            questions = p.questions
    except Exception as exc:
        error = str(exc)

    if not questions:
        source = "generic"
        questions = _extract_with_regex(html)

    seen = set()
    out: list[str] = []
    for q in questions:
        t = _normalize_question(q)
        if t and not _is_noise(t) and t not in seen:
            seen.add(t)
            out.append(t)

    confidence = _calculate_confidence(out, source, html)
    
    # Dynamic ATS indicators check: if we see 'workday', 'greenhouse', 'lever', etc.
    # but the generic regex or parser didn't find much.
    is_dynamic = False
    if "myworkdayjobs" in url_lower or "workday" in html_lower or "smartrecruiters" in url_lower or "ashby" in html_lower:
        is_dynamic = True

    if (confidence < threshold or is_dynamic) and url:
        fallback = playwright_fallback_extract(url)
        if fallback["questions"]:
            # We log the stage transition in app.py or here, but it's easier in app.py.
            return fallback

    return {
        "questions": out,
        "field_map": [{"label": q, "name": q, "type": "text"} for q in out],
        "source": source,
        "confidence": confidence,
        "error": error,
    }


def fetch_html(url: str) -> str:
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    html = ""
    try:
        response = requests.get(url, headers=headers, timeout=12)
        response.raise_for_status()
        html = response.text
    except Exception:
        html = ""

    if html and ("<label" in html.lower() or "application-question" in html.lower()):
        return html

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            rendered = page.content()
            browser.close()
            if rendered:
                return rendered
    except Exception:
        pass

    return html
