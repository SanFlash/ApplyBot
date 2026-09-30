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
JOBVETTA_API_KEY = os.getenv("JOBVETTA_API_KEY", "").strip()
JOBVETTA_API_URL = os.getenv("JOBVETTA_API_URL", "https://api.jobvetta.com/v1/jobs").strip()
INDIANAPI_KEY = os.getenv("INDIANAPI_KEY", "").strip()
INDIANAPI_URL = os.getenv("INDIANAPI_URL", "https://jobs.indianapi.in/jobs").strip()
THEMUSE_API_KEY = os.getenv("THEMUSE_API_KEY", "").strip()
THEMUSE_ENABLED = os.getenv("THEMUSE_ENABLED", "false").lower() == "true"
AI_PROVIDER = os.getenv("AI_PROVIDER", "none").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
REMOTEOK_ENABLED = os.getenv("REMOTEOK_ENABLED", "true").lower() == "true"
JOBICY_API_URL = os.getenv("JOBICY_API_URL", "https://jobicy.com/api/v2/remote-jobs").strip()
JOBICY_API_KEY = os.getenv("JOBICY_API_KEY", "").strip()
JOBICY_COUNT = min(200, max(1, int(os.getenv("JOBICY_COUNT", "200"))))
JOBICY_TIMEOUT = max(5, int(os.getenv("JOBICY_TIMEOUT", "12")))
FETCH_RETRIES = min(3, max(1, int(os.getenv("FETCH_RETRIES", "2"))))

# Indeed RapidAPI provider. Keep the key server-side; never expose it to the browser.
INDEED_RAPIDAPI_KEY = os.getenv("INDEED_RAPIDAPI_KEY", "").strip()
INDEED_RAPIDAPI_HOST = os.getenv("INDEED_RAPIDAPI_HOST", "indeed-jobs-api.p.rapidapi.com").strip()
INDEED_RAPIDAPI_URL = os.getenv("INDEED_RAPIDAPI_URL", "https://indeed-jobs-api.p.rapidapi.com").strip().rstrip("/")
INDEED_RAPIDAPI_PATH = os.getenv("INDEED_RAPIDAPI_PATH", "/jobs").strip() or "/jobs"
INDEED_RAPIDAPI_ENABLED = os.getenv("INDEED_RAPIDAPI_ENABLED", "true").lower() == "true"
INDEED_MAX_PAGES = min(5, max(1, int(os.getenv("INDEED_MAX_PAGES", "1"))))
INDEED_MAX_QUERIES = min(5, max(1, int(os.getenv("INDEED_MAX_QUERIES", "2"))))
INDEED_DATE_POSTED = os.getenv("INDEED_DATE_POSTED", "").strip()
# The provider documents salaryMin/salaryMax as USD. Leave conversion disabled by
# default so USD values can never be mistaken for INR/LPA. Set a trusted rate in
# Render and enable it if you want salary-based qualification for Indeed results.
INDEED_CONVERT_USD_SALARY = os.getenv("INDEED_CONVERT_USD_SALARY", "false").lower() == "true"
INDEED_USD_TO_INR = float(os.getenv("INDEED_USD_TO_INR", "0") or 0)
ENABLE_LEGACY_SOURCES = os.getenv("ENABLE_LEGACY_SOURCES", "false").lower() == "true"
GREENHOUSE_BOARDS = [x.strip() for x in os.getenv("GREENHOUSE_BOARDS", "").split(",") if x.strip()]
LEVER_COMPANIES = [x.strip() for x in os.getenv("LEVER_COMPANIES", "").split(",") if x.strip()]
ASHBY_BOARDS = [x.strip() for x in os.getenv("ASHBY_BOARDS", "").split(",") if x.strip()]
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
BRAVE_SEARCH_ENABLED = os.getenv("BRAVE_SEARCH_ENABLED", "true").lower() == "true"

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
    "Software Tester": ["software tester", "qa tester", "test engineer", "qa analyst", "quality analyst"],
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
    """Score jobs from evidence actually published by the source."""
    title = str(j.get("title") or "").strip().lower()
    location = str(j.get("location") or "").strip().lower()
    mode = str(j.get("work_mode") or "").strip().lower()
    description = str(j.get("description") or "").lower()
    department = str(j.get("department") or "").lower()
    requested = str(j.get("_query") or "").strip().lower()

    if not title:
        return 0, ["Missing job title"], []

    reasons, matched = [], []
    score = 0
    role_hit = None
    for role, keywords in ROLE_KEYWORDS.items():
        if any(k in title for k in keywords):
            role_hit = role
            break

    query_tokens = tokens(requested)
    title_tokens = tokens(title)
    query_overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens))
    role_words = {"qa", "quality", "assurance", "automation", "tester", "testing", "test", "sdet"}

    if role_hit:
        score += 55 if role_hit in CANDIDATE["roles_primary"] else 42
        reasons.append(f"Role matches {role_hit}")
    elif query_overlap >= 0.5 and len(title_tokens & role_words) >= 1:
        score += 42
        reasons.append("Title closely matches requested role")
    else:
        return 0, ["Role does not match the configured QA/automation targets"], []

    compatible_locations = (
        "india", "bengaluru", "bangalore", "pune", "hyderabad", "delhi",
        "gurugram", "gurgaon", "noida", "mumbai", "indore", "chennai",
        "kolkata", "remote", "anywhere", "worldwide", "global", "apac", "asia"
    )
    if any(term in location for term in compatible_locations) or not location:
        score += 18
        reasons.append("Location is compatible with the selected search")
    else:
        return 0, ["Location is outside the selected preferences"], []

    if "remote" in mode or "remote" in location:
        score += 5
        reasons.append("Remote work is available")
    elif "hybrid" in mode or "hybrid" in location:
        score += 4
        reasons.append("Hybrid work is available")

    evidence = " ".join((title, department, description))
    for skill in CANDIDATE["skills"]:
        sk = skill.lower()
        variants = {sk, sk.replace(" ", "-"), sk.replace(" ", "/")}
        if any(v in evidence for v in variants):
            matched.append(skill)
    if matched:
        score += min(17, len(matched) * 3)
        reasons.append("Matched skills: " + ", ".join(matched[:7]))
    else:
        reasons.append("No skill evidence published by the source")

    exp = j.get("experience_min")
    if exp is not None:
        if float(exp) <= CANDIDATE["experience_years"] + 1:
            score += 5
            reasons.append("Published experience requirement is within target")
        else:
            return 0, [f"Experience requirement {float(exp):g}+ years exceeds target"], matched

    smax = j.get("salary_max")
    if smax is not None:
        if float(smax) < CANDIDATE["minimum_ctc_lpa"]:
            return 0, ["Published salary is below the configured minimum"], matched
        score += 5
        reasons.append("Published salary meets the configured minimum")
    else:
        reasons.append("Salary not disclosed; kept neutral")

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


