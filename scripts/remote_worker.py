"""Executor local restrito para solicitações autenticadas do Purple Talent.

O processo deve usar uma pasta privada fora do repositório para o journal.
Este componente apenas administra VMs, não expõe nem encaminha suas portas.
"""
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import orchestrator

MAX_RESPONSE = 32768
LEASE = re.compile(r'[A-Za-z0-9_-]{32,256}\Z')
FLAG = re.compile(r'CTF\{[a-f0-9]{16,64}\}\Z')


def validate_job(job):
    if not isinstance(job, dict) or set(job) != {'id', 'lease', 'action', 'instance', 'scenario', 'flag'}:
        raise ValueError('Solicitação inválida.')
    if type(job['id']) is not int or not 0 < job['id'] < 2**63:
        raise ValueError('Identificador inválido.')
    if not isinstance(job['lease'], str) or not LEASE.fullmatch(job['lease']):
        raise ValueError('Reserva inválida.')
    if not isinstance(job['instance'], str) or not orchestrator.NAME.fullmatch(job['instance']):
        raise ValueError('Instância inválida.')
    if (job['action'] == 'start' and isinstance(job['scenario'], str)
            and job['scenario'] in orchestrator.IMAGES
            and isinstance(job['flag'], str) and FLAG.fullmatch(job['flag'])):
        return
    if job['action'] == 'stop' and job['scenario'] is None and job['flag'] is None:
        return
    raise ValueError('Operação inválida.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SiteClient:
    def __init__(self, base_url, token):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('Use a origem HTTPS do site.')
        if not isinstance(token, str) or not LEASE.fullmatch(token):
            raise ValueError('Credencial do executor inválida.')
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def send(self, endpoint, payload):
        request = urllib.request.Request(self.base_url + endpoint,
            data=json.dumps(payload).encode('utf-8'), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with self.opener.open(request, timeout=20) as response:
            if response.status != 200:
                raise ValueError('Resposta inesperada do site.')
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('Resposta excede o limite.')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Resposta inválida do site.')
        return result


class Worker:
    def __init__(self, client, journal):
        path = Path(journal)
        if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
            raise ValueError('Use caminho absoluto para o journal em uma pasta privada existente.')
        self.client = client
        lock_path = path.with_name(path.name + '.lock')
        if lock_path.is_symlink():
            raise ValueError('Caminho de reserva inválido.')
        self.lock = lock_path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise ValueError('Outro executor já usa este journal.') from None
        self.db = sqlite3.connect(path, timeout=10)
        if os.name != 'nt':
            os.chmod(path, 0o600)
        self.db.execute('''CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY, lease TEXT NOT NULL, action TEXT NOT NULL,
            instance TEXT NOT NULL, state TEXT NOT NULL, port INTEGER,
            acknowledged INTEGER NOT NULL DEFAULT 0)''')
        self.db.commit()

    def close(self):
        self.db.close()
        self.lock.close()

    def recover(self):
        # Uma operação interrompida tem resultado desconhecido. Nunca execute
        # novamente; encerre a VM e registre falha antes de aceitar outro job.
        rows = self.db.execute("SELECT id,instance FROM jobs WHERE state='running'").fetchall()
        for identifier, instance in rows:
            orchestrator.stop(instance)
            with self.db:
                self.db.execute("UPDATE jobs SET state='failed' WHERE id=?", (identifier,))

    def flush(self):
        for identifier, lease, state in self.db.execute(
                "SELECT id,lease,state FROM jobs WHERE acknowledged=0 AND state IN ('completed','failed') ORDER BY id").fetchall():
            result = self.client.send('/api/remote-worker/result',
                                      {'id': identifier, 'lease': lease, 'status': state})
            if result.get('ok') is not True:
                raise ValueError('Resultado não confirmado pelo site.')
            with self.db:
                self.db.execute('UPDATE jobs SET acknowledged=1 WHERE id=?', (identifier,))

    def run_once(self):
        self.recover()
        self.flush()
        response = self.client.send('/api/remote-worker/poll', {})
        job = response.get('job')
        if job is None:
            return
        validate_job(job)
        existing = self.db.execute('SELECT lease FROM jobs WHERE id=?', (job['id'],)).fetchone()
        if existing:
            # ID repetido jamais volta a executar, mesmo com outro lease.
            raise ValueError('Solicitação já registrada no executor.')
        with self.db:
            self.db.execute("INSERT INTO jobs(id,lease,action,instance,state) VALUES(?,?,?,?,'running')",
                            (job['id'], job['lease'], job['action'], job['instance']))
        try:
            if job['action'] == 'start':
                port = orchestrator.start(job['instance'], job['scenario'], 5000, job['flag'])
                if type(port) is not int or not 1 <= port <= 65535:
                    raise orchestrator.LabError('Porta inválida.')
            else:
                orchestrator.stop(job['instance'])
                port = None
            with self.db:
                self.db.execute("UPDATE jobs SET state='completed',port=? WHERE id=?", (port, job['id']))
                if job['action'] == 'stop':
                    self.db.execute("UPDATE jobs SET port=NULL WHERE instance=? AND action='start'", (job['instance'],))
        except (orchestrator.LabError, OSError, sqlite3.Error):
            # A falha de registro após iniciar também exige desligar a VM.
            if job['action'] == 'start':
                orchestrator.stop(job['instance'])
            with self.db:
                self.db.execute("UPDATE jobs SET state='failed',port=NULL WHERE id=?", (job['id'],))
        self.flush()


def main():
    client = SiteClient(os.environ.get('LAB_WORKER_SITE', ''), os.environ.get('LAB_WORKER_TOKEN', ''))
    worker = Worker(client, os.environ.get('LAB_WORKER_JOURNAL', ''))
    try:
        while True:
            try:
                worker.run_once()
            except (OSError, ValueError, sqlite3.Error, urllib.error.URLError, orchestrator.LabError):
                # Nunca imprimir conteúdo de respostas, credenciais ou flags.
                print('Executor aguardando conexão ou intervenção do operador.', flush=True)
            time.sleep(5)
    finally:
        worker.close()


if __name__ == '__main__':
    main()
