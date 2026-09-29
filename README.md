# ApplyBot

ApplyBot is a focused job-search workspace for discovering relevant roles, matching them against a candidate profile, and running supported application workflows.

## Current workflow

```
Free ATS dataset
      ↓
Normalize + deduplicate
      ↓
Role / location / skill matching
      ↓
Experience / salary checks when published
      ↓
Qualified results
      ↓
Review employer application URL
      ↓
Supported browser application flow
      ↓
Application history + evidence
```

## Discovery: free by default

The active discovery engine uses the public, daily-refreshed Open Jobs Data dataset from ConorsCode. It aggregates public job-board feeds from ATS platforms including Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee, Personio and BambooHR. The dataset exposes a normalized `applyUrl`, location, remote flag, employment type and posting timestamp.

No API key, RapidAPI subscription, RSS/Atom feed or LinkedIn login is required for core discovery.

The dataset is fetched server-side and cached for 15 minutes so searches do not repeatedly download the full source.

## Matching

The default candidate profile is configured for:

- QA Automation Engineer
- Automation Tester
- SDET
- Software Tester
- Test Engineer
- AI-assisted QA/testing
- India, Indore, Bengaluru, Pune and remote-compatible roles
- Around 1 year of experience
- Target compensation ₹4–5 LPA
- Minimum compensation ₹3 LPA
- 45-day notice period

Optional fields are treated correctly:

- Missing salary does **not** reduce the match score.
- Missing experience does **not** reject a job.
- Published salary below the configured minimum can reject a job.
- Published experience above the configured maximum can reject a job.
- A role must still match the configured QA/automation role families.

This is important because public ATS datasets do not expose salary and experience consistently.

## Application automation

Playwright is used for supported public employer/ATS application pages.

Supported ATS URL detection currently includes:

- Greenhouse
- Lever
- Workable
- Ashby
- SmartRecruiters

The browser flow:

1. Opens the application URL.
2. Follows an explicit Apply control when needed.
3. Detects CAPTCHA/human-verification challenges.
4. Fills only configured candidate information.
5. Uploads the configured PDF resume.
6. Fills known truthful application answers.
7. Checks remaining required fields.
8. Stops instead of guessing when required information is missing or ambiguous.
9. Submits only when an unambiguous submit control exists.
10. Records the outcome.

ApplyBot does **not** bypass CAPTCHA, authentication, anti-bot systems or access controls.

A job is never marked `applied` merely because an application was prepared.

## Configuration

Required for production:

```env
DATABASE_URL=<PostgreSQL/Supabase URL>
CANDIDATE_EMAIL=<your email>
CANDIDATE_PHONE=<your phone>
```

For automatic submission:

```env
AUTO_APPLY_ENABLED=true
AUTO_APPLY_MAX=3
```

Resume upload is available directly in the dashboard.

Discovery configuration:

```env
FREE_JOB_DATASET_ENABLED=true
FREE_JOB_DATASET_URL=https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/data/jobs.json
FREE_JOB_DATASET_TIMEOUT=30
FREE_JOB_DATASET_CACHE_SECONDS=900
```

## Render

The repository includes a Render blueprint.

Build:

```bash
pip install --upgrade pip && pip install -r requirements.txt && playwright install chromium
```

Start:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 240 app:app
```

Health:

```
GET /api/health
```

Provider smoke test:

```
GET /api/provider-check
```

The production service is:

https://applybot-ykp7.onrender.com

## Local setup

```bash
git clone https://github.com/SanFlash/ApplyBot.git
cd ApplyBot

python -m venv .venv
.venv\\Scripts\\activate

pip install -r requirements.txt
playwright install chromium

python app.py
```

Open `http://localhost:8000`.

## API

### Search and score

`POST /api/discover`

Example:

```json
{
  "query": "QA Automation Engineer",
  "location": "India",
  "remote": false,
  "threshold": 65,
  "max_experience": 2,
  "min_salary": 3
}
```

### Search-only compatibility endpoint

`POST /api/discover/search`

### Jobs

`GET /api/jobs`

### Application

`POST /api/jobs/{job_id}/prepare`

`POST /api/jobs/{job_id}/auto-apply`

### Applications

`GET /api/applications`

`POST /api/applications/{application_id}/status`

### Resume

`POST /api/resume`

Multipart field: `resume=<PDF>`.

### Configuration

`GET /api/config`

### Profile

`GET /api/profile`

## Application states

```
application_ready
requires_configuration
requires_user_action
failed
unsupported
applied
rejected
interview
offer
closed
```

## Database

SQLite is used locally.

Production uses PostgreSQL/Supabase through `DATABASE_URL`.

The startup migration adds newer audit columns to existing databases when required.

## Testing

```bash
pytest -q
python -m py_compile app.py
```

GitHub Actions runs the test suite on pushes and pull requests.

## Security boundary

ApplyBot does not implement:

- LinkedIn password/session-cookie collection
- CAPTCHA solving or bypass
- stealth fingerprinting
- anti-bot evasion
- unauthorized scraping
- fabricated application answers

The application flow is limited to public pages and configured candidate information.

## Repository

https://github.com/SanFlash/ApplyBot
