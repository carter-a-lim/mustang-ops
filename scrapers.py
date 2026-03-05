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

            clean_text = text.lower().replace("*", "").strip()
            ignore_list = {
                "resume",
                "cv",
                "resume/cv",
                "cover letter",
                "first name",
                "last name",
                "email",
                "phone",
                "school",
                "degree",
                "discipline",
                "linkedin profile",
                "website",
                "portfolio",
                "github",
                "start date",
            }
            if text and clean_text not in ignore_list:
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

            clean_text = text.lower().replace("*", "").strip()
            ignore_list = {
                "resume/cv",
                "resume",
                "cv",
                "cover letter",
                "first name",
                "last name",
                "full name",
                "email",
                "phone",
                "company",
                "linkedin profile",
                "website",
                "portfolio url",
                "github url",
                "start date",
            }
            if text and clean_text not in ignore_list:
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
        # iCIMS often uses .iCIMS_JobHeaderField or similar for labels
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
        # iCIMS "ID" is short, common noise
        if clean in ["id"]:
            return True
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
    }
    return clean in ignore


def _calculate_confidence(questions: list[str], ats_type: str, html: str) -> float:
    if not questions:
        return 0.0

    score = 0.5 # Baseline for finding any questions

    # Bonus for common ATS markers in HTML
    markers = {
        "greenhouse": ["boards.greenhouse.io", "field"],
        "lever": ["jobs.lever.co", "application-question"],
        "ashby": ["ashbyhq.com", "ashby"],
        "workday": ["myworkdayjobs.com", "data-automation-id"],
        "smartrecruiters": ["smartrecruiters.com"],
        "icims": ["icims.com", "iCIMS_JobHeaderField"]
    }

    html_lower = html.lower()
    if ats_type in markers:
        for m in markers[ats_type]:
            if m in html_lower:
                score += 0.1

    # Bonus for reasonable number of questions
    if 2 <= len(questions) <= 15:
        score += 0.2
    elif len(questions) > 15:
        score += 0.1

    return min(1.0, score)


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
    # Ashby often renders prompts in heading-like blocks or specific data-attributes
    for m in re.findall(r">\s*([^<\n\r]{12,140}\?)\s*<", html, flags=re.I):
        t = _normalize_question(m)
        if not _is_noise(t):
            out.append(t)

    # Specific ashby data markers
    for m in re.findall(r'data-testid=[\"\'][^\"\']*question[^\"\']*[\"\'][^>]*>(.*?)<', html, flags=re.I | re.S):
        t = _normalize_question(re.sub(r"<[^>]+>", "", m))
        if not _is_noise(t):
            out.append(t)

    return out


def _extract_workday(html: str) -> list[str]:
    out = _extract_with_regex(html)
    # Workday often has data-automation-id markers near prompt text
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


def extract_questions_from_html(html: str, url: str = "") -> dict:
    html_lower = html.lower()
    url_lower = (url or "").lower()

    questions: list[str] = []
    ats_type = "generic"
    error = None

    try:
        if "boards.greenhouse.io" in url_lower or "greenhouse" in html_lower or 'class="field"' in html_lower:
            ats_type = "greenhouse"
            parser = GreenhouseParser()
            parser.feed(html)
            questions = parser.questions
        elif "jobs.lever.co" in url_lower or "application-question" in html_lower:
            ats_type = "lever"
            parser = LeverParser()
            parser.feed(html)
            questions = parser.questions
        elif "ashbyhq" in url_lower or "ashby" in html_lower:
            ats_type = "ashby"
            questions = _extract_ashby(html)
        elif "workday" in url_lower or "myworkdayjobs" in url_lower:
            ats_type = "workday"
            questions = _extract_workday(html)
        elif "smartrecruiters" in url_lower:
            ats_type = "smartrecruiters"
            parser = SmartRecruitersParser()
            parser.feed(html)
            questions = parser.questions
        elif "icims" in url_lower:
            ats_type = "icims"
            parser = ICIMSParser()
            parser.feed(html)
            questions = parser.questions
    except Exception as e:
        error = str(e)

    if not questions:
        # generic fallback for unknown ATS patterns
        questions = _extract_with_regex(html)

    seen = set()
    unique_questions: list[str] = []
    for q in questions:
        t = _normalize_question(q)
        if t and not _is_noise(t) and t not in seen:
            seen.add(t)
            unique_questions.append(t)

    confidence = _calculate_confidence(unique_questions, ats_type, html)

    return {
        "questions": unique_questions,
        "source": ats_type,
        "confidence": confidence,
        "error": error
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

    # Some ATS pages (e.g. Ashby/Workday) render fields client-side.
    # If static HTML looks too thin, try a browser-rendered snapshot.
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
