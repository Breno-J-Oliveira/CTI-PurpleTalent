"""Loopback-only relay for approved lab pages, driven by the worker journal."""
from html.parser import HTMLParser
import http.client

import remote_relay
import remote_worker


class IncidentRecords(HTMLParser):
    """Extract evidence from the guest's main section without rendering its markup."""
    def __init__(self):
        super().__init__()
        self.active = False
        self.ignored = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'main':
            self.active = True
        if tag in ('script', 'style'):
            self.ignored = tag

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None
        if self.active and tag in ('p', 'h1', 'h2', 'tr'):
            self.parts.append('\n')
        if self.active and tag in ('td', 'th'):
            self.parts.append('  ')
        if tag == 'main':
            self.active = False

    def handle_data(self, value):
        if self.active and not self.ignored and value.strip():
            self.parts.append(value.strip())



def serve_once(client, journal, vm_running=None):
    response = client.send('/api/remote-relay/poll', {})
    job = response.get('job')
    if job is None:
        return
    if (not isinstance(job, dict) or set(job) != {'id','lease','instance','scenario','path'}
            or type(job['id']) is not int or not 0 < job['id'] < 2**63
            or not isinstance(job['lease'], str) or not remote_worker.LEASE.fullmatch(job['lease'])
            or not isinstance(job['instance'], str) or not remote_worker.NAME.fullmatch(job['instance'])
            or not isinstance(job['path'], str)
            or not isinstance(job['scenario'], str)
            or job['path'] not in remote_relay.PATHS.get(job['scenario'], frozenset())):
        raise ValueError('Invalid relay request')
    result = {'id':job['id'], 'lease':job['lease'], 'status':'failed',
              'content_type':None, 'body':None}
    row = journal.execute("""SELECT action,state,port,acknowledged FROM jobs
        WHERE instance=? ORDER BY id DESC LIMIT 1""", (job['instance'],)).fetchone()
    if (vm_running is None or vm_running(job['instance'])) and row and row[0] == 'start' and row[1] == 'completed' and row[3] == 1 and type(row[2]) is int and 1 <= row[2] <= 65535:
        connection = http.client.HTTPConnection('127.0.0.1', row[2], timeout=5)
        try:
            connection.request('GET', job['path'], headers={'Accept':'text/html,text/plain', 'Connection':'close'})
            reply = connection.getresponse()
            content_type = reply.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
            body = reply.read(remote_relay.MAX_BODY + 1)
            if reply.status == 200 and content_type in remote_relay.TYPES and len(body) <= remote_relay.MAX_BODY:
                records = body.decode('utf-8', errors='strict')
                if content_type == 'text/html':
                    parser = IncidentRecords()
                    parser.feed(records)
                    records = ''.join(parser.parts).strip()
                if records:
                    result.update(status='completed', content_type='text/plain', body=records)
        except (OSError, UnicodeError, http.client.HTTPException):
            pass
        finally:
            connection.close()
    client.send('/api/remote-relay/result', result)
