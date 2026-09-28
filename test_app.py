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
