from copy import deepcopy
import hashlib
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
import yaml

from benchmark4.visualization.store import Store
from benchmark4.visualization.control import Controller, Conflict
from benchmark4.visualization.server import make_handler
from benchmark4.visualization.demo import fixture, generate
from benchmark4.harness.act_stream_builder import ActStreamSession, build
from benchmark4.harness.factory import Factory
from benchmark4.harness.common import write
from benchmark4.harness.merge_dataset_stream import save_stream


@pytest.fixture
def controller(tmp_path): return Controller(Store(tmp_path/'runtime'))


def command(c, run, action, case=None):
    selected = case or c.store.view(run)['cases'][0]['id']
    state=c.store.state(run,selected)
    return c.command(action,run=run,case=case,expected_revision=state['revision'])


def case(c,run): return c.store.view(run)['cases'][0]


def to_stream(c,run):
    for _ in range(2):
        command(c,run,'step');command(c,run,'approve')


def finish(c,run):
    while case(c,run)['completed_stage'] < 4:
        if case(c,run)['gate']: command(c,run,'approve')
        command(c,run,'step')


def dataset(tmp_path):
    root=tmp_path/'input'; (root/'seeds').mkdir(parents=True)
    seed=fixture()
    seed.update(scenario='task_handoff', dimension='cross_role_contract',code_mode='mode_2',difficulty='easy',
        target_slot='technical_slot', alternatives=['technical alternative'], evolution=['E2','E4'],
        history_evolution=[],history_overwrites=0,obstacles=['O1','O2','O3'],competing_rules=['one','two'],
        fallback={'rule':'technical fallback','source':'public_document','reference':'fixture.md'},
        gold={k:'fixture_'+k for k in ['rule','key_premise','scope_boundary','dead_end']},
        external_profiles={k:{'default':{'available':True},'routes':[]} for k in ['T0_history','A_static','B_irrelevant','C_changed']})
    (root/'seeds'/'fixture.yaml').write_text(yaml.safe_dump(seed,allow_unicode=True))
    base=root/'cases'/seed['id']; base.mkdir(parents=True)
    scores={'B0':dict.fromkeys('ABC',0),'B1':dict.fromkeys('ABC',0.5),'B2':dict.fromkeys('ABC',1)}
    for name in ['qa_calibration','coding_calibration']: write(base/(name+'.json'),{'scores':scores})
    write(base/'coding_evidence.json',{'positive':{'returncode':0},'negative':{'returncode':1},
        'keyframes':[dict(name=n,tool_log='fixture',git_diff='fixture',pytest='fixture') for n in ['T0','T1']]})
    write(base/'symbol_manifest.json',{'symbols':[]})
    save_stream(base/'raw_stream.jsonl',build(seed,[],generate, [{'kind':'tool_log','after_turn':2,'text':'中'*5000}]))
    write(base/'stream_verification.json',{'role_scores':dict.fromkeys(seed['roles'],0),'full_score':1})
    write(base/'benchmark_records.json',[{'gold':seed['gold'],'extracted':seed['gold'],'qa_b2':1,'coding_b2':0.8,
        'coding_b0_c':0.4,'coding_b1_c':0.2,'tokens':10,'communication_bytes':20}])
    return root,seed


def test_gates_single_round_and_completion(controller):
    c=controller; run=c.command('create',demo_mode=True)['id']
    command(c,run,'step')
    assert case(c,run)['completed_stage']==1 and case(c,run)['gate']
    with pytest.raises(Conflict): command(c,run,'step')
    command(c,run,'approve')
    assert case(c,run)['completed_stage']==1 and case(c,run)['status']=='READY'
    command(c,run,'step');command(c,run,'approve')
    command(c,run,'step')
    state=case(c,run)
    assert state['status']=='WAITING_STEP' and state['progress']['total_turns']==1
    assert len(state['dialogue'])==1 and state['completed_stage']==2
    assert '第二幕' not in json.dumps(c.store.view(run),ensure_ascii=False)
    assert '第二幕' not in json.dumps(c.store.events(run),ensure_ascii=False)
    command(c,run,'step')
    assert case(c,run)['progress']['act']==2 and len(case(c,run)['dialogue'])==2
    command(c,run,'step')
    assert len(case(c,run)['dialogue'])==3
    command(c,run,'step')
    assert case(c,run)['status']=='LOCKED' and case(c,run)['gate']
    command(c,run,'approve'); command(c,run,'step')
    assert case(c,run)['status']=='COMPLETE' and not case(c,run)['gate']
    assert all(r['source']=='mock' for r in case(c,run)['results'].values())
    with pytest.raises(Conflict): command(c,run,'step')


