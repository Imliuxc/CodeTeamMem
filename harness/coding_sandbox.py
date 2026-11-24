"""Disposable Docker boundary. Only the repository enters the worker container."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
from .budget_guard import pages
from .stage1_errors import EnvError


def command(args, timeout=120, max_bytes=65536):
    # Capture on disk, read a bounded prefix; never expose unbounded tool output.
    try:
        with tempfile.TemporaryFile() as out:
            result = subprocess.run(args, stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
            total = out.tell(); out.seek(0)
            data = out.read(max_bytes)
        return {'returncode':result.returncode, 'text':data.decode(errors='replace'),
                'total_bytes':total, 'truncated':total > max_bytes}
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvError(f'local command failed ({type(exc).__name__})') from None


class Sandbox:
    def __init__(self, repository, profile_config, profile, *, workspace_image, service_image, network_subnet=None):
        self.repo, self.profile_config = Path(repository).resolve(), Path(profile_config).resolve()
        self.profile, self.workspace_image, self.service_image = profile, workspace_image, service_image
        self.network_subnet = network_subnet
        token = uuid.uuid4().hex[:12]
        self.network, self.service, self.worker, self.volume = ['ctm-'+token+s for s in ('-net','-world','-worker','-data')]
        self.config_volume=self.volume+'-config'

    def checked(self, args):
        result = command(args)
        if result['returncode'] or result['text'].lstrip().startswith(('Error','error:','fatal:')):
            raise EnvError('Docker setup command failed: '+result['text'][:500])
        return result

    def stage(self, source, volume, destination='.'):
        # Docker cp rejects read-only-rootfs destinations (including tmpfs).
        # Only this never-started control-side transfer container is writable.
        name=self.worker+'-transfer'
        try:
            self.checked(['docker','create','--name',name,'--network','none',
                          '-v',f'{volume}:/staging',self.workspace_image,'true'])
            target='/staging' if destination=='.' else '/staging/'+destination
            self.checked(['authbash','docker','cp',str(source),name+':'+target])
        finally: command(['docker','rm','-f',name])

    @staticmethod
    def limits():
        return ['--cap-drop=ALL','--security-opt=no-new-privileges','--memory=1g','--cpus=1',
                '--pids-limit=128','--read-only','--tmpfs','/tmp:rw,nosuid,size=64m']

    def __enter__(self):
        if not self.repo.is_dir() or not self.profile_config.is_file(): raise EnvError('sandbox inputs missing')
        try:
            network_args=['docker','network','create','--internal']
            if self.network_subnet:
                import ipaddress
                ipaddress.ip_network(self.network_subnet,strict=True)
                network_args.extend(['--subnet',self.network_subnet])
            self.checked([*network_args,self.network])
            self.stage(self.profile_config,self.config_volume,'world_profile.yaml')
            self.stage(str(self.repo)+'/.',self.volume)
            self.checked(['docker','run','-d','--name',self.service,'--network',self.network,
                '--network-alias','world',*self.limits(),'-v',f'{self.config_volume}:/config:ro',
                self.service_image,'--profile',self.profile])
            self.checked(['docker','run','-d','--name',self.worker,'--network',self.network,*self.limits(),
                '--user',f'{os.getuid()}:{os.getgid()}',
                '-v',f'{self.volume}:/home/worker/workspace', '-w','/home/worker/workspace',
                '-e','WORLD_URL=http://world:8080/snapshot',self.workspace_image,'sleep','infinity'])
            for _ in range(30):
                result = self.exec(['python','-c', "from urllib.request import Request,urlopen; print(urlopen(Request('http://world:8080/snapshot',data=b'{}',headers={'Content-Type':'application/json'}),timeout=1).read().decode())"])
                if result['returncode'] == 0: return self
                time.sleep(0.1)
            raise EnvError('external world service did not become ready: '+result['text'][-1000:])
        except Exception:
            self.close(); raise

    def exec(self, args, timeout=60):
        return command(['docker','exec',self.worker,'timeout',str(timeout),*args], timeout=timeout+5)

    def snapshot(self):
        result = self.exec(['python','-c', "from urllib.request import Request,urlopen; print(urlopen(Request('http://world:8080/snapshot',data=b'{}',headers={'Content-Type':'application/json'}),timeout=3).read().decode())"])
        if result['returncode']: raise EnvError('world HTTP request failed')
        return json.loads(result['text'])

    def sync_file(self, relative):
        self.stage(self.repo/relative,self.volume,relative)

    def judge(self, tests, *, report=None, base=False, test_name=None):
        # Separate judge; hidden tests never enter worker. Authorized cp handles
        # TSD without rewriting/decrypting host files or mounting wrapped bytes.
        name = self.worker+'-judge'
        tests_volume=self.volume+'-tests'
        try:
            self.stage(str(Path(tests).resolve())+'/.',tests_volume)
            self.checked(['docker','run','-d','--name',name,'--network',self.network,*self.limits(),
                '--user',f'{os.getuid()}:{os.getgid()}',
                '-v',f'{self.volume}:/home/worker/workspace:ro','-v',f'{tests_volume}:/judge:ro', '-w','/home/worker/workspace',
                '-e','PYTHONPATH=/home/worker/workspace','-e','WORLD_URL=http://world:8080/snapshot',
                self.workspace_image,'sleep','infinity'])
            target='/home/worker/workspace/tests_base' if base else '/judge/'+test_name if test_name else '/judge'
            result = command(['docker','exec',name,'timeout','60','python','-m','pytest','-q',
                '-p','no:cacheprovider','--junitxml=/tmp/result.xml',target],timeout=70)
            if report is not None:
                Path(report).with_suffix('.pytest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            # /tmp is tmpfs: read through the running process, not Docker archive.
            exported=command(['docker','exec',name,'python','-c',
                "from pathlib import Path; import sys; sys.stdout.write(Path('/tmp/result.xml').read_text())"],
                timeout=10,max_bytes=1048576)
            if exported['returncode'] or exported['truncated']:
                raise EnvError('judge XML read failed; pytest output: '+result['text'][-1200:])
            xml_text=exported['text']
            if report is not None: Path(report).write_text(xml_text)
            import xml.etree.ElementTree as ET
            try: cases=ET.fromstring(xml_text).findall('.//testcase')
            except ET.ParseError: raise EnvError('judge returned invalid XML; raw evidence saved') from None
            result.update(collected=len(cases), failed=sum(c.find('failure') is not None for c in cases),
                          errors=sum(c.find('error') is not None for c in cases),
                          skipped=sum(c.find('skipped') is not None for c in cases))
            if result['errors'] or not cases or result['returncode'] not in (0,1):
                raise EnvError('judge collection/runtime infrastructure failure: '+result['text'][-1200:])
            result['passed_tests'] = sorted(c.attrib.get('classname','')+'::'+c.attrib['name'] for c in cases
                if all(c.find(k) is None for k in ('failure','error','skipped')))
            return result
        finally:
            command(['docker','rm','-f',name])
            command(['docker','volume','rm',tests_volume])

    def close(self):
        for name in (self.worker,self.service): command(['docker','rm','-f',name])
        command(['docker','network','rm',self.network])
        command(['docker','volume','rm',self.volume])
        command(['docker','volume','rm',self.config_volume])

    def __exit__(self, *args): self.close()
