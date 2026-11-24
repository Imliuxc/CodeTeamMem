"""Stage 4 uses the frozen Stage 2 Coding session and fresh isolated sandboxes."""
from copy import deepcopy
from pathlib import Path
import difflib
import hashlib
import json
import tempfile
from .common import read,write
from .coding_sandbox import Sandbox,command
from .run_coding_calibration import coding_session
from .budget_guard import BudgetExceeded
from .stage1_errors import EnvError


class EvidenceSandbox(Sandbox):
    def __init__(self,*args,artifacts,**kwargs):
        super().__init__(*args,**kwargs);self.artifacts=Path(artifacts);self.judges=[];self.wiring=[]
    def checked(self,args):
        value=super().checked(args)
        if args[:3]==['docker','run','-d'] and self.worker+'-judge' in args:
            info=json.loads(super().checked(['docker','inspect',self.worker+'-judge'])['text'])[0]
            mount=next(m for m in info['Mounts'] if m['Destination']=='/home/worker/workspace')
            if mount['Name']!=self.volume or mount['RW'] or not info['HostConfig']['ReadonlyRootfs']:
                raise EnvError('judge mount isolation failed')
            self.wiring.append({'judge':self.worker+'-judge','candidate_volume':self.volume,'read_only':True})
            write(self.artifacts/'judge_wiring.json',self.wiring)
        return value
    def __enter__(self):
        super().__enter__()
        if not json.loads(self.checked(['docker','network','inspect',self.network])['text'])[0]['Internal']:
            self.close();raise EnvError('internal network required')
        return self
    def judge(self,tests,*,report=None,base=False,test_name=None):
        path=self.artifacts/(('base' if base else 'hidden')+f'_{len(self.judges)+1:03d}.xml')
        result=super().judge(tests,report=path,base=base,test_name=test_name)
        self.judges.append(dict(result,base=base,test_name=test_name,xml=path.name))
        write(self.artifacts/'judges.json',self.judges);return result


def cleanup_probe(prefix):
    residue={}
    for kind,args in [('container',['docker','ps','-a','--filter','name='+prefix,'--format','{{.Names}}']),
                      ('network',['docker','network','ls','--filter','name='+prefix,'--format','{{.Name}}']),
                      ('volume',['docker','volume','ls','--filter','name='+prefix,'--format','{{.Name}}'])]:
        result=command(args)
        if result['returncode']:raise EnvError('resource cleanup inspection failed')
        residue[kind]=result['text'].splitlines()
    return {'prefix':prefix,'residue':residue,'passed':not any(residue.values())}


class FrozenCodingExecutor:
    def __init__(self,dataset,case_id):
        self.dataset=Path(dataset);self.base=self.dataset/'cases'/case_id
        self.prep=read(self.base/'stage2_preparation.json');self.frozen=read(self.base/'coding_calibration.json')
        from .run_qa_calibration import stage1_config
        self.task=read(self.base/'coding_task.json');self.cfg=stage1_config()['stage2']
        self.profile=self.dataset/'artifacts'/case_id/'world_profile.yaml'
    def __call__(self,seed,memory,context,provider,tokenizer,guard,output):
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        local_seed=deepcopy(seed);local_seed['qa']['anchor_contexts']['MEMORY']=memory
        with tempfile.TemporaryDirectory(prefix='ctm-memory-') as tmp:
            repo=Path(tmp)/'repo';repo.mkdir()
            for rel,digest in self.prep['snapshots'].items():
                data=(self.dataset/'repo_base'/rel).read_bytes()
                if hashlib.sha256(data).hexdigest()!=digest:raise EnvError('frozen baseline changed')
                p=repo/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            sandbox=EvidenceSandbox(repo,self.profile,{'A':'A_static','B':'B_irrelevant','C':'C_changed'}[context],
                workspace_image=self.frozen['workspace_image'],service_image=self.frozen['service_image'],
                network_subnet=self.cfg['network_subnet'],artifacts=output)
            try:
                with sandbox:
                    result=coding_session(local_seed,self.task,sandbox,provider,tokenizer,guard,self.cfg,'MEMORY',context)
            except EnvError as exc:result={'outcome':'env_error','error':str(exc),'log':[]}
            except BudgetExceeded as exc:result={'outcome':'budget_stop','error':str(exc),'log':[]}
            finally:sandbox.close()
            patches=[]
            for rel in self.task['writable_paths']:
                patches.extend(difflib.unified_diff((self.dataset/'repo_base'/rel).read_text().splitlines(True),
                    (repo/rel).read_text().splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
            (output/'candidate.patch').write_text(''.join(patches))
            write(output/'candidate_hashes.json',{rel:hashlib.sha256((repo/rel).read_bytes()).hexdigest() for rel in self.prep['snapshots']})
            result['cleanup']=cleanup_probe(sandbox.worker.removesuffix('-worker'))
            if not result['cleanup']['passed']:result.update(outcome='env_error',error='sandbox resource residue')
            result['artifacts']=str(output.resolve());write(output/'session.json',result)
            return result