@pytest.mark.parametrize('stage',range(1,5))
def test_two_failures_cannot_be_reset(controller,stage):
    c=controller;run=c.command('create',demo_mode=True,fail_stage=stage)['id']
    while case(c,run)['completed_stage']<stage-1:
        if case(c,run)['gate']:command(c,run,'approve')
        command(c,run,'step')
    if case(c,run)['gate']:command(c,run,'approve')
    command(c,run,'step'); assert case(c,run)['status']=='FAILED'
    command(c,run,'retry'); assert case(c,run)['failures'][str(stage)]==1
    command(c,run,'step'); assert case(c,run)['status']=='CIRCUIT_OPEN'
    for action in ['retry','step','approve']:
        with pytest.raises(Conflict):command(c,run,action)
    assert case(c,run)['failures'][str(stage)]==2


def test_round_recovery_without_regeneration(controller):
    c=controller;run=c.command('create',demo_mode=True)['id'];to_stream(c,run)
    command(c,run,'step')
    c=Controller(Store(c.store.root));c.store.recover()
    assert case(c,run)['status']=='WAITING_STEP'
    command(c,run,'step')
    assert len(case(c,run)['dialogue'])==2 and case(c,run)['progress']['act']==2


def test_interrupt_requires_retry_and_restarts_stage(controller):
    c=controller;run=c.command('create',demo_mode=True)['id'];to_stream(c,run);command(c,run,'step')
    state=c.store.state(run,'technical_demo');state['status']='RUNNING'
    c.store.save(run,'technical_demo',state,'test_interruption')
    c.store.recover();assert case(c,run)['status']=='INTERRUPTED'
    assert case(c,run)['failures']=={}
    with pytest.raises(Conflict):command(c,run,'step')
    command(c,run,'retry');command(c,run,'step')
    assert len(case(c,run)['dialogue'])==1
    assert any(e['kind']=='interrupted' for e in c.store.events(run))


def test_duplicate_commands_and_no_queue(controller):
    c=controller;run=c.command('create',demo_mode=True)['id']
    c.lock.acquire()
    try:
        with pytest.raises(Conflict,match='busy'):command(c,run,'step')
    finally:c.lock.release()
    assert case(c,run)['completed_stage']==0
    command(c,run,'step')
    with pytest.raises(Conflict,match='stale'):
        c.command('approve',run=run,expected_revision=0)


def test_inflight_stage_is_queryable(controller,monkeypatch,tmp_path):
    import benchmark4.visualization.control as module
    root,seed=dataset(tmp_path);run=controller.command('create',dataset=str(root),case=seed['id'])['id']
    entered,release=threading.Event(),threading.Event()
    def slow(*args):
        def work(stage):entered.set();assert release.wait(3);return True
        return work
    monkeypatch.setattr(module,'artifact_runner',slow)
    thread=threading.Thread(target=lambda:command(controller,run,'step'));thread.start()
    try:
        assert entered.wait(3)
        assert case(controller,run)['status']=='RUNNING'
        assert case(controller,run)['active_stage']==1 and case(controller,run)['completed_stage']==0
        with pytest.raises(Conflict):command(controller,run,'step')
    finally:release.set();thread.join(3)
    assert case(controller,run)['completed_stage']==1


def test_artifact_replay_leaves_input_unchanged(controller,tmp_path):
    c=controller;root,seed=dataset(tmp_path)
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    run=c.command('create',dataset=str(root),case=seed['id'])['id']
    finish(c,run)
    assert case(c,run)['status']=='COMPLETE' and c.store.view(run)['source']=='artifact'
    assert case(c,run)['results']['4']['metrics']['denominator']==1
    after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert before==after
    assert (c.store.root/'runs'/run/seed['id']/'benchmark_metrics.json').is_file()
    evidence=[e for e in c.store.events(run) if e['kind']=='evidence_page']
    assert len(evidence)>1 and all(len(e['payload']['text'].encode())<=4096 for e in evidence)


