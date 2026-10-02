from __future__ import annotations

import re
from typing import Any


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def build_resume_answers(candidate: dict[str, Any], job: dict[str, Any], base_answers: dict[str, Any]) -> dict[str, Any]:
    name = str(candidate.get("name") or "").strip()
    parts = name.split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    return {
        **base_answers,
        "full_name": name,
        "first_name": first,
        "last_name": last,
        "email": candidate.get("email", ""),
        "phone": candidate.get("phone", ""),
        "city": "Bhopal",
        "country": "India",
        "current_company": "AM Webtech",
        "current_title": "QA Engineer",
        "experience_years": str(candidate.get("experience_years", "1")),
        "notice_period_days": str(candidate.get("notice_period_days", "45")),
        "current_ctc": str(candidate.get("current_ctc_lpa", "2.2")),
        "expected_ctc": "₹4–5 LPA",
        "linkedin": "https://www.linkedin.com/in/satyendra-namdeo/",
        "github": "https://github.com/SanFlash",
        "portfolio": "https://satyendranamdeo.co.in",
        "skills": ", ".join(candidate.get("skills", [])),
        "education": "MCA, University Institute of Technology, Bhopal (CGPA 8.32); B.Tech EEE, Lakshmi Narain College of Technology (CGPA 8.77)",
        "work_authorization": "Yes",
        "sponsorship": "No",
        "relocation": "Yes",
        "gender": "",
        "dob": "",
    }


# Ordered patterns: more specific patterns must appear before generic ones.
FIELD_RULES = [
    ("first_name", [r"first\s*name", r"given\s*name", r"forename"]),
    ("last_name", [r"last\s*name", r"family\s*name", r"surname"]),
    ("full_name", [r"full\s*name", r"candidate\s*name", r"your\s*name", r"^name$"]),
    ("email", [r"e\s*mail", r"email\s*address"]),
    ("phone", [r"phone", r"mobile", r"telephone", r"contact\s*number"]),
    ("linkedin", [r"linkedin"]),
    ("github", [r"github", r"git\s*hub"]),
    ("portfolio", [r"portfolio", r"personal\s*(website|site)", r"website", r"personal\s*url"]),
    ("current_company", [r"current\s*company", r"current\s*employer", r"employer"]),
    ("current_title", [r"current\s*(job\s*)?title", r"current\s*role"]),
    ("experience_years", [r"years?\s*of\s*experience", r"total\s*experience", r"experience\s*in\s*years"]),
    ("notice_period_days", [r"notice\s*period", r"days?\s*to\s*join", r"availability"]),
    ("current_ctc", [r"current\s*(ctc|salary|compensation)", r"present\s*(ctc|salary)"]),
    ("expected_ctc", [r"expected\s*(ctc|salary|compensation)", r"desired\s*(salary|compensation)"]),
    ("city", [r"current\s*city", r"city", r"location"]),
    ("country", [r"country", r"country\s*of\s*residence"]),
    ("work_authorization", [r"work\s*authorization", r"authorized\s*to\s*work", r"legally\s*authorized"]),
    ("sponsorship", [r"visa\s*sponsorship", r"require.*sponsorship", r"sponsorship"]),
    ("relocation", [r"relocat", r"willing\s*to\s*move"]),
    ("skills", [r"skills", r"technical\s*skills", r"technologies"]),
    ("education", [r"education", r"degree", r"qualification"]),
    ("cover_letter", [r"cover\s*letter", r"additional\s*information", r"message", r"about\s*you"]),
    ("why_interested", [r"why.*interested", r"why.*apply", r"why.*join", r"why.*want"]),
    ("why_hire", [r"why.*hire", r"why.*you", r"what.*qualif"]),
    ("automation_experience", [r"automation.*experience", r"test.*automation"]),
    ("playwright_experience", [r"playwright"]),
    ("mobile_automation_experience", [r"mobile.*automation", r"appium"]),
    ("api_testing_experience", [r"api.*test", r"rest.*api"]),
    ("database_experience", [r"database", r"sql.*experience"]),
    ("ai_qa_experience", [r"ai.*qa", r"ai.*test", r"artificial.*intelligence.*test"]),
]


def answer_for_descriptor(descriptor: str, answers: dict[str, Any]) -> tuple[str | None, str | None]:
    text = normalize(descriptor)
    if not text:
        return None, None
    for key, patterns in FIELD_RULES:
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            value = str(answers.get(key) or "").strip()
            if value:
                return key, value
    return None, None


def option_match(options: list[str], value: str) -> str | None:
    target = normalize(value)
    if not target:
        return None
    exact = {normalize(x): x for x in options}
    if target in exact:
        return exact[target]
    aliases = {
        "yes": {"yes", "y", "true"},
        "no": {"no", "n", "false"},
        "india": {"india", "indian"},
        "remote": {"remote", "work from home", "wfh"},
        "hybrid": {"hybrid"},
        "full time": {"full time", "full-time", "fulltime"},
    }
    for canonical, values in aliases.items():
        if target == canonical:
            for option in options:
                if normalize(option) in values:
                    return option
    for option in options:
        n = normalize(option)
        if target in n or n in target:
            return option
    return None
