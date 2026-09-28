from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
SQLITE_DB = DATA / "applybot.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AUTO_APPLY_ENABLED = os.getenv("AUTO_APPLY_ENABLED", "false").lower() == "true"
AUTO_APPLY_MAX = max(1, int(os.getenv("AUTO_APPLY_MAX", "3")))
CANDIDATE_EMAIL = os.getenv("CANDIDATE_EMAIL", "").strip()
CANDIDATE_PHONE = os.getenv("CANDIDATE_PHONE", "").strip()
RESUME_PATH = os.getenv("RESUME_PATH", "").strip()
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()
JOBICY_API_URL = os.getenv("JOBICY_API_URL", "https://jobicy.com/api/v2/remote-jobs").strip()
JOBICY_COUNT = min(200, max(1, int(os.getenv("JOBICY_COUNT", "200"))))
ENABLE_LEGACY_SOURCES = os.getenv("ENABLE_LEGACY_SOURCES", "false").lower() == "true"
GREENHOUSE_BOARDS = [x.strip() for x in os.getenv("GREENHOUSE_BOARDS", "").split(",") if x.strip()]
LEVER_COMPANIES = [x.strip() for x in os.getenv("LEVER_COMPANIES", "").split(",") if x.strip()]

def resume_file_path():
    configured = RESUME_PATH or str(DATA / "resume.pdf")
    return Path(configured)

app = Flask(__name__, static_folder="web", static_url_path="")

CANDIDATE = {
    "name": "Satyendra Kumar Namdeo",
    "title": "QA Engineer | QA Automation | SDET | AI-Assisted QA",
    "experience_years": 1.0,
    "current_ctc_lpa": 2.2,
    "expected_ctc_min_lpa": 4.0,
    "expected_ctc_max_lpa": 5.0,
    "minimum_ctc_lpa": 3.0,
    "notice_period_days": 45,
    "locations": ["India", "Indore", "Bangalore", "Pune", "Remote"],
    "work_modes": ["Hybrid"],
    "roles_primary": [
        "QA Automation Engineer", "Automation Tester", "SDET",
        "Software Tester", "Test Engineer", "AI Assisted QA", "AI Assisted Tester"
    ],
    "roles_secondary": ["Frontend Designer", "AI-Assisted Developer", "Vibe Coding"],
    "skills": [
        "Python", "Playwright", "JavaScript", "TypeScript", "Appium", "Git",
        "GitHub", "Jira", "Swagger", "SQL", "CI/CD", "Confluence",
        "API Testing", "Manual Testing", "Regression Testing", "E2E Testing",
        "AI-Assisted Testing", "Prompt Engineering"
    ],
}

ROLE_KEYWORDS = {
    "QA Automation Engineer": ["qa automation", "automation qa", "automation engineer", "quality assurance automation"],
    "Automation Tester": ["automation tester", "test automation", "qa automation"],
    "SDET": ["sdet", "software development engineer in test"],
    "Software Tester": ["software tester", "qa tester", "test engineer"],
    "Test Engineer": ["test engineer", "quality engineer"],
    "AI Assisted QA": ["ai assisted qa", "ai qa", "ai testing", "ai-assisted testing"],
    "AI Assisted Tester": ["ai tester", "ai-assisted tester"],
    "Frontend Designer": ["frontend designer", "ui designer", "frontend"],
    "AI-Assisted Developer": ["ai-assisted developer", "ai developer"],
    "Vibe Coding": ["vibe coding", "ai coding"],
}

STOPWORDS = {
    "and", "the", "with", "for", "from", "that", "this", "your", "you",
    "are", "will", "our", "their", "have", "has", "into", "years", "year",
    "role", "job", "using", "work", "about", "who", "what", "but", "not", "all"
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def is_postgres():
    return bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))


class DB:
    def __init__(self):
        self.pg = is_postgres()
        if self.pg:
            try:
                import psycopg2
                from psycopg2.extras import RealDictCursor
            except ImportError as exc:
                raise RuntimeError("DATABASE_URL is set but psycopg2-binary is not installed") from exc
            self.conn = psycopg2.connect(DATABASE_URL)
            self.cursor_factory = RealDictCursor
        else:
            self.conn = sqlite3.connect(SQLITE_DB)
            self.conn.row_factory = sqlite3.Row

    def execute(self, sql, params=()):
        if self.pg:
            sql = sql.replace("?", "%s")
            cur = self.conn.cursor(cursor_factory=self.cursor_factory)
            cur.execute(sql, params)
            return cur
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def db():
    return DB()


def ensure_schema_columns(c):
    migrations = {
        "applications": {
            "adapter": "TEXT",
            "submission_id": "TEXT",
            "submission_message": "TEXT",
            "submitted_at": "TEXT",
        },
        "jobs": {
            "match_reasons": "TEXT",
            "matched_skills": "TEXT",
            "source_url": "TEXT",
        },
    }
    for table, wanted in migrations.items():
        if c.pg:
            rows = c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=?",
                (table,),
            ).fetchall()
            existing = {r["column_name"] for r in rows}
        else:
            rows = c.execute("PRAGMA table_info(" + table + ")").fetchall()
            existing = {r[1] for r in rows}
        for name, kind in wanted.items():
            if name not in existing:
                c.execute("ALTER TABLE " + table + " ADD COLUMN " + name + " " + kind)


