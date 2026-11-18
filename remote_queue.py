"""Admission and FIFO scheduling for the single remote laboratory slot."""
import secrets

import remote_worker

SESSION_SECONDS = 3600
WAIT_SECONDS = 24 * 3600
OPEN = """j.status IN ('queued','running','completed','interrupted')
          AND (i.stop_job_id IS NULL OR stop.status != 'completed')"""
JOINS = """FROM remote_challenge_instances i
           JOIN remote_worker_jobs j ON j.id=i.start_job_id
           LEFT JOIN remote_worker_jobs stop ON stop.id=i.stop_job_id"""


def migrate(con):
    con.execute('CREATE INDEX IF NOT EXISTS idx_remote_instance_user ON remote_challenge_instances(user_id,id)')
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_remote_instance_start ON remote_challenge_instances(start_job_id)')


def current(con, uid):
    return con.execute(f"""SELECT i.challenge_id {JOINS}
        WHERE i.user_id=? AND ({OPEN}) ORDER BY i.id LIMIT 1""", (uid,)).fetchone()


def cancel_start(con, job_id, now):
    con.execute("""UPDATE remote_worker_jobs SET status='failed', finished_at=?, flag=NULL
        WHERE status='queued' AND id=?""", (now, job_id))


def request_stop(con, row):
    job = remote_worker.enqueue(con, request_key=secrets.token_urlsafe(24),
                                action='stop', instance=row['instance'])
    con.execute('UPDATE remote_challenge_instances SET stop_job_id=? WHERE id=?', (job, row['id']))


def next_job(con, now):
    """Run with the worker's write transaction, before granting the next lease."""
    con.execute("""UPDATE remote_worker_jobs SET status='failed',finished_at=?,flag=NULL
        WHERE status='queued' AND action='start' AND id IN (
            SELECT i.start_job_id FROM remote_challenge_instances i
            JOIN users u ON u.id=i.user_id JOIN challenges c ON c.id=i.challenge_id
            WHERE i.created_at<=? OR c.active!=1 OR c.image IS NULL
                OR c.image NOT IN ('cti-lab/incident-01','cti-lab/web-01')
                OR u.role!='participante'
                OR (c.side IN ('Red Team','Blue Team') AND NOT EXISTS (
                    SELECT 1 FROM team_members m JOIN teams t ON t.id=m.team_id
                    WHERE m.user_id=i.user_id AND t.side=c.side)))""", (now, now - WAIT_SECONDS))
    for row in con.execute(f"""SELECT i.id,i.instance {JOINS}
        WHERE i.stop_job_id IS NULL AND j.status='completed' AND i.expires_at<=?""", (now,)).fetchall():
        request_stop(con, row)

    stop = con.execute("""SELECT id,action,instance,scenario,flag FROM remote_worker_jobs
        WHERE status='queued' AND action='stop' ORDER BY id LIMIT 1""").fetchone()
    if stop:
        return stop
    occupied = con.execute(f"""SELECT 1 {JOINS}
        WHERE j.status IN ('running','completed','interrupted')
        AND (i.stop_job_id IS NULL OR stop.status!='completed') LIMIT 1""").fetchone()
    if occupied:
        return None
    return con.execute("""SELECT id,action,instance,scenario,flag FROM remote_worker_jobs
        WHERE status='queued' AND action='start' ORDER BY id LIMIT 1""").fetchone()


def on_result(con, job_id, status, now):
    if status == 'completed':
        con.execute('UPDATE remote_challenge_instances SET expires_at=? WHERE start_job_id=?',
                    (now + SESSION_SECONDS, job_id))


def cancel(con, uid, cid, now):
    row = con.execute(f"""SELECT i.id,i.instance,i.start_job_id,i.stop_job_id,j.status AS start_status,
        stop.status AS stop_status {JOINS} WHERE i.user_id=? AND i.challenge_id=?
        AND ({OPEN}) ORDER BY i.id LIMIT 1""", (uid, cid)).fetchone()
    if not row:
        return 'none'
    if row['stop_job_id'] is not None and row['stop_status'] != 'failed':
        return 'stopping'
    if row['start_status'] == 'queued':
        cancel_start(con, row['start_job_id'], now)
        con.execute('UPDATE remote_challenge_instances SET expires_at=? WHERE id=?', (now, row['id']))
        return 'cancelled'
    request_stop(con, row)
    return 'stopping'


def state(con, uid, cid, now):
    row = con.execute(f"""SELECT i.id,i.challenge_id,i.expires_at,i.start_job_id,i.stop_job_id,
        j.status AS start_status,stop.status AS stop_status {JOINS}
        WHERE i.user_id=? AND (i.challenge_id=? OR ({OPEN}))
        ORDER BY CASE WHEN ({OPEN}) THEN 0 ELSE 1 END, i.id DESC LIMIT 1""", (uid, cid)).fetchone()
    if not row:
        return {'state': 'empty'}
    if row['challenge_id'] != cid:
        return {'state': 'other', 'challenge_id': row['challenge_id']}
    if row['stop_status'] == 'completed':
        return {'state': 'ended'}
    if row['start_status'] == 'interrupted' or row['stop_status'] == 'interrupted':
        return {'state': 'interrupted'}
    if row['stop_status'] == 'failed':
        return {'state': 'stop_failed'}
    if row['stop_job_id'] is not None:
        return {'state': 'stopping'}
    if row['start_status'] == 'queued':
        position = con.execute("""SELECT COUNT(*) FROM remote_worker_jobs
            WHERE action='start' AND status='queued' AND id<=?""", (row['start_job_id'],)).fetchone()[0]
        return {'state': 'queued', 'position': position}
    if row['start_status'] == 'running':
        return {'state': 'preparing'}
    if row['start_status'] == 'completed':
        if row['expires_at'] <= now:
            return {'state': 'stopping'}
        return {'state': 'ready', 'instance_id': row['id'], 'expires_at': row['expires_at'], 'now': now}
    return {'state': 'failed' if row['expires_at'] > now else 'ended'}


def overview(con):
    return con.execute(f"""SELECT u.name,c.title,j.status AS start_status,stop.status AS stop_status,i.expires_at
        {JOINS} JOIN users u ON u.id=i.user_id JOIN challenges c ON c.id=i.challenge_id
        WHERE {OPEN} ORDER BY (j.status='queued'), j.id""").fetchall()
