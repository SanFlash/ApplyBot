# ApplyBot

AI-assisted job discovery, matching, application preparation, and tracking workspace for Satyendra Kumar Namdeo.

ApplyBot is designed to reduce repetitive job-search work without fabricating candidate information or using unauthorized account automation.

## Stage 2 now included

- SQLite for local development.
- PostgreSQL/Supabase support through `DATABASE_URL`.
- Persistent jobs, applications, settings, and feed-source tables.
- RSS/Atom feed ingestion from permitted job sources.
- Configurable feed registry.
- Duplicate protection using stable external IDs.
- Job fingerprinting support.
- Salary and experience extraction from descriptions.
- Candidate-specific match scoring.
- Application draft generation.
- Application status tracking.
- Health endpoint showing the active database.
- CLI database initialization command.
- Render/Gunicorn deployment support.
- GitHub Actions test pipeline.

## Candidate configuration

### Primary roles

- QA Automation Engineer
- Automation Tester
- SDET
- Software Tester
- Test Engineer
- AI-Assisted QA
- AI-Assisted Tester

### Secondary roles

- Frontend Designer
- AI-Assisted Developer
- Vibe Coding

### Preferences

| Setting | Value |
|---|---|
| Experience | ~1 year |
| Maximum role requirement | 2 years |
| Expected CTC | ₹4–5 LPA |
| Hard minimum CTC | ₹3 LPA |
| Notice period | 45 days |
| Locations | India, Indore, Bangalore, Pune, Remote |
| Work preference | Hybrid |

Unpaid internships are excluded.

## Architecture

```
Permitted Job Feed / ATS
        |
        v
  Feed Discovery API
        |
        v
 Salary + Experience Extraction
        |
        v
 Candidate Match Engine
        |
        +------> Skip / record reason
        |
        v
   Application Queue
        |
        v
 Tailored Application Draft
        |
        v
 Human Review
        |
        v
 Application Tracking
        |
        v
 PostgreSQL / Supabase
```

## Repository structure

```
ApplyBot/
├── app.py
├── web/
│   └── index.html
├── data/
│   └── applybot.db          # local SQLite only
├── test_app.py
├── requirements.txt
├── Dockerfile
├── render.yaml
├── .env.example
├── .github/workflows/ci.yml
└── README.md
```

## Local setup

### 1. Clone

```bash
git clone https://github.com/SanFlash/ApplyBot.git
cd ApplyBot
```

### 2. Create virtual environment

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install

```bash
pip install -r requirements.txt
```

### 4. Environment

Copy `.env.example` to `.env`.

For local SQLite, no database variable is required.

For PostgreSQL:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
PORT=8000
DEBUG=false
```

### 5. Initialize database

The application initializes its tables on startup. You can also run:

```bash
flask --app app init-db
```

### 6. Run

```bash
python app.py
```

Open:

```
http://localhost:8000
```

## Database

### Local

SQLite is used automatically when `DATABASE_URL` is not set.

### Production

Use PostgreSQL or Supabase.

Set:

```env
DATABASE_URL=postgresql://...
```

The application detects PostgreSQL automatically.

Never commit database credentials.

## Job import API

```http
POST /api/jobs/import
```

Example:

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

If salary or experience is omitted, ApplyBot attempts to extract them from the job description.

## Feed discovery

ApplyBot can ingest RSS/Atom feeds from permitted sources.

### Add a feed

```http
POST /api/feeds
Content-Type: application/json
```

```json
{
  "name": "Example Jobs Feed",
  "url": "https://example.com/jobs/feed.xml",
  "source_type": "rss"
}
```

### List feeds

```http
GET /api/feeds
```

### Discover jobs

```http
POST /api/discover
```

The discovery endpoint:

1. Loads enabled feeds.
2. Downloads RSS/Atom XML.
3. Extracts title, URL and description.
4. Runs the candidate matching engine.
5. Stores suitable and skipped jobs.
6. Ignores duplicate external IDs.
7. Returns source errors without discarding successful sources.

Only use feeds and sources you are permitted to access.

## Matching rules

A job can be rejected because:

- The role is outside the configured targets.
- Required experience is above the configured limit.
- Location is outside preferences.
- Published salary is below ₹3 LPA.

Jobs without published salary are not automatically rejected; they are marked as requiring compensation verification.

The match score combines:

- Role relevance
- Experience fit
- Location fit
- Work-mode fit
- Salary fit
- Skill overlap

## Application generation

```http
POST /api/jobs/{job_id}/prepare
```

Creates:

- Tailored professional summary
- Cover letter
- Reusable application answers
- Expected compensation answer
- Relocation answer
- Notice-period answer
- Automation experience answer
- Playwright experience answer
- Selenium answer
- Work authorization answer

The generated material is based on the configured candidate profile.

It must not be used to invent qualifications or employment history.

## Application statuses

```
draft
approved
applied
rejected
interview
offer
closed
```

API:

```http
GET  /api/applications
POST /api/applications/{id}/status
```

## Health check

```http
GET /api/health
```

Example:

```json
{
  "status": "ok",
  "service": "ApplyBot",
  "database": "postgres"
}
```

## Render deployment

Create a Render Web Service connected to:

```
SanFlash/ApplyBot
```

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
gunicorn -b 0.0.0.0:$PORT app:app
```

