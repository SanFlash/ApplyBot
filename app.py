from __future__ import annotations

import json, os, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
DATA.mkdir(exist_ok=True)
DB = DATA / 'applybot.db'
app = Flask(__name__, static_folder='web', static_url_path='')

CANDIDATE = {
    'name': 'Satyendra Kumar Namdeo',
    'title': 'QA Engineer | QA Automation | SDET | AI-Assisted QA',
    'experience_years': 1.0,
    'current_ctc_lpa': 2.2,
    'expected_ctc_min_lpa': 4.0,
    'expected_ctc_max_lpa': 5.0,
    'minimum_ctc_lpa': 3.0,
    'notice_period_days': 45,
    'locations': ['India', 'Indore', 'Bangalore', 'Pune', 'Remote'],
    'work_modes': ['Hybrid'],
    'roles_primary': ['QA Automation Engineer', 'Automation Tester', 'SDET', 'Software Tester', 'Test Engineer', 'AI Assisted QA', 'AI Assisted Tester'],
    'roles_secondary': ['Frontend Designer', 'AI-Assisted Developer', 'Vibe Coding'],
    'skills': ['Python','Playwright','JavaScript','TypeScript','Appium','Git','GitHub','Jira','Swagger','SQL','CI/CD','Confluence','API Testing','Manual Testing','Regression Testing','E2E Testing','AI-Assisted Testing','Prompt Engineering'],
}
ROLE_KEYWORDS = {
    'QA Automation Engineer': ['qa automation','automation qa','automation engineer','quality assurance automation'],
    'Automation Tester': ['automation tester','test automation','qa automation'],
    'SDET': ['sdet','software development engineer in test'],
    'Software Tester': ['software tester','qa tester','test engineer'],
    'Test Engineer': ['test engineer','quality engineer'],
    'AI Assisted QA': ['ai assisted qa','ai qa','ai testing','ai-assisted testing'],
    'AI Assisted Tester': ['ai tester','ai-assisted tester'],
    'Frontend Designer': ['frontend designer','ui designer','frontend'],
    'AI-Assisted Developer': ['ai-assisted developer','ai developer'],
    'Vibe Coding': ['vibe coding','ai coding'],
}
STOPWORDS = {'and','the','with','for','from','that','this','your','you','are','will','our','their','have','has','into','years','year','role','job','using','work','about','who','what','but','not','all'}

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT UNIQUE, source TEXT NOT NULL,
      title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, work_mode TEXT,
      salary_min REAL, salary_max REAL, experience_min REAL, url TEXT NOT NULL, description TEXT NOT NULL,
      discovered_at TEXT NOT NULL, match_score REAL DEFAULT 0, status TEXT DEFAULT 'new', skip_reason TEXT);
    CREATE TABLE IF NOT EXISTS applications (
      id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL, tailored_summary TEXT,
      cover_letter TEXT, answers_json TEXT, status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(id));
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    '''); c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',('candidate',json.dumps(CANDIDATE))); c.commit(); c.close()

def tokens(text): return {x for x in re.findall(r'[a-zA-Z][a-zA-Z0-9+#./-]*',text.lower()) if x not in STOPWORDS}

def extract_salary(text):
    vals=[]
    for m in re.finditer(r'(?:₹|rs\.?|inr\s*)?\s*(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*l(?:pa|akh)?',text,re.I): vals += [float(m.group(1)),float(m.group(2))]
    for m in re.finditer(r'(?:₹|rs\.?|inr\s*)?\s*(\d+(?:\.\d+)?)\s*lpa',text,re.I): vals.append(float(m.group(1)))
    return (min(vals),max(vals)) if vals else (None,None)

def extract_experience(text):
    vals=[float(m.group(1)) for m in re.finditer(r'(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)',text,re.I)]
    return min(vals) if vals else None

def score_job(j):
    text=((j.get('title') or '')+' '+(j.get('description') or '')).lower(); title=(j.get('title') or '').lower()
    score=0; reasons=[]; matched=[]; role_hit=False
    for role,kws in ROLE_KEYWORDS.items():
        if any(k in title for k in kws): role_hit=True; score+=30 if role in CANDIDATE['roles_primary'] else 15; reasons.append(f'Role matches {role}'); break
    if not role_hit: return 0,['Role does not match configured targets'],[]
    exp=j.get('experience_min')
    if exp is not None:
        if exp <= CANDIDATE['experience_years']+1: score+=20; reasons.append('Experience requirement is within configured range')
        else: reasons.append(f'Experience requirement {exp:g}+ years exceeds limit'); return 0,reasons,[]
    else: score+=8
    loc=(j.get('location') or '').lower(); mode=(j.get('work_mode') or '').lower()
    loc_ok=any(x.lower() in loc for x in CANDIDATE['locations'] if x.lower() not in {'india','remote'}) or 'remote' in loc or 'india' in loc or not loc
    if not loc_ok: reasons.append('Location is outside preferences'); return 0,reasons,[]
    score+=15; reasons.append('Location matches preferences')
    if not mode or mode in {m.lower() for m in CANDIDATE['work_modes']} or 'hybrid' in mode or 'remote' in mode: score+=8
    smin,smax=j.get('salary_min'),j.get('salary_max')
    if smax is not None and smax < CANDIDATE['minimum_ctc_lpa']: reasons.append('Salary is below minimum threshold'); return 0,reasons,[]
    if smax is not None: score += 15 if smax >= CANDIDATE['expected_ctc_min_lpa'] else 8; reasons.append('Salary meets minimum threshold')
    else: score+=3; reasons.append('Salary not disclosed; needs verification')
    jt=tokens(text)
    for skill in CANDIDATE['skills']:
        if skill.lower() in jt or skill.lower().replace(' ','-') in jt: matched.append(skill)
    score+=min(12,len(matched)); reasons.append(f'{len(matched)} relevant skills detected')
    return min(100,score),reasons,matched

def make_answers(job):
    title,company=job['title'],job['company']
    return {
      'why_interested':f'I’m interested in the {title} opportunity at {company} because it aligns with my hands-on experience in QA automation, Playwright, API validation, mobile testing and AI-assisted testing. In my current QA role, I work across functional, regression, integration and end-to-end testing and build reusable automation workflows.',
      'why_hire':'I bring hands-on experience across manual and automation testing, with practical exposure to Playwright, JavaScript/TypeScript, Appium, API validation, SQL, CI/CD and real-device testing. I also use AI-assisted workflows for test design, automation development, debugging and edge-case analysis while validating the output against requirements.',
      'expected_salary':'₹4–5 LPA, negotiable based on the role, responsibilities, overall compensation and growth opportunity.',
      'relocation':'Yes. I am open to relocating for the right opportunity, particularly to Bengaluru or Pune.',
      'sponsorship':'No.','join':'I currently have a 45-day notice period.',
      'automation_experience':'Around 1 year of hands-on QA automation experience using Playwright with JavaScript/TypeScript and Page Object Model, plus Appium for Android and iOS mobile automation. I have also worked with API validation, SQL/database validation, cross-browser/device testing and end-to-end workflows.',
      'playwright_experience':'Approximately 1 year of hands-on experience.',
      'selenium_experience':'I do not currently list professional Selenium experience on my resume.','authorized_india':'Yes.'}

@app.get('/')
def index(): return send_from_directory(BASE/'web','index.html')
@app.get('/api/health')
def health(): return {'status':'ok','service':'ApplyBot','time':datetime.now(timezone.utc).isoformat()}
@app.get('/api/profile')
def profile(): return jsonify(CANDIDATE)
@app.get('/api/jobs')
def jobs():
    c=db(); rows=c.execute('SELECT * FROM jobs ORDER BY match_score DESC, discovered_at DESC').fetchall(); c.close(); return jsonify([dict(r) for r in rows])
@app.post('/api/jobs/import')
def import_jobs():
    items=(request.get_json(silent=True) or {}).get('jobs',[]); c=db(); created=[]
    for j in items:
        if not all(j.get(k) for k in ['title','company','url','description']): continue
        ext=j.get('external_id') or j['url']; smin,smax=j.get('salary_min'),j.get('salary_max')
        if smin is None and smax is None: smin,smax=extract_salary(j['description'])
        exp=j.get('experience_min') if j.get('experience_min') is not None else extract_experience(j['description'])
        base={**j,'salary_min':smin,'salary_max':smax,'experience_min':exp}; sc,reasons,matched=score_job(base); status='ready' if sc>0 else 'skipped'
        try:
            c.execute('''INSERT INTO jobs(external_id,source,title,company,location,work_mode,salary_min,salary_max,experience_min,url,description,discovered_at,match_score,status,skip_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (ext,j.get('source','manual'),j['title'],j['company'],j.get('location',''),j.get('work_mode',''),smin,smax,exp,j['url'],j['description'],datetime.now(timezone.utc).isoformat(),sc,status,'; '.join(reasons)))
            created.append({'external_id':ext,'score':sc,'status':status,'matched_skills':matched,'reasons':reasons})
        except sqlite3.IntegrityError: pass
    c.commit(); c.close(); return jsonify({'imported':len(created),'results':created})