def fetch_json(url, params=None, headers=None, timeout=None):
    from urllib.parse import urlencode
    import gzip
    import time
    target = url
    if params:
        target += ("&" if "?" in target else "?") + urlencode(params)
    request_headers = {
        "User-Agent": "ApplyBot/1.1 (+in-app job discovery; live API client)",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache",
        "Connection": "close",
    }
    if headers:
        request_headers.update(headers)
    last_error = None
    for attempt in range(FETCH_RETRIES):
        req = urllib.request.Request(target, headers=request_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or JOBICY_TIMEOUT) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "code", None)
            if status not in (429, 500, 502, 503, 504) or attempt == 2:
                break
            time.sleep(1.5 * (attempt + 1))
    status_code = getattr(last_error, "code", None)
    attempts_made = attempt + 1
    suffix = f" HTTP {status_code}" if status_code else ""
    raise RuntimeError(f"GET {target} failed after {attempts_made} attempt(s){suffix}: {last_error}")


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
            "url": usable_apply or linkedin_url, "description": description or title,            "application_url": usable_apply,
            "application_type": str(_first_value(raw, "applyType", "applicationType")).strip(),
            "posted_at": str(_first_value(raw, "postedAt", "postedDate", "publishedAt", "posted_date")).strip(),
            "employment_type": str(_first_value(raw, "employmentType", "contractType", "job_type")).strip(),
            "seniority": str(_first_value(raw, "seniorityLevel", "experienceLevel", "seniority")).strip(),
        })
    return jobs


def _indeed_salary_to_lpa(salary, salary_type=""):
    """Convert documented Indeed USD salary values to INR LPA only when explicitly enabled."""
    if not INDEED_CONVERT_USD_SALARY or not INDEED_USD_TO_INR or salary is None:
        return None
    try:
        value = float(salary)
    except (TypeError, ValueError):
        return None
    if str(salary_type).upper() == "HOURLY":
        value *= 2080
    return (value * INDEED_USD_TO_INR) / 100000


def _indeed_country(location):
    value = (location or "").strip().lower()
    if not value:
        return "IN"
    mapping = {
        "india": "IN", "ind": "IN", "indore": "IN", "bangalore": "IN", "bengaluru": "IN",
        "pune": "IN", "hyderabad": "IN", "mumbai": "IN", "delhi": "IN", "noida": "IN",
        "gurgaon": "IN", "gurugram": "IN", "chennai": "IN", "remote": "IN",
        "usa": "US", "united states": "US", "us": "US", "uk": "GB", "united kingdom": "GB",
        "canada": "CA", "australia": "AU", "germany": "DE", "france": "FR",
        "singapore": "SG", "uae": "AE",
    }
    for key, country in mapping.items():
        if key in value:
            return country
    return "IN"


def _indeed_search_queries(query):
    requested = (query or "").strip()
    candidates = [requested]
    q = requested.lower()
    if any(x in q for x in ("qa", "quality", "tester", "testing", "test", "automation", "sdet")):
        related = ["QA Automation Engineer", "Automation Tester", "SDET"]
    else:
        related = list(CANDIDATE["roles_primary"][:3])
    existing = {x.lower() for x in candidates}
    for item in related:
        if item.lower() not in existing:
            candidates.append(item)
            existing.add(item.lower())
        if len(candidates) >= INDEED_MAX_QUERIES:
            break
    return [x for x in candidates if x][:INDEED_MAX_QUERIES]


def normalize_indeed_jobs(data):
    rows = data.get("jobs", []) if isinstance(data, dict) else []
    jobs = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        company = str(raw.get("company") or "Unknown").strip()
        location = str(raw.get("location") or "").strip()
        job_key = str(raw.get("jobKey") or "").strip()
        apply_url = str(raw.get("applyUrl") or "").strip()
        employer_url = str(raw.get("thirdPartyApplyUrl") or "").strip()
        url = employer_url or apply_url
        if not title or not company or not url or not job_key:
            continue
        description = strip_html(str(raw.get("snippet") or ""))
        remote_label = str(raw.get("remote") or "").strip()
        remote_text = (remote_label + " " + title + " " + description).lower()
        work_mode = "Remote" if "remote" in remote_text else ("Hybrid" if "hybrid" in remote_text else "")
        salary = raw.get("salary") if isinstance(raw.get("salary"), dict) else {}
        salary_type = str(salary.get("type") or "")
        salary_min = _indeed_salary_to_lpa(salary.get("min"), salary_type)
        salary_max = _indeed_salary_to_lpa(salary.get("max"), salary_type)
        salary_text = str(salary.get("text") or "").strip()
        exp = extract_experience(description)
        jobs.append({
            "external_id": "indeed:" + job_key,
            "source": "Indeed RapidAPI",
            "source_url": apply_url or url,
            "title": title,
            "company": company,
            "location": location,
            "work_mode": work_mode,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_text": salary_text,
            "salary_currency": "USD" if salary_text and not INDEED_CONVERT_USD_SALARY else ("INR" if salary_min is not None else ""),
            "experience_min": exp,
            "url": url,
            "description": description or title,
            "application_url": employer_url,
            "posted_at": str(raw.get("postedAt") or "").strip(),
            "employment_type": ", ".join(str(x) for x in (raw.get("jobTypes") or [])),
            "indeed_apply_enabled": bool(raw.get("indeedApplyEnabled")),
            "is_sponsored": bool(raw.get("isSponsored")),
            "is_urgently_hiring": bool(raw.get("isUrgentlyHiring")),
        })
    return jobs


def _indeed_error_kind(message):
    text = str(message or "").lower()
    if "http error 401" in text or "http error 403" in text or "forbidden" in text or "unauthorized" in text:
        return "authorization"
    if "http error 429" in text or "too many requests" in text:
        return "rate_limit"
    return "provider_error"


