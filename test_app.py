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


def test_search_links_are_user_initiated(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    r = client.get("/api/search-links?query=QA%20Automation%20Engineer&location=India&remote=true")
    assert r.status_code == 200
    assert "linkedin.com/jobs/search" in r.json["linkedin"]
    assert "QA+Automation+Engineer" in r.json["linkedin"]
    assert "f_WT=2" in r.json["linkedin"]
    assert "does not scrape LinkedIn" in r.json["note"]


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


def test_add_feed_sqlite(tmp_path, monkeypatch):
    client = setup_db(tmp_path, monkeypatch)
    r = client.post("/api/feeds", json={
        "name": "Example Jobs",
        "url": "https://example.com/jobs.xml",
        "source_type": "rss",
    })
    assert r.status_code == 200
    feeds = client.get("/api/feeds").json
    assert feeds[0]["enabled"] in (1, True)
