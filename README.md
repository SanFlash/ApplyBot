# ApplyBot

ApplyBot is an in-app job discovery, matching, application preparation and supported-ATS auto-application system. The default discovery layer is **Jobicy's free public Jobs REST API**; no Jobicy API key is required for the public endpoint.

The workflow is:

```
Search inside ApplyBot
      ↓
Jobicy public REST API
      ↓
Normalize + deduplicate live listings
      ↓
Role / skill / location / experience / salary scoring
      ↓
Threshold-qualified queue
      ↓
Generate truthful application answers
      ↓
Resolve employer application link when exposed
      ↓
Detect supported ATS
      ↓
Fill public application form
      ↓
Submit only when the form is unambiguous
      ↓
Record evidence/status
```

## Jobicy discovery

ApplyBot calls:

`GET https://jobicy.com/api/v2/remote-jobs`

The public endpoint requires **no API key**, supports up to 200 listings per request, and accepts `count`, `geo`, `industry` and `tag` filters. Jobicy recommends using its taxonomy endpoints when storing production filter slugs and not polling more often than once per hour. citeturn0search0turn0search1

ApplyBot uses a strong keyword anchor (for example `qa` for QA Automation Engineer) in Jobicy's `tag` filter, then performs the exact role/skill/experience/location scoring locally. This avoids treating a multi-word role phrase as an exact Jobicy search. Jobicy currently exposes regional/country slugs such as APAC, USA, Europe and others; it does not expose a dedicated India slug in its current location taxonomy. Therefore an India search uses **APAC coverage** and does not guarantee an India-only result. City searches such as Indore/Bengaluru/Pune are not guaranteed by this provider.

For every result the dashboard records:

- Job title
- Company
- Jobicy listing URL
- Geography
- Match percentage
- Match/rejection reasons
- Matched skills
- Salary when available
- Detected application adapter
- Application outcome

Jobicy's fair-use rules permit using its listings in applications and user experiences, require keeping Jobicy as the original source, and prohibit abusive/high-frequency polling. citeturn0search3


### Real application links

The free Jobicy API returns a Jobicy listing URL. Jobicy documents that the original employer/ATS URL is returned when a valid Commercial Jobs API Bearer key is supplied; that commercial service can charge for direct application URLs. ApplyBot therefore has two honest modes:

- **Free mode:** discovers and scores live Jobicy listings. If the Jobicy page exposes an external application link, ApplyBot can resolve it and attempt supported browser submission.
- **Commercial-key mode:** sends the Jobicy Bearer key server-side and uses the returned direct ATS URL when available. This is the preferred path for reliable automatic application routing.

ApplyBot never treats a Jobicy listing page as if it were an employer application form. It also stops on CAPTCHA, login, ambiguous required questions, unsupported ATS flows, or missing candidate configuration instead of claiming a submission happened.

## Free-first configuration

No Jobicy API key is needed for normal discovery:

```env
JOBICY_API_URL=https://jobicy.com/api/v2/remote-jobs
JOBICY_API_KEY=
JOBICY_COUNT=200
JOBICY_TIMEOUT=30
ENABLE_LEGACY_SOURCES=false
```

Legacy providers remain available only when explicitly enabled. This keeps unrelated sources from polluting a focused search.

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

The repository includes `render.yaml`. Set `JOBICY_API_KEY` only in Render Environment Variables if you have purchased/enabled Jobicy commercial direct-URL access; never commit the key.

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


## Multi-source job discovery

ApplyBot now supports multiple in-app discovery providers. For India, **Jobvetta** is the preferred additional provider: its free API provides live India jobs gathered from official employer sources, with 50 API requests per key per UTC day. IndianAPI can also be enabled with its free API key. RemoteOK is enabled for remote-only searches. Adzuna and Arbeitnow remain optional legacy providers.

LinkedIn remains disabled unless you have an authorized LinkedIn API integration. **Indeed is now supported through your subscribed RapidAPI Indeed Jobs API** (`indeed-jobs-api.p.rapidapi.com`). ApplyBot does not scrape Indeed directly; it calls the RapidAPI provider server-side using `X-RapidAPI-Key` and `X-RapidAPI-Host`.

