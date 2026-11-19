"""Isolated synthetic data for responsive browser QA; no real VM or team data."""
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['SECRET_KEY'] = secrets.token_hex(32)
from scripts.prepare_demo import prepare_demo
import app
import blog
import recruitment
import remote_worker


def seed_extra(database):
    now = int(time.time())
    with sqlite3.connect(database) as con:
        uid = con.execute("SELECT id FROM users WHERE email='candidato@demo.invalid'").fetchone()[0]
        mentor = con.execute("SELECT id FROM users WHERE role='mentor'").fetchone()[0]
        jobs = [r[0] for r in con.execute('SELECT id FROM jobs ORDER BY id')]
        # Keep completed evidence reachable at its selection route.
        con.execute("UPDATE applications SET status='review' WHERE submitted_at IS NOT NULL")
        draft = con.execute("SELECT id,form_version FROM applications WHERE status='draft'").fetchone()
        qs = recruitment.load_questions(con, draft[1])
        recruitment.write_answers(con, draft[0], qs, dict(availability='Tarde, disponibilidade fictícia.', correlation='Request ID', experience='Investigação fictícia de logs em ambiente didático.', portfolio=''))
        # A separate job/application allows checking in-progress assessment without
        # sacrificing the saved-draft and completed-assessment fixtures.
        jid = con.execute('''INSERT INTO jobs(title,company,description,side,min_points,active,created_by,created_at,status,updated_at)
            VALUES('QA — Avaliação em andamento','Empresa fictícia','Cenário de QA sem recrutamento real.','Blue Team',0,1,?,?,'published',?)''', (mentor, now, now)).lastrowid
        ver = recruitment.create_version(con, jid, recruitment.defaults('Blue Team'), mentor)
        con.execute('UPDATE jobs SET current_form_version=? WHERE id=?', (ver, jid))
        aid = con.execute('''INSERT INTO applications(job_id,user_id,created_at,status,form_version,updated_at,submitted_at)
            VALUES(?,?,?,'submitted',?,?,?)''', (jid, uid, now, ver, now, now)).lastrowid
        post = con.execute('''INSERT INTO blog_posts(title,category,summary,body,published,author_id,created_at,updated_at)
            VALUES('QA — Guia de investigação','Logs','Artigo fictício de QA.','Conteúdo fictício de teste com evidências e hipóteses em um ambiente didático.',1,?,?,?)''', (mentor, now, now)).lastrowid
        team = con.execute("SELECT id FROM teams WHERE side='Blue Team' ORDER BY id LIMIT 1").fetchone()[0]
        con.execute('INSERT INTO team_members(team_id,user_id,joined_at) VALUES(?,?,?)', (team, uid, now))
        con.execute("UPDATE users SET team='Blue Team Alpha' WHERE id=?", (uid,))
        for cid, correct in ((1, 1), (3, 0), (4, 1)):
            con.execute('INSERT INTO attempts(user_id,challenge_id,correct,created_at) VALUES(?,?,?,?)', (uid, cid, correct, now))
        con.execute('INSERT INTO writeups(user_id,challenge_id,content,updated_at) VALUES(?,?,?,?)', (uid, 1, 'Relato fictício de QA: preservei os registros e documentei as hipóteses e os limites da investigação.', now))
        con.execute('INSERT INTO evaluations(user_id,mentor_id,logica,comunicacao,colaboracao,decisao,notes,created_at) VALUES(?,?,4,4,3,4,?,?)', (uid, mentor, 'Avaliação didática fictícia de QA.', now))
        con.execute("INSERT INTO occurrences(user_id,challenge_id,kind,created_at) VALUES(?,4,'window_blur',?)", (uid, now))
        incident = con.execute("SELECT id FROM challenges WHERE image='cti-lab/incident-01'").fetchone()[0]
        instance_name = f'lab-u{uid}-c{incident}-aabbcc'
        worker_job = remote_worker.enqueue(con, request_key='responsive-fixture-start-job', action='start', instance=instance_name, scenario='cti-lab/incident-01', flag='CTF{' + 'a' * 32 + '}')
        con.execute("UPDATE remote_worker_jobs SET status='completed',finished_at=? WHERE id=?", (now, worker_job))
        instance = con.execute('''INSERT INTO remote_challenge_instances(user_id,challenge_id,instance,answer_hash,start_job_id,created_at,expires_at)
            VALUES(?,?,?,?,?,?,?)''', (uid, incident, instance_name, hashlib.sha256(('CTF{' + 'a' * 32 + '}').encode()).hexdigest(), worker_job, now, now + 86400)).lastrowid
        applications = [r[0] for r in con.execute('SELECT id FROM applications ORDER BY id')]
        challenges = [r[0] for r in con.execute('SELECT id FROM challenges ORDER BY id')]
        con.execute('PRAGMA foreign_keys=ON')
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []
    return dict(user=uid, jobs=jobs + [jid], applications=applications,
                challenges=challenges, post=post, pendingApplication=aid, instance=instance, incident=incident,
                draftApplication=draft[0])


if __name__ == '__main__':
    target = ROOT / 'output' / 'qa' / 'responsive'
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-', dir=target) as folder:
        app.DB = str(prepare_demo(Path(folder) / 'fixture.db'))
        # Exercise production-only HTML with synthetic queue rows. No worker,
        # VM, credentials, network relay, or real command is started.
        app.remote_enabled = True
        fixture = seed_extra(app.DB)
        fixture['htmlRoutes'] = [str(rule) for rule in app.app.url_map.iter_rules()
                                 if 'GET' in rule.methods and rule.endpoint != 'static'
                                 and '/request/' not in str(rule)]
        (target / 'fixture.json').write_text(json.dumps(fixture, indent=2), encoding='utf-8')
        print('Responsive QA fixture ready on http://127.0.0.1:5058', flush=True)
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        app.app.run(host='127.0.0.1', port=5058, debug=False, use_reloader=False)
