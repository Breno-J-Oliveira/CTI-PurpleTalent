import os
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, g
import remote_worker


class RemoteWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, 'test.db')
        self.environment = patch.dict(os.environ, {'REMOTE_WORKER_TOKEN': 't' * 40})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        with closing(sqlite3.connect(self.path)) as con, con:
            remote_worker.migrate(con)
        app = Flask(__name__)
        app.config['TESTING'] = True

        def db():
            if 'db' not in g:
                g.db = sqlite3.connect(self.path, timeout=10)
            return g.db

        @app.teardown_appcontext
        def close(error):
            if 'db' in g:
                g.db.close()

        remote_worker.register_routes(app, db)
        self.client = app.test_client()
        self.headers = {'Authorization': 'Bearer ' + 't' * 40}
        self.flag = 'CTF{' + 'a' * 16 + '}'

    def enqueue(self, key='a' * 16, action='start', flag=None):
        with closing(sqlite3.connect(self.path)) as con, con:
            return remote_worker.enqueue(con, request_key=key, action=action,
                instance='lab-u1-c2-aabbcc', scenario='cti-lab/web-01' if action == 'start' else None,
                flag=(flag or self.flag) if action == 'start' else None)

    def poll(self):
        return self.client.post('/api/remote-worker/poll', json={}, headers=self.headers)

    def test_authenticated_single_delivery_and_idempotent_result(self):
        job_id = self.enqueue()
        self.assertEqual(self.client.post('/api/remote-worker/poll', json={}).status_code, 401)
        job = self.poll().get_json()['job']
        self.assertEqual(job['id'], job_id)
        self.assertEqual(job['flag'], self.flag)
        self.assertIsNone(self.poll().get_json()['job'])
        result = {'id': job_id, 'lease': job['lease'], 'status': 'completed'}
        self.assertEqual(self.client.post('/api/remote-worker/result', json=result, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/api/remote-worker/result', json=result, headers=self.headers).status_code, 200)
        result['status'] = 'failed'
        self.assertEqual(self.client.post('/api/remote-worker/result', json=result, headers=self.headers).status_code, 409)
        with closing(sqlite3.connect(self.path)) as con, con:
            self.assertIsNone(con.execute('SELECT flag FROM remote_worker_jobs').fetchone()[0])
        self.assertEqual(self.enqueue(), job_id)

    def test_expired_lease_blocks_queue_and_rejects_late_result(self):
        self.enqueue()
        job = self.poll().get_json()['job']
        self.enqueue('b' * 16, 'stop')
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('UPDATE remote_worker_jobs SET lease_until=0 WHERE id=?', (job['id'],))
        self.assertIsNone(self.poll().get_json()['job'])
        response = self.client.post('/api/remote-worker/result',
            json={'id': job['id'], 'lease': job['lease'], 'status': 'completed'}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        with closing(sqlite3.connect(self.path)) as con, con:
            self.assertEqual(con.execute('SELECT status FROM remote_worker_jobs ORDER BY id').fetchall(),
                             [('interrupted',), ('queued',)])

    def test_invalid_actions_and_reused_keys_are_rejected(self):
        self.enqueue()
        with self.assertRaises(ValueError):
            self.enqueue(flag='CTF{' + 'b' * 16 + '}')
        with closing(sqlite3.connect(self.path)) as con, con:
            for name in ['127.0.0.1', '../lab-u1-c2-aabbcc', 'lab-u1-c2-ABCDEF']:
                with self.assertRaises(ValueError):
                    remote_worker.enqueue(con, request_key='c' * 16, action='stop', instance=name)
        self.assertEqual(self.client.post('/api/remote-worker/poll', json={'url': 'x'}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/remote-worker/result', json={'id': 2**64, 'lease': 'x' * 40, 'status': 'completed'}, headers=self.headers).status_code, 400)
