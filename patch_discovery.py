from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

if 'THEMUSE_ENABLED = os.getenv("THEMUSE_ENABLED"' not in s:
    s = s.replace(
        'THEMUSE_API_KEY = os.getenv("THEMUSE_API_KEY", "").strip()',
        'THEMUSE_API_KEY = os.getenv("THEMUSE_API_KEY", "").strip()\nTHEMUSE_ENABLED = os.getenv("THEMUSE_ENABLED", "false").lower() == "true"',
        1,
    )

start = s.index("def search_additional_providers(")
end = s.index("\n\ndef _jobicy_geo", start)

replacement = '''def normalize_muse_jobs(data):
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
'''
s = s[:start] + replacement + s[end:]

old = '''def run_discovery(body):
    query = str(body.get("query") or "QA Automation Engineer").strip()
    location = str(body.get("location") or "India").strip()
    remote = bool(body.get("remote", False))
    threshold = float(body.get("threshold", 70))
    max_experience = float(body.get("max_experience", 2))
    min_salary = max(float(body.get("min_salary", 3)), CANDIDATE["minimum_ctc_lpa"])
    items, errors, source_status = search_public_sources(query, location, remote)
    results = import_job_items(items)
'''
new = '''def run_discovery(body):
    query = str(body.get("query") or "QA Automation Engineer").strip()
    location = str(body.get("location") or "India").strip()
    remote = bool(body.get("remote", False))
    threshold = float(body.get("threshold", 70))
    max_experience = float(body.get("max_experience", 2))
    min_salary = max(float(body.get("min_salary", 3)), CANDIDATE["minimum_ctc_lpa"])
    items, errors, source_status = search_public_sources(query, location, remote)
    try:
        results = import_job_items(items)
    except Exception as exc:
        errors.append({"source": "database", "error": str(exc)[:1500]})
        results = []
'''
if old not in s:
    raise SystemExit("run_discovery anchor not found")
s = s.replace(old, new, 1)

if '"TheMuse": THEMUSE_ENABLED' not in s:
    s = s.replace('"RemoteOK": REMOTEOK_ENABLED,', '"RemoteOK": REMOTEOK_ENABLED,\n            "TheMuse": THEMUSE_ENABLED,', 1)

marker = '@app.get("/api/provider-check")'
if 'def discovery_diagnostics()' not in s:
    diagnostic = '''@app.get("/api/discovery-diagnostics")
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


'''
    s = s.replace(marker, diagnostic + marker, 1)

p.write_text(s, encoding="utf-8")
print("ApplyBot discovery patch applied")
