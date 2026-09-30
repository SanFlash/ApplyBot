# ApplyBot — Simple Free-First Configuration

## Free setup
Job discovery works without API keys using Hopin, Arbeitnow, the free ATS dataset, and RemoteOK/Remotive for Remote searches.

Recommended Render environment:

AUTO_APPLY_ENABLED=false
AUTO_APPLY_MAX=3
CANDIDATE_EMAIL=your-email@example.com
CANDIDATE_PHONE=+91XXXXXXXXXX
RESUME_PATH=data/resume.pdf
FREE_JOB_DATASET_ENABLED=true
REMOTEOK_ENABLED=true

Use PostgreSQL on Render if you want application history to persist across deploys. SQLite is fine for local testing.

## Search
Start with Query = QA Automation Engineer and Location = India. For a city, use the city name. For remote roles, use Location = Remote and enable Remote.

## LinkedIn
ApplyBot creates an official role + location search link. It does not store LinkedIn credentials, cookies, or scrape/login to LinkedIn. Open the search and apply in LinkedIn.

LinkedIn currently prohibits unauthorized scraping and automated activity: https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions

## Indeed
ApplyBot creates an official search handoff without an API key. The optional existing RapidAPI adapter can be enabled with:

INDEED_RAPIDAPI_ENABLED=true
INDEED_RAPIDAPI_KEY=YOUR_KEY
INDEED_RAPIDAPI_HOST=indeed-jobs-api.p.rapidapi.com
INDEED_RAPIDAPI_URL=https://indeed-jobs-api.p.rapidapi.com
INDEED_RAPIDAPI_PATH=/jobs
INDEED_MAX_PAGES=1
INDEED_MAX_QUERIES=2

RapidAPI is optional and is not guaranteed to be free forever. Official Indeed API access is subject to Indeed's developer agreement and approval/verification.

## Naukri
ApplyBot generates a role + location Naukri search handoff. Do not add Naukri credentials or an unofficial scraper. Flow: ApplyBot → Open Naukri search → select job → apply in Naukri.

## Apna
ApplyBot generates a role + location Apna search handoff. Do not add Apna credentials or an unofficial scraper. Flow: ApplyBot → Open Apna search → select job → apply in Apna.

## Employer ATS automation
Playwright automation is limited to Greenhouse, Lever, Ashby, Workable and SmartRecruiters. No global ATS API key is required.

The supported flow is: find job → resolve employer application URL → detect ATS → fill known fields → upload resume → stop for CAPTCHA/ambiguous required fields → submit only when the submit control is unambiguous.

## Why you saw the application URL error
A job can be real but use an unsupported application form. Previously ApplyBot returned: No supported employer application URL was found.

The current code now returns a human handoff instead: it gives you the discovered listing/application URL and asks you to complete that unsupported form manually. This is intentional; ApplyBot does not guess how arbitrary forms work.

## CAPTCHA
When a supported ATS shows CAPTCHA/human verification, ApplyBot stops. Complete verification yourself, then use Continue after verification. ApplyBot does not bypass CAPTCHA.

## Render
Render → ApplyBot service → Environment: add the candidate variables above, deploy, then test with AUTO_APPLY_ENABLED=false.

Once discovery and the Prepare/Application Ready flow are verified, enable AUTO_APPLY_ENABLED=true. Keep AUTO_APPLY_MAX small while testing.

Never commit real API keys, database URLs, passwords, cookies, phone numbers, or a private resume to a public GitHub repository.

## Architecture
Free discovery: Hopin + Arbeitnow + ATS dataset + RemoteOK/Remotive.
Platform search: LinkedIn + Indeed + Naukri + Apna official handoffs.
Automatic submission: supported employer ATS only.
Unsupported employer form: human handoff.
CAPTCHA: human verification.
