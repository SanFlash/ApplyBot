"""ApplyBot discovery engine v3.

Design:
1. Direct employer ATS APIs when configured (Greenhouse, Lever, Ashby).
2. Brave Search API as a broad web-discovery fallback. It finds live career/ATS
   pages, then ApplyBot fetches those pages and extracts schema.org JobPosting data.
3. Existing public aggregators remain secondary fallbacks (The Muse, RemoteOK,
   Jobicy) rather than the single source of truth.

This keeps discovery inside ApplyBot and does not require scraping LinkedIn/Indeed.
"""

from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import urlparse

BRAVE_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
BRAVE_ENABLED = os.getenv("BRAVE_SEARCH_ENABLED", "true").lower() == "true" and bool(BRAVE_API_KEY)
BRAVE_TIMEOUT = max(5, int(os.getenv("BRAVE_SEARCH_TIMEOUT", "15")))
BRAVE_MAX_QUERIES = min(8, max(1, int(os.getenv("BRAVE_MAX_QUERIES", "5"))))
ASHBY_BOARDS = [x.strip() for x in os.getenv("ASHBY_BOARDS", "").split(",") if x.strip()]
SMARTRECRUITERS_COMPANIES = [x.strip() for x in os.getenv("SMARTRECRUITERS_COMPANIES", "").split(",") if x.strip()]
SMARTRECRUITERS_API_KEY = os.getenv("SMARTRECRUITERS_API_KEY", "").strip()


def _tokens(text):
    return {x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]*", (text or "").lower()) if len(x) >= 2}


def _relevant(job, query):
    q = (query or "").strip().lower()
    if not q:
        return True
    title = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    qt = _tokens(q)
    if not qt:
        return True
    title_tokens = _tokens(title)
    if len(qt & title_tokens) >= max(1, (len(qt) + 1) // 2):
        return True
    families = [
        ("qa", "quality assurance", "qa engineer", "quality engineer"),
        ("automation", "test automation", "automation tester", "automation engineer"),
        ("sdet", "software development engineer in test"),
        ("tester", "software tester", "test engineer", "qa tester"),
    ]
    compact = re.sub(r"[^a-z0-9 ]", " ", q)
    for family in families:
        if any(x in compact for x in family) and any(x in title for x in family):
            return True
    hits = sum(1 for token in qt if token in (title + " " + description))
    return hits >= max(2, min(3, len(qt)))


def _dedupe(app, items):
    out, seen = [], set()
    for job in items:
        if not job.get("title") or not job.get("company") or not job.get("url"):
            continue
        key = job.get("external_id") or app.job_fingerprint(job)
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def _location_ok(app, job, location, remote):
    return app.location_matches(job, location, remote)


def _strip_html(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"<[^>]+>", " ", value).strip()


def _first(obj, *keys):
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return ""


def _jsonld_jobposting(page_html):
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html or "",
        flags=re.I | re.S,
    )
    found = []
    for block in blocks:
        try:
            value = json.loads(html.unescape(block.strip()))
        except Exception:
            continue
        stack = value if isinstance(value, list) else [value]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
                typ = item.get("@type")
                if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
                    found.append(item)
    return found


