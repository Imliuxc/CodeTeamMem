"""Recipe-driven, zero-model Stage 2 construction and Docker acceptance checks."""
import argparse
import ast
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import tokenize
import yaml
from .common import read, write, selector, seeds
from .coding_sandbox import Sandbox, command
from .symbol_extract import extract, clean_why, scan_leaks
from .stage1_errors import EnvError


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def place(root, files):
    for relative, text in files.items():
        path = (root/relative).resolve()
        if not path.is_relative_to(root.resolve()): raise ValueError('unsafe recipe file path')
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text)


def prepare(dataset, seed, reference_path, config, *, resume=False):
    dataset = Path(dataset).resolve(); case = seed['id']
    base = dataset/'cases'/case
    prior = read(base/'qa_calibration.json')
    state = read(base/'factory_state.json')
    if state['stage'] != 1 or not (state['gate'] or (resume and 1 in state.get('approved_gates',[]))) or not prior['passed']:
        raise ValueError('Stage 1 Gate required before Stage 2 preparation')
    recipe = read(dataset/'recipes'/f'{case}.yaml')
    artifacts = dataset/'artifacts'/case
    artifacts.mkdir(parents=True,exist_ok=True)
    history = artifacts/'history_repo'
    repo = dataset/'repo_base'
    hidden = dataset/'tests_eval'/case
    if resume:
        if not history.is_dir() or not repo.is_dir(): raise ValueError('no existing snapshots to resume')
    elif history.exists() or repo.exists(): raise ValueError('refusing to overwrite existing Stage 2 snapshots')
    hidden.mkdir(parents=True,exist_ok=True)
    place(hidden,recipe['hidden_tests'])
    write(artifacts/'world_profile.yaml',{'profiles':seed['external_profiles']})
    # Exact Stage 1 public objects; no Gold or private profile files in worker.
    public = {'public_policy.md':json.dumps(seed['public_policy'],ensure_ascii=False,sort_keys=True,indent=2)+'\n',
              'data_schema.json':json.dumps(seed['data_schema'],ensure_ascii=False,sort_keys=True,indent=2)+'\n'}
    cfg = config['stage2']
    logs=[]
    def run(args,timeout=120):
        result=command(args,timeout); logs.append(dict(result,command=args))
        write(artifacts/'construction_tool_log.json',logs)
        if result['returncode']: raise EnvError('preparation command failed: '+result['text'][:800])
        return result
    import uuid
    developer='ctm-history-'+uuid.uuid4().hex[:10]
    def docker(args):
        if args[0]=='git': args=['git','-c','safe.directory=/home/worker/workspace',*args[1:]]
        return run(['docker','exec',developer,*args])
    if resume:
        try:
            run(['docker','run','-d','--name',developer,'--network','none','--user','0:0',
                 '-e','PYTHONDONTWRITEBYTECODE=1','-w','/home/worker/workspace',cfg['workspace_image'],'sleep','infinity'])
            run(['authbash','docker','cp',str(history)+'/.',developer+':/home/worker/workspace'])
            t1=docker(['git','rev-parse','HEAD'])['text'].strip()
            t0=docker(['git','rev-parse','HEAD^'])['text'].strip()
            diff=docker(['git','diff',t0,t1])['text']
            if diff!=(artifacts/'git_diff.patch').read_text(): raise ValueError('preserved keyframe diff changed')
            docker(['git','checkout','--detach',t0])
            pytest0=docker(['python','-m','pytest','-q','-p','no:cacheprovider','tests_base'])
            docker(['git','checkout','--detach',t1])
            pytest1=docker(['python','-m','pytest','-q','-p','no:cacheprovider','tests_base'])
        finally:
            command(['docker','rm','-f',developer])
    else:
        history.mkdir()
        place(history,dict(recipe['history_t0'],**public))
        try:
            run(['docker','run','-d','--name',developer,'--network','none','--user','0:0',
                 '-e','PYTHONDONTWRITEBYTECODE=1','-w','/home/worker/workspace',cfg['workspace_image'],'sleep','infinity'])
            run(['authbash','docker','cp',str(history)+'/.',developer+':/home/worker/workspace'])
            docker(['git','init'])
            docker(['git','add','.'])
            docker(['git','-c','user.name=CodeTeamMem','-c','user.email=local@example.invalid','commit','-m','T0-public-schema'])
            t0=docker(['git','rev-parse','HEAD'])['text'].strip()
            pytest0=docker(['python','-m','pytest','-q','-p','no:cacheprovider','tests_base'])
            place(history,recipe['history_t1'])
            for relative in recipe['history_t1']:
                run(['authbash','docker','cp',str(history/relative),developer+':/home/worker/workspace/'+relative])
            docker(['git','add','.'])
            docker(['git','-c','user.name=CodeTeamMem','-c','user.email=local@example.invalid','commit','-m','T1-public-projection'])
            t1=docker(['git','rev-parse','HEAD'])['text'].strip()
            diff=docker(['git','diff',t0,t1])['text']
            (artifacts/'git_diff.patch').write_text(diff)
            pytest1=docker(['python','-m','pytest','-q','-p','no:cacheprovider','tests_base'])
            run(['authbash','docker','cp',developer+':/home/worker/workspace/.',str(history)])
        finally:
            command(['docker','rm','-f',developer])
        shutil.copytree(history,repo,ignore=shutil.ignore_patterns('.git','*.pyc','__pycache__','.pytest_cache'))
        for path in repo.rglob('*.py'): path.write_text(clean_why(path.read_text()))
    symbols=set(); violations=[]
    for path in repo.rglob('*.py'):
        source=path.read_text(); symbols.update(extract(source))
        violations.extend(f'{path.relative_to(repo)}: {x}' for x in scan_leaks(source,['逐笔对账','Gold','receipt_v2','REG03','E01','E02','E05','why','rationale']))
        if any(t.type==tokenize.COMMENT for t in tokenize.generate_tokens(io.StringIO(source).readline)):
            violations.append('comment remained')
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and ast.get_docstring(node):
                violations.append('docstring remained')
    unwanted=[str(p.relative_to(repo)) for p in repo.rglob('*') if p.name in {'.git','__pycache__','.pytest_cache'} or p.suffix=='.pyc']
    if violations or unwanted: raise ValueError('snapshot leak scan failed')
    files=sorted(str(p.relative_to(repo)) for p in repo.rglob('*') if p.is_file())
    write(base/'symbol_manifest.json',{'symbols':sorted(symbols),'files':files})
    profile_config=artifacts/'world_profile.yaml'
    def sandbox(path,profile):
        return Sandbox(path,profile_config,profile,workspace_image=cfg['workspace_image'],service_image=cfg['service_image'],network_subnet=cfg.get('network_subnet'))
    probes={}; snapshots={}; selfcheck={}
    with sandbox(repo,'T0_history') as s:
        actual=s.snapshot()
        write(artifacts/'tool_log.json',{'source':'real Docker worker HTTP call','profile':'T0_history','response':actual})
        assert actual==seed['external_profiles']['T0_history']['default']
    reference_path=Path(reference_path).resolve()
    reference_hash=sha(reference_path)
    with tempfile.TemporaryDirectory(prefix='ctm-reference-') as tmp:
        positive=Path(tmp)/'workspace'; shutil.copytree(repo,positive)
        target=recipe['coding_task']['writable_paths']
        if len(target)!=1: raise ValueError('preparation reference expects one target policy file')
        shutil.copyfile(reference_path,positive/target[0])
        for context,profile in [('A','A_static'),('B','B_irrelevant'),('C','C_changed')]:
            with sandbox(repo,profile) as s:
                snapshots[context]=s.snapshot()
                probe_code="""import json,os,pathlib,socket
from urllib.request import Request,urlopen
from urllib.error import HTTPError
checks={}
for p in ['/srv/app.py','/config/world_profile.yaml','/var/run/docker.sock','/judge','/home/worker/workspace/.git']:
    try:
        with open(p,'rb') as f: f.read(1)
        checks[p]=False
    except (FileNotFoundError,PermissionError,IsADirectoryError): checks[p]=True
try:
    urlopen(Request('http://world:8080/snapshot',data=b'{"world_profile":"T0_history"}',headers={'Content-Type':'application/json'}),timeout=2)
    checks['other_profile_blocked']=False
except HTTPError as e: checks['other_profile_blocked']=e.code==400
try:
    socket.create_connection(('1.1.1.1',443),timeout=1).close();checks['external_network_blocked']=False
except OSError:checks['external_network_blocked']=True
checks['no_api_credentials']=not any(k in os.environ for k in ['ARK_API_KEY','OPENAI_API_KEY','CODETEAMMEM_API_KEY'])
checks['no_reference_in_workspace']=not any('reference' in p.name.lower() for p in pathlib.Path('.').rglob('*'))
print(json.dumps(checks))
"""
                p=s.exec(['python','-c',probe_code]); assert p['returncode']==0
                probes[context]=json.loads(p['text']); assert all(probes[context].values())
                negative=s.judge(hidden,test_name=f'test_{context}.py',report=artifacts/f'negative_{context}.xml')
                assert negative['returncode']==1 and negative['failed']==negative['collected']==3 and not negative['skipped']
            with sandbox(positive,profile) as s:
                positive_result=s.judge(hidden,test_name=f'test_{context}.py',report=artifacts/f'positive_{context}.xml')
                base_result=s.judge(hidden,base=True,report=artifacts/f'base_positive_{context}.xml')
                assert positive_result['returncode']==0 and len(positive_result['passed_tests'])==3 and base_result['returncode']==0
            selfcheck[context]={'negative':negative,'positive':positive_result,'base_positive':base_result}
    reference_path.unlink()
    assert not reference_path.exists()
    with sandbox(repo,'A_static') as s:
        clean_base=s.judge(hidden,base=True,report=artifacts/'base_clean.xml')
        assert clean_base['returncode']==0
    assert snapshots['A']['protocol']!=snapshots['C']['protocol']
    assert read(repo/'public_policy.md')==seed['public_policy'] and read(repo/'data_schema.json')==seed['data_schema']
    assert hashlib.sha256(json.dumps(seed['public_policy'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()==prior['policy_hash']
    assert hashlib.sha256(json.dumps(seed['data_schema'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()==prior['schema_hash']
    assert sha(repo/target[0])!=reference_hash
    watched={}
    for relative in seed['watched_files']:
        path=dataset/relative
        if relative=='public_policy.md': path=repo/'public_policy.md'
        watched[relative]={'materialized_path':str(path.relative_to(dataset)),'sha256':sha(path)}
    write(base/'watched_files.json',watched)
    write(artifacts/'construction_tool_log.json',logs)
    write(artifacts/'git_diff.json',{'T0':t0,'T1':t1,'diff':diff})
    frames=[{'name':'T0','commit':t0,'tool_log':str(artifacts/'tool_log.json'),'git_diff':'initial snapshot','pytest':pytest0},
            {'name':'T1','commit':t1,'tool_log':str(artifacts/'tool_log.json'),'git_diff':diff,'pytest':pytest1}]
    write(base/'coding_evidence.json',dict(selfcheck['A'],keyframes=frames))
    task=dict(recipe['coding_task'],hidden_tests=str(hidden),test_files={c:f'test_{c}.py' for c in 'ABC'})
    task['smoke_imports'] = recipe['coding_task'].get('smoke_imports',[])
    write(base/'coding_task.json',task)
    result={'case_id':case,'stage':2,'status':'READY_FOR_CODING_APPROVAL','passed':True,'model_calls':0,
        'isolation':{'passed':True,'probes':probes,'A_protocol':snapshots['A']['protocol'],'C_protocol':snapshots['C']['protocol']},
        'self_check':{'passed':True,'profiles':selfcheck,'reference_removed':True,'reference_sha256':reference_hash},
        'cleaning':{'passed':True,'violations':violations,'unwanted_files':unwanted,'base_tests':clean_base},
        'public_policy':{'unchanged':True,'policy_hash':prior['policy_hash'],'schema_hash':prior['schema_hash'],'qa_rerun_required':False},
        'keyframes':{'T0':t0,'T1':t1},'workspace_files':files,'coding_config':cfg,
        'snapshots':{str(p.relative_to(repo)):sha(p) for p in repo.rglob('*') if p.is_file()}}
    for key,image in [('workspace_image',cfg['workspace_image']),('service_image',cfg['service_image'])]:
        result[key]=json.loads(run(['docker','image','inspect',image])['text'])[0]['Id']
    write(base/'stage2_preparation.json',result)
    return result


def main():
    p=selector(__doc__); p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--resume',action='store_true',help='user-authorized resume; preserve existing keyframes and baseline')
    args=p.parse_args()
    if args.all: raise SystemExit('a temporary reference is per case; select --case')
    from .run_qa_calibration import stage1_config
    for seed in seeds(args):
        result=prepare(args.dataset,seed,args.reference,stage1_config(),resume=args.resume)
        print(seed['id'],result['status'],'4/4 checks passed; model_calls=0')


if __name__=='__main__': main()