def test_missing_artifacts_failed_not_zero(controller,tmp_path):
    root,seed=dataset(tmp_path);(root/'cases'/seed['id']/'qa_calibration.json').unlink()
    run=controller.command('create',dataset=str(root),case=seed['id'])['id'];command(controller,run,'step')
    assert case(controller,run)['status']=='FAILED' and case(controller,run)['results']=={}


def test_changed_future_artifact_fails_without_exposure(controller,tmp_path):
    c=controller;root,seed=dataset(tmp_path);run=c.command('create',dataset=str(root),case=seed['id'])['id']
    to_stream(c,run);command(c,run,'step')
    p=root/'cases'/seed['id']/'raw_stream.jsonl';p.write_text(p.read_text()+'FUTURE_CHANGED_SECRET')
    command(c,run,'step');assert case(c,run)['status']=='FAILED'
    assert 'FUTURE_CHANGED_SECRET' not in json.dumps(c.store.view(run))


def test_multi_case_requires_selection(controller,tmp_path):
    root,seed=dataset(tmp_path);second=deepcopy(seed);second.update(id='second',target_slot='second_slot')
    (root/'seeds'/'second.yaml').write_text(yaml.safe_dump(second))
    run=controller.command('create',dataset=str(root),all_cases=True)['id']
    with pytest.raises(ValueError,match='explicit'):
        controller.command('step',run=run,expected_revision=0)
    command(controller,run,'step',case=seed['id'])
    assert controller.store.state(run,'second')['completed_stage']==0


def test_events_pagination_and_private_config(controller):
    c=controller;run=c.command('create',demo_mode=True)['id'];state=c.store.state(run,'technical_demo')
    for _ in range(105):c.store.save(run,'technical_demo',state,'sample')
    a=c.store.events(run);b=c.store.events(run,after=a[-1]['seq'])
    assert len(a)==100 and len(b)==6
    assert len({e['seq'] for e in a+b})==106
    assert '_factory' not in json.dumps(c.store.view(run))
    assert 'seeds' not in json.dumps(c.store.runs())


def test_harness_hooks_and_session():
    events=[];f=Factory(on_event=events.append);f.advance(1,lambda _:True)
    assert [e['kind'] for e in events]==['stage_started','stage_completed']
    seed=fixture();session=ActStreamSession(seed,[],on_event=events.append)
    seen=[]
    def generator(view):seen.append(view);return generate(view)
    session.step(generator)
    assert len(session.stream)==1 and len(seen[0]['facts'])==1
    assert session.progress()['facts_met'] and not session.progress()['exit_met']
    restored=ActStreamSession(seed,[],snapshot=session.snapshot());restored.step(generator)
    assert restored.progress()['act']==2
    assert events[-1]['kind']=='turn_completed'


def test_http_loopback_readonly_control_boundary(controller):
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(controller))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def req(path,data=None,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        return urlopen(Request(base+path,data=json.dumps(data).encode() if data else None,headers=headers),timeout=3)
    try:
        with req('/') as r:
            html=r.read().decode();assert 'READ ONLY' in html and '<button' not in html
        with req('/app.js') as r:
            js=r.read().decode();assert 'setInterval(poll,1000)' in js and "'/control'" not in js
        with req('/control',{'action':'create','demo_mode':True}) as r:run=json.load(r)['id']
        with req('/api/runs/'+run) as r:assert json.load(r)['source']=='mock'
        with req('/api/runs/'+run+'/events?after=0') as r:assert len(json.load(r))==1
        with pytest.raises(HTTPError) as exc:req('/control',{'action':'step'},origin=base)
        assert exc.value.code==403
        with pytest.raises(HTTPError) as exc:req('/api/runs/'+run+'/events?after=-1')
        assert exc.value.code==400
        with pytest.raises(HTTPError) as exc:req('/../store.py')
        assert exc.value.code==404
        with pytest.raises(HTTPError) as exc:req('/control',{'action':'step','run':run,'expected_revision':99})
        assert exc.value.code==409
    finally:server.shutdown();server.server_close();thread.join(3)
