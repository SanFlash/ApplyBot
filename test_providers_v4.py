import providers_v4


def test_free_dataset_normalizes_job():
    row = {
        "company": "Example Labs",
        "platform": "greenhouse",
        "jobId": "123",
        "title": "QA Automation Engineer",
        "locations": ["Bengaluru, India"],
        "isRemote": False,
        "employmentType": "Full-time",
        "applyUrl": "https://example.com/apply/123",
        "postedAt": "2026-09-29T00:00:00Z",
    }
    job = providers_v4._normalize(row)
    assert job["company"] == "Example Labs"
    assert job["ats_platform"] == "greenhouse"
    assert job["url"].endswith("/123")


def test_free_dataset_relevance_and_india_location():
    job = providers_v4._normalize({
        "company": "Example Labs",
        "platform": "lever",
        "jobId": "qa-1",
        "title": "QA Automation Engineer",
        "locations": ["Pune, India"],
        "applyUrl": "https://jobs.example.com/qa-1",
    })
    assert providers_v4._relevant(job, "QA Automation Engineer")
    assert providers_v4._location_ok(job, "India", False)


def test_free_dataset_remote():
    job = providers_v4._normalize({
        "company": "Example Labs",
        "platform": "ashby",
        "jobId": "r-1",
        "title": "QA Engineer",
        "locations": ["Remote - India"],
        "isRemote": True,
        "applyUrl": "https://jobs.example.com/r-1",
    })
    assert providers_v4._location_ok(job, "India", True)
