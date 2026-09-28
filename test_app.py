from app import app, init_db

def test_health(tmp_path, monkeypatch):
    monkeypatch.setattr('app.DB', tmp_path/'db.sqlite')
    init_db()
    r = app.test_client().get('/api/health')
    assert r.status_code == 200 and r.json['status'] == 'ok'

def test_import_and_filter(tmp_path, monkeypatch):
    monkeypatch.setattr('app.DB', tmp_path/'db.sqlite')
    init_db()
    client = app.test_client()
    good = {
        'external_id':'g1','source':'test','title':'QA Automation Engineer',
        'company':'Example','location':'Bangalore','work_mode':'Hybrid',
        'salary_min':4,'salary_max':6,'experience_min':2,
        'url':'https://example.com/1','description':'Playwright Python SQL API testing'
    }
    bad = {**good,'external_id':'b1','title':'Senior SDET','experience_min':4}
    r = client.post('/api/jobs/import', json={'jobs':[good,bad]})
    assert r.status_code == 200
    jobs = client.get('/api/jobs').json
    assert any(x['status']=='ready' for x in jobs)
    assert any(x['status']=='skipped' for x in jobs)

def test_prepare_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr('app.DB', tmp_path/'db.sqlite')
    init_db()
    client = app.test_client()
    job = {
        'external_id':'g1','source':'test','title':'SDET','company':'Example',
        'location':'Pune','work_mode':'Hybrid','salary_min':4,'salary_max':6,
        'experience_min':1,'url':'https://example.com/1',
        'description':'Playwright Python SQL API testing'
    }
    client.post('/api/jobs/import', json={'jobs':[job]})
    j = client.get('/api/jobs').json[0]
    r = client.post(f"/api/jobs/{j['id']}/prepare")
    assert r.status_code == 200 and r.json['application_id']
    appid = r.json['application_id']
    r = client.post(f'/api/applications/{appid}/status', json={'status':'approved'})
    assert r.status_code == 200
