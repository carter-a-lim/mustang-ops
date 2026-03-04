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
            if "field" in attr_dict.get("class", ""):
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
        cls = attr_dict.get("class", "")
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


def extract_questions_from_html(html: str, url: str = "") -> list[str]:
    html_lower = html.lower()

    if "boards.greenhouse.io" in url.lower() or "greenhouse" in html_lower or 'class="field"' in html_lower:
        parser = GreenhouseParser()
        parser.feed(html)
        questions = parser.questions
        if not questions:
            parser = LeverParser()
            parser.feed(html)
            questions = parser.questions
    else:
        parser = LeverParser()
        parser.feed(html)
        questions = parser.questions
        if not questions:
            parser = GreenhouseParser()
            parser.feed(html)
            questions = parser.questions

    seen = set()
    out = []
    for q in questions:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def fetch_html(url: str) -> str:
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=12)
        response.raise_for_status()
        return response.text
    except Exception:
        return ""
