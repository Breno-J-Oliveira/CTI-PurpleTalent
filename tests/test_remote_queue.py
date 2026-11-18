import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import app as site
import remote_queue


class RemoteQueueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db_path = str(Path(temp.name) / 'queue.db')
        settings = patch.multiple(site, DB=db_path, production=True, remote_enabled=True)
        settings.start()
        self.addCleanup(settings.stop)
        token = patch.dict(os.environ, REMOTE_WORKER_TOKEN='t' * 40,
                           MENTOR_PASSWORD='mentor-fixture-password')
        token.start()
        self.addCleanup(token.stop)
        self.headers = {'Authorization': 'Bearer ' + 't' * 40}
        site.RATE_BUCKETS.clear()
        site.init_db()
        with closing(sqlite3.connect(site.DB)) as con, con:
            for uid in (2, 3, 4):
                con.execute("INSERT INTO users(id,name,email,role) VALUES(?,?,?,'participante')",
                            (uid, f'Pessoa {uid}', f'{uid}@example.invalid'))
            self.challenge = con.execute("""SELECT id FROM challenges WHERE image='cti-lab/incident-01'""").fetchone()[0]
        self.path = f'/challenge/{self.challenge}'
        self.worker = site.app.test_client()

    def client(self, uid):
        client = site.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid, csrf='test')
        return client

    def request(self, client, action):
        return client.post(self.path + '/' + action, data={'csrf_token': 'test'})

    def status(self, client):
        response = client.get(self.path + '/lab-status')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def poll(self):
        response = self.worker.post('/api/remote-worker/poll', headers=self.headers, json={})
        self.assertEqual(response.status_code, 200)
        return response.get_json()['job']

    def result(self, job, status='completed'):
        response = self.worker.post('/api/remote-worker/result', headers=self.headers,
                                    json={'id': job['id'], 'lease': job['lease'], 'status': status})
        self.assertEqual(response.status_code, 200)

    def test_fifo_cancellation_duplicate_admission_and_mentor_view(self):
        first, second, third = (self.client(uid) for uid in (2, 3, 4))
        for client in (first, second, third):
            self.assertEqual(self.request(client, 'start').status_code, 302)
        self.request(third, 'start')
        self.assertIn('Posição 1 na fila', self.status(first))
        self.assertIn('Posição 2 na fila', self.status(second))
        self.assertIn('Posição 3 na fila', self.status(third))
        self.assertNotIn('Pessoa 3', self.status(first))
        overview = first.get('/labs').get_data(as_text=True)
        self.assertIn('Ver minha reserva', overview)
        self.assertNotIn('VirtualBox', overview)
        self.assertEqual(first.get('/ambientes').status_code, 403)
        dashboard = self.client(1).get('/ambientes').get_data(as_text=True)
        self.assertLess(dashboard.index('Pessoa 2'), dashboard.index('Pessoa 3'))
        self.assertLess(dashboard.index('Pessoa 3'), dashboard.index('Pessoa 4'))
        start = self.poll()
        self.assertTrue(start['instance'].startswith('lab-u2-'))
        self.assertIn('VM está iniciando', self.status(first))
        self.assertIn('Posição 1 na fila', self.status(second))
        self.result(start)
        self.assertIsNone(self.poll())
        self.assertIn('Restam 60 min', self.status(first))
        with closing(sqlite3.connect(site.DB)) as con:
            slot = con.execute('SELECT id FROM remote_challenge_instances WHERE user_id=2').fetchone()[0]
        self.assertEqual(second.get(f'/remote-lab/{slot}').status_code, 404)
        self.assertIn('Tempo restante', first.get(f'/remote-lab/{slot}').get_data(as_text=True))
        self.request(second, 'stop')
        self.assertIn('Posição 1 na fila', self.status(third))
        self.request(first, 'stop')
        self.assertEqual(first.get(f'/remote-lab/{slot}').status_code, 404)
        stop = self.poll()
        self.assertEqual(stop['action'], 'stop')
        self.assertEqual(stop['instance'], start['instance'])
        self.result(stop)
        following = self.poll()
        self.assertTrue(following['instance'].startswith('lab-u4-'))
        self.result(following)

    def test_wait_does_not_consume_session_and_duplicate_ack_does_not_extend(self):
        first = self.client(2)
        self.request(first, 'start')
        with closing(sqlite3.connect(site.DB)) as con, con:
            past = int(time.time()) - 7200
            con.execute('UPDATE remote_challenge_instances SET created_at=?,expires_at=?', (past, past + 3600))
        start = self.poll()
        self.result(start)
        with closing(sqlite3.connect(site.DB)) as con, con:
            expiry = con.execute('SELECT expires_at FROM remote_challenge_instances').fetchone()[0]
            self.assertGreaterEqual(expiry - int(time.time()), remote_queue.SESSION_SECONDS - 3)
            con.execute('UPDATE remote_challenge_instances SET expires_at=expires_at-60')
        self.result(start)
        with closing(sqlite3.connect(site.DB)) as con, con:
            self.assertEqual(con.execute('SELECT expires_at FROM remote_challenge_instances').fetchone()[0], expiry - 60)
            con.execute('UPDATE remote_challenge_instances SET expires_at=0')
        self.request(self.client(3), 'start')
        stop = self.poll()
        self.assertEqual(stop['action'], 'stop')
        self.result(stop)
        incoming = self.poll()
        self.assertEqual(incoming['action'], 'start')
        self.assertTrue(incoming['instance'].startswith('lab-u3-'))

    def test_failed_stop_blocks_next_candidate_until_retry_succeeds(self):
        first = self.client(2)
        self.request(first, 'start')
        self.request(self.client(3), 'start')
        start = self.poll()
        self.result(start)
        self.request(first, 'stop')
        stop = self.poll()
        self.result(stop, status='failed')
        self.assertIsNone(self.poll())
        self.assertIn('Tentar encerrar novamente', self.status(first))
        self.request(first, 'stop')
        retry = self.poll()
        self.assertEqual(retry['action'], 'stop')
        self.result(retry)
        self.assertTrue(self.poll()['instance'].startswith('lab-u3-'))

    def test_dispatch_rechecks_team_and_queue_expiration(self):
        with closing(sqlite3.connect(site.DB)) as con, con:
            con.execute('UPDATE challenges SET requires_team=1 WHERE id=?', (self.challenge,))
            con.execute("""INSERT INTO team_members
                SELECT t.id,u.id,0 FROM teams t CROSS JOIN users u
                WHERE t.name='Blue Team Alpha' AND u.id IN (2,3,4)""")
        for uid in (2, 3, 4):
            self.request(self.client(uid), 'start')
        with closing(sqlite3.connect(site.DB)) as con, con:
            con.execute('DELETE FROM team_members WHERE user_id=2')
            con.execute('UPDATE remote_challenge_instances SET created_at=0 WHERE user_id=3')
        self.assertTrue(self.poll()['instance'].startswith('lab-u4-'))
        with closing(sqlite3.connect(site.DB)) as con:
            self.assertEqual(con.execute("""SELECT j.status,j.flag FROM remote_worker_jobs j
                JOIN remote_challenge_instances i ON i.start_job_id=j.id WHERE i.user_id IN (2,3)
                ORDER BY i.user_id""").fetchall(), [('failed', None), ('failed', None)])

    def test_duplicate_concurrent_requests_reserve_only_one_place(self):
        def book(_):
            return self.request(self.client(2), 'start').status_code
        with ThreadPoolExecutor(max_workers=4) as workers:
            self.assertEqual(list(workers.map(book, range(4))), [302] * 4)
        with closing(sqlite3.connect(site.DB)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM remote_challenge_instances').fetchone()[0], 1)