def _schema_location(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        address = value.get("address") or {}
        parts = [
            address.get("addressLocality") if isinstance(address, dict) else "",
            address.get("addressRegion") if isinstance(address, dict) else "",
            address.get("addressCountry") if isinstance(address, dict) else "",
        ]
        return ", ".join(str(x) for x in parts if x)
    return ""


def _schema_job(app, data, page_url):
    title = str(data.get("title") or "").strip()
    org = data.get("hiringOrganization") or {}
    company = str(org.get("name") if isinstance(org, dict) else org or "").strip()
    location = _schema_location(data.get("jobLocation"))
    description = _strip_html(data.get("description") or "")
    if not title or not company:
        return None
    identifier = data.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name")
    ext = str(identifier or page_url).strip()
    work_mode = "Remote" if str(data.get("jobLocationType") or "").upper() == "TELECOMMUTE" or "remote" in (location + " " + description).lower() else ""
    salary_min = salary_max = None
    salary = data.get("baseSalary")
    if isinstance(salary, dict):
        value = salary.get("value") or {}
        if isinstance(value, dict):
            try: salary_min = float(value.get("minValue")) if value.get("minValue") is not None else None
            except Exception: pass
            try: salary_max = float(value.get("maxValue")) if value.get("maxValue") is not None else None
    return {
        "external_id": "webjob:" + ext,
        "source": "Web Career Search",
        "source_url": page_url,
        "title": title,
        "company": company,
        "location": location or "Unspecified",
        "work_mode": work_mode,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "experience_min": app.extract_experience(description),
        "url": page_url,
        "description": description or title,
        "posted_at": str(data.get("datePosted") or ""),
        "employment_type": str(data.get("employmentType") or ""),
    }


def _brave_search(app, query, location):
    import urllib.request
    endpoint = "https://api.search.brave.com/res/v1/web/search"
    params = {
        "q": query,
        "country": "IN" if (location or "").lower() in {"india", "ind", "indore", "bangalore", "bengaluru", "pune"} else "US",
        "search_lang": "en",
        "count": 10,
        "safesearch": "moderate",
    }
    from urllib.parse import urlencode
    url = endpoint + "?" + urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_API_KEY,
            "User-Agent": "ApplyBot/3.0",
        },
    )
    with urllib.request.urlopen(req, timeout=BRAVE_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _brave_results(data):
    web = data.get("web") if isinstance(data, dict) else {}
    return web.get("results", []) if isinstance(web, dict) else []


def _search_queries(query, location, remote):
    base = query or "QA Automation Engineer"
    loc = "remote" if remote else (location or "India")
    queries = [
        f'"{base}" "{loc}" jobs',
        f'"{base}" "{loc}" careers apply',
        f'site:boards.greenhouse.io "{base}" "{loc}"',
        f'site:jobs.lever.co "{base}" "{loc}"',
        f'site:jobs.ashbyhq.com "{base}" "{loc}"',
        f'site:apply.workable.com "{base}" "{loc}"',
        f'site:jobs.smartrecruiters.com "{base}" "{loc}"',
        f'"{base}" "{loc}" "JobPosting"',
    ]
    # Remote-only searches should emphasize remote pages.
    if remote:
        queries.insert(0, f'"{base}" remote jobs careers apply')
    return queries[:BRAVE_MAX_QUERIES]


def _web_search_discovery(app, query, location, remote):
    import urllib.request
    rows, errors = [], []
    seen_urls = set()
    for search_query in _search_queries(query, location, remote):
        try:
            data = _brave_search(app, search_query, location)
            for result in _brave_results(data):
                url = str(result.get("url") or "").strip()
                if not url or url in seen_urls or not url.startswith("http"):
                    continue
                host = (urlparse(url).hostname or "").lower()
                # Avoid search result pages and job boards that are not actual postings.
                if any(x in host for x in ("google.", "bing.", "brave.com")):
                    continue
                seen_urls.add(url)
                try:
                    req = urllib.request.Request(
                        url,
                        headers={"User-Agent": "ApplyBot/3.0", "Accept": "text/html,application/xhtml+xml"},
                    )
                    with urllib.request.urlopen(req, timeout=BRAVE_TIMEOUT) as response:
                        page = response.read(1_500_000).decode("utf-8", errors="ignore")
                    postings = _jsonld_jobposting(page)
                    for posting in postings[:3]:
                        job = _schema_job(app, posting, url)
                        if job:
                            job["_query"] = query
                            rows.append(job)
                            break
                except Exception as exc:
                    # Search results are still useful if the page blocks us; retain
                    # them only as diagnostics rather than pretending they are jobs.
                    errors.append({"source": "Web Career Search", "error": f"{url}: {str(exc)[:300]}"})
        except Exception as exc:
            errors.append({"source": "Brave Search", "error": str(exc)[:700]})
    selected = [
        job for job in _dedupe(app, rows)
        if _relevant(job, query) and _location_ok(app, job, location, remote)
    ]
    return selected[:200], errors


def _ashby(app, query, location, remote):
    import urllib.request
    rows, errors = [], []
    for board in ASHBY_BOARDS:
        try:
            url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
            data = app.fetch_json(url, {"includeCompensation": "true"}, timeout=app.JOBICY_TIMEOUT)
            for raw in data.get("jobs", []):
                loc = str(raw.get("location") or "")
                desc = _strip_html(raw.get("descriptionHtml") or raw.get("description") or raw.get("summary") or "")
                job_url = str(raw.get("jobUrl") or raw.get("applyUrl") or "").strip()
                if not job_url:
                    continue
                job = {
                    "external_id": "ashby:" + str(raw.get("jobUrl") or job_url),
                    "source": "Ashby:" + board,
                    "source_url": job_url,
                    "title": str(raw.get("title") or "").strip(),
                    "company": board,
                    "location": loc,
                    "work_mode": "Remote" if "remote" in (loc + " " + desc).lower() else "",
                    "salary_min": None,
                    "salary_max": None,
                    "experience_min": app.extract_experience(desc),
                    "url": job_url,
                    "description": desc or str(raw.get("title") or ""),
                }
                if _relevant(job, query) and _location_ok(app, job, location, remote):
                    job["_query"] = query
                    rows.append(job)
        except Exception as exc:
            errors.append({"source": "Ashby:" + board, "error": str(exc)[:800]})
    return rows, errors


def search_public_sources(query, location="", remote=False):
    import app as applybot
    query = (query or "").strip() or "QA Automation Engineer"
    location = (location or "").strip() or "India"
    results, errors, status = [], [], []

    def status_item(source, found, configured, provider, raw=None, **extra):
        item = {"source": source, "found": int(found or 0), "raw_found": int(raw if raw is not None else found or 0), "configured": bool(configured), "provider": provider}
        item.update(extra)
        status.append(item)

    # A. Broad web/ATS discovery first. This is the new primary path.
    if BRAVE_ENABLED:
        try:
            selected, errs = _web_search_discovery(applybot, query, location, remote)
            results.extend(selected)
            errors.extend(errs)
            status_item("Career Web Search", len(selected), True, "Brave Search API + JobPosting JSON-LD", raw=len(selected), queries=_search_queries(query, location, remote))
        except Exception as exc:
            errors.append({"source": "Brave Search", "error": str(exc)[:1000]})
            status_item("Career Web Search", 0, True, "Brave Search API", raw=0)
    else:
        status_item("Career Web Search", 0, False, "Set BRAVE_SEARCH_API_KEY to enable broad career-site discovery", raw=0)

    # B. Direct ATS board APIs.
    if ASHBY_BOARDS:
        selected, errs = _ashby(applybot, query, location, remote)
        results.extend(selected)
        errors.extend(errs)
        status_item("Ashby", len(selected), True, "Ashby public Job Postings API", raw=len(selected), boards=len(ASHBY_BOARDS))
    else:
        status_item("Ashby", 0, False, "Configure ASHBY_BOARDS for direct ATS discovery", raw=0)

    # Greenhouse and Lever use the existing normalizers and configured public board/company slugs.
    if applybot.GREENHOUSE_BOARDS:
        raw_total = selected = 0
        for board in applybot.GREENHOUSE_BOARDS:
            try:
                data = applybot.fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", {"content": "true"}, timeout=applybot.JOBICY_TIMEOUT)
                jobs = applybot.normalize_greenhouse_jobs(data, board)
                raw_total += len(jobs)
                for job in jobs:
                    if _relevant(job, query) and _location_ok(applybot, job, location, remote):
                        job["_query"] = query
                        results.append(job); selected += 1
            except Exception as exc:
                errors.append({"source": "Greenhouse:" + board, "error": str(exc)[:700]})
        status_item("Greenhouse", selected, True, "Greenhouse public Job Board API", raw=raw_total, boards=len(applybot.GREENHOUSE_BOARDS))
    else:
        status_item("Greenhouse", 0, False, "Configure GREENHOUSE_BOARDS for direct ATS discovery", raw=0)

    if applybot.LEVER_COMPANIES:
        raw_total = selected = 0
        for company in applybot.LEVER_COMPANIES:
            try:
                data = applybot.fetch_json(f"https://api.lever.co/v0/postings/{company}", {"mode": "json", "limit": 100}, timeout=applybot.JOBICY_TIMEOUT)
                jobs = applybot.normalize_lever_jobs(data, company)
                raw_total += len(jobs)
                for job in jobs:
                    if _relevant(job, query) and _location_ok(applybot, job, location, remote):
                        job["_query"] = query
                        results.append(job); selected += 1
            except Exception as exc:
                errors.append({"source": "Lever:" + company, "error": str(exc)[:700]})
        status_item("Lever", selected, True, "Lever public Postings API", raw=raw_total, companies=len(applybot.LEVER_COMPANIES))
    else:
        status_item("Lever", 0, False, "Configure LEVER_COMPANIES for direct ATS discovery", raw=0)

    # C. Public aggregators are fallbacks, not the core.
    try:
        muse_raw = []
        for page in range(0, 5):
            data = applybot.fetch_json(
                "https://www.themuse.com/api/public/jobs",
                {"page": page, "location": location or "India", "descending": "true"},
                timeout=applybot.JOBICY_TIMEOUT,
            )
            page_rows = applybot.normalize_muse_jobs(data)
            if not page_rows:
                break
            muse_raw.extend(page_rows)
        selected = [j for j in _dedupe(applybot, muse_raw) if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
        for j in selected: j["_query"] = query
        results.extend(selected[:100])
        status_item("The Muse", len(selected), True, "The Muse public Jobs API", raw=len(muse_raw), pages=5)
    except Exception as exc:
        errors.append({"source": "The Muse", "error": str(exc)[:800]})
        status_item("The Muse", 0, True, "The Muse public Jobs API", raw=0)

    if applybot.REMOTEOK_ENABLED and (remote or location.lower() in {"remote", "anywhere", "worldwide", "global"}):
        try:
            raw = applybot.normalize_remoteok_jobs(applybot.fetch_json("https://remoteok.com/api", timeout=applybot.JOBICY_TIMEOUT))
            selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
            for j in selected: j["_query"] = query
            results.extend(selected[:100])
            status_item("RemoteOK", len(selected), True, "RemoteOK public API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "RemoteOK", "error": str(exc)[:800]})
            status_item("RemoteOK", 0, True, "RemoteOK public API", raw=0)

    # Jobicy is deliberately last: its public endpoint is currently returning
    # HTTP 400 for tag searches in the observed deployment, so it cannot be the
    # primary source.
    try:
        data = applybot.fetch_json(applybot.JOBICY_API_URL, {"count": min(applybot.JOBICY_COUNT, 100)}, timeout=applybot.JOBICY_TIMEOUT)
        raw = applybot.normalize_jobicy_jobs(data)
        selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
        for j in selected: j["_query"] = query
        results.extend(selected[:100])
        status_item("Jobicy", len(selected), True, "Jobicy public REST fallback", raw=len(raw))
    except Exception as exc:
        errors.append({"source": "Jobicy", "error": str(exc)[:800]})
        status_item("Jobicy", 0, True, "Jobicy public REST fallback", raw=0)

    if applybot.ADZUNA_APP_ID and applybot.ADZUNA_APP_KEY:
        try:
            data = applybot.fetch_json(
                "https://api.adzuna.com/v1/api/jobs/in/search/1",
                {"app_id": applybot.ADZUNA_APP_ID, "app_key": applybot.ADZUNA_APP_KEY, "results_per_page": 50, "what": query, "where": location, "content-type": "application/json", "sort_by": "date"},
                timeout=applybot.JOBICY_TIMEOUT,
            )
            raw = applybot.normalize_adzuna_jobs(data)
            selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
            for j in selected: j["_query"] = query
            results.extend(selected)
            status_item("Adzuna", len(selected), True, "Adzuna India API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "Adzuna", "error": str(exc)[:700]})
            status_item("Adzuna", 0, True, "Adzuna India API", raw=0)
    else:
        status_item("Adzuna", 0, False, "Optional app_id/app_key", raw=0)

    if applybot.INDIANAPI_KEY:
        try:
            data = applybot.fetch_json(applybot.INDIANAPI_URL, {"limit": "100", "title": query, "location": location}, headers={"X-Api-Key": applybot.INDIANAPI_KEY}, timeout=applybot.JOBICY_TIMEOUT)
            raw = applybot.normalize_indianapi_jobs(data)
            selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
            for j in selected: j["_query"] = query
            results.extend(selected)
            status_item("IndianAPI", len(selected), True, "IndianAPI Jobs API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "IndianAPI", "error": str(exc)[:700]})
            status_item("IndianAPI", 0, True, "IndianAPI Jobs API", raw=0)
    else:
        status_item("IndianAPI", 0, False, "Optional API key", raw=0)

    final = _dedupe(applybot, results)
    return final[:500], errors, status