To enable India sources on Render:
1. Create a free Jobvetta API key.
2. In Render → ApplyBot → Environment, set `JOBVETTA_API_KEY`.
3. Optionally create an IndianAPI key and set `INDIANAPI_KEY`.
4. Redeploy.
5. Search **QA Automation Engineer / Automation Tester / SDET** with **India**.
6. The Results section will show the provider/source, source URL, score, matched skills and qualification reason.
7. Auto-apply remains limited to supported employer ATS forms; aggregator pages are discovery sources, not automatically submitted applications.

## Complete setup and verification

### 1. Open the deployed application

Primary Render URL:

https://applybot-ykp7.onrender.com

### 2. Verify the server before searching

Open:

https://applybot-ykp7.onrender.com/api/health

Expected JSON contains:
- `"status": "ok"`
- `"service": "ApplyBot"`
- `"database": "postgres"` when the production database is configured.

Then open:

https://applybot-ykp7.onrender.com/api/provider-check

Expected result:
- `"ok": true`
- `jobicy.ok: true`
- `database_schema.ok: true`
- `jobicy.count` greater than zero when Jobicy currently has matching QA listings.

This endpoint performs a read-only Jobicy public-API check and does not use the paid direct-ATS API key.

### 3. Configure candidate application data

In Render → ApplyBot → Environment, configure:

```text
AUTO_APPLY_ENABLED=true
AUTO_APPLY_MAX=3
CANDIDATE_EMAIL=your-real-email
CANDIDATE_PHONE=your-real-phone
JOBICY_API_URL=https://jobicy.com/api/v2/remote-jobs
JOBICY_COUNT=200
JOBICY_TIMEOUT=30
ENABLE_LEGACY_SOURCES=false
```

If you have Jobicy Commercial Jobs API access, put the Bearer key in `JOBICY_API_KEY`. Never commit it to GitHub.

### 4. Upload the real resume

Open the dashboard and use the resume upload control. Confirm the UI reports that the resume is configured.

### 5. Search for the desired role

Use, for example:

```text
Query: QA Automation Engineer
Location: India
Remote: enabled if remote roles are acceptable
Threshold: 55
Maximum experience: 2
Minimum salary: 3
```

ApplyBot first requests current Jobicy data, then scores the returned listings locally. It does not use RSS/Atom or redirect you to LinkedIn for discovery.

### 6. Understand the result

The dashboard should show:

```text
Jobicy: N
Found: N
Qualified: N
```

For each listing, verify:
- company
- role
- location/eligibility
- match score
- matched skills
- Jobicy listing URL
- employer application URL when one is actually available

### 7. Automatic application

A qualified job is only submitted when all configured checks pass.

The browser automation:
1. opens the employer application URL;
2. detects the supported ATS;
3. fills known candidate fields;
4. uploads the configured resume;
5. answers only questions supported by the candidate profile;
6. checks required fields;
7. stops if CAPTCHA, login, ambiguous questions, or unsupported flows are encountered;
8. submits only when a clear submit control exists;
9. verifies a submission/confirmation signal;
10. records the application result.

The database is updated to `applied` only after the submission step completes. A listing is never marked applied merely because it was discovered.

### 8. Jobicy direct application URLs

The free Jobicy API returns Jobicy listing URLs. Jobicy documents that the Commercial Jobs API can return the original ATS application URL when one exists, using a Bearer API key. The commercial API can charge per newly resolved direct URL, so ApplyBot's diagnostic endpoint intentionally uses the free public API.

Without the commercial key, ApplyBot can still inspect a Jobicy listing page for an external application link, but some jobs will remain `requires_user_action` or `unsupported`.

### 9. If Search & Score fails

Do not repeatedly press Search. First open:

```text
/api/provider-check
```

Then check the Render service logs for:
- `Jobicy`
- `psycopg2`
- `UndefinedColumn`
- `HTTP Error`
- `timeout`

The production app initializes and migrates its PostgreSQL schema during Gunicorn import, so an existing database receives missing columns automatically.

### 10. GitHub and Render

