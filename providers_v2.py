"""ApplyBot discovery engine v2.

Provider strategy:
- Jobicy public REST: primary remote discovery.
- The Muse public Jobs API: secondary broad discovery, paginated.
- RemoteOK public API: remote-only fallback.
- Greenhouse/Lever public job-board APIs when board/company slugs are configured.
- Adzuna/Jobvetta/IndianAPI only when the user supplies credentials.

No RapidAPI/Indeed dependency is required for core discovery.
"""

import re


def _tokens(text):
    return {
        x for x in re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]*", (text or "").lower())
        if len(x) >= 2
    }


def _relevant(job, query):
    q = (query or "").strip().lower()
    if not q:
        return True
    title = (job.get("title") or "").lower()
    text = title + " " + (job.get("description") or "").lower()
    qt = _tokens(q)
    if not qt:
        return True

    # Strong title match.
    title_hits = len(qt & _tokens(title))
    if title_hits >= max(1, (len(qt) + 1) // 2):
        return True

    # Common QA role families.
    families = [
        ("qa", "quality assurance", "qa engineer", "quality engineer"),
        ("automation", "test automation", "automation tester", "automation engineer"),
        ("sdet", "software development engineer in test"),
        ("tester", "software tester", "test engineer", "qa tester"),
    ]
    q_compact = re.sub(r"[^a-z0-9 ]", " ", q)
    for family in families:
        if any(x in q_compact for x in family) and any(x in title for x in family):
            return True

    # Description match: require meaningful overlap rather than one incidental word.
    hits = sum(1 for token in qt if token in text)
    return hits >= max(2, min(3, len(qt)))


def _location_ok(applybot, job, location, remote):
    return applybot.location_matches(job, location, remote)


def _dedupe(items):
    out, seen = [], set()
    for job in items:
        if not job.get("title") or not job.get("company") or not job.get("url"):
            continue
        key = job.get("external_id") or applybot.job_fingerprint(job)
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def search_public_sources(query, location="", remote=False):
    # Import lazily so app.py can safely delegate to this module.
    import app as applybot

    query = (query or "").strip() or "QA Automation Engineer"
    location = (location or "").strip() or "India"

    results = []
    errors = []
    status = []

    def add_status(source, found, configured=True, provider="", raw=None, **extra):
        item = {
            "source": source,
            "found": int(found or 0),
            "raw_found": int(raw if raw is not None else found or 0),
            "configured": bool(configured),
            "provider": provider,
        }
        item.update(extra)
        status.append(item)

    # 1) Jobicy — public JSON, no key required.
    try:
        tags = applybot._jobicy_search_tags(query)
        raw_rows = []
        modes = []
        for tag in tags:
            attempts = []
            geo = applybot._jobicy_geo(location)
            if remote and not geo:
                geo = "anywhere"
            if geo:
                attempts.append(("tag+geo", {"count": min(applybot.JOBICY_COUNT, 100), "tag": tag, "geo": geo}))
            attempts.append(("tag", {"count": min(applybot.JOBICY_COUNT, 100), "tag": tag}))
            for mode, params in attempts:
                try:
                    headers = {}
                    if applybot.JOBICY_API_KEY:
                        headers["Authorization"] = "Bearer " + applybot.JOBICY_API_KEY
                    data = applybot.fetch_json(applybot.JOBICY_API_URL, params, headers=headers, timeout=applybot.JOBICY_TIMEOUT)
                    rows = applybot.normalize_jobicy_jobs(data)
                    raw_rows.extend(rows)
                    modes.append(tag + ":" + mode)
                    break
                except Exception as exc:
                    errors.append({"source": "Jobicy", "error": f"{tag}/{mode}: {str(exc)[:500]}"})
        filtered = []
        for job in _dedupe(raw_rows):
            if _relevant(job, query) and _location_ok(applybot, job, location, remote):
                job["_query"] = query
                filtered.append(job)
        results.extend(filtered[:200])
        add_status(
            "Jobicy", len(filtered), True,
            "Jobicy Commercial API" if applybot.JOBICY_API_KEY else "Jobicy Public REST API",
            raw=len(raw_rows), tags=tags, request_mode=",".join(modes) or "failed",
            direct_application_urls=bool(applybot.JOBICY_API_KEY),
        )
    except Exception as exc:
        errors.append({"source": "Jobicy", "error": str(exc)[:1000]})
        add_status("Jobicy", 0, True, "Jobicy Public REST API", raw=0)

    # 2) The Muse — public API. Fetch several pages so a noisy first page
    # doesn't make discovery appear empty.
    try:
        muse_raw = []
        pages = 5
        category = "Software Engineering"
        for page in range(pages):
            params = {
                "page": page,
                "location": location if location else "India",
                "category": category,
                "descending": "true",
            }
            if applybot.THEMUSE_API_KEY:
                params["api_key"] = applybot.THEMUSE_API_KEY
            data = applybot.fetch_json(
                "https://www.themuse.com/api/public/jobs",
                params,
                timeout=applybot.JOBICY_TIMEOUT,
            )
            rows = applybot.normalize_muse_jobs(data)
            if not rows:
                break
            muse_raw.extend(rows)
        selected = [
            j for j in _dedupe(muse_raw)
            if _relevant(j, query) and _location_ok(applybot, j, location, remote)
        ]
        for job in selected:
            job["_query"] = query
        results.extend(selected[:100])
        add_status(
            "The Muse", len(selected), True,
            "The Muse public Jobs API",
            raw=len(muse_raw), pages_checked=pages,
        )
    except Exception as exc:
        errors.append({"source": "The Muse", "error": str(exc)[:1000]})
        add_status("The Muse", 0, True, "The Muse public Jobs API", raw=0)

    # 3) RemoteOK — only query when the user wants remote/global work.
    if applybot.REMOTEOK_ENABLED and (
        remote or location.lower() in {"remote", "anywhere", "worldwide", "global"}
    ):
        try:
            raw = applybot.normalize_remoteok_jobs(
                applybot.fetch_json("https://remoteok.com/api", timeout=applybot.JOBICY_TIMEOUT)
            )
            selected = [
                j for j in _dedupe(raw)
                if _relevant(j, query) and _location_ok(applybot, j, location, remote)
            ]
            for job in selected:
                job["_query"] = query
            results.extend(selected[:100])
            add_status("RemoteOK", len(selected), True, "RemoteOK public API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "RemoteOK", "error": str(exc)[:1000]})
            add_status("RemoteOK", 0, True, "RemoteOK public API", raw=0)

    # 4) Employer ATS APIs. These are real structured job-board endpoints and
    # require only public board/company slugs for discovery.
    if applybot.GREENHOUSE_BOARDS:
        total_raw = 0
        selected = []
        for board in applybot.GREENHOUSE_BOARDS:
            try:
                data = applybot.fetch_json(
                    f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                    {"content": "true"},
                    headers={"Accept": "application/json"},
                    timeout=applybot.JOBICY_TIMEOUT,
                )
                rows = applybot.normalize_greenhouse_jobs(data, board)
                total_raw += len(rows)
                selected.extend(
                    j for j in rows
                    if _relevant(j, query) and _location_ok(applybot, j, location, remote)
                )
            except Exception as exc:
                errors.append({"source": "Greenhouse:" + board, "error": str(exc)[:800]})
        for job in selected:
            job["_query"] = query
        results.extend(selected[:100])
        add_status("Greenhouse", len(selected), True, "Greenhouse public Job Board API", raw=total_raw, boards=len(applybot.GREENHOUSE_BOARDS))
    else:
        add_status("Greenhouse", 0, False, "Configure GREENHOUSE_BOARDS for employer ATS discovery", raw=0)

    if applybot.LEVER_COMPANIES:
        total_raw = 0
        selected = []
        for company in applybot.LEVER_COMPANIES:
            try:
                data = applybot.fetch_json(
                    f"https://api.lever.co/v0/postings/{company}",
                    {"mode": "json", "limit": 100},
                    headers={"Accept": "application/json"},
                    timeout=applybot.JOBICY_TIMEOUT,
                )
                rows = applybot.normalize_lever_jobs(data, company)
                total_raw += len(rows)
                selected.extend(
                    j for j in rows
                    if _relevant(j, query) and _location_ok(applybot, j, location, remote)
                )
            except Exception as exc:
                errors.append({"source": "Lever:" + company, "error": str(exc)[:800]})
        for job in selected:
            job["_query"] = query
        results.extend(selected[:100])
        add_status("Lever", len(selected), True, "Lever public Postings API", raw=total_raw, companies=len(applybot.LEVER_COMPANIES))
    else:
        add_status("Lever", 0, False, "Configure LEVER_COMPANIES for employer ATS discovery", raw=0)

    # 5) Credentialed India providers remain optional.
    if applybot.JOBVETTA_API_KEY:
        try:
            data = applybot.fetch_json(
                applybot.JOBVETTA_API_URL,
                {"q": query, "location": location, "days": 30, "limit": 50},
                headers={"Authorization": "Bearer " + applybot.JOBVETTA_API_KEY},
                timeout=applybot.JOBICY_TIMEOUT,
            )
            raw = applybot.normalize_jobvetta_jobs(data)
            selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
            for job in selected:
                job["_query"] = query
            results.extend(selected)
            add_status("Jobvetta", len(selected), True, "Jobvetta API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "Jobvetta", "error": str(exc)[:800]})
            add_status("Jobvetta", 0, True, "Jobvetta API", raw=0)
    else:
        add_status("Jobvetta", 0, False, "Jobvetta API key required", raw=0)

    if applybot.INDIANAPI_KEY:
        try:
            data = applybot.fetch_json(
                applybot.INDIANAPI_URL,
                {"limit": "100", "title": query, "location": location},
                headers={"X-Api-Key": applybot.INDIANAPI_KEY},
                timeout=applybot.JOBICY_TIMEOUT,
            )
            raw = applybot.normalize_indianapi_jobs(data)
            selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
            for job in selected:
                job["_query"] = query
            results.extend(selected)
            add_status("IndianAPI", len(selected), True, "IndianAPI Jobs API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "IndianAPI", "error": str(exc)[:800]})
            add_status("IndianAPI", 0, True, "IndianAPI Jobs API", raw=0)
    else:
        add_status("IndianAPI", 0, False, "IndianAPI API key optional", raw=0)

    # Optional Adzuna if credentials are already configured.
    if applybot.ADZUNA_APP_ID and applybot.ADZUNA_APP_KEY:
        try:
            data = applybot.fetch_json(
                "https://api.adzuna.com/v1/api/jobs/in/search/1",
                {
                    "app_id": applybot.ADZUNA_APP_ID,
                    "app_key": applybot.ADZUNA_APP_KEY,
                    "results_per_page": 50,
                    "what": query,
                    "where": location,
                    "content-type": "application/json",
                    "sort_by": "date",
                },
                timeout=applybot.JOBICY_TIMEOUT,
            )
            raw = applybot.normalize_adzuna_jobs(data)
            selected = [j for j in raw if _relevant(j, query) and _location_ok(applybot, j, location, remote)]
            for job in selected:
                job["_query"] = query
            results.extend(selected)
            add_status("Adzuna", len(selected), True, "Adzuna API", raw=len(raw))
        except Exception as exc:
            errors.append({"source": "Adzuna", "error": str(exc)[:800]})
            add_status("Adzuna", 0, True, "Adzuna API", raw=0)

    final = _dedupe(results)
    for job in final:
        job["_query"] = query

    # Never allow a provider error to hide successful results.
    return final[:300], errors, status