def init_db():
    c = db()

    if c.pg:
        statements = [
            """CREATE TABLE IF NOT EXISTS jobs (
              id BIGSERIAL PRIMARY KEY, external_id TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
              title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, work_mode TEXT,
              salary_min DOUBLE PRECISION, salary_max DOUBLE PRECISION, experience_min DOUBLE PRECISION,
              source_url TEXT, url TEXT NOT NULL, description TEXT NOT NULL, discovered_at TEXT NOT NULL,
              match_score DOUBLE PRECISION DEFAULT 0, status TEXT DEFAULT 'new', skip_reason TEXT)""",
            """CREATE TABLE IF NOT EXISTS applications (
              id BIGSERIAL PRIMARY KEY, job_id BIGINT NOT NULL, tailored_summary TEXT,
              cover_letter TEXT, answers_json TEXT, status TEXT NOT NULL DEFAULT 'draft',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
        ]
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
              title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, work_mode TEXT,
              salary_min REAL, salary_max REAL, experience_min REAL,
              source_url TEXT, url TEXT NOT NULL, description TEXT NOT NULL, discovered_at TEXT NOT NULL,
              match_score REAL DEFAULT 0, status TEXT DEFAULT 'new', skip_reason TEXT)""",
            """CREATE TABLE IF NOT EXISTS applications (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, tailored_summary TEXT,
              cover_letter TEXT, answers_json TEXT, status TEXT NOT NULL DEFAULT 'draft',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL)""",

        ]

    for statement in statements:
        c.execute(statement)

    ensure_schema_columns(c)

    candidate_json = json.dumps(CANDIDATE)
    if c.pg:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            ("candidate", candidate_json),
        )
    else:
        c.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
            ("candidate", candidate_json),
        )

    c.commit()
    c.close()

def tokens(text):
    return {
        x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]*", text.lower())
        if x not in STOPWORDS
    }


def extract_salary(text):
    vals = []
    patterns = [
        r"(?:₹|rs\.?|inr\s*)?\s*(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*l(?:pa|akh)?",
        r"(?:₹|rs\.?|inr\s*)?\s*(\d+(?:\.\d+)?)\s*lpa",
    ]
    for idx, pattern in enumerate(patterns):
        for m in re.finditer(pattern, text, re.I):
            vals.extend([float(m.group(1)), float(m.group(2))] if idx == 0 else [float(m.group(1))])
    return (min(vals), max(vals)) if vals else (None, None)


