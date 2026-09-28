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
        "external_id": "g1", "source": "test", "title": "QA Automation Engineer",
        "company": "Example", "location": "Bangalore", "work_mode": "Hybrid",
        "salary_min": 4, "salary_max": 6, "experience_min": 2,
        "url": "https://example.com/1", "description": "Playwright Python SQL API testing",
    }
    bad = {**good, "external_id": "b1", "title": "Senior SDET", "experience_min": 4}
    r = client.post("/api/jobs/import", json={"jobs": [good, bad]})
    assert r.status_code == 200
    jobs = client.get("/api/jobs").json
    assert any(x["status"] == "ready" for x in jobs)
    assert any(x["status"] == "skipped" for x in jobs)


def test_prepare_and_status(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    job = {
        "external_id": "g1", "source": "test", "title": "SDET", "company": "Example",
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
        for table in ("jobs", "applications", "feed_sources")
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
    assert jobs[0]["salary_min"] == 40000


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
        }], [])

    monkeypatch.setattr(applybot, "search_public_sources", fake_search)
    r = client.post("/api/discover/search", json={"query": "QA Automation Engineer", "location": "India", "remote": True})
    assert r.status_code == 200
    assert r.json["mode"] == "in_app"
    assert r.json["items_seen"] == 1
    assert r.json["new_jobs"] == 1
    assert client.get("/api/jobs").json[0]["source"] == "Remotive"




def test_discover_search_uses_threshold_and_returns_job_ids(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)

    def fake_search(query, location="", remote=False):
        return ([{
            "external_id": "job:999",
            "source": "test-api",
            "title": "QA Automation Engineer",
            "company": "Example",
            "location": "Indore",
            "work_mode": "Hybrid",
            "salary_min": 4,
            "salary_max": 6,
            "experience_min": 1,
            "url": "https://example.com/jobs/999",
            "description": "Playwright Python API testing",
        }], [])

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
        "source": "test-api",
        "title": "QA Automation Engineer",
        "company": "Example",
        "location": "Indore",
        "work_mode": "Hybrid",
        "salary_min": 4,
        "salary_max": 6,
        "experience_min": 1,
        "url": "https://example.com/jobs/threshold-1",
        "description": "Playwright Python API testing",
    }
    client.post("/api/jobs/import", json={"jobs": [job]})
    job_row = client.get("/api/jobs").json[0]
    r = client.post(f"/api/jobs/{job_row['id']}/auto-apply", json={"threshold": 99})
    assert r.status_code == 200
    assert r.json["status"] == "below_threshold"
    assert r.json["submitted"] if "submitted" in r.json else True
