# ApplyBot

ApplyBot is an in-app job discovery, matching, application generation and supported-ATS auto-application system.

The workflow is:

```
Search inside ApplyBot
      ↓
Fetch job listings
      ↓
Show SOURCE + URL + job details
      ↓
ApplyBot scoring
      ↓
Threshold + salary + experience filters
      ↓
Qualified queue
      ↓
Generate truthful application answers
      ↓
Detect supported ATS
      ↓
Fill public application form
      ↓
Submit when the form is unambiguous
      ↓
Record submitted / failed / requires-user-action
```

## What it shows

For every discovered job the dashboard shows:

- Job title
- Company
- Location
- Work mode
- Source that supplied the listing
- Original job URL
- Match percentage
- Match/rejection reasons
- Matched skills
- Salary when available
- Detected application adapter
- Final application status

Current discovery sources:

- **Adzuna** — broad live job-ad search for India; requires an `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
- **Greenhouse** — direct employer ATS postings when company board tokens are configured in `GREENHOUSE_BOARDS`.
- **Lever** — direct employer ATS postings when company slugs are configured in `LEVER_COMPANIES`.
- **Arbeitnow** — public normalized job-board data.
- **Remotive** — discovery-only remote jobs; its public API terms prohibit submitting its listings to third-party sites.

For a genuinely broad, current search, configure Adzuna. The Adzuna API provides job-ad search by keywords and location and requires an app ID/key. urlAdzuna API documentationhttps://developer.adzuna.com/overview

Lever's public postings API exposes published postings, including application URLs, while its authenticated API is separate. urlLever developer documentationhttps://hire.lever.co/developer/documentation

There is no RSS/Atom workflow in the current discovery path and ApplyBot does not open LinkedIn or Google as a discovery step.

## Matching

Default candidate configuration:

| Rule | Value |
|---|---|
| Experience | ~1 year |
| Maximum target experience | 2 years |
| Expected CTC | ₹4–5 LPA |
| Hard minimum CTC | ₹3 LPA |
| Notice period | 45 days |
| Locations | India, Indore, Bangalore, Pune, Remote |
| Work preference | Hybrid |

A job can be rejected when:

- The title does not match the configured target roles.
- Required experience exceeds the configured limit.
- Location does not match.
- Published salary is below the hard minimum.

A missing salary is not treated as a false salary match; it is shown as undisclosed.

## Automatic application

The repository now includes a real browser-based submission layer using Playwright.

Supported public ATS adapters:

- Greenhouse public application pages
- Lever public application pages

The adapter:

1. Opens the job/application URL.
2. Detects CAPTCHA/human-verification pages.
3. Fills available candidate fields.
4. Uploads the configured PDF resume.
5. Fills known truthful application questions.
6. Checks for remaining required fields.
7. Stops instead of guessing when required information is unknown.
8. Submits through the public application form when an unambiguous submit control exists.
9. Records the outcome.

It never attempts to bypass CAPTCHA, authentication, anti-bot challenges or session controls. Remotive API listings are displayed for discovery only; ApplyBot does not auto-submit those listings because Remotive's public API terms prohibit third-party submission.

### Important configuration

Set these Render environment variables:

```env
DATABASE_URL=<your PostgreSQL/Supabase URL>

AUTO_APPLY_ENABLED=true
AUTO_APPLY_MAX=3

CANDIDATE_EMAIL=<your email>
CANDIDATE_PHONE=<your phone>
```

The dashboard also provides **Upload resume**. The uploaded PDF is stored as `data/resume.pdf` for the running service instance.

For production, use a persistent disk or external private storage if the resume must survive service replacement/redeployment.

## Render deployment

The repository includes `render.yaml`.

Build:

```bash
pip install --upgrade pip && pip install -r requirements.txt && playwright install chromium
```

Start:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 app:app
```

The Render blueprint sets Python 3.13.3 through:

```
.python-version
```

### Required Render secrets

Do not commit these:

- `DATABASE_URL`
- `CANDIDATE_EMAIL`
- `CANDIDATE_PHONE`

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

Open:

```
http://localhost:8000
```

## API

### Discovery

`POST /api/discover`

Example:

```json
{
  "query": "QA Automation Engineer",
  "location": "India",
  "remote": false,
  "threshold": 70,
  "max_experience": 2,
  "min_salary": 3
}
```

The response includes:

- sources checked
- number of listings found
- number of qualified jobs
- provider errors
- job IDs
- scores
- reasons
- matched skills

### Search only

`POST /api/discover/search`

### Auto apply

`POST /api/jobs/{job_id}/auto-apply`

The endpoint re-checks the threshold before starting submission.

### Configuration

`GET /api/config`

Shows whether automatic application, email, phone, resume and supported ATS adapters are configured.

### Resume upload

`POST /api/resume`

Multipart field:

`resume=<PDF>`

### Jobs

`GET /api/jobs`

### Applications

`GET /api/applications`

### Application status

`POST /api/applications/{id}/status`

### Health

`GET /api/health`

## Application states

```
application_ready
approved
requires_configuration
requires_user_action
unsupported_source_policy
failed
applied
rejected
interview
offer
closed
```

**Applied** is only recorded when the browser submission step completes. A prepared application is never falsely reported as submitted.

## Database

SQLite is used locally.

Production uses PostgreSQL/Supabase through:

```env
DATABASE_URL=postgresql://...
```

The startup migration creates any new audit columns required by newer ApplyBot versions.

## Tests

```bash
pytest -q
```

GitHub Actions runs the test suite on pushes and pull requests.

## Security boundary

ApplyBot does not implement:

- LinkedIn password collection
- LinkedIn session-cookie extraction
- CAPTCHA solving/bypass
- stealth fingerprinting
- anti-bot evasion
- unauthorized scraping
- guessed answers to required application questions

Automatic application is limited to public, supported ATS application forms and truthful configured candidate information.

## Repository

GitHub:

https://github.com/SanFlash/ApplyBot