def search_indeed_jobs(query, location="", remote=False):
    if not INDEED_RAPIDAPI_ENABLED:
        return [], [], [_provider_status("Indeed", 0, False, "Indeed RapidAPI — disabled")]
    if not INDEED_RAPIDAPI_KEY:
        return [], [], [_provider_status("Indeed", 0, False, "Indeed RapidAPI — API key required")]
    country = _indeed_country(location)
    queries = _indeed_search_queries(query)
    headers = {"X-RapidAPI-Key": INDEED_RAPIDAPI_KEY, "X-RapidAPI-Host": INDEED_RAPIDAPI_HOST}
    results, errors = [], []
    successful_requests = 0
    pages_checked = 0
    auth_error = None
    for search_query in queries:
        for page in range(1, INDEED_MAX_PAGES + 1):
            params = {"query": search_query, "location": "Remote" if remote else (location or "India"), "country": country, "page": page, "sort": "date"}
            if remote:
                params["remoteOnly"] = "true"
            if INDEED_DATE_POSTED:
                try: params["datePosted"] = int(INDEED_DATE_POSTED)
                except ValueError: pass
            try:
                data = fetch_json(INDEED_RAPIDAPI_URL + INDEED_RAPIDAPI_PATH, params, headers=headers, timeout=JOBICY_TIMEOUT)
                successful_requests += 1; pages_checked += 1
                rows = normalize_indeed_jobs(data)
                for job in rows:
                    job["_query"] = search_query
                    if location_matches(job, location, remote): results.append(job)
                if len(rows) < 15: break
            except Exception as exc:
                message = str(exc)[:900]
                kind = _indeed_error_kind(message)
                if kind == "authorization":
                    auth_error = message
                    break
                errors.append({"source": "Indeed", "error": f"query={search_query!r}, page={page}: {message}", "kind": kind})
                break
        if auth_error: break
    unique, seen = [], set()
    for job in results:
        key = job.get("external_id") or job_fingerprint(job)
        if key in seen: continue
        seen.add(key); unique.append(job)
    # A present API key means the provider is configured; authorization is a
    # separate state. Keep configured=True so the UI does not incorrectly say
    # "not configured" when RapidAPI itself returns HTTP 401/403.
    configured = bool(INDEED_RAPIDAPI_KEY)
    status_message = "Indeed Jobs API via RapidAPI" if not auth_error else "Indeed RapidAPI authorization failed — check RapidAPI subscription/key/host"
    if auth_error:
        errors.append({"source":"Indeed","error":auth_error,"kind":"authorization","action":"Verify the RapidAPI subscription and X-RapidAPI-Key for this Indeed API, then update Render."})
    elif errors:
        status_message += " — partial provider errors"
    status = _provider_status("Indeed", len(unique), configured, status_message)
    status.update({"raw_found":len(unique),"queries":queries,"pages_checked":pages_checked,"country":country,"max_pages":INDEED_MAX_PAGES,"endpoint":INDEED_RAPIDAPI_URL + INDEED_RAPIDAPI_PATH,"direct_application_urls":any(bool(j.get("application_url")) for j in unique),"authorization_ok":not bool(auth_error)})
    return unique, errors, [status]

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
        job_level = str(raw.get("jobLevel") or "").strip()
        jobs.append({
            "external_id": "jobicy:" + str(raw.get("id") or raw.get("jobSlug") or url),
            "source": "Jobicy",
            "source_url": (f"https://jobicy.com/jobs/{raw.get('id')}" if raw.get("id") else url),
            "title": title,
            "company": company,
            "location": location,
            "work_mode": "Remote",
            "salary_min": salary_min,
            "salary_max": salary_max,
            "experience_min": extract_experience(description) or extract_experience(job_level),
            "url": url,
            "description": description or title,
            "employment_type": ", ".join(str(x) for x in (raw.get("jobType") or [])),
            "posted_at": str(raw.get("pubDate") or "").strip(),
        })
    return jobs


def normalize_jobvetta_jobs(data):
    rows = data.get("jobs", []) if isinstance(data, dict) else []
    jobs = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        company = str(raw.get("company") or "Unknown").strip()
        url = str(raw.get("url") or "").strip()
        location = str(raw.get("location") or "India").strip()
        if not title or not url:
            continue
        description = strip_html(raw.get("description") or " ".join(raw.get("skills_required") or []))
        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        currency = str(raw.get("salary_currency") or "INR").upper()
        if currency == "INR":
            try:
                salary_min = float(salary_min) / 100000 if salary_min is not None else None
                salary_max = float(salary_max) / 100000 if salary_max is not None else None
            except (TypeError, ValueError):
                salary_min = salary_max = None
        else:
            salary_min = salary_max = None
        jobs.append({
            "external_id": "jobvetta:" + str(raw.get("job_id") or url),
            "source": "Jobvetta",
            "source_url": url,
            "title": title,
            "company": company,
            "location": location,
            "work_mode": str(raw.get("work_model") or ""),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "experience_min": extract_experience(description + " " + str(raw.get("experience_level") or "")),
            "url": url,
            "description": description or title,
            "employment_type": str(raw.get("employment_type") or ""),
            "posted_at": str(raw.get("created_at") or ""),
        })
    return jobs


def normalize_indianapi_jobs(data):
    rows = data.get("jobs", []) if isinstance(data, dict) and isinstance(data.get("jobs"), list) else (data if isinstance(data, list) else [])
    jobs = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("job_title") or "").strip()
        company = str(raw.get("company") or "Unknown").strip()
        url = str(raw.get("apply_link") or raw.get("url") or "").strip()
        location = str(raw.get("location") or "India").strip()
        description = strip_html(" ".join(str(raw.get(k) or "") for k in ("job_description","role_and_responsibility","education_and_skills","about_company")))
        if not title or not url:
            continue
        smin, smax = extract_salary(description)
        exp = extract_experience(description + " " + str(raw.get("experience") or ""))
        jobs.append({
            "external_id": "indianapi:" + str(raw.get("id") or url),
            "source": "IndianAPI",
            "source_url": url,
            "title": title,
            "company": company,
            "location": location,
            "work_mode": "Remote" if "remote" in (location + " " + description).lower() else "",
            "salary_min": smin,
            "salary_max": smax,
            "experience_min": exp,
            "url": url,
            "description": description or title,
            "employment_type": str(raw.get("job_type") or ""),
            "posted_at": str(raw.get("posted_date") or ""),
        })
    return jobs


