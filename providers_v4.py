"""ApplyBot v4 — free-first job discovery.

Primary source: a public MIT-licensed, daily-refreshed normalized dataset built
from nine public ATS job-board feeds. No API key, RapidAPI, Brave, RSS, login,
or browser automation is required for discovery.

Secondary source: providers_v3, which still supports direct ATS boards and public
fallbacks when configured.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.parse

FREE_DATASET_URL = os.getenv(
    "FREE_JOB_DATASET_URL",
    "https://cdn.jsdelivr.net/gh/ConorsCode/open-jobs-data@main/data/jobs.json",
).strip()
FREE_DATASET_FALLBACK_URLS = [
    FREE_DATASET_URL,
    "https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/data/jobs.json",
    "https://cdn.jsdelivr.net/gh/ConorsCode/open-jobs-data/main/data/jobs.json",
]
FREE_DATASET_ENABLED = os.getenv("FREE_JOB_DATASET_ENABLED", "true").lower() == "true"
FREE_DATASET_TIMEOUT = max(5, int(os.getenv("FREE_JOB_DATASET_TIMEOUT", "25")))
FREE_DATASET_CACHE_SECONDS = max(60, int(os.getenv("FREE_JOB_DATASET_CACHE_SECONDS", "900")))
_cache = {"at": 0.0, "jobs": None}


def _tokens(text):
    return {
        x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]*", (text or "").lower())
        if len(x) >= 2
    }


def _relevant(job, query):
    q = (query or "").lower().strip()
    if not q:
        return True
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    qt = _tokens(q)
    tt = _tokens(title)
    if not qt:
        return True
    if len(qt & tt) >= max(1, (len(qt) + 1) // 2):
        return True
    families = [
        ("qa", "quality assurance", "qa engineer", "quality engineer"),
        ("automation", "test automation", "automation tester", "automation engineer"),
        ("sdet", "software development engineer in test"),
        ("tester", "software tester", "test engineer", "qa tester"),
    ]
    for family in families:
        if any(x in q for x in family) and any(x in title for x in family):
            return True
    hits = sum(1 for token in qt if token in title + " " + desc)
    return hits >= max(2, min(3, len(qt)))


def _location_ok(job, location, remote):
    text = " ".join([
        str(job.get("location") or ""),
        str(job.get("description") or ""),
        str(job.get("work_mode") or ""),
    ]).lower()
    wanted = (location or "India").lower().strip()
    remote_flag = bool(job.get("work_mode") and "remote" in str(job["work_mode"]).lower())
    if remote and (remote_flag or "remote" in text or bool(job.get("is_remote"))):
        return True
    if wanted in {"remote", "anywhere", "worldwide", "global"}:
        return remote_flag or "remote" in text or bool(job.get("is_remote"))
    aliases = {
        "india": ("india", "bengaluru", "bangalore", "pune", "hyderabad", "delhi", "gurugram", "noida", "mumbai", "indore", "chennai", "kolkata"),
        "indore": ("indore",),
        "bangalore": ("bangalore", "bengaluru"),
        "bengaluru": ("bangalore", "bengaluru"),
        "pune": ("pune",),
        "hyderabad": ("hyderabad",),
    }
    needles = aliases.get(wanted, (wanted,))
    return any(n in text for n in needles) or (remote and "remote" in text)


def _normalize(row):
    locations = row.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]
    location = ", ".join(str(x) for x in locations if x) or "Unspecified"
    apply_url = str(row.get("applyUrl") or "").strip()
    if not apply_url:
        return None
    title = str(row.get("title") or "").strip()
    company = str(row.get("company") or "").strip()
    if not title or not company:
        return None
    platform = str(row.get("platform") or "ATS").strip().lower()
    job_id = str(row.get("jobId") or apply_url)
    remote = row.get("isRemote")
    work_mode = "Remote" if remote is True or "remote" in location.lower() else ""
    return {
        "external_id": f"free-ats:{platform}:{job_id}",
        "source": f"Free ATS Dataset ({platform})",
        "source_url": apply_url,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": work_mode,
        "salary_min": None,
        "salary_max": None,
        "experience_min": None,
        "url": apply_url,
        "description": " ".join(
            str(x) for x in [row.get("department"), row.get("employmentType"), location]
            if x
        ) or title,
        "posted_at": str(row.get("postedAt") or row.get("scrapedAt") or ""),
        "employment_type": str(row.get("employmentType") or ""),
        "ats_platform": platform,
        "is_remote": remote,
    }


def _fetch_dataset():
    now = time.time()
    if _cache["jobs"] is not None and now - _cache["at"] < FREE_DATASET_CACHE_SECONDS:
        return _cache["jobs"], None

    last_error = None
    seen_urls = set()
    for url in FREE_DATASET_FALLBACK_URLS:
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "ApplyBot/5.0 (+public-job-discovery)",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=FREE_DATASET_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("free ATS dataset did not return a JSON array")

            rows = []
            for raw in payload:
                job = _normalize(raw)
                if job:
                    rows.append(job)

            if rows:
                _cache.update({"at": now, "jobs": rows})
                return rows, None
            last_error = ValueError("free ATS dataset returned zero usable jobs")
        except Exception as exc:
            last_error = exc

    if _cache["jobs"] is not None:
        return _cache["jobs"], "Using stale cached free ATS data after upstream fetch failure"

    raise RuntimeError(
        "Free ATS discovery is temporarily unavailable. "
        f"Tried {len(seen_urls)} public endpoints. Last error: {last_error}"
    )


def _dedupe(jobs):
    out, seen = [], set()
    for job in jobs:
        key = job.get("external_id") or job.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def _live_job_matches(job, query):
    """Match a live listing against the requested role without requiring an exact title."""
    q = (query or "").strip().lower()
    if not q:
        return True
    title = str(job.get("title") or "").lower()
    description = str(job.get("description") or "").lower()
    text = title + " " + description
    qt = _tokens(q)
    if not qt:
        return True

    # Strong role-family matching for common QA/search terms.
    families = [
        ("qa", ("qa", "quality assurance", "qa engineer", "quality engineer")),
        ("automation", ("automation", "test automation", "automation tester", "automation engineer")),
        ("sdet", ("sdet", "software development engineer in test")),
        ("tester", ("tester", "software tester", "test engineer", "qa tester", "testing")),
    ]
    requested_families = []
    for key, phrases in families:
        if any(p in q for p in phrases):
            requested_families.append(key)

    if requested_families:
        for key, phrases in families:
            if key in requested_families and any(p in title for p in phrases):
                return True

    title_hits = len(qt & _tokens(title))
    text_hits = sum(1 for token in qt if token in text)
    if len(qt) == 1:
        return next(iter(qt)) in text
    return title_hits >= max(1, (len(qt) + 1) // 2) or text_hits >= max(2, min(3, len(qt)))


def _live_location_matches(job, location, remote=False):
    """Match requested city/state/country using published location/work-mode text."""
    wanted = (location or "").strip().lower()
    loc = str(job.get("location") or "").lower()
    desc = str(job.get("description") or "").lower()
    mode = str(job.get("work_mode") or "").lower()
    text = " ".join((loc, desc, mode))

    if remote:
        return "remote" in text or bool(job.get("is_remote"))

    if not wanted:
        return True

    if wanted in {"remote", "anywhere", "worldwide", "global"}:
        return "remote" in text or bool(job.get("is_remote"))

    aliases = {
        "india": ("india", "indian", "bengaluru", "bangalore", "pune", "hyderabad", "mumbai",
                  "delhi", "new delhi", "noida", "gurugram", "gurgaon", "chennai", "kolkata",
                  "indore", "bhopal", "jaipur", "ahmedabad", "kochi"),
        "bengaluru": ("bengaluru", "bangalore"),
        "bangalore": ("bengaluru", "bangalore"),
        "mumbai": ("mumbai",),
        "delhi": ("delhi", "new delhi"),
        "gurugram": ("gurugram", "gurgaon"),
        "gurgaon": ("gurugram", "gurgaon"),
        "noida": ("noida",),
        "hyderabad": ("hyderabad",),
        "pune": ("pune",),
        "chennai": ("chennai",),
        "kolkata": ("kolkata",),
        "indore": ("indore",),
        "bhopal": ("bhopal",),
        "jaipur": ("jaipur",),
        "ahmedabad": ("ahmedabad",),
        "kochi": ("kochi", "cochin"),
    }
    needles = aliases.get(wanted, (wanted,))
    if any(n in loc for n in needles):
        return True

    # Country-wide searches can accept clearly country-wide/remote postings.
    if wanted in {"india", "ind"} and any(x in text for x in ("apac", "asia", "south asia", "remote")):
        return True

    return False


def _normalize_arbeitnow(raw):
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    company = str(raw.get("company_name") or raw.get("company") or "Unknown").strip()
    location = str(raw.get("location") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not title or not url:
        return None
    description = re.sub(r"<[^>]+>", " ", str(raw.get("description") or "")).strip()
    remote = bool(raw.get("remote")) or "remote" in (location + " " + description).lower()
    return {
        "external_id": "arbeitnow:" + str(raw.get("slug") or raw.get("id") or url),
        "source": "Arbeitnow Live",
        "source_url": url,
        "title": title,
        "company": company,
        "location": location or ("Remote" if remote else "Unspecified"),
        "work_mode": "Remote" if remote else "",
        "salary_min": None,
        "salary_max": None,
        "experience_min": None,
        "url": url,
        "description": description or title,
        "employment_type": str(raw.get("job_types") or raw.get("job_type") or ""),
        "posted_at": str(raw.get("created_at") or raw.get("date") or ""),
        "is_remote": remote,
    }


def _fetch_live_arbeitnow(query, location, remote):
    results, errors = [], []
    # Arbeitnow exposes a public job-board API. We inspect several fresh pages
    # because a single page can easily miss a requested city.
    for page in range(1, 6):
        try:
            url = "https://www.arbeitnow.com/api/job-board-api?page=" + str(page)
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "ApplyBot/6.0 (+live job discovery)",
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            if not rows:
                break
            for raw in rows:
                job = _normalize_arbeitnow(raw)
                if job and _live_job_matches(job, query) and _live_location_matches(job, location, remote):
                    job["_query"] = query
                    results.append(job)
            meta = payload.get("meta") if isinstance(payload, dict) else {}
            if not isinstance(meta, dict) or not meta.get("has_more_pages"):
                break
        except Exception as exc:
            errors.append("page %d: %s" % (page, str(exc)[:500]))
            break
    return _dedupe(results), errors


def _normalize_remotive_live(raw):
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    company = str(raw.get("company_name") or "Unknown").strip()
    url = str(raw.get("url") or "").strip()
    if not title or not url:
        return None
    description = re.sub(r"<[^>]+>", " ", str(raw.get("description") or "")).strip()
    location = str(raw.get("candidate_required_location") or "Remote").strip()
    return {
        "external_id": "remotive:" + str(raw.get("id") or url),
        "source": "Remotive Live",
        "source_url": url,
        "title": title,
        "company": company,
        "location": location,
        "work_mode": "Remote",
        "salary_min": None,
        "salary_max": None,
        "experience_min": None,
        "url": url,
        "description": description or title,
        "employment_type": str(raw.get("job_type") or ""),
        "posted_at": str(raw.get("publication_date") or ""),
        "is_remote": True,
    }


def _fetch_live_remote(query):
    results, errors = [], []
    endpoints = [
        "https://remotive.com/api/remote-jobs?search=" + urllib.parse.quote(query),
        "https://remoteok.com/api",
    ]
    for endpoint in endpoints:
        try:
            req = urllib.request.Request(
                endpoint,
                headers={"User-Agent": "ApplyBot/6.0 (+live remote job discovery)", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if "remotive.com" in endpoint:
                rows = payload.get("jobs", []) if isinstance(payload, dict) else []
                for raw in rows:
                    job = _normalize_remotive_live(raw)
                    if job and _live_job_matches(job, query):
                        job["_query"] = query
                        results.append(job)
            else:
                rows = payload if isinstance(payload, list) else []
                for raw in rows:
                    title = str(raw.get("position") or "").strip() if isinstance(raw, dict) else ""
                    url = str(raw.get("url") or "").strip() if isinstance(raw, dict) else ""
                    if not title or not url:
                        continue
                    description = re.sub(r"<[^>]+>", " ", str(raw.get("description") or "")).strip()
                    job = {
                        "external_id": "remoteok:" + str(raw.get("id") or url),
                        "source": "RemoteOK Live",
                        "source_url": url,
                        "title": title,
                        "company": str(raw.get("company") or "Unknown").strip(),
                        "location": str(raw.get("location") or "Worldwide").strip(),
                        "work_mode": "Remote",
                        "salary_min": None,
                        "salary_max": None,
                        "experience_min": None,
                        "url": url,
                        "description": description or title,
                        "is_remote": True,
                    }
                    if _live_job_matches(job, query):
                        job["_query"] = query
                        results.append(job)
        except Exception as exc:
            errors.append(endpoint.split("/")[2] + ": " + str(exc)[:500])
    return _dedupe(results), errors



def _normalize_hopin(raw, source_name="Hopin Live"):
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    company = str(raw.get("company") or "Unknown").strip()
    location = str(raw.get("location") or "").strip()
    if not title or not location:
        return None
    description = str(raw.get("description") or "").strip()
    ctc = str(raw.get("ctc_amount") or "").strip()
    text = " ".join((title, description, ctc))
    return {
        "external_id": "hopin:" + str(raw.get("id") or (company + "|" + title + "|" + location)),
        "source": source_name,
        "source_url": str(raw.get("url") or raw.get("application_url") or "https://hopinjobs.com").strip(),
        "title": title,
        "company": company,
        "location": location,
        "work_mode": str(raw.get("work_type") or ""),
        "salary_min": None,
        "salary_max": None,
        "experience_min": 0.0 if any(x in text.lower() for x in ("fresher", "entry level", "entry-level", "graduate", "0-2", "0 - 2")) else None,
        "url": str(raw.get("url") or raw.get("application_url") or "https://hopinjobs.com").strip(),
        "description": (description + " " + ctc).strip() or title,
        "employment_type": str(raw.get("job_type") or ""),
        "posted_at": str(raw.get("posted_at") or ""),
        "is_remote": "remote" in (location + " " + str(raw.get("work_type") or "")).lower(),
    }


def _hopin_filter_value(location):
    wanted = (location or "").strip().lower()
    if not wanted:
        return None
    try:
        req = urllib.request.Request(
            "https://api.hopinjobs.com/api/filters",
            headers={"User-Agent": "ApplyBot/6.0 (+live India job discovery)", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        values = ((payload.get("filters") or {}).get("location") or []) if isinstance(payload, dict) else []
        candidates = []
        for item in values:
            if isinstance(item, dict):
                value = str(item.get("filter_value") or "")
                label = str(item.get("display_label") or value)
            else:
                value = label = str(item)
            if not value:
                continue
            low = (value + " " + label).lower()
            if wanted == value.lower() or wanted == label.lower():
                return value
            if wanted in low:
                candidates.append(value)
        return candidates[0] if candidates else None
    except Exception:
        return None


def _fetch_live_hopin(query, location, remote):
    results, errors = [], []
    requested = (location or "").strip()
    filter_value = _hopin_filter_value(requested)
    base = "https://api.hopinjobs.com/api/jobs"
    params = {"is_unofficial": "true"}
    if filter_value and requested.lower() not in {"remote", "anywhere", "worldwide", "global"}:
        params["location"] = filter_value
    if remote or requested.lower() in {"remote", "anywhere", "worldwide", "global"}:
        params["work_type"] = "Remote"

    for endpoint_name, path in (("Hopin jobs", "/api/jobs"), ("Hopin internships", "/api/internships")):
        try:
            query_params = dict(params)
            url = "https://api.hopinjobs.com" + path + "?" + urllib.parse.urlencode(query_params)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ApplyBot/6.0 (+live India job discovery)", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            key = "jobs" if path.endswith("/jobs") else "internships"
            rows = payload.get(key, []) if isinstance(payload, dict) else []
            for raw in rows:
                job = _normalize_hopin(raw, endpoint_name)
                if not job:
                    continue
                if _live_job_matches(job, query) and _live_location_matches(job, requested, remote):
                    job["_query"] = query
                    results.append(job)
        except Exception as exc:
            errors.append(endpoint_name + ": " + str(exc)[:500])

    return _dedupe(results), errors, filter_value



def _dataset_status(selected, raw_count):
    return {
        "source": "Free ATS Dataset",
        "found": len(selected),
        "raw_found": raw_count,
        "configured": True,
        "provider": "Public daily-updated dataset from Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee, Personio and BambooHR",
    }


def search_public_sources(query, location="", remote=False):
    """Search live location-aware feeds first, then use the ATS snapshot as fallback.

    Live sources are intentionally additive: if a live provider is temporarily
    unavailable, the daily ATS dataset still gives the user useful results.
    """
    query = (query or "").strip() or "QA Automation Engineer"
    location = (location or "").strip() or "India"
    results, errors, status = [], [], []

    # India-first live source with server-side city/location filtering.
    hopin, hopin_errors, hopin_filter = _fetch_live_hopin(query, location, remote)
    results.extend(hopin)
    errors.extend({"source": "Hopin", "error": e} for e in hopin_errors)
    status.append({
        "source": "Hopin Live",
        "found": len(hopin),
        "raw_found": len(hopin),
        "configured": True,
        "provider": "Public live India jobs + internships API",
        "location_filter": hopin_filter or "local text matching",
        "fresh": True,
    })

    # Additional live public feed. This is especially useful for international
    # locations, while the Hopin feed is strongest for Indian fresher roles.
    arbeit, arbeit_errors = _fetch_live_arbeitnow(query, location, remote)
    results.extend(arbeit)
    errors.extend({"source": "Arbeitnow", "error": e} for e in arbeit_errors)
    status.append({
        "source": "Arbeitnow Live",
        "found": len(arbeit),
        "raw_found": len(arbeit),
        "configured": True,
        "provider": "Public live job-board API",
        "location_search": location,
        "fresh": True,
    })

    if remote or location.lower() in {"remote", "anywhere", "worldwide", "global"}:
        remote_jobs, remote_errors = _fetch_live_remote(query)
        results.extend(remote_jobs)
        errors.extend({"source": "Remote feeds", "error": e} for e in remote_errors)
        status.append({
            "source": "Remote Live",
            "found": len(remote_jobs),
            "raw_found": len(remote_jobs),
            "configured": True,
            "provider": "Remotive + RemoteOK public APIs",
            "fresh": True,
        })

    # Daily normalized ATS data is retained as a fallback/backfill.
    if FREE_DATASET_ENABLED:
        try:
            raw, stale_note = _fetch_dataset()
            selected = [
                j for j in raw
                if _relevant(j, query) and _location_ok(j, location, remote)
            ]
            for j in selected:
                j["_query"] = query
            results.extend(selected[:500])
            status.append(_dataset_status(selected, len(raw)))
            if stale_note:
                status[-1]["note"] = stale_note
        except Exception as exc:
            errors.append({"source": "Free ATS Dataset", "error": str(exc)[:800]})
            status.append(_dataset_status([], 0))

    final = _dedupe(results)
    return final[:1000], errors, status