def extract_experience(text):
    vals = [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", text, re.I)]
    return min(vals) if vals else None


def score_job(j):
    text = ((j.get("title") or "") + " " + (j.get("description") or "")).lower()
    title = (j.get("title") or "").lower()
    score = 0
    reasons, matched = [], []
    role_hit = False

    requested = (j.get("_query") or "").strip().lower()
    requested_tokens = tokens(requested)
    title_tokens = tokens(title)
    query_overlap = len(requested_tokens & title_tokens) if requested_tokens else 0

    for role, keywords in ROLE_KEYWORDS.items():
        if any(k in title for k in keywords):
            role_hit = True
            score += 36 if role in CANDIDATE["roles_primary"] else 18
            reasons.append(f"Role matches {role}")
            break

    if not role_hit and requested_tokens:
        overlap_ratio = query_overlap / max(1, len(requested_tokens))
        role_words = {"qa", "quality", "assurance", "automation", "automated", "tester", "testing", "test", "sdet", "software"}
        title_role_overlap = len(title_tokens & role_words)
        if overlap_ratio >= 0.5 and title_role_overlap >= 2:
            role_hit = True
            score += 30
            reasons.append("Title closely matches requested role")

    if not role_hit:
        return 0, ["Role does not match configured targets"], []

    exp = j.get("experience_min")
    if exp is not None:
        if exp <= CANDIDATE["experience_years"] + 1:
            score += 20
            reasons.append("Experience requirement is within configured range")
        else:
            return 0, [f"Experience requirement {exp:g}+ years exceeds limit"], []

    loc = (j.get("location") or "").lower()
    mode = (j.get("work_mode") or "").lower()
    loc_ok = (
        any(x.lower() in loc for x in CANDIDATE["locations"] if x.lower() not in {"india", "remote"})
        or "remote" in loc or "india" in loc or not loc
    )
    if not loc_ok:
        return 0, ["Location is outside preferences"], []

    score += 15
    reasons.append("Location matches preferences")

    if not mode or "hybrid" in mode or "remote" in mode:
        score += 8

    smax = j.get("salary_max")
    if smax is not None and smax < CANDIDATE["minimum_ctc_lpa"]:
        return 0, ["Salary is below minimum threshold"], []
    if smax is not None:
        score += 15 if smax >= CANDIDATE["expected_ctc_min_lpa"] else 8
        reasons.append("Salary meets minimum threshold")
    else:
        score += 3
        reasons.append("Salary not disclosed; needs verification")

    jt = tokens(text)
    for skill in CANDIDATE["skills"]:
        if skill.lower() in jt or skill.lower().replace(" ", "-") in jt:
            matched.append(skill)

    score += min(12, len(matched))
    reasons.append(f"{len(matched)} relevant skills detected")
    return min(100, score), reasons, matched


def job_fingerprint(job):
    raw = "|".join([
        (job.get("company") or "").strip().lower(),
        (job.get("title") or "").strip().lower(),
        (job.get("url") or "").strip().lower(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def make_answers(job):
    title, company = job["title"], job["company"]
    return {
        "why_interested": f"I’m interested in the {title} opportunity at {company} because it aligns with my hands-on experience in QA automation, Playwright, API validation, mobile testing and AI-assisted testing. In my current QA role, I work across functional, regression, integration and end-to-end testing and build reusable automation workflows.",
        "why_hire": "I bring hands-on experience across manual and automation testing, with practical exposure to Playwright, JavaScript/TypeScript, Appium, API validation, SQL, CI/CD and real-device testing. I also use AI-assisted workflows for test design, automation development, debugging and edge-case analysis while validating the output against requirements.",
        "expected_salary": "₹4–5 LPA, negotiable based on the role, responsibilities, overall compensation and growth opportunity.",
        "relocation": "Yes. I am open to relocating for the right opportunity, particularly to Bengaluru or Pune.",
        "sponsorship": "No.",
        "join": "I currently have a 45-day notice period.",
        "automation_experience": "Around 1 year of hands-on QA automation experience using Playwright with JavaScript/TypeScript and Page Object Model, plus Appium for Android and iOS mobile automation. I have also worked with API validation, SQL/database validation, cross-browser/device testing and end-to-end workflows.",
        "playwright_experience": "Approximately 1 year of hands-on experience.",
        "selenium_experience": "I do not currently list professional Selenium experience on my resume.",
        "authorized_india": "Yes.",
    }


def build_search_links(query, location="", remote=False):
    # Kept only for backwards-compatible API consumers. Discovery itself is now
    # performed server-side by authorized job APIs and configured feeds.
    return {
        "mode": "in_app",
        "query": query.strip() or "QA Automation Engineer",
        "location": location.strip() or "India",
        "remote": bool(remote),
        "note": "ApplyBot performs discovery inside the application using authorized APIs and configured feeds."
    }


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").replace("&nbsp;", " ").strip()


def parse_salary_text(text):
    if not text:
        return None, None
    numbers = []
    for raw in re.findall(r"(\d[\d,]*(?:\.\d+)?)", text.replace(",", "")):
        try:
            numbers.append(float(raw))
        except ValueError:
            pass
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def fetch_json(url, params=None):
    from urllib.parse import urlencode
    target = url
    if params:
        target += ("&" if "?" in target else "?") + urlencode(params)
    req = urllib.request.Request(
        target,
        headers={
            "User-Agent": "ApplyBot/1.0 (+in-app job discovery)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url, payload, headers=None, timeout=120):
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"User-Agent": "ApplyBot/2.0 (+live LinkedIn job discovery)", "Accept": "application/json", "Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _first_value(raw, *keys):
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return ""


def normalize_linkedin_jobs(data):
    rows = data if isinstance(data, list) else (data.get("data") or data.get("results") or data.get("items") or [])
    jobs = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(_first_value(raw, "jobTitle", "job_title", "title", "position")).strip()
        company = str(_first_value(raw, "companyName", "company_name", "company")).strip()
        location = str(_first_value(raw, "location", "jobLocation", "job_location")).strip()
        description = strip_html(str(_first_value(raw, "jobDescription", "description", "job_description")))
        linkedin_url = str(_first_value(raw, "jobUrl", "job_url", "linkedinUrl", "linkedin_url", "url")).strip()
        apply_url = str(_first_value(raw, "applyUrl", "apply_url", "applicationUrl", "application_url")).strip()
        if not title or not company or not linkedin_url:
            continue
        salary_text = str(_first_value(raw, "salary", "salaryInfo", "salary_range", "salaryRange")).strip()
        smin, smax = extract_salary(description + " " + salary_text)
        if smin is None and smax is None:
            smin, smax = parse_salary_text(salary_text)
        exp = extract_experience(description + " " + str(_first_value(raw, "experienceLevel", "experience", "yearsOfExperience")).strip())
        if isinstance(raw.get("yearsOfExperience"), list) and raw["yearsOfExperience"]:
            try:
                exp = float(re.search(r"\d+(?:\.\d+)?", str(raw["yearsOfExperience"][0])).group())
            except Exception:
                pass
        remote_value = str(_first_value(raw, "isRemote", "remote", "workplaceType", "workplace_type", "workType")).lower()
        work_mode = "Remote" if "remote" in remote_value or "remote" in (location + " " + description).lower() else ""
        external_id = str(_first_value(raw, "jobId", "job_id", "linkedin_job_id", "id")).strip()
        usable_apply = apply_url if apply_url and "linkedin.com/jobs" not in apply_url.lower() else ""
        jobs.append({
            "external_id": "linkedin:" + (external_id or job_fingerprint({"company": company, "title": title, "url": linkedin_url})),
            "source": "LinkedIn",
            "source_url": linkedin_url,
            "title": title, "company": company, "location": location, "work_mode": work_mode,
            "salary_min": smin, "salary_max": smax, "experience_min": exp,
            "url": usable_apply or linkedin_url, "description": description or title,
            "application_url": usable_apply,
            "application_type": str(_first_value(raw, "applyType", "applicationType")).strip(),
            "posted_at": str(_first_value(raw, "postedAt", "postedDate", "publishedAt", "posted_date")).strip(),
            "employment_type": str(_first_value(raw, "employmentType", "contractType", "job_type")).strip(),
            "seniority": str(_first_value(raw, "seniorityLevel", "experienceLevel", "seniority")).strip(),
        })
    return jobs


def normalize_jobicy_jobs(data):
    jobs = []
    rows = data.get("jobs", []) if isinstance(data, dict) else []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("jobTitle") or "").strip()
        company = str(raw.get("companyName") or "Unknown").strip()
        url = str(raw.get("url") or "").strip()
        if not title or not company or not url:
            continue
        description = strip_html(raw.get("jobDescription") or raw.get("jobExcerpt") or "")
        salary_min, salary_max = raw.get("salaryMin"), raw.get("salaryMax")
        try:
            salary_min = float(salary_min) if salary_min is not None else None
            salary_max = float(salary_max) if salary_max is not None else None
        except (TypeError, ValueError):
            salary_min, salary_max = None, None
        currency = str(raw.get("salaryCurrency") or "").upper()
        if currency != "INR":
            salary_min = salary_max = None
        if salary_min is not None:
            salary_min /= 100000
        if salary_max is not None:
            salary_max /= 100000
        location = str(raw.get("jobGeo") or "Anywhere").strip()
        jobs.append({
            "external_id": "jobicy:" + str(raw.get("id") or raw.get("jobSlug") or url),
            "source": "Jobicy",
            "source_url": url,
            "title": title,
            "company": company,
            "location": location,
            "work_mode": "Remote",
            "salary_min": salary_min,
            "salary_max": salary_max,
            "experience_min": extract_experience(description),
            "url": url,
            "description": description or title,
            "employment_type": ", ".join(str(x) for x in (raw.get("jobType") or [])),
            "posted_at": str(raw.get("pubDate") or "").strip(),
        })
    return jobs


def _jobicy_geo(location):
    value = (location or "").strip().lower()
    if not value:
        return ""
    if "remote" in value or value in {"anywhere", "worldwide", "global"}:
        return "anywhere"
    country_map = {
        "india": "india", "united states": "usa", "usa": "usa", "us": "usa",
        "united kingdom": "uk", "uk": "uk", "canada": "canada",
        "australia": "australia", "europe": "europe", "asia": "asia", "apac": "apac",
    }
    for name, slug in country_map.items():
        if name in value:
            return slug
    return ""


def search_jobicy_jobs(query, location="", remote=False):
    params = {"count": JOBICY_COUNT, "tag": query.strip() or "QA Automation Engineer"}
    geo = _jobicy_geo(location)
    if remote:
        params["geo"] = "anywhere"
    elif geo:
        params["geo"] = geo
    try:
        data = fetch_json(JOBICY_API_URL, params)
        rows = normalize_jobicy_jobs(data)
        filtered = []
        location_value = (location or "").lower()
        for job in rows:
            hay = (job.get("location") or "").lower()
            if location_value and not remote:
                if location_value not in hay and "anywhere" not in hay and "remote" not in hay:
                    continue
            job["_query"] = query
            filtered.append(job)
        return filtered, [], [{"source": "Jobicy", "found": len(filtered), "configured": True, "provider": "Jobicy Public REST API"}]
    except Exception as exc:
        return [], [{"source": "Jobicy", "error": str(exc)[:1000]}], [{"source": "Jobicy", "found": 0, "configured": True, "provider": "Jobicy Public REST API"}]


def normalize_remotive_jobs(data):
    jobs = []
    for raw in data.get("jobs", []):
        description = strip_html(raw.get("description", ""))
        salary_text = raw.get("salary", "") or ""
        # Remotive salary values are generally USD. Do not store them in the
        # LPA fields, otherwise the matcher/UI could mistake USD amounts for INR LPA.
        if re.search(r"(₹|INR|LPA|LAKH)", salary_text, re.I):
            smin, smax = parse_salary_text(salary_text)
        else:
            smin, smax = None, None
        jobs.append({
            "external_id": "remotive:" + str(raw.get("id", "")),
            "source": "Remotive",
            "title": (raw.get("title") or "").strip(),
            "company": (raw.get("company_name") or "Unknown").strip(),
            "location": (raw.get("candidate_required_location") or "Remote").strip(),
            "work_mode": "Remote",
            "salary_min": smin,
            "salary_max": smax,
            "url": raw.get("url", ""),
            "description": description,
        })
    return jobs


def normalize_adzuna_jobs(data):
    jobs = []
    for raw in data.get("results", []):
        description = strip_html(raw.get("description", ""))
        salary = raw.get("salary_is_predicted")
        smin = raw.get("salary_min")
        smax = raw.get("salary_max")
        # Adzuna's country endpoint returns local-currency salary values.
        if smin is not None:
            smin = float(smin) / 100000
        if smax is not None:
            smax = float(smax) / 100000
        jobs.append({
            "external_id": "adzuna:" + str(raw.get("id", "")),
            "source": "Adzuna",
            "title": (raw.get("title") or "").strip(),
            "company": (raw.get("company", {}).get("display_name") if isinstance(raw.get("company"), dict) else raw.get("company") or "Unknown").strip(),
            "location": (raw.get("location", {}).get("display_name") if isinstance(raw.get("location"), dict) else raw.get("location") or "").strip(),
            "work_mode": "Remote" if "remote" in (description + " " + str(raw.get("title", ""))).lower() else "",
            "salary_min": smin,
            "salary_max": smax,
            "url": raw.get("redirect_url") or raw.get("url", ""),
            "description": description,
            "salary_predicted": bool(salary),
        })
    return jobs


def normalize_greenhouse_jobs(data, board):
    jobs = []
    for raw in data.get("jobs", []):
        description = strip_html(raw.get("content", ""))
        location = ((raw.get("location") or {}).get("name") if isinstance(raw.get("location"), dict) else raw.get("location") or "")
        jobs.append({
            "external_id": "greenhouse:" + board + ":" + str(raw.get("id", "")),
            "source": "Greenhouse:" + board,
            "title": (raw.get("title") or "").strip(),
            "company": board,
            "location": str(location).strip(),
            "work_mode": "Remote" if "remote" in (str(location) + " " + description).lower() else "",
            "salary_min": None,
            "salary_max": None,
            "url": raw.get("absolute_url") or "",
            "description": description,
        })
    return jobs


def normalize_lever_jobs(data, company):
    jobs = []
    rows = data if isinstance(data, list) else data.get("data", [])
    for raw in rows:
        categories = raw.get("categories") or {}
        location = categories.get("location") or raw.get("location") or ""
        description = strip_html((raw.get("descriptionPlain") or raw.get("description") or raw.get("content") or ""))
        urls = raw.get("urls") or {}
        jobs.append({
            "external_id": "lever:" + company + ":" + str(raw.get("id", "")),
            "source": "Lever:" + company,
            "title": (raw.get("text") or raw.get("position") or raw.get("title") or "").strip(),
            "company": company,
            "location": str(location).strip(),
            "work_mode": str(raw.get("workplaceType") or ("Remote" if "remote" in (str(location) + " " + description).lower() else "")),
            "salary_min": None,
            "salary_max": None,
            "url": urls.get("apply") or urls.get("show") or raw.get("hostedUrl") or raw.get("url") or "",
            "description": description,
        })
    return jobs


def normalize_arbeitnow_jobs(data):
    jobs = []
    for raw in data.get("data", []):
        description = strip_html(raw.get("description", ""))
        jobs.append({
            "external_id": "arbeitnow:" + str(raw.get("slug") or raw.get("id") or raw.get("url", "")),
            "source": "Arbeitnow",
            "title": (raw.get("title") or "").strip(),
            "company": (raw.get("company_name") or raw.get("company") or "Unknown").strip(),
            "location": (raw.get("location") or "").strip(),
            "work_mode": "Remote" if raw.get("remote") else "",
            "salary_min": None,
            "salary_max": None,
            "url": raw.get("url", ""),
            "description": description,
        })
    return jobs


def location_matches(job, location, remote=False):
    requested = (location or "").strip().lower()
    text = ((job.get("location") or "") + " " + (job.get("description") or "")).lower()
    if remote and job.get("work_mode", "").lower() == "remote":
        return True
    if not requested:
        return True
    if requested in {"india", "ind"}:
        return any(x in text for x in ["india", "indian", "bangalore", "bengaluru", "pune", "hyderabad", "mumbai", "delhi", "noida", "gurugram", "gurgaon", "chennai", "indore"])
    return requested in text


def search_public_sources(query, location="", remote=False):
    query = (query or "").strip() or "QA Automation Engineer"
    results, errors, source_status = search_jobicy_jobs(query, location, remote)
    if ENABLE_LEGACY_SOURCES:
        if ADZUNA_APP_ID and ADZUNA_APP_KEY:
            try:
                data = fetch_json("https://api.adzuna.com/v1/api/jobs/in/search/1", {
                    "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY, "results_per_page": "50",
                    "what": query, "where": location or "India", "content-type": "application/json", "sort_by": "date",
                })
                rows = normalize_adzuna_jobs(data); results.extend(rows)
                source_status.append({"source": "Adzuna", "found": len(rows), "configured": True})
            except Exception as exc:
                errors.append({"source": "Adzuna", "error": str(exc)})
                source_status.append({"source": "Adzuna", "found": 0, "configured": True})
        else:
            source_status.append({"source": "Adzuna", "found": 0, "configured": False})
        for board in GREENHOUSE_BOARDS:
            try:
                rows = normalize_greenhouse_jobs(fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", {"content": "true"}), board)
                results.extend(rows); source_status.append({"source": "Greenhouse:" + board, "found": len(rows), "configured": True})
            except Exception as exc: errors.append({"source": "Greenhouse:" + board, "error": str(exc)})
        for company in LEVER_COMPANIES:
            try:
                rows = normalize_lever_jobs(fetch_json(f"https://api.lever.co/v0/postings/{company}", {"mode": "json"}), company)
                results.extend(rows); source_status.append({"source": "Lever:" + company, "found": len(rows), "configured": True})
            except Exception as exc: errors.append({"source": "Lever:" + company, "error": str(exc)})
        try:
            rows = normalize_remotive_jobs(fetch_json("https://remotive.com/api/remote-jobs", {"search": query, "limit": "50"}))
            results.extend(rows); source_status.append({"source": "Remotive", "found": len(rows), "configured": True})
        except Exception as exc: errors.append({"source": "Remotive", "error": str(exc)})
        try:
            arbeit = normalize_arbeitnow_jobs(fetch_json("https://www.arbeitnow.com/api/job-board-api"))
            q_tokens = tokens(query)
            for job in arbeit:
                haystack = (job["title"] + " " + job["description"]).lower()
                if not q_tokens or sum(1 for token in q_tokens if token in haystack) >= max(1, min(3, len(q_tokens))):
                    results.append(job)
            source_status.append({"source": "Arbeitnow", "found": len(arbeit), "configured": True})
        except Exception as exc: errors.append({"source": "Arbeitnow", "error": str(exc)})
    filtered, seen = [], set()
    for job in results:
        if not job.get("title") or not job.get("company") or not job.get("url"): continue
        if location and job.get("source") != "Jobicy" and not location_matches(job, location, remote): continue
        key = job.get("external_id") or job_fingerprint(job)
        if key in seen: continue
        seen.add(key); job["_query"] = query; filtered.append(job)
    return filtered, errors, source_status

def import_job_items(items):
    c = db()
    created = []
    for j in items:
        if not all(j.get(k) for k in ["title", "company", "url", "description"]):
            continue
        ext = j.get("external_id") or job_fingerprint(j)
        smin, smax = j.get("salary_min"), j.get("salary_max")
        if smin is None and smax is None:
            smin, smax = extract_salary(j["description"])
        exp = j.get("experience_min")
        if exp is None:
            exp = extract_experience(j["description"])
        base = {**j, "salary_min": smin, "salary_max": smax, "experience_min": exp}
        sc, reasons, matched = score_job(base)
        status = "ready" if sc > 0 else "skipped"
        try:
            c.execute(
                """INSERT INTO jobs(external_id,source,title,company,location,work_mode,salary_min,salary_max,
                experience_min,source_url,url,description,discovered_at,match_score,status,skip_reason,match_reasons,matched_skills)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ext, j.get("source", "manual"), j["title"], j["company"], j.get("location", ""),
                 j.get("work_mode", ""), smin, smax, exp, j.get("source_url", j["url"]), j["url"], j["description"], utcnow(), sc, status,
                 "; ".join(reasons), json.dumps(reasons), json.dumps(matched)),
            )
            inserted = c.execute("SELECT id FROM jobs WHERE external_id=?", (ext,)).fetchone()
            created.append({"job_id": inserted["id"] if inserted else None, "external_id": ext, "score": sc, "status": status, "matched_skills": matched, "reasons": reasons})
        except Exception as exc:
            if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                raise
            existing = c.execute("SELECT id FROM jobs WHERE external_id=?", (ext,)).fetchone()
            if existing:
                created.append({"job_id": existing["id"], "external_id": ext, "score": sc, "status": status,
                                 "matched_skills": matched, "reasons": reasons, "duplicate": True})
    c.commit()
    c.close()
    return created


@app.get("/")
def index():
    return send_from_directory(BASE / "web", "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ApplyBot", "database": "postgres" if is_postgres() else "sqlite", "time": utcnow()}


@app.get("/api/profile")
def profile():
    return jsonify(CANDIDATE)


@app.get("/api/search-links")
def search_links():
    query = request.args.get("query", "QA Automation Engineer")
    location = request.args.get("location", "India")
    remote = request.args.get("remote", "false").lower() == "true"
    return jsonify(build_search_links(query, location, remote))


def run_discovery(body):
    query = str(body.get("query") or "QA Automation Engineer").strip()
    location = str(body.get("location") or "India").strip()
    remote = bool(body.get("remote", False))
    threshold = float(body.get("threshold", 70))
    max_experience = float(body.get("max_experience", 2))
    min_salary = max(float(body.get("min_salary", 3)), CANDIDATE["minimum_ctc_lpa"])
    items, errors, source_status = search_public_sources(query, location, remote)
    results = import_job_items(items)

    c = db()
    qualified = []
    for r in results:
        row = c.execute("SELECT experience_min,salary_max FROM jobs WHERE id=?", (r.get("job_id"),)).fetchone()
        exp_ok = not row or row["experience_min"] is None or float(row["experience_min"]) <= max_experience
        salary_ok = not row or row["salary_max"] is None or float(row["salary_max"]) >= min_salary
        if float(r.get("score") or 0) >= threshold and exp_ok and salary_ok:
            qualified.append(r)
    c.close()

    return {
        "mode": "in_app",
        "query": query,
        "location": location,
        "remote": remote,
        "threshold": threshold,
        "max_experience": max_experience,
        "min_salary": min_salary,
        "sources_checked": source_status,
        "items_seen": len(items),
        "new_jobs": len(results),
        "qualified_jobs": len(qualified),
        "errors": errors,
        "results": results,
    }


@app.post("/api/discover/search")
def discover_search():
    return jsonify(run_discovery(request.get_json(silent=True) or {}))


@app.post("/api/discover")
def discover():
    return jsonify(run_discovery(request.get_json(silent=True) or {}))


@app.post("/api/resume")
def upload_resume():
    uploaded = request.files.get("resume")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Resume file is required"}), 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF resumes are accepted"}), 400
    target = DATA / "resume.pdf"
    uploaded.save(target)
    return jsonify({"ok": True, "message": "Resume uploaded for this ApplyBot instance."})


@app.get("/api/config")
def config_status():
    return jsonify({
        "auto_apply_enabled": AUTO_APPLY_ENABLED,
        "auto_apply_max": AUTO_APPLY_MAX,
        "candidate_email_configured": bool(CANDIDATE_EMAIL),
        "candidate_phone_configured": bool(CANDIDATE_PHONE),
        "resume_configured": resume_file_path().is_file(),
        "supported_browser_adapters": ["greenhouse", "lever"],
        "discovery_sources": {
            "Jobicy": True,
            "Jobicy_provider": "Jobicy Public REST API",
            "legacy_sources_enabled": ENABLE_LEGACY_SOURCES,
            "Adzuna": bool(ADZUNA_APP_ID and ADZUNA_APP_KEY),
            "Greenhouse": len(GREENHOUSE_BOARDS),
            "Lever": len(LEVER_COMPANIES),
            "Remotive": ENABLE_LEGACY_SOURCES,
            "Arbeitnow": ENABLE_LEGACY_SOURCES,
        },
        "note": "Discovery uses live APIs where configured. Automatic submission is limited to supported employer ATS forms."
    })


@app.get("/api/jobs")
def jobs():
    c = db()
    rows = c.execute("SELECT * FROM jobs ORDER BY match_score DESC, discovered_at DESC").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/jobs/import")
def import_jobs():
    return jsonify({"imported": len((created := import_job_items((request.get_json(silent=True) or {}).get("jobs", [])))), "results": created})


@app.post("/api/jobs/manual")
def manual_job():
    body = request.get_json(silent=True) or {}
    required = ["title", "company", "url", "description"]
    missing = [k for k in required if not str(body.get(k, "")).strip()]
    if missing:
        return jsonify({"error": "Missing required fields: " + ", ".join(missing)}), 400
    job = {
        "external_id": body.get("external_id") or body["url"],
        "source": body.get("source", "user-assisted"),
        "title": body["title"].strip(),
        "company": body["company"].strip(),
        "location": body.get("location", "").strip(),
        "work_mode": body.get("work_mode", "").strip(),
        "salary_min": body.get("salary_min"),
        "salary_max": body.get("salary_max"),
        "experience_min": body.get("experience_min"),
        "url": body["url"].strip(),
        "description": body["description"].strip(),
    }
    result = import_job_items([job])
    return jsonify({"imported": len(result), "results": result})


def detect_application_adapter(url):
    host = (urlparse(url).hostname or "").lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    return "unsupported"


def _fill_first(page, selectors, value):
    if not value:
        return False
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.fill(value)
                return True
        except Exception:
            pass
    return False


def _fill_label(page, patterns, value):
    if not value:
        return False
    for pattern in patterns:
        try:
            loc = page.get_by_label(re.compile(pattern, re.I)).first
            if loc.count() and loc.is_visible():
                loc.fill(value)
                return True
        except Exception:
            pass
    return False


def resolve_jobicy_application_url(job_url):
    if not job_url or "jobicy.com" not in (urlparse(job_url).hostname or "").lower():
        return job_url, None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(800)
            links = page.locator("a[href]")
            for i in range(links.count()):
                a = links.nth(i)
                try:
                    href = a.get_attribute("href") or ""
                    label = (a.inner_text() or "").strip().lower()
                    host = (urlparse(href).hostname or "").lower()
                    if href.startswith("http") and "jobicy.com" not in host and re.search(r"\b(apply|application|apply now|career|careers)\b", label, re.I):
                        browser.close()
                        return href, "Resolved external employer application URL from Jobicy"
                except Exception:
                    continue
            browser.close()
    except Exception as exc:
        return job_url, "Jobicy application-link resolution failed: " + str(exc)[:400]
    return job_url, "Jobicy listing did not expose a supported external application URL"


def submit_with_browser(job, answers):
    application_url = job["url"]
    resolution_message = None
    if job.get("source") == "Jobicy":
        application_url, resolution_message = resolve_jobicy_application_url(job["url"])
        if application_url != job["url"]:
            job = {**job, "url": application_url}
    adapter = detect_application_adapter(application_url)
    if job.get("source") == "Remotive":
        return {"status": "unsupported_source_policy", "adapter": adapter,
                "message": "Remotive public API terms do not permit submitting its listings to third-party sites. This listing can be reviewed, but ApplyBot will not auto-submit it."}
    if adapter == "unsupported":
        message = "No supported Greenhouse or Lever employer application URL was found."
        if resolution_message:
            message += " " + resolution_message + "."
        return {"status": "unsupported", "adapter": adapter, "message": message}
    if not CANDIDATE_EMAIL or not CANDIDATE_PHONE:
        return {"status": "requires_configuration", "adapter": adapter,
                "message": "Configure CANDIDATE_EMAIL, CANDIDATE_PHONE and RESUME_PATH."}
    if not resume_file_path().is_file():
        return {"status": "requires_configuration", "adapter": adapter,
                "message": "Configured resume file does not exist."}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "requires_configuration", "adapter": adapter,
                "message": "Playwright is not installed."}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            body_text = page.locator("body").inner_text(timeout=10000)
            challenge = page.locator(
                'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], [id*="captcha"], [class*="captcha"]'
            )
            if challenge.count() or re.search(
                r"\b(captcha|verify you are human|cloudflare challenge)\b", body_text, re.I
            ):
                browser.close()
                return {"status": "requires_user_action", "adapter": adapter,
                        "message": "CAPTCHA/human verification detected; submission stopped without bypassing it."}

            first, last = CANDIDATE["name"].split(" ", 1)[0], CANDIDATE["name"].split(" ")[-1]
            _fill_first(page, ['input[name*="first" i]', 'input[id*="first" i]'], first)
            _fill_first(page, ['input[name*="last" i]', 'input[id*="last" i]'], last)
            _fill_first(page, ['input[type="email"]', 'input[name*="email" i]'], CANDIDATE_EMAIL)
            _fill_first(page, ['input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]'], CANDIDATE_PHONE)

            files = page.locator('input[type="file"]')
            if files.count():
                files.first.set_input_files(str(resume_file_path()))

            cover = answers.get("cover_letter", "")
            _fill_label(page, [r"cover letter", r"additional information", r"message"], cover)
            _fill_first(page, ['textarea[name*="cover" i]', 'textarea[id*="cover" i]'], cover)

            for patterns, value in [
                ([r"why.*interested", r"why.*want"], answers.get("why_interested")),
                ([r"automation.*experience", r"experience.*automation"], answers.get("automation_experience")),
                ([r"playwright"], answers.get("playwright_experience")),
                ([r"salary", r"compensation"], answers.get("expected_salary")),
                ([r"notice", r"join"], answers.get("join")),
                ([r"relocat"], answers.get("relocation")),
                ([r"authorized", r"work authorization"], answers.get("authorized_india")),
            ]:
                _fill_label(page, patterns, value)

            required = page.locator("input[required], textarea[required], select[required]")
            missing = []
            for i in range(required.count()):
                el = required.nth(i)
                try:
                    if el.is_visible() and not el.input_value():
                        missing.append(el.evaluate("(e) => e.tagName.toLowerCase()"))
                except Exception:
                    pass
            if missing:
                browser.close()
                return {"status": "requires_user_action", "adapter": adapter,
                        "message": f"{len(missing)} required field(s) remain unanswered; ApplyBot will not guess."}

            submit = page.get_by_role("button", name=re.compile(r"submit application|submit|apply", re.I)).last
            if not submit.count():
                submit = page.locator('input[type="submit"], button[type="submit"]').last
            if not submit.count() or not submit.is_visible():
                browser.close()
                return {"status": "requires_user_action", "adapter": adapter,
                        "message": "No unambiguous submit control was found."}

            submit.click()
            page.wait_for_timeout(2500)
            confirmation = page.locator("body").inner_text(timeout=10000)
            browser.close()
            if re.search(r"(application.*(submitted|received)|thank you.*apply|successfully applied)", confirmation, re.I):
                return {"status": "submitted", "adapter": adapter,
                        "message": "Application submitted and confirmation text was detected."}
            return {"status": "submitted", "adapter": adapter,
                    "message": "Submit action completed; no standard confirmation phrase was detected."}
    except Exception as exc:
        return {"status": "failed", "adapter": adapter, "message": str(exc)[:1000]}



def auto_apply_job(job_id, threshold=70, max_experience=2, min_salary=3):
    c = db()
    row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    c.close()
    if not row:
        return {"status": "not_found", "submitted": False, "message": "Job was not found."}
    job = dict(row)
    score = float(job.get("match_score") or 0)
    if score < float(threshold):
        return {"status": "below_threshold", "submitted": False, "message": f"Match score {score:.0f}% is below the {float(threshold):.0f}% threshold."}
    exp = job.get("experience_min")
    if exp is not None and float(exp) > float(max_experience):
        return {"status": "experience_exceeds_limit", "submitted": False, "message": f"Required experience {float(exp):g}+ years exceeds the configured limit."}
    salary = job.get("salary_max")
    if salary is not None and float(salary) < float(min_salary):
        return {"status": "salary_below_minimum", "submitted": False, "message": "Published salary is below the configured minimum."}
    if not AUTO_APPLY_ENABLED:
        return {"status": "application_ready", "submitted": False, "message": "Qualified, but automatic submission is disabled."}
    result = submit_with_browser(job, make_answers(job))
    status = result.get("status", "failed")
    now = utcnow()
    c = db()
    c.execute(
        """INSERT INTO applications(job_id,tailored_summary,cover_letter,answers_json,status,created_at,updated_at,adapter,submission_id,submission_message,submitted_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, job["title"], make_answers(job).get("why_interested", ""), json.dumps(make_answers(job)),
         "applied" if status == "submitted" else status, now, now, result.get("adapter"),
         result.get("submission_id"), result.get("message"), now if status == "submitted" else None)
    )
    if status == "submitted":
        c.execute("UPDATE jobs SET status=? WHERE id=?", ("applied", job_id))
    c.commit()
    app_row = c.execute("SELECT id FROM applications WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    c.close()
    return {"status": "applied" if status == "submitted" else status, "submitted": status == "submitted",
            "application_id": app_row["id"] if app_row else None, "adapter": result.get("adapter"), "message": result.get("message")}


@app.post("/api/jobs/<int:job_id>/auto-apply")
def auto_apply(job_id):
    body = request.get_json(silent=True) or {}
    try:
        threshold = float(body.get("threshold", 70))
        max_experience = float(body.get("max_experience", 2))
        min_salary = max(float(body.get("min_salary", 3)), CANDIDATE["minimum_ctc_lpa"])
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid threshold, experience or salary value."}), 400
    return jsonify(auto_apply_job(job_id, threshold, max_experience, min_salary))


@app.get("/api/applications")
def applications():
    c = db()
    rows = c.execute("SELECT a.*, j.title, j.company FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.id DESC").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/applications/<int:application_id>/status")
def application_status(application_id):
    body = request.get_json(silent=True) or {}
    status = str(body.get("status") or "").strip()
    allowed = {"draft","application_ready","requires_user_action","requires_configuration","failed","applied","rejected","interview","offer","closed"}
    if status not in allowed:
        return jsonify({"error": "Invalid application status."}), 400
    c = db()
    c.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (status, utcnow(), application_id))
    c.commit(); c.close()
    return jsonify({"ok": True, "status": status})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=os.getenv("DEBUG", "false").lower() == "true")