def normalize_remoteok_jobs(data):
    rows = data if isinstance(data, list) else []
    jobs = []
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("position") or not raw.get("url"):
            continue
        title = str(raw.get("position")).strip()
        company = str(raw.get("company") or "Unknown").strip()
        description = strip_html(raw.get("description") or "")
        salary_text = str(raw.get("salary") or "")
        smin, smax = parse_salary_text(salary_text)
        jobs.append({
            "external_id": "remoteok:" + str(raw.get("id") or raw.get("url")),
            "source": "RemoteOK",
            "source_url": str(raw.get("url")),
            "title": title,
            "company": company,
            "location": str(raw.get("location") or "Worldwide").strip(),
            "work_mode": "Remote",
            "salary_min": None,
            "salary_max": None,
            "experience_min": extract_experience(description),
            "url": str(raw.get("url")),
            "description": description or title,
            "employment_type": "",
            "posted_at": str(raw.get("date") or raw.get("published_at") or ""),
        })
    return jobs


def normalize_muse_jobs(data):
    rows = data.get("results", []) if isinstance(data, dict) else []
    jobs = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        company = raw.get("company") or {}
        company_name = company.get("name") if isinstance(company, dict) else str(company)
        locations = raw.get("locations") or []
        location_names = []
        for loc in locations:
            location_names.append(str(loc.get("name") or "") if isinstance(loc, dict) else str(loc))
        description = strip_html(str(raw.get("contents") or raw.get("description") or ""))
        title = str(raw.get("name") or raw.get("title") or "").strip()
        refs = raw.get("refs") if isinstance(raw.get("refs"), dict) else {}
        url = str(refs.get("landing_page") or raw.get("url") or "").strip()
        if not title or not url:
            continue
        jobs.append({
            "external_id": "themuse:" + str(raw.get("id") or url),
            "source": "The Muse",
            "source_url": url,
            "title": title,
            "company": str(company_name or "Unknown").strip(),
            "location": ", ".join(x for x in location_names if x) or "Remote",
            "work_mode": "Remote" if any("remote" in x.lower() for x in location_names) else "",
            "salary_min": None,
            "salary_max": None,
            "experience_min": extract_experience(description),
            "url": url,
            "description": description or title,
        })
    return jobs


def _provider_status(source, found, configured, provider, error=None):
    item = {"source": source, "found": int(found or 0), "configured": bool(configured), "provider": provider}
    if error:
        item["error"] = str(error)[:1000]
    return item


def search_additional_providers(query, location="", remote=False):
    results, errors, status = [], [], []

    indeed_results, indeed_errors, indeed_status = search_indeed_jobs(query, location, remote)
    results.extend(indeed_results)
    errors.extend(indeed_errors)
    status.extend(indeed_status)

    if JOBVETTA_API_KEY and (
        not location or "india" in location.lower() or
        location.lower() in {"ind", "bengaluru", "bangalore", "pune", "mumbai", "hyderabad", "indore", "delhi", "noida", "gurgaon", "gurugram"}
    ):
        try:
            data = fetch_json(
                JOBVETTA_API_URL,
                {"q": query, "location": location or "India", "days": 30, "limit": 10},
                headers={"Authorization": f"Bearer {JOBVETTA_API_KEY}"},
                timeout=JOBICY_TIMEOUT,
            )
            rows = [j for j in normalize_jobvetta_jobs(data) if location_matches(j, location, remote)]
            results.extend(rows)
            status.append(_provider_status("Jobvetta", len(rows), True, "Jobvetta Free India API"))
        except Exception as exc:
            errors.append({"source": "Jobvetta", "error": str(exc)[:1000]})
            status.append(_provider_status("Jobvetta", 0, True, "Jobvetta Free India API", exc))
    else:
        status.append(_provider_status("Jobvetta", 0, False, "Free India API — API key required"))

    if INDIANAPI_KEY:
        try:
            data = fetch_json(
                INDIANAPI_URL,
                {"limit": "50", "title": query, "location": location or "India"},
                headers={"X-Api-Key": INDIANAPI_KEY},
                timeout=JOBICY_TIMEOUT,
            )
            rows = [j for j in normalize_indianapi_jobs(data) if location_matches(j, location, remote)]
            results.extend(rows)
            status.append(_provider_status("IndianAPI", len(rows), True, "IndianAPI Free Jobs API"))
        except Exception as exc:
            errors.append({"source": "IndianAPI", "error": str(exc)[:1000]})
            status.append(_provider_status("IndianAPI", 0, True, "IndianAPI Free Jobs API", exc))
    else:
        status.append(_provider_status("IndianAPI", 0, False, "Free India Jobs API — API key required"))

    if THEMUSE_ENABLED:
        try:
            params = {"page": 1}
            if THEMUSE_API_KEY:
                params["api_key"] = THEMUSE_API_KEY
            data = fetch_json("https://www.themuse.com/api/public/jobs", params, timeout=JOBICY_TIMEOUT)
            q_tokens = tokens(query)
            rows = normalize_muse_jobs(data)
            selected = [
                j for j in rows
                if not q_tokens or sum(t in (j["title"] + " " + j["description"]).lower() for t in q_tokens) >= max(1, min(2, len(q_tokens)))
            ]
            selected = [j for j in selected if location_matches(j, location, remote)]
            results.extend(selected)
            status.append(_provider_status("The Muse", len(selected), True, "The Muse public Jobs API"))
        except Exception as exc:
            errors.append({"source": "The Muse", "error": str(exc)[:1000]})
            status.append(_provider_status("The Muse", 0, True, "The Muse public Jobs API", exc))
    else:
        status.append(_provider_status("The Muse", 0, False, "Optional; set THEMUSE_ENABLED=true"))

    if REMOTEOK_ENABLED and (remote or not location or location.lower() in {"remote", "anywhere", "worldwide"}):
        try:
            rows = normalize_remoteok_jobs(fetch_json("https://remoteok.com/api"))
            q_tokens = tokens(query)
            selected = [
                j for j in rows
                if not q_tokens or sum(t in (j["title"] + " " + j["description"]).lower() for t in q_tokens) >= max(1, min(2, len(q_tokens)))
            ]
            results.extend(selected[:100])
            status.append(_provider_status("RemoteOK", len(selected[:100]), True, "RemoteOK public API"))
        except Exception as exc:
            errors.append({"source": "RemoteOK", "error": str(exc)[:1000]})
            status.append(_provider_status("RemoteOK", 0, True, "RemoteOK public API", exc))
    else:
        status.append(_provider_status("RemoteOK", 0, REMOTEOK_ENABLED, "Remote-only public API"))

    return results, errors, status