The GitHub repository is the source of truth. Render deploys the `main` branch. After a code change, wait for the Render deployment to become `Live` before testing.

Current production deployment verified on 2026-09-28:
- commit: `d488ff28ff68c627b1dac71763744fb18aea0415`
- Render deploy: `dep-dat66bojo6nc73edmlug`
- status: `live`
- primary URL: `https://applybot-ykp7.onrender.com`



## Indeed RapidAPI integration

ApplyBot now includes a first-class **Indeed RapidAPI** discovery provider using the API documented in your RapidAPI subscription.

Base URL:

```
https://indeed-jobs-api.p.rapidapi.com
```

Required server-side headers:

```
X-RapidAPI-Key: <your key>
X-RapidAPI-Host: indeed-jobs-api.p.rapidapi.com
```

The provider calls `GET /jobs` and supports the documented `query`, `location`, `country`, `page`, `datePosted`, `remoteOnly`, `workSetting`, `jobType`, `experienceLevel`, `sort` and related filters. It uses the API's 15-results-per-page pagination and deduplicates jobs by `jobKey`.

### What ApplyBot does with Indeed results

1. Searches the user's requested role.
2. Adds a small set of related QA roles (`QA Automation Engineer`, `Automation Tester`, `SDET`) so one exact title does not unnecessarily limit discovery.
3. Uses the correct Indeed country code; India is `IN`.
4. Supports India city searches and remote searches.
5. Uses `thirdPartyApplyUrl` when supplied, otherwise the Indeed `applyUrl`.
6. Normalizes title, company, location, remote/hybrid mode, job ID, posted date, job type and salary metadata.
7. Deduplicates repeated results across query variants/pages.
8. Sends the normalized jobs through the existing role, experience, location, salary and skill matcher.
9. Keeps the RapidAPI key exclusively on the server.
10. Continues other providers when one Indeed query/page fails.

### Important salary handling

The RapidAPI documentation describes the Indeed `salaryMin`/`salaryMax` search filters and returned salary values as **USD**. ApplyBot therefore does **not** silently treat those values as INR/LPA. By default salary conversion is disabled, so an Indeed USD salary cannot create a false INR qualification.

If you have a trusted USD→INR rate, configure:

```env
INDEED_CONVERT_USD_SALARY=true
INDEED_USD_TO_INR=YOUR_TRUSTED_RATE
```

### Render configuration

In **Render → ApplyBot → Environment Variables**, add:

```env
INDEED_RAPIDAPI_ENABLED=true
INDEED_RAPIDAPI_KEY=YOUR_RAPIDAPI_KEY
INDEED_RAPIDAPI_HOST=indeed-jobs-api.p.rapidapi.com
INDEED_RAPIDAPI_URL=https://indeed-jobs-api.p.rapidapi.com
INDEED_MAX_PAGES=2
INDEED_MAX_QUERIES=3
INDEED_DATE_POSTED=7
INDEED_CONVERT_USD_SALARY=false
INDEED_USD_TO_INR=0
```

Never commit `INDEED_RAPIDAPI_KEY` to GitHub.

### Request-volume control

The default is deliberately conservative: up to 3 query variants × 2 pages per discovery. Because your RapidAPI account is subscribed to the BASIC plan, keep these values modest and watch your RapidAPI quota/usage dashboard. You can reduce them to `INDEED_MAX_QUERIES=1` and `INDEED_MAX_PAGES=1` while testing.

### Diagnostics

After Render redeploys, use:

```
GET /api/discovery-diagnostics?query=QA%20Automation%20Engineer&location=India&remote=false
```

and:

```
GET /api/provider-check
```

The discovery diagnostics include the provider status, query variants, pages checked and any RapidAPI errors. A RapidAPI failure for one query does not abort the other provider searches.

### Local setup

```powershell
$env:INDEED_RAPIDAPI_ENABLED="true"
$env:INDEED_RAPIDAPI_KEY="YOUR_RAPIDAPI_KEY"
python app.py
```

Then open `http://localhost:8000`, search for `QA Automation Engineer`, select `India`, and inspect the source/provider column for **Indeed RapidAPI**.
