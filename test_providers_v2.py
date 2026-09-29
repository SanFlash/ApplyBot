import app as applybot
import providers_v2


def test_v2_discovery_uses_jobicy_and_muse_without_indeed(monkeypatch):
    calls = []

    def fake_fetch(url, params=None, headers=None, timeout=None):
        calls.append((url, params or {}))
        if "jobicy.com" in url:
            return {"jobs": [{
                "id": 1,
                "jobTitle": "QA Automation Engineer",
                "companyName": "Example India",
                "jobGeo": "India",
                "jobDescription": "<p>Playwright Python API testing, 1 year experience.</p>",
                "url": "https://jobicy.com/jobs/1",
            }]}
        if "themuse.com/api/public/jobs" in url:
            return {"results": [{
                "id": 2,
                "name": "QA Automation Engineer",
                "company": {"name": "Muse Example"},
                "locations": [{"name": "India"}],
                "contents": "Playwright Python API testing",
                "refs": {"landing_page": "https://www.themuse.com/jobs/2"},
            }]}
        if "remoteok.com" in url:
            return []
        raise AssertionError(url)

    monkeypatch.setattr(applybot, "fetch_json", fake_fetch)
    monkeypatch.setattr(applybot, "JOBICY_COUNT", 20)
    monkeypatch.setattr(applybot, "THEMUSE_API_KEY", "")
    monkeypatch.setattr(applybot, "REMOTEOK_ENABLED", False)
    monkeypatch.setattr(applybot, "GREENHOUSE_BOARDS", [])
    monkeypatch.setattr(applybot, "LEVER_COMPANIES", [])
    monkeypatch.setattr(applybot, "JOBVETTA_API_KEY", "")
    monkeypatch.setattr(applybot, "INDIANAPI_KEY", "")
    monkeypatch.setattr(applybot, "ADZUNA_APP_ID", "")
    monkeypatch.setattr(applybot, "ADZUNA_APP_KEY", "")

    jobs, errors, status = providers_v2.search_public_sources("QA Automation Engineer", "India", False)

    assert not errors
    assert any(j["source"] == "Jobicy" for j in jobs)
    assert any(j["source"] == "The Muse" for j in jobs)
    assert all("Indeed" not in (j.get("source") or "") for j in jobs)
    assert any(s["source"] == "The Muse" and s["found"] >= 1 for s in status)
    assert not any("rapidapi" in url.lower() for url, _ in calls)


def test_v2_discovery_remote_enables_remoteok(monkeypatch):
    def fake_fetch(url, params=None, headers=None, timeout=None):
        if "jobicy.com" in url:
            return {"jobs": []}
        if "themuse.com/api/public/jobs" in url:
            return {"results": []}
        if "remoteok.com" in url:
            return [{
                "id": 10,
                "position": "Senior QA Automation Engineer",
                "company": "Remote Example",
                "location": "Worldwide",
                "url": "https://remoteok.com/example/10",
                "description": "Playwright Python API testing",
            }]
        raise AssertionError(url)

    monkeypatch.setattr(applybot, "fetch_json", fake_fetch)
    monkeypatch.setattr(applybot, "REMOTEOK_ENABLED", True)
    monkeypatch.setattr(applybot, "GREENHOUSE_BOARDS", [])
    monkeypatch.setattr(applybot, "LEVER_COMPANIES", [])
    monkeypatch.setattr(applybot, "JOBVETTA_API_KEY", "")
    monkeypatch.setattr(applybot, "INDIANAPI_KEY", "")
    monkeypatch.setattr(applybot, "ADZUNA_APP_ID", "")
    monkeypatch.setattr(applybot, "ADZUNA_APP_KEY", "")

    jobs, errors, status = providers_v2.search_public_sources("QA Automation Engineer", "Remote", True)

    assert any(j["source"] == "RemoteOK" for j in jobs)
    assert any(s["source"] == "RemoteOK" and s["found"] == 1 for s in status)
