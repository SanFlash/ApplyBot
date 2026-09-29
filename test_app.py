from pathlib import Path

from app import app, init_db
import app as applybot


def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    monkeypatch.setattr(applybot, "DATABASE_URL", "")
    monkeypatch.setattr(applybot, "SQLITE_DB", Path(db_path))
    init_db()
    return app.test_client()


def test_health(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json["status"] == "ok"
    assert r.json["database"] == "sqlite"


def test_import_and_filter(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    good = {
        "external_id": "g1", "source": "Jobicy", "title": "QA Automation Engineer",
        "company": "Example", "location": "Bangalore", "work_mode": "Hybrid",
        "salary_min": 4, "salary_max": 6, "experience_min": 2,
        "url": "https://example.com/1", "description": "Playwright Python SQL API testing",
    }
    bad = {**good, "external_id": "b1", "source": "Jobicy", "title": "Senior SDET", "experience_min": 4}
    r = client.post("/api/jobs/import", json={"jobs": [good, bad]})
    assert r.status_code == 200
    jobs = client.get("/api/jobs").json
    assert any(x["status"] == "ready" for x in jobs)
    assert any(x["status"] == "skipped" for x in jobs)


def test_prepare_and_status(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    job = {
        "external_id": "g1", "source": "Jobicy", "title": "SDET", "company": "Example",
        "location": "Pune", "work_mode": "Hybrid", "salary_min": 4, "salary_max": 6,
        "experience_min": 1, "url": "https://example.com/1",
        "description": "Playwright Python SQL API testing",
    }
    client.post("/api/jobs/import", json={"jobs": [job]})
    j = client.get("/api/jobs").json[0]
    r = client.post(f"/api/jobs/{j['id']}/prepare")
    assert r.status_code == 200
    assert r.json["application_id"]
    appid = r.json["application_id"]
    r = client.post(f"/api/applications/{appid}/status", json={"status": "approved"})
    assert r.status_code == 200


def test_database_initialization_uses_valid_sqlite_identity_columns(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    conn = applybot.sqlite3.connect(applybot.SQLITE_DB)
    columns = {
        row[1]: row[5]
        for table in ("jobs", "applications")
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    conn.close()
    assert columns["id"] == 1


def test_search_links_now_describe_in_app_mode(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    r = client.get("/api/search-links?query=QA%20Automation%20Engineer&location=India&remote=true")
    assert r.status_code == 200
    assert r.json["mode"] == "in_app"
    assert r.json["query"] == "QA Automation Engineer"
    assert r.json["location"] == "India"
    assert r.json["remote"] is True
    assert "inside the application" in r.json["note"]


def test_location_matches_india_and_remote():
    assert applybot.location_matches({"location": "Bengaluru, India", "description": ""}, "India")
    assert applybot.location_matches({"location": "Worldwide", "work_mode": "Remote", "description": ""}, "India", True)
    assert not applybot.location_matches({"location": "Berlin, Germany", "description": ""}, "India")


def test_normalize_remotive_job():
    jobs = applybot.normalize_remotive_jobs({
        "jobs": [{
            "id": 123,
            "title": "QA Automation Engineer",
            "company_name": "Example",
            "candidate_required_location": "India",
            "salary": "$40,000 - $50,000",
            "url": "https://remotive.com/remote-jobs/example/qa-automation-engineer-123",
            "description": "<p>Playwright Python API testing</p>",
        }]
    })
    assert jobs[0]["external_id"] == "remotive:123"
    assert jobs[0]["company"] == "Example"
    assert jobs[0]["work_mode"] == "Remote"
    assert jobs[0]["salary_min"] is None


def test_manual_job_import_from_user_assisted_source(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    job = {
        "title": "QA Automation Engineer",
        "company": "Example",
        "location": "Indore",
        "work_mode": "Hybrid",
        "url": "https://www.linkedin.com/jobs/view/example-123",
        "description": "QA Automation Engineer, 1 year experience, Playwright, Python, API testing, 4-6 LPA",
    }
    r = client.post("/api/jobs/manual", json=job)
    assert r.status_code == 200
    assert r.json["imported"] == 1
    jobs = client.get("/api/jobs").json
    assert jobs[0]["source"] == "user-assisted"
    assert jobs[0]["status"] == "ready"


def test_discover_search_uses_server_side_sources(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)

    def fake_search(query, location="", remote=False):
        return ([{
            "external_id": "remotive:999",
            "source": "Remotive",
            "title": "QA Automation Engineer",
            "company": "Example Remote",
            "location": "India",
            "work_mode": "Remote",
            "salary_min": None,
            "salary_max": None,
            "url": "https://remotive.com/remote-jobs/example/qa-automation-engineer-999",
            "description": "Playwright Python API testing, 1 year experience, 4-6 LPA",
        }], [], [{"source": "Remotive", "found": 1, "configured": True}])

    monkeypatch.setattr(applybot, "search_public_sources", fake_search)
    r = client.post("/api/discover/search", json={"query": "QA Automation Engineer", "location": "India", "remote": True})
    assert r.status_code == 200
    assert r.json["mode"] == "in_app"
    assert r.json["items_seen"] == 1
    assert r.json["new_jobs"] == 1
    assert len(client.get("/api/jobs").json) == 1




def test_discover_search_uses_threshold_and_returns_job_ids(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)

    def fake_search(query, location="", remote=False):
        return ([{
            "external_id": "job:999",
            "source": "Jobicy",
            "title": "QA Automation Engineer",
            "company": "Example",
            "location": "Indore",
            "work_mode": "Hybrid",
            "salary_min": 4,
            "salary_max": 6,
            "experience_min": 1,
            "url": "https://example.com/jobs/999",
            "description": "Playwright Python API testing",
        }], [], [{"source": "test-api", "found": 1, "configured": True}])

    monkeypatch.setattr(applybot, "search_public_sources", fake_search)
    r = client.post("/api/discover/search", json={
        "query": "QA Automation Engineer",
        "location": "Indore",
        "remote": False,
        "threshold": 70,
    })
    assert r.status_code == 200
    assert r.json["mode"] == "in_app"
    assert r.json["qualified_jobs"] == 1
    assert r.json["results"][0]["job_id"]


def test_auto_apply_is_threshold_gated(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    job = {
        "external_id": "threshold-1",
        "source": "Jobicy",
        "title": "QA Automation Engineer",
        "company": "Example",
        "location": "Indore",
        "work_mode": "Hybrid",
        "salary_min": 4,
        "salary_max": 6,
        "experience_min": 1,
        "url": "https://example.com/jobs/threshold-1",
        "description": "QA Automation Engineer, 1 year experience, 4-6 LPA",
    }
    client.post("/api/jobs/import", json={"jobs": [job]})
    job_row = client.get("/api/jobs").json[0]
    r = client.post(f"/api/jobs/{job_row['id']}/auto-apply", json={"threshold": 99})
    assert r.status_code == 200
    assert r.json["status"] == "below_threshold"
    assert r.json["status"] == "below_threshold"


def test_supported_adapter_detection():
    assert applybot.detect_application_adapter("https://boards.greenhouse.io/example/jobs/123") == "greenhouse"
    assert applybot.detect_application_adapter("https://jobs.lever.co/example/abc/apply") == "lever"
    assert applybot.detect_application_adapter("https://example.com/jobs/123") == "unsupported"


def test_auto_apply_prepares_when_disabled(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr(applybot, "AUTO_APPLY_ENABLED", False)
    job = {
        "external_id": "auto-1",
        "source": "Jobicy",
        "title": "QA Automation Engineer",
        "company": "Example",
        "location": "Indore",
        "work_mode": "Hybrid",
        "salary_min": 4,
        "salary_max": 6,
        "experience_min": 1,
        "url": "https://boards.greenhouse.io/example/jobs/123",
        "description": "Playwright Python API testing",
    }
    client.post("/api/jobs/import", json={"jobs": [job]})
    row = client.get("/api/jobs").json[0]
    r = client.post(f"/api/jobs/{row['id']}/auto-apply", json={"threshold": 70})
    assert r.status_code == 200
    assert r.json["status"] == "application_ready"
    assert r.json["submitted"] is False

def test_normalize_jobicy_job():
    jobs = applybot.normalize_jobicy_jobs({
        "jobs": [{
            "id": 123,
            "jobTitle": "QA Automation Engineer",
            "companyName": "Example",
            "jobGeo": "India",
            "jobDescription": "<p>1 year experience with Playwright and Python.</p>",
            "url": "https://jobicy.com/jobs/example",
            "salaryMin": 400000,
            "salaryMax": 600000,
            "salaryCurrency": "INR",
            "jobType": ["full-time"],
        }]
    })
    assert jobs[0]["source"] == "Jobicy"
    assert jobs[0]["title"] == "QA Automation Engineer"
    assert jobs[0]["salary_min"] == 4
    assert jobs[0]["salary_max"] == 6
    assert jobs[0]["experience_min"] == 1
    assert jobs[0]["source_url"].startswith("https://jobicy.com/")


def test_jobicy_search_tag_prefers_qa():
    assert applybot._jobicy_search_tag("QA Automation Engineer") == "qa"


def test_jobicy_search_tags_expand_qa_recall():
    assert applybot._jobicy_search_tags("QA Automation Engineer") == ["qa", "automation", "sdet"]


def test_job_query_filter_rejects_unrelated_qa_tag_results():
    unrelated = {
        "title": "Director of Product Management - US Remote",
        "description": "Product strategy, roadmaps, stakeholder management.",
    }
    relevant = {
        "title": "Senior QA Automation Engineer",
        "description": "Playwright, Python, API testing and CI/CD.",
    }
    assert not applybot.job_matches_query(unrelated, "QA Automation Engineer")
    assert applybot.job_matches_query(relevant, "QA Automation Engineer")


def test_jobicy_provider_is_public(monkeypatch):
    def fake_fetch(url, params, **kwargs):
        assert "jobicy.com/api/v2/remote-jobs" in url
        if "tag" in params:
            assert params["tag"] == "qa"
        return {"jobs": []}
    monkeypatch.setattr(applybot, "fetch_json", fake_fetch)
    jobs, errors, status = applybot.search_jobicy_jobs("QA Automation Engineer", "India")
    assert jobs == []
    assert errors == []
    assert status[0]["source"] == "Jobicy"
    assert status[0]["configured"] is True


def test_jobicy_india_match_can_use_description_country_list():
    job = {
        "location": "UK, USA, Canada +11 more",
        "description": "Eligible countries include India, Ireland and Portugal.",
        "work_mode": "Remote",
    }
    assert applybot.location_matches(job, "India")
    assert applybot.location_matches(job, "India", True)


def test_score_job_accepts_remote_anywhere_for_india():
    job = {
        "title": "QA Automation Engineer",
        "company": "Remote Example",
        "location": "Anywhere",
        "work_mode": "Remote",
        "experience_min": 1,
        "salary_min": None,
        "salary_max": None,
        "url": "https://example.com/job/remote-anywhere",
        "description": "Playwright Python API testing",
        "_query": "QA Automation Engineer",
    }
    score, reasons, matched = applybot.score_job(job)
    assert score >= 57
    assert "Location matches preferences" in reasons
    assert "Playwright" in matched


def test_jobicy_anywhere_is_valid_for_india():
    job = {"location": "Anywhere", "description": "", "work_mode": "Remote"}
    assert applybot.location_matches(job, "India")
    assert applybot.location_matches(job, "India", True)


def test_discovery_duplicate_import_does_not_abort_transaction(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)

    def fake_search(query, location="", remote=False):
        return ([{
            "external_id": "duplicate-1",
            "source": "Jobicy",
            "title": "QA Automation Engineer",
            "company": "Example",
            "location": "Indore",
            "work_mode": "Hybrid",
            "salary_min": 4,
            "salary_max": 6,
            "experience_min": 1,
            "url": "https://example.com/jobs/duplicate-1",
            "description": "Playwright Python API testing, 1 year experience",
        }], [], [{"source": "Jobicy", "found": 1, "configured": True}])

    monkeypatch.setattr(applybot, "search_public_sources", fake_search)

    first = client.post("/api/discover", json={
        "query": "QA Automation Engineer", "location": "Indore",
        "threshold": 50, "max_experience": 2, "min_salary": 3,
    })
    second = client.post("/api/discover", json={
        "query": "QA Automation Engineer", "location": "Indore",
        "threshold": 50, "max_experience": 2, "min_salary": 3,
    })

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json["qualified_jobs"] == 1
    assert second.json["qualified_jobs"] == 1
    assert not any(e.get("source") == "database" for e in second.json.get("errors", []))
    assert len(client.get("/api/jobs").json) == 1


def test_normalize_indeed_job():
    jobs = applybot.normalize_indeed_jobs({
        "jobs": [{
            "jobKey": "indeed-123",
            "title": "QA Automation Engineer",
            "company": "Example India",
            "location": "Indore, Madhya Pradesh",
            "remote": "Hybrid work",
            "salary": {"min": 10000, "max": 14000, "type": "YEARLY", "text": "$10,000 - $14,000 a year"},
            "snippet": "Playwright Python API testing, 1 year experience.",
            "applyUrl": "https://www.indeed.com/viewjob?jk=indeed-123",
            "thirdPartyApplyUrl": "https://example.com/careers/qa-123",
            "jobTypes": ["Full-time"],
            "indeedApplyEnabled": True,
        }]
    })
    assert len(jobs) == 1
    assert jobs[0]["external_id"] == "indeed:indeed-123"
    assert jobs[0]["source"] == "Indeed RapidAPI"
    assert jobs[0]["url"] == "https://example.com/careers/qa-123"
    assert jobs[0]["source_url"].startswith("https://www.indeed.com/")
    assert jobs[0]["salary_min"] is None  # USD is not treated as INR/LPA by default
    assert jobs[0]["work_mode"] == "Hybrid"


def test_indeed_provider_queries_pages_and_deduplicates(monkeypatch):
    monkeypatch.setattr(applybot, "INDEED_RAPIDAPI_ENABLED", True)
    monkeypatch.setattr(applybot, "INDEED_RAPIDAPI_KEY", "test-key")
    monkeypatch.setattr(applybot, "INDEED_MAX_QUERIES", 2)
    monkeypatch.setattr(applybot, "INDEED_MAX_PAGES", 1)

    calls = []
    def fake_fetch(url, params, **kwargs):
        calls.append(params.copy())
        return {"jobs": [{
            "jobKey": "indeed-123",
            "title": "QA Automation Engineer",
            "company": "Example India",
            "location": "Indore, India",
            "remote": "Hybrid work",
            "salary": None,
            "snippet": "Playwright Python API testing, 1 year experience.",
            "applyUrl": "https://www.indeed.com/viewjob?jk=indeed-123",
            "thirdPartyApplyUrl": "https://example.com/careers/qa-123",
            "jobTypes": ["Full-time"],
        }]}

    monkeypatch.setattr(applybot, "fetch_json", fake_fetch)
    jobs, errors, status = applybot.search_indeed_jobs("QA Automation Engineer", "India")
    assert not errors
    assert len(jobs) == 1
    assert len(calls) == 2
    assert all(call["country"] == "IN" for call in calls)
    assert status[0]["source"] == "Indeed"
    assert status[0]["configured"] is True


def test_jobicy_geo_400_falls_back_to_tag(monkeypatch):
    from urllib.error import HTTPError
    calls = []

    def fake_fetch(url, params, **kwargs):
        calls.append(params.copy())
        if "geo" in params:
            raise HTTPError(url, 400, "Bad Request", hdrs=None, fp=None)
        return {"jobs": [{
            "id": 1,
            "jobTitle": "QA Automation Engineer",
            "companyName": "Example Remote",
            "jobGeo": "Anywhere",
            "jobDescription": "Playwright Python API testing",
            "url": "https://jobicy.com/jobs/1",
        }]}

    monkeypatch.setattr(applybot, "fetch_json", fake_fetch)
    jobs, errors, status = applybot.search_jobicy_jobs("QA Automation Engineer", "India")
    assert len(jobs) == 1
    assert "qa:tag" in status[0]["request_mode"]
    assert "automation:tag" in status[0]["request_mode"]
    assert any("geo" in call for call in calls)
    assert any("tag" in call and "geo" not in call for call in calls)


def test_indeed_403_is_reported_as_configuration_error(monkeypatch):
    monkeypatch.setattr(applybot, "INDEED_RAPIDAPI_ENABLED", True)
    monkeypatch.setattr(applybot, "INDEED_RAPIDAPI_KEY", "test-key")
    monkeypatch.setattr(applybot, "INDEED_MAX_QUERIES", 3)
    monkeypatch.setattr(applybot, "INDEED_MAX_PAGES", 2)

    def fake_fetch(url, params=None, headers=None, **kwargs):
        assert headers["X-RapidAPI-Key"] == "test-key"
        assert headers["X-RapidAPI-Host"] == applybot.INDEED_RAPIDAPI_HOST
        raise RuntimeError("GET https://indeed-jobs-api.p.rapidapi.com/jobs failed after 1 attempt(s) HTTP 403: Forbidden")

    monkeypatch.setattr(applybot, "fetch_json", fake_fetch)
    jobs, errors, status = applybot.search_indeed_jobs("QA Automation Engineer", "India")
    assert jobs == []
    assert status[0]["source"] == "Indeed"
    assert status[0]["configured"] is True
    assert status[0]["authorization_ok"] is False
    assert errors[0]["kind"] == "authorization"
    assert len(errors) == 1


def test_import_job_items_batch_upsert(monkeypatch, tmp_path):
    db_path = tmp_path / "applybot-test.db"
    monkeypatch.setattr(applybot, "SQLITE_DB", str(db_path))
    monkeypatch.setattr(applybot, "DATABASE_URL", "")
    monkeypatch.setattr(applybot, "AI_PROVIDER", "none")
    applybot.init_db()

    job = {
        "external_id": "job:test-batch",
        "source": "Test",
        "title": "QA Automation Engineer",
        "company": "Example Co",
        "location": "India",
        "work_mode": "Hybrid",
        "url": "https://example.com/job/test-batch",
        "source_url": "https://example.com/job/test-batch",
        "description": "QA Automation Engineer with Python Playwright and 1 year experience.",
    }
    first = applybot.import_job_items([job])
    second = applybot.import_job_items([job])
    assert len(first) == 1
    assert len(second) == 1
    c = applybot.db()
    try:
        row = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE external_id=?", ("job:test-batch",)).fetchone()
        assert row["n"] == 1
    finally:
        c.close()


def test_discovery_qualification_does_not_open_per_job_database_connections(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)

    jobs = []
    for i in range(120):
        jobs.append({
            "external_id": f"bulk-{i}",
            "source": "Jobicy",
            "title": "QA Automation Engineer",
            "company": "Example",
            "location": "India",
            "work_mode": "Remote",
            "salary_min": 4,
            "salary_max": 6,
            "experience_min": 1,
            "url": f"https://example.com/jobs/{i}",
            "description": "Playwright Python API testing",
        })

    def fake_search(query, location="", remote=False):
        return (jobs, [], [{"source": "Jobicy", "found": len(jobs), "configured": True}])

    monkeypatch.setattr(applybot, "search_public_sources", fake_search)
    r = client.post("/api/discover", json={
        "query": "QA Automation Engineer",
        "location": "India",
        "threshold": 50,
        "max_experience": 2,
        "min_salary": 3,
    })
    assert r.status_code == 200
    assert r.json["items_seen"] == 120
    assert r.json["qualified_jobs"] == 120
