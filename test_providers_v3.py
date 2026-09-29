import providers_v3


def test_search_queries_include_real_ats_domains():
    queries = providers_v3._search_queries("QA Automation Engineer", "India", False)
    joined = " ".join(queries)
    assert "boards.greenhouse.io" in joined
    assert "jobs.lever.co" in joined
    assert "jobs.ashbyhq.com" in joined


def test_schema_jobposting_normalization():
    class Stub:
        def extract_experience(self, text):
            return 1.0
    job = providers_v3._schema_job(
        Stub(),
        {
            "@type": "JobPosting",
            "title": "QA Automation Engineer",
            "hiringOrganization": {"name": "Example Labs"},
            "jobLocation": {"address": {"addressLocality": "Bengaluru", "addressCountry": "IN"}},
            "description": "<p>Playwright Python API testing</p>",
            "identifier": {"value": "qa-123"},
        },
        "https://example.com/careers/qa-123",
    )
    assert job["title"] == "QA Automation Engineer"
    assert job["company"] == "Example Labs"
    assert job["external_id"] == "webjob:qa-123"
    assert "Playwright" in job["description"]


def test_relevance_prefers_qa_title():
    job = {
        "title": "QA Automation Engineer",
        "description": "Playwright Python API testing",
    }
    assert providers_v3._relevant(job, "QA Automation Engineer")