def _jobicy_geo(location):
    value = (location or "").strip().lower()
    if not value:
        return ""
    if "remote" in value or value in {"anywhere", "worldwide", "global"}:
        return "anywhere"
    country_map = {
        "india": "apac", "united states": "usa", "usa": "usa", "us": "usa",
        "united kingdom": "uk", "uk": "uk", "canada": "canada",
        "australia": "australia", "europe": "europe", "asia": "asia", "apac": "apac",
    }
    for name, slug in country_map.items():
        if name in value:
            return slug
    return ""


def _jobicy_search_tag(query):
    requested = (query or "").strip()
    q = requested.lower()
    for role in CANDIDATE["roles_primary"]:
        if role.lower() in q or q in role.lower():
            words = [w for w in re.findall(r"[a-z]+", role.lower()) if len(w) >= 3 or w == "qa"]
            for preferred in ("qa", "sdet", "automation", "tester", "testing", "software"):
                if preferred in words:
                    return preferred
            return words[0] if words else "qa"
    words = [w for w in re.findall(r"[a-z]+", q) if len(w) >= 3 and w not in STOPWORDS]
    return words[0] if words else "qa"


def _jobicy_search_tags(query):
    """Return a small set of role-specific tags to improve recall without broad scraping."""
    q = (query or "").lower()
    tags = [_jobicy_search_tag(query)]
    if any(x in q for x in ("qa", "quality", "test", "tester", "sdet", "automation")):
        tags.extend(["automation", "sdet", "tester"])
    else:
        tags.extend([w for w in re.findall(r"[a-z]+", q) if len(w) >= 4 and w not in STOPWORDS])
    unique = []
    for tag in tags:
        if tag and tag not in unique:
            unique.append(tag)
    return unique[:3]