@app.post('/api/jobs/<int:job_id>/prepare')
def prepare(job_id):
    c=db(); r=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
    if not r: c.close(); return jsonify({'error':'job not found'}),404
    j=dict(r); answers=make_answers(j)
    summary='QA Engineer with ~1 year of hands-on experience in manual and automation testing across web and mobile products. Strong practical experience with Playwright, JavaScript/TypeScript, Page Object Model, Appium for Android/iOS, REST API validation, SQL/database testing, cross-browser/device testing, and AI-assisted QA workflows.'
    cover=f'''Dear Hiring Team,\n\nI am excited to apply for the {j['title']} position at {j['company']}. I currently work as a QA Engineer with hands-on experience across manual testing, web automation, mobile automation, API validation, database testing and end-to-end quality assurance.\n\nMy strongest automation experience is with Playwright using JavaScript/TypeScript and Page Object Model, along with Appium for Android and iOS testing. I also use AI-assisted workflows to accelerate test design, automation scripting, debugging and edge-case analysis while keeping human validation in the loop.\n\nI would welcome the opportunity to bring this practical QA and automation mindset to your team.\n\nRegards,\nSatyendra Kumar Namdeo'''
    now=datetime.now(timezone.utc).isoformat(); c.execute('INSERT INTO applications(job_id,tailored_summary,cover_letter,answers_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(job_id,summary,cover,json.dumps(answers),'draft',now,now)); c.execute('UPDATE jobs SET status=? WHERE id=?',('application_ready',job_id)); c.commit(); aid=c.lastrowid; c.close()
    return jsonify({'application_id':aid,'summary':summary,'cover_letter':cover,'answers':answers})
@app.get('/api/applications')
def applications():
    c=db(); rows=c.execute('''SELECT a.*,j.title,j.company,j.location,j.url,j.match_score FROM applications a JOIN jobs j ON j.id=a.job_id ORDER BY a.created_at DESC''').fetchall(); c.close(); return jsonify([dict(r) for r in rows])
@app.post('/api/applications/<int:app_id>/status')
def app_status(app_id):
    status=(request.get_json(silent=True) or {}).get('status'); allowed={'draft','approved','applied','rejected','interview','offer','closed'}
    if status not in allowed: return jsonify({'error':'invalid status'}),400
    c=db(); c.execute('UPDATE applications SET status=?,updated_at=? WHERE id=?',(status,datetime.now(timezone.utc).isoformat(),app_id)); c.commit(); c.close(); return {'ok':True,'status':status}

if __name__=='__main__':
    init_db(); app.run(host='0.0.0.0',port=int(os.getenv('PORT','8000')),debug=os.getenv('DEBUG','false').lower()=='true')
