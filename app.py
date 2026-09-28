from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
SQLITE_DB = DATA / "applybot.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

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


def init_db():
    c = db()

    if c.pg:
        statements = [
            """CREATE TABLE IF NOT EXISTS jobs (
              id BIGSERIAL PRIMARY KEY, external_id TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
              title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, work_mode TEXT,
              salary_min DOUBLE PRECISION, salary_max DOUBLE PRECISION, experience_min DOUBLE PRECISION,
              url TEXT NOT NULL, description TEXT NOT NULL, discovered_at TEXT NOT NULL,
              match_score DOUBLE PRECISION DEFAULT 0, status TEXT DEFAULT 'new', skip_reason TEXT)""",
            """CREATE TABLE IF NOT EXISTS applications (
              id BIGSERIAL PRIMARY KEY, job_id BIGINT NOT NULL, tailored_summary TEXT,
              cover_letter TEXT, answers_json TEXT, status TEXT NOT NULL DEFAULT 'draft',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS feed_sources (
              id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL,
              source_type TEXT NOT NULL DEFAULT 'rss', enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL)""",
        ]
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
              title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, work_mode TEXT,
              salary_min REAL, salary_max REAL, experience_min REAL,
              url TEXT NOT NULL, description TEXT NOT NULL, discovered_at TEXT NOT NULL,
              match_score REAL DEFAULT 0, status TEXT DEFAULT 'new', skip_reason TEXT)""",
            """CREATE TABLE IF NOT EXISTS applications (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, tailored_summary TEXT,
              cover_letter TEXT, answers_json TEXT, status TEXT NOT NULL DEFAULT 'draft',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS feed_sources (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL,
              source_type TEXT NOT NULL DEFAULT 'rss', enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL)""",
        ]

    for statement in statements:
        c.execute(statement)

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

    for role, keywords in ROLE_KEYWORDS.items():
        if any(k in title for k in keywords):
            role_hit = True
            score += 30 if role in CANDIDATE["roles_primary"] else 15
            reasons.append(f"Role matches {role}")
            break

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
    from urllib.parse import quote_plus
    q = quote_plus(query.strip() or "QA Automation Engineer")
    loc = quote_plus(location.strip())
    linkedin = f"https://www.linkedin.com/jobs/search/?keywords={q}"
    if location.strip():
        linkedin += f"&location={loc}"
    if remote:
        linkedin += "&f_WT=2"
    google_query = quote_plus("site:linkedin.com/jobs/view " + (query.strip() or "QA Automation Engineer") + ((" " + location.strip()) if location.strip() else ""))
    return {
        "linkedin": linkedin,
        "google_linkedin": f"https://www.google.com/search?q={google_query}",
        "note": "These are user-initiated search links. ApplyBot does not scrape LinkedIn or use session cookies."
    }


def parse_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ApplyBot/1.0 (+personal job assistant)"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read()
    root = ET.fromstring(data)
    items = []
    for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        def val(*names):
            for name in names:
                node = item.find(name)
                if node is not None and node.text:
                    return node.text.strip()
            return ""
        link = val("link", "{http://www.w3.org/2005/Atom}link")
        if not link:
            node = item.find("{http://www.w3.org/2005/Atom}link")
            link = node.attrib.get("href", "") if node is not None else ""
        title = val("title", "{http://www.w3.org/2005/Atom}title")
        desc = val("description", "summary", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content")
        if title and link:
            items.append({
                "external_id": link,
                "source": urlparse(url).netloc,
                "title": title,
                "company": val("author", "company") or urlparse(url).netloc,
                "location": "",
                "work_mode": "",
                "url": link,
                "description": re.sub(r"<[^>]+>", " ", desc),
            })
    return items


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
                experience_min,url,description,discovered_at,match_score,status,skip_reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ext, j.get("source", "manual"), j["title"], j["company"], j.get("location", ""),
                 j.get("work_mode", ""), smin, smax, exp, j["url"], j["description"], utcnow(), sc, status,
                 "; ".join(reasons)),
            )
            created.append({"external_id": ext, "score": sc, "status": status, "matched_skills": matched, "reasons": reasons})
        except Exception as exc:
            if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                raise
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


@app.get("/api/feeds")
def feeds():
    c = db()
    rows = c.execute("SELECT * FROM feed_sources ORDER BY enabled DESC, name").fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/feeds")
def add_feed():
    body = request.get_json(silent=True) or {}
    if not body.get("name") or not body.get("url"):
        return jsonify({"error": "name and url are required"}), 400
    if not body["url"].startswith(("https://", "http://")):
        return jsonify({"error": "feed URL must be http(s)"}), 400
    c = db()
    try:
        c.execute(
            "INSERT INTO feed_sources(name,url,source_type,enabled,created_at) VALUES(?,?,?,?,?)",
            (body["name"], body["url"], body.get("source_type", "rss"), 1, utcnow()),
        )
        c.commit()
    except Exception as exc:
        c.close()
        return jsonify({"error": str(exc)}), 409
    c.close()
    return {"ok": True}


@app.post("/api/discover")
def discover():
    c = db()
    feeds = c.execute("SELECT * FROM feed_sources WHERE enabled=1").fetchall()
    c.close()
    all_items, errors = [], []
    for feed in feeds:
        try:
            all_items.extend(parse_feed(feed["url"]))
        except Exception as exc:
            errors.append({"feed": feed["name"], "error": str(exc)})
    results = import_job_items(all_items)
    return jsonify({"feeds_checked": len(feeds), "items_seen": len(all_items), "new_jobs": len(results), "errors": errors, "results": results})


@app.post("/api/jobs/<int:job_id>/prepare")
def prepare(job_id):
    c = db()
    r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        c.close()
        return jsonify({"error": "job not found"}), 404
    j = dict(r)
    answers = make_answers(j)
    summary = (
        "QA Engineer with ~1 year of hands-on experience in manual and automation testing across web and mobile products. "
        "Strong practical experience with Playwright, JavaScript/TypeScript, Page Object Model, Appium for Android/iOS, "
        "REST API validation, SQL/database testing, cross-browser/device testing, and AI-assisted QA workflows."
    )
    cover = f"""Dear Hiring Team,

I am excited to apply for the {j['title']} position at {j['company']}. I currently work as a QA Engineer with hands-on experience across manual testing, web automation, mobile automation, API validation, database testing and end-to-end quality assurance.

My strongest automation experience is with Playwright using JavaScript/TypeScript and Page Object Model, along with Appium for Android and iOS testing. I also use AI-assisted workflows to accelerate test design, automation scripting, debugging and edge-case analysis while keeping human validation in the loop.

I would welcome the opportunity to bring this practical QA and automation mindset to your team.

Regards,
Satyendra Kumar Namdeo"""
    now = utcnow()
    if c.pg:
        cur = c.execute(
            "INSERT INTO applications(job_id,tailored_summary,cover_letter,answers_json,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?) RETURNING id",
            (job_id, summary, cover, json.dumps(answers), "draft", now, now),
        )
        aid = cur.fetchone()["id"]
    else:
        cur = c.execute(
            "INSERT INTO applications(job_id,tailored_summary,cover_letter,answers_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (job_id, summary, cover, json.dumps(answers), "draft", now, now),
        )
        aid = cur.lastrowid
    c.execute("UPDATE jobs SET status=? WHERE id=?", ("application_ready", job_id))
    c.commit()
    c.close()
    return jsonify({"application_id": aid, "summary": summary, "cover_letter": cover, "answers": answers})


@app.get("/api/applications")
def applications():
    c = db()
    rows = c.execute(
        """SELECT a.*,j.title,j.company,j.location,j.url,j.match_score
        FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.created_at DESC"""
    ).fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/applications/<int:app_id>/status")
def app_status(app_id):
    status = (request.get_json(silent=True) or {}).get("status")
    allowed = {"draft", "approved", "applied", "rejected", "interview", "offer", "closed"}
    if status not in allowed:
        return jsonify({"error": "invalid status"}), 400
    c = db()
    c.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (status, utcnow(), app_id))
    c.commit()
    c.close()
    return {"ok": True, "status": status}


@app.cli.command("init-db")
def init_command():
    init_db()
    print("ApplyBot database initialized.")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=os.getenv("DEBUG", "false").lower() == "true")
