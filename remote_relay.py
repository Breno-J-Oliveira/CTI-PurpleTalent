"""Restricted asynchronous reads from disposable challenge VMs.

The worker uses its private journal to resolve an instance to a loopback port.
Only server-owned scenario paths are sent. Results are JSON, never served as
active HTML. This module requires integration with browser and worker code.
"""
import hmac
import secrets
import sqlite3
import time

from flask import abort, jsonify, request, session
import remote_worker

PATHS = {
    'cti-lab/incident-01': {'/': 'Visão geral', '/access': 'Acessos HTTP', '/events': 'Eventos',
                             '/processes': 'Processos', '/changes': 'Alterações', '/network': 'Conexões'},
    'cti-lab/web-01': {'/': 'Visão geral', '/catalogo': 'Catálogo aprovado',
                       '/publicacoes': 'Registro de publicação', '/revisoes': 'Referências de revisão'},
}
TYPES = frozenset(('text/html', 'text/plain'))
MAX_BODY = 32768
REQUEST_TTL = 60
LEASE_SECONDS = 30


def migrate(con):
    con.execute('''CREATE TABLE IF NOT EXISTS remote_relay_reads (
        id INTEGER PRIMARY KEY, instance_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL, path TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
        lease TEXT, created_at INTEGER NOT NULL, deadline INTEGER NOT NULL,
        lease_until INTEGER, content_type TEXT, body TEXT)''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_remote_relay_queue ON remote_relay_reads(status,id)')


def allowed_instance(con, identifier, user_id, now):
    return con.execute('''SELECT i.id,i.instance,c.image,c.id,i.expires_at
        FROM remote_challenge_instances i
        JOIN challenges c ON c.id=i.challenge_id
        JOIN remote_worker_jobs j ON j.id=i.start_job_id
        WHERE i.id=? AND i.user_id=? AND i.expires_at>?
        AND i.stop_job_id IS NULL AND j.status='completed' AND c.active=1 AND c.image IN ('cti-lab/incident-01','cti-lab/web-01')
        AND (c.requires_team=0 OR EXISTS (
            SELECT 1 FROM team_members m JOIN teams t ON t.id=m.team_id
            WHERE m.user_id=i.user_id AND t.side=c.side))''',
        (identifier, user_id, now)).fetchone()


def register_routes(app, db, login_required):
    """Mount routes only after integrating the worker and UI.

    Application CSRF protection must remain for browser POSTs. Only the two
    worker endpoints may use bearer authentication in lieu of browser CSRF.
    """
    @app.post('/remote-lab/<int:instance_id>/request')
    @login_required
    def remote_relay_create(instance_id):
        uid = session['user_id']
        path = request.form.get('path', '')
        con = db()
        con.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        item = allowed_instance(con, instance_id, uid, now)
        if not item:
            con.rollback()
            abort(404)
        if path not in PATHS.get(item[2], frozenset()):
            con.rollback()
            abort(400)
        con.execute('DELETE FROM remote_relay_reads WHERE deadline<=?', (now,))
        pending = con.execute("""SELECT COUNT(*) FROM remote_relay_reads
            WHERE user_id=? AND status IN ('queued','running')""", (uid,)).fetchone()[0]
        if pending >= 2:
            con.rollback()
            abort(429)
        cursor = con.execute('''INSERT INTO remote_relay_reads
            (instance_id,user_id,path,status,created_at,deadline)
            VALUES(?,?,?,'queued',?,?)''', (instance_id, uid, path, now, now + REQUEST_TTL))
        con.commit()
        return jsonify(id=cursor.lastrowid, status='queued'), 202

    @app.get('/remote-lab/<int:instance_id>/request/<int:read_id>')
    @login_required
    def remote_relay_view(instance_id, read_id):
        uid = session['user_id']
        con = db()
        now = int(time.time())
        if not allowed_instance(con, instance_id, uid, now):
            abort(404)
        row = con.execute('''SELECT status,content_type,body FROM remote_relay_reads
            WHERE id=? AND instance_id=? AND user_id=? AND deadline>?''',
            (read_id, instance_id, uid, now)).fetchone()
        if not row:
            abort(404)
        return jsonify(status=row[0], content_type=row[1], body=row[2])

    @app.post('/api/remote-relay/poll')
    def remote_relay_poll():
        remote_worker.authenticate()
        if request.get_json(silent=True) != {}:
            abort(400)
        con = db()
        con.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        con.execute('DELETE FROM remote_relay_reads WHERE deadline<=?', (now,))
        con.execute("""UPDATE remote_relay_reads SET status='failed'
            WHERE status='running' AND lease_until<=?""", (now,))
        row = con.execute('''SELECT r.id,r.path,i.instance,c.image
            FROM remote_relay_reads r
            JOIN remote_challenge_instances i ON i.id=r.instance_id AND i.user_id=r.user_id
            JOIN challenges c ON c.id=i.challenge_id
            JOIN remote_worker_jobs j ON j.id=i.start_job_id
            WHERE r.status='queued' AND r.deadline>? AND i.expires_at>?
            AND i.stop_job_id IS NULL AND j.status='completed' AND c.active=1 AND c.image IN ('cti-lab/incident-01','cti-lab/web-01')
            ORDER BY r.id LIMIT 1''', (now, now)).fetchone()
        job = None
        if row:
            if row[1] not in PATHS.get(row[3], frozenset()) or not remote_worker.NAME.fullmatch(row[2]):
                con.rollback()
                abort(409)
            lease = secrets.token_urlsafe(32)
            con.execute("""UPDATE remote_relay_reads SET status='running',lease=?,lease_until=?
                WHERE id=? AND status='queued'""", (lease, now + LEASE_SECONDS, row[0]))
            job = dict(id=row[0], path=row[1], instance=row[2], scenario=row[3], lease=lease)
        con.commit()
        return jsonify(job=job)

    @app.post('/api/remote-relay/result')
    def remote_relay_result():
        remote_worker.authenticate()
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'id','lease','status','content_type','body'}:
            abort(400)
        if (type(data['id']) is not int or not 0 < data['id'] < 2**63
                or not isinstance(data['lease'], str) or not remote_worker.LEASE.fullmatch(data['lease'])
                or data['status'] not in ('completed','failed')):
            abort(400)
        if data['status'] == 'completed':
            if (not isinstance(data['content_type'], str) or data['content_type'] not in TYPES
                    or not isinstance(data['body'], str)
                    or len(data['body'].encode('utf-8', errors='replace')) > MAX_BODY):
                abort(400)
        elif data['content_type'] is not None or data['body'] is not None:
            abort(400)
        con = db()
        con.execute('BEGIN IMMEDIATE')
        now = int(time.time())
        row = con.execute('''SELECT r.lease FROM remote_relay_reads r
            JOIN remote_challenge_instances i ON i.id=r.instance_id AND i.user_id=r.user_id
            JOIN challenges c ON c.id=i.challenge_id
            JOIN remote_worker_jobs j ON j.id=i.start_job_id
            WHERE r.id=? AND r.status='running' AND r.lease_until>? AND r.deadline>?
            AND i.expires_at>? AND i.stop_job_id IS NULL AND j.status='completed' AND c.active=1 AND c.image IN ('cti-lab/incident-01','cti-lab/web-01') ''',
            (data['id'], now, now, now)).fetchone()
        if not row or not row[0] or not hmac.compare_digest(row[0], data['lease']):
            con.rollback()
            abort(409)
        con.execute('''UPDATE remote_relay_reads SET status=?,content_type=?,body=?
            WHERE id=?''', (data['status'], data['content_type'], data['body'], data['id']))
        con.commit()
        return jsonify(ok=True)
