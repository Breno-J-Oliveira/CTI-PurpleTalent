"""Run a read-only fictional incident case in a disposable QEMU guest."""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import http.client

import orchestrator


class QemuIncident:
    def __init__(self, runtime, wheels):
        self.runtime = Path(runtime).resolve(strict=True)
        self.wheels = sorted(Path(wheels).resolve(strict=True).glob('*.whl'))
        self.base = self.runtime / 'ubuntu-base.img'
        self.qemu = self.runtime / 'qemu/qemu-system-x86_64.exe'
        self.image_tool = self.qemu.with_name('qemu-img.exe')
        if not all(p.is_file() for p in (self.base, self.qemu, self.image_tool)) or not self.wheels:
            raise ValueError('Runtime QEMU ou dependências da VM ausentes.')
        sys.path.insert(0, str(self.runtime / 'tools/lib'))
        import pycdlib
        self.pycdlib = pycdlib
        self.process = None
        self.instance = None

    def seed(self, folder, flag):
        entries = []

        def add(path, data, mode='0644'):
            entries.append(dict(path=path, encoding='b64', owner='root:root',
                                permissions=mode, content=base64.b64encode(data).decode('ascii')))

        source = Path(__file__).resolve().parents[1] / 'challenges/incident-01/app.py'
        add('/opt/cti-case/app.py', source.read_bytes())
        add('/opt/cti-case/config', ('FLAG=' + flag + '\n').encode('ascii'), '0600')
        for wheel in self.wheels:
            add('/opt/cti-wheels/' + wheel.name, wheel.read_bytes())
        add('/opt/cti-case/bootstrap.py', b"""from pathlib import Path
from zipfile import ZipFile
for wheel in Path('/opt/cti-wheels').glob('*.whl'):
    with ZipFile(wheel) as archive:
        archive.extractall('/opt/cti-python')
""")
        add('/etc/systemd/system/cti-http.service', b"""[Service]
User=ctf
EnvironmentFile=/opt/cti-case/config
Environment=PYTHONPATH=/opt/cti-python
WorkingDirectory=/opt/cti-case
ExecStart=/usr/bin/python3 /opt/cti-case/app.py
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
[Install]
WantedBy=multi-user.target
""")
        config = dict(hostname='cti-incident', disable_root=True, ssh_pwauth=False,
                      users=[], write_files=entries, package_update=False,
                      runcmd=[['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'ctf'],
                              ['/usr/bin/python3', '/opt/cti-case/bootstrap.py'],
                              ['systemctl', 'daemon-reload'],
                              ['systemd-run', '--on-active=65m', '/usr/sbin/poweroff'],
                              ['systemctl', 'enable', '--now', 'cti-http.service']])
        iso = self.pycdlib.PyCdlib()
        iso.new(interchange_level=3, joliet=3, rock_ridge='1.09', vol_ident='cidata')
        try:
            items = [('user-data', '#cloud-config\n' + json.dumps(config)),
                     ('meta-data', json.dumps({'instance-id': folder.name}))]
            for index, (name, content) in enumerate(items):
                data = content.encode('utf-8')
                iso.add_fp(io.BytesIO(data), len(data), iso_path=f'/FILE{index}.;1', rr_name=name, joliet_path='/'+name)
            iso.write(str(folder / 'seed.iso'))
        finally:
            iso.close()

    def start(self, instance, scenario, guest_port, flag):
        if scenario != 'cti-lab/incident-01' or guest_port != 5000:
            raise orchestrator.LabError('Cenário não disponível neste executor.')
        if self.process is not None:
            raise orchestrator.LabError('Já há uma VM sob supervisão.')
        if shutil.disk_usage(self.runtime).free < 1200 * 1024**2:
            raise orchestrator.LabError('Espaço insuficiente no disco do runtime.')
        folder = Path(tempfile.mkdtemp(prefix='incident-', dir=self.runtime))
        disk = folder / 'disk.qcow2'
        self.seed(folder, flag)
        subprocess.run([str(self.image_tool),'create','-f','qcow2','-F','qcow2','-b',str(self.base),str(disk)],
                       check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port = orchestrator._free_port()
        with (folder/'qemu.err').open('w', encoding='utf-8') as log:
            self.process = subprocess.Popen([
                str(self.qemu), '-machine','q35','-accel','tcg,thread=multi','-cpu','max','-smp','2','-m','1024',
                '-display','none','-monitor','none','-vga','none','-serial','file:'+str(folder/'serial.log'),
                '-drive',f'file={disk},if=virtio,format=qcow2,throttling.bps-write=10485760',
                '-drive',f'file={folder / "seed.iso"},if=virtio,format=raw,readonly=on',
                '-smbios','type=1,serial=ds=nocloud',
                '-netdev',f'user,id=lab,restrict=on,ipv6=off,hostfwd=tcp:127.0.0.1:{port}-:5000',
                '-device','virtio-net-pci,netdev=lab','-no-reboot'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.instance = instance
        deadline = time.monotonic() + 510
        try:
            while self.status(instance) and time.monotonic() < deadline:
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    connection.request('GET', '/health')
                    reply = connection.getresponse()
                    if reply.status == 200 and json.loads(reply.read(128)) == {'status': 'ok'} and self.status(instance):
                        return port
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
                time.sleep(2)
            raise orchestrator.LabError('A VM não respondeu dentro do prazo.')
        except BaseException:
            self.stop(instance)
            raise

    def status(self, instance):
        return instance == self.instance and self.process is not None and self.process.poll() is None

    def stop(self, instance):
        if instance != self.instance or self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        self.process = None
        self.instance = None
