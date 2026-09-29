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


def search_public_sources(query, location="", remote=False):
    query = (query or "").strip() or "QA Automation Engineer"
    location = (location or "").strip() or "India"
    results, errors, status = [], [], []

    if FREE_DATASET_ENABLED:
        try:
            raw, _ = _fetch_dataset()
            selected = [
                j for j in raw
                if _relevant(j, query) and _location_ok(j, location, remote)
            ]
            for j in selected:
                j["_query"] = query
            results.extend(selected[:500])
            status.append({
                "source": "Free ATS Dataset",
                "found": len(selected),
                "raw_found": len(raw),
                "configured": True,
                "provider": "Public daily-updated dataset from Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee, Personio and BambooHR",
            })
        except Exception as exc:
            errors.append({"source": "Free ATS Dataset", "error": str(exc)[:800]})
            status.append({
                "source": "Free ATS Dataset",
                "found": 0,
                "raw_found": 0,
                "configured": True,
                "provider": "Public GitHub JSON dataset",
            })
    else:
        status.append({
            "source": "Free ATS Dataset",
            "found": 0,
            "raw_found": 0,
            "configured": False,
            "provider": "Disabled",
        })

    # v4 is intentionally self-contained. Do not import providers_v3 here:
    # legacy providers can have optional dependencies, slow network calls, or
    # stale APIs and must never be able to break the free discovery path.
    status.append({
        "source": "Legacy Providers",
        "found": 0,
        "raw_found": 0,
        "configured": False,
        "provider": "Disabled in free-first discovery path",
    })

    return _dedupe(results)[:500], errors, status