Set:

```env
DEBUG=false
DATABASE_URL=<your Supabase/PostgreSQL connection string>
```

The repository includes `render.yaml`.

### Recommended Render architecture

```
Render Web Service
        |
        +---- Flask API
        |
        +---- ApplyBot dashboard
        |
        v
Supabase PostgreSQL
```

Do not rely on Render's local filesystem for permanent job/application data.

## Vercel

The current application is Flask-first and is therefore best deployed as a Render backend.

For the eventual production UI:

```
Vercel
  |
  +-- Next.js frontend
          |
          v
      Render Flask API
          |
          v
      Supabase PostgreSQL
```

A dedicated Next.js frontend can be added in the next stage without changing the backend API contract.

## Docker

Build:

```bash
docker build -t applybot .
```

Run:

```bash
docker run -p 8000:8000 applybot
```

## Tests

```bash
pytest -q
```

GitHub Actions also runs tests on push and pull request.

## Production security boundary

ApplyBot intentionally does **not** implement:

- LinkedIn password collection.
- LinkedIn session-cookie collection.
- CAPTCHA bypass.
- Stealth browser fingerprinting.
- Unauthorized LinkedIn scraping.
- Automated activity intended to evade platform controls.

Use authorized APIs, public/authorized feeds, company ATS integrations, or user-initiated workflows.

Application submission remains a human-controlled step.

## Environment variables

```env
PORT=8000
DEBUG=false
DATABASE_URL=
```

Do not commit:

- `.env`
- passwords
- API keys
- database credentials
- browser session cookies
- private tokens

## Roadmap

### Stage 1 — Foundation
- Candidate profile
- Job matching
- Application drafts
- Dashboard
- Tracking
- CI/CD

### Stage 2 — Current
- PostgreSQL/Supabase support
- RSS/Atom discovery
- Feed registry
- Duplicate handling
- Extraction
- Production database boundary

### Stage 3 — Next
- Scheduled discovery worker
- More authorized job-source connectors
- Better semantic job matching
- AI-powered JD analysis
- Resume tailoring
- Duplicate-company/application intelligence
- Notifications

### Stage 4
- Next.js/Vercel dashboard
- Authentication
- User-configurable search profiles
- Application analytics
- Interview tracking
- Recruiter follow-up management

### Stage 5
- Production background workers
- Queue management
- Observability
- Multi-user architecture
- Approved ATS application workflows

## Author

Satyendra Kumar Namdeo

QA Engineer | QA Automation | SDET | AI-Assisted QA

GitHub: https://github.com/SanFlash

LinkedIn: https://www.linkedin.com/in/satyendra-namdeo/
