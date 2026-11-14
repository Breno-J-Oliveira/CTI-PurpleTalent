import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import remote_worker as client
import remote_worker as queue
from flask import Flask, g


def job(action='start', identifier=1):
    return {'id': identifier, 'lease': 'l' * 43, 'action': action,
            'instance': 'lab-u1-c2-abcdef',
            'scenario': 'cti-lab/web-01' if action == 'start' else None,
            'flag': 'CTF{0123456789abcdef}' if action == 'start' else None}


class RemoteWorkerClientTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.api = Mock()
        self.path = Path(self.folder.name) / 'state.db'
        self.worker = client.Worker(self.api, self.path)
        self.addCleanup(self.worker.close)

    def test_only_expected_actions_and_inputs_are_accepted(self):
        client.validate_job(job())
        client.validate_job(job('stop'))
        for replacement in ({'action': 'shell'}, {'instance': '../test'},
                            {'scenario': []}, {'flag': 'bad'}, {'id': True},
                            {'lease': 'short'}):
            invalid = job()
            invalid.update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                client.validate_job(invalid)

    def test_start_acknowledges_and_saves_port_locally(self):
        self.api.send.side_effect = [{'job': job()}, {'ok': True}]
        with patch.object(client.orchestrator, 'start', return_value=12345) as start:
            self.worker.run_once()
        start.assert_called_once()
        self.assertEqual(self.worker.db.execute('SELECT state,port,acknowledged FROM jobs').fetchone(),
                         ('completed', 12345, 1))
        sent = self.api.send.call_args_list[-1].args[1]
        self.assertEqual(set(sent), {'id', 'lease', 'status'})
        self.assertNotIn('12345', json.dumps(sent))
        self.assertNotIn('CTF{', self.path.read_bytes().decode('latin1'))

    def test_lost_ack_is_retried_without_second_execution(self):
        self.api.send.side_effect = [{'job': job()}, OSError('network')]
        with patch.object(client.orchestrator, 'start', return_value=12345) as start:
            with self.assertRaises(OSError):
                self.worker.run_once()
            self.api.send.side_effect = [{'ok': True}, {'job': None}]
            self.worker.run_once()
        start.assert_called_once()
        self.assertEqual(self.worker.db.execute('SELECT acknowledged FROM jobs').fetchone()[0], 1)

    def test_interrupted_start_is_cleaned_up_and_not_repeated(self):
        with self.worker.db:
            self.worker.db.execute("INSERT INTO jobs(id,lease,action,instance,state) VALUES(?,?,?,?,?)",
                                   (1, 'l'*43, 'start', 'lab-u1-c2-abcdef', 'running'))
        self.api.send.side_effect = [{'ok': True}, {'job': None}]
        with patch.object(client.orchestrator, 'stop') as stop, patch.object(client.orchestrator, 'start') as start:
            self.worker.run_once()
        stop.assert_called_once_with('lab-u1-c2-abcdef')
        start.assert_not_called()
        self.assertEqual(self.worker.db.execute('SELECT state FROM jobs').fetchone()[0], 'failed')

    def test_duplicate_id_does_not_execute(self):
        with self.worker.db:
            self.worker.db.execute("INSERT INTO jobs(id,lease,action,instance,state,acknowledged) VALUES(?,?,?,?,?,1)",
                                   (1, 'l'*43, 'start', 'lab-u1-c2-abcdef', 'completed'))
        self.api.send.return_value = {'job': job()}
        with patch.object(client.orchestrator, 'start') as start, self.assertRaises(ValueError):
            self.worker.run_once()
        start.assert_not_called()

    def test_failed_start_is_cleaned_before_reporting(self):
        self.api.send.side_effect = [{'job': job()}, {'ok': True}]
        with patch.object(client.orchestrator, 'start', side_effect=client.orchestrator.LabError('fixture')), patch.object(client.orchestrator, 'stop') as stop:
            self.worker.run_once()
        stop.assert_called_once_with('lab-u1-c2-abcdef')
        self.assertEqual(self.worker.db.execute('SELECT state FROM jobs').fetchone()[0], 'failed')

    def test_journal_rejects_a_second_worker(self):
        with self.assertRaisesRegex(ValueError, 'Outro executor'):
            client.Worker(self.api, self.path)

    def test_site_requires_https_and_valid_credentials(self):
        for url in ['http://example.test', 'https://user:pass@example.test', 'https://example.test/path', 'https://example.test/?token=x']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.SiteClient(url, 'a'*48)
        with self.assertRaises(ValueError):
            client.SiteClient('https://example.test', 'short')

    def test_real_queue_and_worker_agree_on_start_and_stop_contract(self):
        path = Path(self.folder.name) / 'site.db'
        site = Flask(__name__)
        site.config['TESTING'] = True
        with closing(sqlite3.connect(path)) as con, con:
            queue.migrate(con)
            queue.enqueue(con, request_key='request-start-1234', action='start',
                          instance='lab-u1-c2-abcdef', scenario='cti-lab/web-01',
                          flag='CTF{0123456789abcdef}')

        def db():
            if 'db' not in g:
                g.db = sqlite3.connect(path)
            return g.db

        @site.teardown_appcontext
        def close_db(error):
            if 'db' in g:
                g.db.close()

        queue.register_routes(site, db)
        browser = site.test_client()

        def send(endpoint, payload):
            response = browser.post(endpoint, json=payload,
                                    headers={'Authorization': 'Bearer ' + 't'*40})
            self.assertEqual(response.status_code, 200)
            return response.get_json()

        self.api.send.side_effect = send
        with patch.dict(os.environ, {'REMOTE_WORKER_TOKEN': 't'*40}), \
                patch.object(client.orchestrator, 'start', return_value=12345), \
                patch.object(client.orchestrator, 'stop') as stop:
            self.worker.run_once()
            with closing(sqlite3.connect(path)) as con, con:
                queue.enqueue(con, request_key='request-stop-12345', action='stop',
                              instance='lab-u1-c2-abcdef')
            self.worker.run_once()
        stop.assert_called_once_with('lab-u1-c2-abcdef')
        self.assertEqual(self.worker.db.execute("SELECT port FROM jobs WHERE action='start'").fetchone()[0], None)
        with closing(sqlite3.connect(path)) as con:
            self.assertEqual(con.execute('SELECT status FROM remote_worker_jobs ORDER BY id').fetchall(),
                             [('completed',), ('completed',)])