def job_matches_query(job, query):
    """Require actual query/role relevance before a listing enters ApplyBot results."""
    q = (query or "").strip().lower()
    if not q:
        return True
    title = (job.get("title") or "").lower()
    text = (title + " " + (job.get("description") or "")).lower()
    q_tokens = tokens(q)
    title_tokens = tokens(title)

    # Exact configured role families get priority.
    for role, keywords in ROLE_KEYWORDS.items():
        if any(k in title for k in keywords) and (
            role.lower() in q or q in role.lower() or
            any(k in q for k in keywords)
        ):
            return True

    if len(q_tokens) == 1:
        return next(iter(q_tokens)) in text

    overlap = len(q_tokens & title_tokens)
    text_overlap = sum(1 for token in q_tokens if token in text)
    required_title = max(2, (len(q_tokens) + 1) // 2)
    return overlap >= required_title or text_overlap >= max(2, min(3, len(q_tokens)))


def search_jobicy_jobs(query, location="", remote=False):
    """Fetch live Jobicy data, query-filter it, and apply requested location matching."""
    location_text = (location or "").strip()
    geo = _jobicy_geo(location_text)
    if remote and not geo:
        geo = "anywhere"
    tags = _jobicy_search_tags(query)
    headers = {}
    if JOBICY_API_KEY:
        headers["Authorization"] = f"Bearer {JOBICY_API_KEY}"

    all_rows = []
    errors = []
    modes = []
    for tag in tags:
        attempts = []
        if geo:
            attempts.append(("tag+geo", {"count": min(JOBICY_COUNT, 100), "tag": tag, "geo": geo}))
        attempts.append(("tag", {"count": min(JOBICY_COUNT, 100), "tag": tag}))
        rows_for_tag = []
        successful_mode = None
        for mode, params in attempts:
            try:
                data = fetch_json(JOBICY_API_URL, params, headers=headers, timeout=JOBICY_TIMEOUT)
                rows_for_tag = normalize_jobicy_jobs(data)
                successful_mode = mode
                break
            except Exception as exc:
                errors.append(f"{tag}/{mode}: {str(exc)[:500]}")
        if successful_mode:
            modes.append(f"{tag}:{successful_mode}")
            all_rows.extend(rows_for_tag)

    # If every tag request failed, use one global request as a final recovery.
    if not all_rows and errors:
        try:
            data = fetch_json(
                JOBICY_API_URL, {"count": min(JOBICY_COUNT, 200)},
                headers=headers, timeout=JOBICY_TIMEOUT
            )
            all_rows = normalize_jobicy_jobs(data)
            modes.append("global")
        except Exception as exc:
            errors.append(f"global: {str(exc)[:500]}")

    unique = []
    seen = set()
    for job in all_rows:
        key = job.get("external_id") or job_fingerprint(job)
        if key in seen:
            continue
        seen.add(key)
        job["_query"] = query
        if job_matches_query(job, query) and location_matches(job, location_text, remote):
            unique.append(job)
        if len(unique) >= min(200, JOBICY_COUNT):
            break

    provider = {
        "source": "Jobicy",
        "found": len(unique),
        "raw_found": len(all_rows),
        "configured": True,
        "provider": "Jobicy Commercial API" if JOBICY_API_KEY else "Jobicy Public REST API",
        "direct_application_urls": bool(JOBICY_API_KEY),
        "tags": tags,
        "geo": geo or "anywhere",
        "request_mode": ",".join(modes) if modes else "failed",
        "query_filtered": True,
    }
    if errors:
        provider["fallback_notes"] = errors[:4]
    provider_errors = [{"source": "Jobicy", "error": "; ".join(errors[:3])}] if errors and not unique else []
    return unique, provider_errors, [provider]



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
    location_text = (job.get("location") or "").lower()
    description = (job.get("description") or "").lower()
    text = location_text + " " + description
    if not requested:
        return (not remote) or job.get("work_mode", "").lower() == "remote"
    if requested in {"india", "ind"}:
        india_terms = ["india", "indian", "bangalore", "bengaluru", "pune", "hyderabad", "mumbai", "delhi", "noida", "gurugram", "gurgaon", "chennai", "indore"]
        matched = any(x in text for x in india_terms) or any(x in location_text for x in ("apac", "asia", "south asia", "anywhere", "worldwide", "global"))
        return matched and (not remote or job.get("work_mode", "").lower() == "remote")
    matched = requested in text or "anywhere" in location_text or "worldwide" in location_text
    return matched and (not remote or job.get("work_mode", "").lower() == "remote")


def search_public_sources(query, location="", remote=False):
    """Delegate discovery to the resilient multi-provider engine.

    The legacy provider implementation remains in this file for compatibility,
    but the active discovery path no longer depends on Indeed/RapidAPI.
    """
    from providers_v4 import search_public_sources as discover_v4
    return discover_v4(query, location, remote)


def import_job_items(items):
    """Persist a discovery batch efficiently without one SQL round-trip/savepoint per job."""
    c = db()
    created = []
    try:
        valid = []
        for j in items:
            if not all(j.get(k) for k in ["title", "company", "url", "description"]):
                continue
            ext = j.get("external_id") or job_fingerprint(j)
            smin, smax = j.get("salary_min"), j.get("salary_max")
            if smin is None and smax is None:
                smin, smax = extract_salary(j["description"])
            exp = j.get("experience_min") if j.get("experience_min") is not None else extract_experience(j["description"])
            base = {**j, "salary_min": smin, "salary_max": smax, "experience_min": exp}

            # AI enrichment is deliberately not part of the synchronous discovery
            # path. Provider results must be searchable even when an AI service is slow.
            sc, reasons, matched = score_job(base)
            valid.append((base, sc, reasons, matched))

        if not valid:
            return []

        now = utcnow()
        rows_to_write = []
        for j, sc, reasons, matched in valid:
            ext = j.get("external_id") or job_fingerprint(j)
            status = "ready" if sc > 0 else "skipped"
            rows_to_write.append((
                ext, j.get("source", "manual"), j["title"], j["company"],
                j.get("location", ""), j.get("work_mode", ""),
                j.get("salary_min"), j.get("salary_max"), j.get("experience_min"),
                j.get("source_url", j["url"]), j["url"], j["description"], now,
                sc, status, "; ".join(reasons), "; ".join(reasons), json.dumps(matched),
            ))

        upsert_sql = """INSERT INTO jobs(
            external_id,source,title,company,location,work_mode,salary_min,salary_max,
            experience_min,source_url,url,description,discovered_at,match_score,status,
            skip_reason,match_reasons,matched_skills
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(external_id) DO UPDATE SET
            source=excluded.source,
            title=excluded.title,
            company=excluded.company,
            location=excluded.location,
            work_mode=excluded.work_mode,
            salary_min=excluded.salary_min,
            salary_max=excluded.salary_max,
            experience_min=excluded.experience_min,
            source_url=excluded.source_url,
            url=excluded.url,
            description=excluded.description,
            discovered_at=excluded.discovered_at,
            match_score=excluded.match_score,
            status=excluded.status,
            skip_reason=excluded.skip_reason,
            match_reasons=excluded.match_reasons,
            matched_skills=excluded.matched_skills"""

        if c.pg:
            # execute_values collapses the whole discovery batch into one PostgreSQL
            # statement, which is substantially faster than 143 individual SAVEPOINTs.
            from psycopg2.extras import execute_values
            cur = c.conn.cursor(cursor_factory=c.cursor_factory)
            execute_values(cur, upsert_sql.replace("VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", "VALUES %s"), rows_to_write, page_size=100)
            cur.close()
            ext_ids = [row[0] for row in rows_to_write]
            rows = c.execute("SELECT id,external_id FROM jobs WHERE external_id = ANY(?)", (ext_ids,)).fetchall()
            id_by_ext = {r["external_id"]: r["id"] for r in rows}
        else:
            c.conn.executemany(upsert_sql, rows_to_write)
            ext_ids = [row[0] for row in rows_to_write]
            placeholders = ",".join("?" for _ in ext_ids)
            rows = c.execute(f"SELECT id,external_id FROM jobs WHERE external_id IN ({placeholders})", tuple(ext_ids)).fetchall()
            id_by_ext = {r["external_id"]: r["id"] for r in rows}

        c.commit()

        for j, sc, reasons, matched in valid:
            ext = j.get("external_id") or job_fingerprint(j)
            created.append({
                "job_id": id_by_ext.get(ext),
                "external_id": ext,
                "score": sc,
                "status": "ready" if sc > 0 else "skipped",
                "matched_skills": matched,
                "reasons": reasons,
                "duplicate": ext in id_by_ext,
                "experience_min": j.get("experience_min"),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
            })
        return created
    except Exception:
        c.conn.rollback()
        raise
    finally:
        c.close()


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


def experience_matches_filter(experience_min, max_experience):
    """Apply the UI experience filter fairly, including true fresher mode.

    max_experience == 0 means entry-level/fresher: accept explicit 0-year,
    fresher/intern-style roles and roles where the source did not publish an
    experience requirement. For positive values, enforce the requested upper
    bound while keeping undisclosed experience neutral.
    """
    if experience_min is None:
        return True
    try:
        exp = float(experience_min)
        limit = float(max_experience)
    except (TypeError, ValueError):
        return True
    if limit <= 0:
        return exp <= 0.0
    return exp <= limit


def run_discovery(body):
    query = str(body.get("query") or "QA Automation Engineer").strip()
    location = str(body.get("location") or "India").strip()
    remote = bool(body.get("remote", False))
    threshold = float(body.get("threshold", 70))
    max_experience = max(0.0, float(body.get("max_experience", 2)))
    min_salary = max(float(body.get("min_salary", 3)), CANDIDATE["minimum_ctc_lpa"])

    items, errors, source_status = search_public_sources(query, location, remote)
    try:
        results = import_job_items(items)
    except Exception as exc:
        # Discovery should not crash the HTTP request. Return the provider data
        # and a precise persistence error so the UI can still diagnose it.
        errors.append({"source": "database", "error": str(exc)[:1500]})
        results = []

    # import_job_items already returned the normalized experience/salary values.
    # Do not open a new PostgreSQL connection for every result: large Jobicy
    # batches can contain 100+ jobs and the per-row connections can exhaust or
    # stall a small Render instance.
    qualified = []
    for r in results:
        exp_value = r.get("experience_min")
        salary_value = r.get("salary_max")
        exp_ok = experience_matches_filter(exp_value, max_experience)
        salary_ok = salary_value is None or float(salary_value) >= min_salary
        threshold_ok = float(r.get("score") or 0) >= threshold
        r["qualified"] = bool(threshold_ok and exp_ok and salary_ok)
        r["qualification_reason"] = (
            "Qualified" if r["qualified"] else
            ("Below match threshold" if not threshold_ok else
             ("Experience exceeds the selected fresher/maximum-years filter" if not exp_ok else "Published salary is below minimum"))
        )
        if r["qualified"]:
            qualified.append(r)

    return {
        "mode": "in_app",
        "query": query,
        "location": location,
        "remote": remote,
        "threshold": threshold,
        "max_experience": max_experience,
        "min_salary": min_salary,
        "sources_checked": source_status,
        "provider_summary": {str(x.get("source")): int(x.get("found") or 0) for x in source_status},
        "items_seen": len(items),
        "new_jobs": len(results),
        "qualified_jobs": len(qualified),
        "errors": errors,
        "results": results,
    }


@app.post("/api/discover/search")
def discover_search():
    try:
        return jsonify(run_discovery(request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({"error": "Discovery failed", "details": str(exc)[:1500]}), 502


@app.post("/api/discover")
def discover():
    try:
        return jsonify(run_discovery(request.get_json(silent=True) or {}))
    except Exception as exc:
        return jsonify({"error": "Discovery failed", "details": str(exc)[:1500]}), 502


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


@app.get("/api/discovery-diagnostics")
def discovery_diagnostics():
    query = request.args.get("query", "QA Automation Engineer")
    location = request.args.get("location", "India")
    remote = request.args.get("remote", "false").lower() == "true"
    try:
        items, errors, sources = search_public_sources(query, location, remote)
        return jsonify({
            "ok": True,
            "query": query,
            "location": location,
            "remote": remote,
            "items_seen": len(items),
            "sources_checked": sources,
            "errors": errors,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:2000]}), 200


@app.get("/api/provider-check")
def provider_check():
    """Small smoke test for the only active discovery dependency."""
    result = {
        "service": "ApplyBot",
        "strategy": "Free ATS dataset → local matching → supported employer application",
        "database": "postgres" if is_postgres() else "sqlite",
    }
    try:
        from providers_v4 import _fetch_dataset
        jobs, _ = _fetch_dataset()
        result["source"] = {
            "name": "Open Jobs Data",
            "provider": "ConorsCode/open-jobs-data",
            "ok": bool(jobs),
            "count": len(jobs),
            "endpoint": "https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/data/jobs.json",
        }
    except Exception as exc:
        result["source"] = {"name": "Open Jobs Data", "ok": False, "error": str(exc)[:1000]}
    try:
        c = db()
        if c.pg:
            rows = c.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", ("jobs",)).fetchall()
            columns = {r["column_name"] for r in rows}
        else:
            rows = c.execute("PRAGMA table_info(jobs)").fetchall()
            columns = {r[1] for r in rows}
        c.close()
        required = {"source_url", "match_reasons", "matched_skills"}
        result["database_schema"] = {"ok": required.issubset(columns), "missing": sorted(required - columns)}
    except Exception as exc:
        result["database_schema"] = {"ok": False, "error": str(exc)[:1000]}
    result["ok"] = bool(result["source"].get("ok")) and bool(result["database_schema"].get("ok"))
    return jsonify(result), (200 if result["ok"] else 503)


@app.get("/api/config")
def config_status():
    return jsonify({
        "auto_apply_enabled": AUTO_APPLY_ENABLED,
        "auto_apply_max": AUTO_APPLY_MAX,
        "candidate_email_configured": bool(CANDIDATE_EMAIL),
        "candidate_phone_configured": bool(CANDIDATE_PHONE),
        "resume_configured": resume_file_path().is_file(),
        "supported_browser_adapters": ["greenhouse", "lever", "workable", "ashby", "smartrecruiters"],
        "discovery": {
            "provider": "ConorsCode/open-jobs-data",
            "free": True,
            "api_key_required": False,
            "rss_used": False,
            "aggregator_redirects_used": False,
        },
        "note": "Discovery is free and in-app. Submission stops for CAPTCHA, login, missing required answers, or unsupported forms."
    })


@app.get("/api/jobs")
def jobs():
    try:
        c = db()
        rows = c.execute("SELECT * FROM jobs ORDER BY match_score DESC, discovered_at DESC").fetchall()
        c.close()
        payload = []
        for row in rows:
            item = dict(row)
            item["reasons"] = [x.strip() for x in (item.get("match_reasons") or "").split(";") if x.strip()]
            try: item["matched_skills"] = json.loads(item.get("matched_skills") or "[]")
            except Exception: item["matched_skills"] = []
            payload.append(item)
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"error": "Could not load jobs", "details": str(exc)[:1000]}), 500


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
    if "workable.com" in host:
        return "workable"
    if "ashbyhq.com" in host:
        return "ashby"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
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


