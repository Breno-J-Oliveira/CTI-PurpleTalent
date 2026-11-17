import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from functools import wraps
from unittest.mock import patch

from flask import Flask, g, session, abort
import remote_relay
import remote_worker
from scripts import remote_relay as local_relay


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, 'test.db')
        self.env = patch.dict(os.environ, {'REMOTE_WORKER_TOKEN':'x' * 40})
        self.env.start()
        self.addCleanup(self.env.stop)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('CREATE TABLE challenges(id INTEGER PRIMARY KEY,image TEXT,active INTEGER)')
            con.execute('CREATE TABLE remote_challenge_instances(id INTEGER PRIMARY KEY,user_id INTEGER,challenge_id INTEGER,instance TEXT,start_job_id INTEGER,stop_job_id INTEGER,expires_at INTEGER)')
            remote_worker.migrate(con)
            remote_relay.migrate(con)
            con.execute("INSERT INTO challenges VALUES(1,'cti-lab/incident-01',1)")
            con.execute("INSERT INTO remote_worker_jobs(id,request_key,action,instance,status,created_at) VALUES(1,'start_fixture_123','start','lab-u2-c1-aabbcc','completed',0)")
            con.execute("INSERT INTO remote_challenge_instances VALUES(1,2,1,'lab-u2-c1-aabbcc',1,NULL,?)", (int(time.time())+120,))
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.app.config['TESTING'] = True
        def db():
            if 'db' not in g:
                g.db = sqlite3.connect(self.path, timeout=10)
            return g.db
        @self.app.teardown_appcontext
        def close(error):
            if 'db' in g:
                g.db.close()
        def login_required(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                if 'user_id' not in session:
                    abort(401)
                return f(*args, **kwargs)
            return wrapper
        remote_relay.register_routes(self.app, db, login_required)
        self.client = self.app.test_client()
        self.worker = self.app.test_client()
        self.headers = {'Authorization':'Bearer ' + 'x' * 40}
        with self.client.session_transaction() as s:
            s['user_id'] = 2

    def tearDown(self):
        self.temp.cleanup()

    def create(self, path='/access'):
        return self.client.post('/remote-lab/1/request', data={'path':path})

    def poll(self):
        return self.worker.post('/api/remote-relay/poll', json={}, headers=self.headers)

    def test_owner_and_allowlist(self):
        self.assertEqual(self.create('http://127.0.0.1:22/').status_code, 400)
        self.assertEqual(self.create('/%72obots.txt').status_code, 400)
        self.assertEqual(self.worker.post('/api/remote-relay/poll', json={}).status_code, 401)
        with self.client.session_transaction() as s:
            s['user_id'] = 3
        self.assertEqual(self.create().status_code, 404)
        self.assertIsNone(self.poll().get_json()['job'])

    def test_round_trip_and_results_are_json(self):
        response = self.create()
        self.assertEqual(response.status_code, 202)
        rid = response.get_json()['id']
        job = self.poll().get_json()['job']
        self.assertEqual(job['path'], '/access')
        payload = dict(id=rid, lease=job['lease'], status='completed', content_type='text/plain', body='User-agent: *')
        self.assertEqual(self.worker.post('/api/remote-relay/result', json=payload, headers=self.headers).status_code, 200)
        response = self.client.get(f'/remote-lab/1/request/{rid}')
        self.assertEqual(response.get_json()['body'], 'User-agent: *')
        self.assertTrue(response.content_type.startswith('application/json'))
        with self.client.session_transaction() as s:
            s['user_id'] = 3
        self.assertEqual(self.client.get(f'/remote-lab/1/request/{rid}').status_code, 404)

    def test_cancelled_and_expired_block_poll_or_result(self):
        rid = self.create().get_json()['id']
        job = self.poll().get_json()['job']
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('UPDATE remote_challenge_instances SET stop_job_id=5')
        payload = dict(id=rid, lease=job['lease'], status='completed', content_type='text/plain', body='x')
        self.assertEqual(self.worker.post('/api/remote-relay/result', json=payload, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.get(f'/remote-lab/1/request/{rid}').status_code, 404)

    def test_lease_and_payload_limit(self):
        rid = self.create().get_json()['id']
        job = self.poll().get_json()['job']
        payload = dict(id=rid, lease=job['lease'], status='completed', content_type='text/html', body='x' * (remote_relay.MAX_BODY+1))
        self.assertEqual(self.worker.post('/api/remote-relay/result', json=payload, headers=self.headers).status_code, 400)
        payload['body'] = 'ok'
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('UPDATE remote_relay_reads SET lease_until=0')
        self.assertEqual(self.worker.post('/api/remote-relay/result', json=payload, headers=self.headers).status_code, 409)


class LocalRelayTests(unittest.TestCase):
    def test_invalid_or_stopped_instances_never_reach_a_port(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE TABLE jobs(id INTEGER, instance TEXT, action TEXT, state TEXT, port INTEGER, acknowledged INTEGER)')
        con.execute("INSERT INTO jobs VALUES(1,'lab-u2-c1-aabbcc','stop','completed',NULL,1)")
        class Client:
            def __init__(self): self.requests = []
            def send(self, path, payload):
                self.requests.append((path,payload))
                if path.endswith('poll'):
                    return {'job':dict(id=1, lease='x'*40, instance='lab-u2-c1-aabbcc', scenario='cti-lab/incident-01', path='/')}
                return {'ok':True}
        client = Client()
        with patch.object(local_relay.http.client, 'HTTPConnection') as connection:
            local_relay.serve_once(client, con)
            connection.assert_not_called()
        self.assertEqual(client.requests[-1][1]['status'], 'failed')

    def test_input_cannot_choose_target(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        class Client:
            def send(self, path, payload):
                return {'job':dict(id=1, lease='x'*40, instance='lab-u2-c1-aabbcc', scenario='cti-lab/incident-01', path='http://127.0.0.1:5000/')}
        with self.assertRaises(ValueError):
            local_relay.serve_once(Client(), con)
