"""Persistent, single-delivery queue for a trusted local VM executor.

The browser cannot enqueue jobs through this module. A caller with a validated
session must enqueue them inside its own transaction. The worker never receives
shell commands, hostnames, URLs, or ports from the site.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

from flask import abort, jsonify, request

LEASE_SECONDS = 600
SCENARIOS = ('cti-lab/web-01', 'cti-lab/incident-01')
NAME = re.compile(r'lab-u[0-9]+-c[0-9]+-[a-f0-9]{6,32}\Z')
FLAG = re.compile(r'CTF\{[a-f0-9]{16,64}\}\Z')
LEASE = re.compile(r'[A-Za-z0-9_-]{32,128}\Z')


def migrate(con):
    con.execute('''CREATE TABLE IF NOT EXISTS remote_worker_jobs(
        id INTEGER PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
        action TEXT NOT NULL CHECK(action IN ('start','stop')),
        instance TEXT NOT NULL, scenario TEXT, flag TEXT, flag_hash TEXT,
        status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN
            ('queued','running','completed','failed','interrupted')),
        lease TEXT, lease_until INTEGER, created_at INTEGER NOT NULL,
        finished_at INTEGER)''')


def enqueue(con, *, request_key, action, instance, scenario=None, flag=None):
    """Insert one job atomically with the caller's changes; never commits.

    A repeated request key is accepted only when the payload matches. Do not
    reuse a completed request key for another action.
    """
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_key):
        raise ValueError('Invalid request key')
    if not isinstance(instance, str) or not NAME.fullmatch(instance):
        raise ValueError('Invalid instance')
    if action == 'start':
        if scenario not in SCENARIOS or not isinstance(flag, str) or not FLAG.fullmatch(flag):
            raise ValueError('Invalid start request')
    elif action != 'stop' or scenario is not None or flag is not None:
        raise ValueError('Invalid stop request')
    flag_hash = hashlib.sha256(flag.encode('ascii')).hexdigest() if flag else None
    row = con.execute('SELECT id,action,instance,scenario,flag_hash,status FROM remote_worker_jobs WHERE request_key=?', (request_key,)).fetchone()
    if row:
        if tuple(row[1:5]) != (action, instance, scenario, flag_hash):
            raise ValueError('Request key already used')
        return row[0]
    cursor = con.execute('INSERT INTO remote_worker_jobs(request_key,action,instance,scenario,flag,flag_hash,created_at) VALUES(?,?,?,?,?,?,?)',
                         (request_key, action, instance, scenario, flag, flag_hash, int(time.time())))
    return cursor.lastrowid


def authenticate():
    expected = os.environ.get('REMOTE_WORKER_TOKEN', '')
    actual = request.headers.get('Authorization', '')
    if not (32 <= len(expected) <= 256 and expected.isascii() and
            actual.startswith('Bearer ') and actual[7:].isascii() and
            hmac.compare_digest(actual[7:], expected)):
        abort(401)


def register_routes(app, db):
    """Register authenticated polling and acknowledgement endpoints.

    The application must exempt only these endpoints from browser CSRF after
    calling authenticate() in its before-request handler, and call migrate()
    when initializing the database. Do not bypass host checks.
    """
    @app.post('/api/remote-worker/poll')
    def remote_worker_poll():
        authenticate()
        if request.get_json(silent=True) != {}:
            abort(400)
        con = db()
        con.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        con.execute("UPDATE remote_worker_jobs SET status='interrupted',finished_at=?,flag=NULL WHERE status='running' AND lease_until<=?", (now, now))
        # One executor operates one job at a time. Do not dispatch another job
        # while a previous lease is awaiting acknowledgement.
        running = con.execute("SELECT 1 FROM remote_worker_jobs WHERE status IN ('running','interrupted') LIMIT 1").fetchone()
        row = None if running else con.execute("SELECT id,action,instance,scenario,flag FROM remote_worker_jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        job = None
        if row:
            lease = secrets.token_urlsafe(32)
            con.execute("UPDATE remote_worker_jobs SET status='running',lease=?,lease_until=? WHERE id=? AND status='queued'", (lease, now + LEASE_SECONDS, row[0]))
            job = dict(id=row[0], action=row[1], instance=row[2], scenario=row[3], flag=row[4], lease=lease)
        con.commit()
        return jsonify(job=job)

    @app.post('/api/remote-worker/result')
    def remote_worker_result():
        authenticate()
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'id', 'lease', 'status'}
                or type(data['id']) is not int or not 0 < data['id'] < 2**63
                or not isinstance(data['lease'], str) or not LEASE.fullmatch(data['lease'])
                or data['status'] not in ('completed', 'failed')):
            abort(400)
        con = db()
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT status,lease,lease_until FROM remote_worker_jobs WHERE id=?', (data['id'],)).fetchone()
        if not row or not row[1] or not hmac.compare_digest(row[1], data['lease']):
            con.rollback()
            abort(409)
        now = int(time.time())
        if row[0] == 'running' and row[2] > now:
            con.execute('UPDATE remote_worker_jobs SET status=?,finished_at=?,flag=NULL WHERE id=?', (data['status'], now, data['id']))
        elif row[0] != data['status']:
            con.rollback()
            abort(409)
        con.commit()
        return jsonify(ok=True)