def resolve_application_url(job_url):
    """Resolve a public listing to an employer/ATS URL, using HTTP first.

    Browser rendering is only a fallback. This keeps link resolution working on
    Render even when a browser is temporarily unavailable and avoids launching
    Chromium for ordinary server-rendered job pages.
    """
    if not job_url:
        return job_url, None
    host = (urlparse(job_url).hostname or "").lower()
    supported_hosts = (
        "greenhouse.io", "lever.co", "workable.com", "ashbyhq.com",
        "smartrecruiters.com"
    )
    if any(x in host for x in supported_hosts):
        return job_url, None

    def pick_link(html):
        from html import unescape
        candidates = re.findall(
            r'<a[^>]+href=["\\\']([^"\\\']+)["\\\'][^>]*>(.*?)</a>',
            html or "", re.I | re.S
        )
        for href, label_html in candidates[:500]:
            href = unescape(href).strip()
            label = strip_html(unescape(label_html)).strip().lower()
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(job_url, href)
            if not href.startswith("http") or href == job_url:
                continue
            h2 = (urlparse(href).hostname or "").lower()
            if any(x in h2 for x in supported_hosts):
                return href
            if re.search(r"\\b(apply|application|apply now|submit application)\\b", label, re.I) and h2:
                return href
        return None

    # Fast, dependency-free resolution path.
    try:
        req = urllib.request.Request(
            job_url,
            headers={"User-Agent": "Mozilla/5.0 ApplyBot/5.1", "Accept": "text/html,*/*"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read(2_000_000).decode("utf-8", errors="ignore")
        resolved = pick_link(html)
        if resolved:
            return resolved, "Resolved employer application URL without browser"
    except Exception:
        pass

    # Dynamic-page fallback.
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()
            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(700)
            links = page.locator("a[href]")
            for i in range(min(links.count(), 300)):
                a = links.nth(i)
                try:
                    href = a.get_attribute("href") or ""
                    label = (a.inner_text() or "").strip().lower()
                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(job_url, href)
                    h2 = (urlparse(href).hostname or "").lower()
                    if not href.startswith("http") or href == job_url:
                        continue
                    if any(x in h2 for x in supported_hosts) or re.search(
                        r"\\b(apply|application|apply now|submit application)\\b", label, re.I
                    ):
                        browser.close()
                        return href, "Resolved employer application URL"
                except Exception:
                    continue
            browser.close()
    except Exception as exc:
        return job_url, "Application-link resolution unavailable: " + str(exc)[:300]
    return job_url, "No supported employer application URL found on the listing"


# Backward-compatible alias.
def resolve_jobicy_application_url(job_url):
    return resolve_application_url(job_url)

def submit_with_browser(job, answers):
    application_url = job["url"]
    resolution_message = None
    adapter = detect_application_adapter(application_url)
    if adapter == "unsupported":
        application_url, resolution_message = resolve_application_url(application_url)
        if application_url != job["url"]:
            job = {**job, "url": application_url}
            adapter = detect_application_adapter(application_url)
    if job.get("source") == "Remotive":
        return {"status": "unsupported_source_policy", "adapter": adapter,
                "message": "Remotive public API terms do not permit submitting its listings to third-party sites. This listing can be reviewed, but ApplyBot will not auto-submit it."}
    if adapter == "unsupported":
        message = "No supported employer application URL was found."
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

            # Some ATS pages land on a job-detail screen first. Follow an
            # explicit Apply button before inspecting fields.
            email_fields = page.locator('input[type="email"], input[name*="email" i]')
            file_fields = page.locator('input[type="file"]')
            if not email_fields.count() and not file_fields.count():
                apply_link = page.get_by_role("link", name=re.compile(r"apply now|apply|start application", re.I)).last
                apply_button = page.get_by_role("button", name=re.compile(r"apply now|apply|start application", re.I)).last
                target = apply_link if apply_link.count() else apply_button
                if target.count() and target.is_visible():
                    try:
                        target.click()
                        page.wait_for_timeout(1800)
                    except Exception:
                        pass

            body_text = page.locator("body").inner_text(timeout=10000)
            challenge = page.locator(
                'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], [id*="captcha"], [class*="captcha"]'
            )
            if challenge.count() or re.search(
                r"\b(captcha|verify you are human|cloudflare challenge)\b", body_text, re.I
            ):
                browser.close()
                return {
                    "status": "requires_user_action",
                    "adapter": adapter,
                    "application_url": page.url or job["url"],
                    "message": "Human verification/CAPTCHA detected. The employer page is ready for you to complete verification; ApplyBot will not bypass it. After verification, return to ApplyBot and choose Continue after verification.",
                }

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
        """INSERT INTO applications(job_id,tailored_summary,cover_letter,answers_json,status,created_at,updated_at,adapter,submission_id,submission_message,submitted_at,application_url)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, job["title"], make_answers(job).get("why_interested", ""), json.dumps(make_answers(job)),
         "applied" if status == "submitted" else status, now, now, result.get("adapter"),
         result.get("submission_id"), result.get("message"), now if status == "submitted" else None,
         result.get("application_url") or job.get("url"))
    )
    if status == "submitted":
        c.execute("UPDATE jobs SET status=? WHERE id=?", ("applied", job_id))
    c.commit()
    app_row = c.execute("SELECT id FROM applications WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    c.close()
    return {"status": "applied" if status == "submitted" else status, "submitted": status == "submitted",
            "application_id": app_row["id"] if app_row else None, "adapter": result.get("adapter"),
            "application_url": result.get("application_url") or job.get("url"),
            "message": result.get("message")}


@app.post("/api/jobs/<int:job_id>/continue-after-verification")
def continue_after_verification(job_id):
    """Retry the controlled application flow after the user handles a challenge."""
    body = request.get_json(silent=True) or {}
    try:
        threshold = float(body.get("threshold", 70))
        max_experience = max(0.0, float(body.get("max_experience", 2)))
        min_salary = max(float(body.get("min_salary", 3)), CANDIDATE["minimum_ctc_lpa"])
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid threshold, experience or salary value."}), 400
    result = auto_apply_job(job_id, threshold, max_experience, min_salary)
    result["continued_after_verification"] = True
    return jsonify(result)


@app.post("/api/jobs/<int:job_id>/prepare")
def prepare_application(job_id):
    c = db()
    row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        c.close()
        return jsonify({"error": "Job was not found."}), 404
    job = dict(row)
    answers = make_answers(job)
    now = utcnow()
    cover = answers.get("why_interested", "")
    c.execute(
        """INSERT INTO applications(job_id,tailored_summary,cover_letter,answers_json,status,created_at,updated_at,adapter,submission_id,submission_message,submitted_at,application_url)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, job["title"], cover, json.dumps(answers), "application_ready", now, now, detect_application_adapter(job["url"]), None, "Application prepared; not submitted.", None, job.get("url"))
    )
    c.commit()
    app_row = c.execute("SELECT id FROM applications WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    c.close()
    return jsonify({"ok": True, "application_id": app_row["id"] if app_row else None, "status": "application_ready", "answers": answers})

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
    allowed = {"draft","application_ready","approved","requires_user_action","requires_configuration","failed","unsupported","unsupported_source_policy","applied","rejected","interview","offer","closed"}
    if status not in allowed:
        return jsonify({"error": "Invalid application status."}), 400
    c = db()
    c.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (status, utcnow(), application_id))
    c.commit(); c.close()
    return jsonify({"ok": True, "status": status})


# Gunicorn imports this module instead of executing __main__. Initialize and
# migrate the production database during application import so existing Render/
# Supabase PostgreSQL schemas receive all required columns before requests arrive.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=os.getenv("DEBUG", "false").lower() == "true")