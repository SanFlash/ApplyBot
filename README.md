# ApplyBot

AI-assisted job discovery, matching, application preparation, and tracking workspace for Satyendra Kumar Namdeo.

ApplyBot is designed to reduce repetitive job-search work without fabricating candidate information or using unauthorized account automation.

## Stage 2 now included

- SQLite for local development.
- PostgreSQL/Supabase support through `DATABASE_URL`.
- Persistent jobs, applications, settings, and feed-source tables.
- RSS/Atom feed ingestion from permitted job sources.
- Configurable feed registry.
- LinkedIn-assisted job search links (no scraping or session cookies).
- User-assisted job import for jobs found on LinkedIn or other authorized sources.
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
Authorized Feed / ATS       LinkedIn Search (user initiated)
        |                              |
        v                              v
   Feed Discovery API          User selects a job
        |                              |
        +--------------+---------------+
                       v
                 Job Analysis
                       |
                       v
          Salary + Experience Extraction
                       |
                       v
              Candidate Match Engine
                       |
             +---------+---------+
             |                   |
          Skip/reason        Ready match
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

## Job discovery

ApplyBot performs job discovery **inside the application**. The dashboard no longer opens LinkedIn, Google, or another hiring-site search page for discovery.

### Built-in sources

1. **Remotive public API** — remote jobs with keyword search.
2. **Arbeitnow public Job Board API** — public job data aggregated from multiple ATS sources.
3. **Authorized RSS/Atom feeds** — optional feeds you configure under Job Discovery.

Remotive documents keyword filtering through its public API and asks integrations to attribute/link the original listing. Its public data may be delayed, so ApplyBot keeps requests bounded rather than continuously polling. Arbeitnow documents its free, no-key job API and notes that its data comes from multiple ATS/job sources. citeturn3search0turn2view0

### In-app workflow

Enter:

- **Role / keywords** — e.g. QA Automation Engineer
- **Location** — e.g. India
- **Remote only** — optional

Then click **Search inside ApplyBot**.

The backend:

1. Queries the authorized public job APIs.
2. Normalizes different source formats into one job model.
3. Filters by location/remote preference.
4. Removes duplicate listings.
5. Extracts salary/experience only when the source format is unambiguous.
6. Scores each job against the candidate profile.
7. Stores the results in PostgreSQL/Supabase or SQLite.
8. Displays the matches directly in **Application Queue**.

Click **Discover & score jobs** to run the same API search plus all enabled RSS/Atom feeds.

### Discovery API

POST /api/discover/search

```json
{
  "query": "QA Automation Engineer",
  "location": "India",
  "remote": false
}
```

The response includes:

- items_seen
- new_jobs
- sources_checked
- errors
- scoring results for newly imported jobs

### RSS/Atom feeds

You can still add an authorized company/organization feed:

POST /api/feeds

```json
{
  "name": "Example Company Jobs",
  "url": "https://example.com/jobs/feed.xml",
  "source_type": "rss"
}
```

Then **Discover & score jobs** fetches both the built-in APIs and enabled feeds.

A feed URL must return RSS/Atom XML; a normal careers page or LinkedIn search URL is not a feed.

### Manual job analysis

The **Analyze a job you found** section remains available when you already have a job URL and description. It is an optional fallback, not part of automatic discovery.

### Security / platform boundary

ApplyBot does not:

- collect LinkedIn passwords or session cookies
- bypass CAPTCHAs
- use stealth fingerprinting
- scrape authenticated hiring-platform pages
- automate activity intended to evade platform controls

Discovery uses documented/public APIs and feeds that permit automated access.

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

## Recommended real-world workflow

For your current job search, use this sequence:

```
1. Enter role + location
        ↓
2. In-app job search
        ↓
3. Open a suitable job
        ↓
4. Paste job details into ApplyBot
        ↓
5. ApplyBot scores the job
        ↓
6. Prepare application
        ↓
7. Review summary / cover letter / answers
        ↓
8. Open the original job URL
        ↓
9. Submit manually
        ↓
10. Track application status in ApplyBot
```

This gives you the repetitive analysis and application-preparation benefits without making the system dependent on unauthorized LinkedIn automation.

## API summary

| Endpoint | Purpose |
|---|---|
| `GET /api/search-links` | Generate user-initiated job search links |
| `POST /api/jobs/manual` | Analyze and store a job selected by the user |
| `POST /api/jobs/import` | Import structured jobs |
| `GET /api/jobs` | List scored jobs |
| `POST /api/jobs/{id}/prepare` | Generate application draft |
| `GET /api/applications` | Track applications |
| `POST /api/applications/{id}/status` | Update application status |
| `POST /api/feeds` | Add authorized RSS/Atom feed |
| `POST /api/discover` | Discover jobs from feeds |
| `GET /api/health` | Health/database status |

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
- Scheduled discovery worker for permitted feeds
- More authorized job-source connectors
- Browser-assisted handoff workflows that keep final submission human-controlled
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
