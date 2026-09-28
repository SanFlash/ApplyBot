# ApplyBot

ApplyBot is an AI-assisted job-application workspace for one candidate. It accepts genuine job records from permitted sources, evaluates fit against explicit rules, prepares tailored application material, and tracks each application.

## Candidate rules configured

- Primary roles: QA Automation Engineer, Automation Tester, SDET, Software Tester, Test Engineer, AI Assisted QA/Tester.
- Secondary roles: Frontend Designer, AI-assisted Developer, Vibe Coding.
- Location: India-wide, Indore, Bangalore, Pune, Remote.
- Work preference: Hybrid.
- Experience: 1 year; reject roles requiring more than 2 years.
- Compensation: expected ₹4–5 LPA; hard floor ₹3 LPA.
- Exclude unpaid internships.
- Notice period: 45 days.
- Skills: Python, Playwright, JavaScript/TypeScript, Appium, Git, Jira, Swagger, SQL, CI/CD, Confluence, API testing, manual/regression/E2E testing, AI-assisted testing.

## Local setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:8000.

## Job ingestion

POST `/api/jobs/import` with JSON:

```json
{
  "jobs": [{
    "external_id": "example-123",
    "source": "company-ats",
    "title": "QA Automation Engineer",
    "company": "Example Corp",
    "location": "Bangalore",
    "work_mode": "Hybrid",
    "salary_min": 5,
    "salary_max": 7,
    "experience_min": 1,
    "url": "https://jobs.example.com/123",
    "description": "Playwright, Python, SQL, API testing..."
  }]
}
```

## API

- GET /api/health
- GET /api/profile
- GET /api/jobs
- POST /api/jobs/import
- POST /api/jobs/<id>/prepare
- GET /api/applications
- POST /api/applications/<id>/status

## Production boundary

This repo deliberately does not contain a LinkedIn password bot, session-cookie collector, CAPTCHA bypass, stealth automation, or scraping loop. Use permitted APIs, feeds, company ATS pages, or user-initiated workflows. Keep secrets outside source control.

For durable production storage, replace SQLite with PostgreSQL/Supabase.

## Deployment

The included `Dockerfile` and `render.yaml` provide a Render-ready deployment using Gunicorn.
