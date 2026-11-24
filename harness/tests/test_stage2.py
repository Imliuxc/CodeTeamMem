"""Offline unit checks; real Docker preparation has separate recorded evidence."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from benchmark4.harness.run_coding_calibration import (ToolPager, semantic_state,coding_prompt,
    coding_session,calibrate_coding,CodingRunner)
from benchmark4.harness.run_qa_calibration import stage1_config
from benchmark4.harness.budget_guard import BudgetGuard,BudgetExceeded
from benchmark4.harness.stage1_provider import Utf8BoundTokenizer
from benchmark4.harness.stage1_errors import EnvError,CalibrationFailed
from benchmark4.harness.factory import Factory,CircuitOpen


def config():
    cfg=stage1_config()
    cfg['stage2'].update(max_turns=50,stall_limit=5,exploration_limit=8,max_input_tokens=24000,no_edit_warn=900,no_edit_stop=1000)
    return cfg  # explicit legacy limits remain supported; expanded defaults tested separately


def test_paging_and_truncation():
    pager=ToolPager(max_bytes=9000)
    first=pager.add({'text':'中'*5000,'returncode':0})
    assert first['truncated'] and len(first['content'].encode())<=4096
    for i in range(first['page_count']):
        assert len(pager.get(first['output_id'],i)['content'].encode())<=4096
    with pytest.raises(ValueError): pager.get(first['output_id'],-1)


def test_prompt_preserves_task_and_caps_input():
    tokenizer=Utf8BoundTokenizer();header={'instruction':'fixed','team_record':'do not lose this'}
    prompt=coding_prompt(header,[{'action':{'tool':'read','arguments':{'path':'example.py'}},
        'result':{'content':'x'*10000}} for _ in range(10)],tokenizer,cap=24000)
    assert len(tokenizer.encode(prompt))+64<=24000
    assert json.loads(json.loads(prompt)['input'][0]['content'])==header
    with pytest.raises(BudgetExceeded): coding_prompt({'instruction':'x'*25000},[],tokenizer,cap=24000)


def test_semantic_progress_ignores_comments_whitespace_and_detects_change(tmp_path):
    p=tmp_path/'slot.py';p.write_text('def f():\n    return 1\n')
    original=semantic_state(tmp_path,['slot.py'])
    p.write_text('# arbitrary chatter\n\ndef f():\n    return 1\n')
    assert semantic_state(tmp_path,['slot.py'])==original
    p.write_text('def f():\n    return 2\n')
    assert semantic_state(tmp_path,['slot.py'])!=original


class FakeSandbox:
    def __init__(self,repo,passed=True): self.repo=repo;self.passed=passed;self.synced=[]
    def sync_file(self,name): self.synced.append(name)
    def snapshot(self): return {'objective':'fixture'}
    def exec(self,args): return {'returncode':0,'text':'fixture','truncated':False}
    def judge(self,tests,**kwargs):
        return {'returncode':0 if self.passed else 1,'failed':0 if self.passed else 3,
                'skipped':0,'collected':3,'passed_tests':['base::one']}
    def __enter__(self): return self
    def __exit__(self,*args): pass


@pytest.fixture
def session(tmp_path,seed):
    (tmp_path/'slot.py').write_text('def f():\n    return 1\n')
    seed['public_policy']={'default':'fixture'};seed['data_schema']={'fixture':'text'}
    seed['qa']={'anchor_contexts':{'B0':'','B1':'stale','B2':'full'}}
    task={'instruction':'fixture task','writable_paths':['slot.py'],'hidden_tests':'private',
          'test_files':{c:f'test_{c}.py' for c in 'ABC'}}
    return seed,task,FakeSandbox(tmp_path)


def provider(actions):
    values=iter(actions)
    def call(prompt,*,max_output):
        return {'text':next(values,actions[-1]),'usage_tokens':20}
    return call


def test_mock_edit_finish_and_hidden_tests_never_in_prompt(session):
    seed,task,sandbox=session;seen=[]
    raw=[json.dumps({'tool':'write','arguments':{'path':'slot.py','content':'def f():\n    return 2\n'}}),'{"tool":"finish"}']
    inner=provider(raw)
    def model(prompt,**kwargs): seen.append(prompt);return inner(prompt,**kwargs)
    result=coding_session(seed,task,sandbox,model,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='pass' and result['turns']==2 and sandbox.synced==['slot.py']
    assert all('private' not in p and 'test_A.py' not in p for p in seen)


def test_disabled_model_never_called(session):
    seed,task,sandbox=session;called=[]
    with pytest.raises(RuntimeError):
        coding_session(seed,task,sandbox,lambda *a,**k:called.append(1),Utf8BoundTokenizer(),BudgetGuard(100000),config()['stage2'],'B0','A')
    assert not called


@pytest.mark.parametrize('raw',['not json','{"tool":"write","arguments":{"path":"../escape","content":"bad"}}',
    '{"tool":"read","arguments":{"path":"/etc/passwd"}}','{"tool":"unknown"}'])
def test_bad_or_escaping_actions(session,raw):
    seed,task,sandbox=session
    result=coding_session(seed,task,sandbox,provider([raw]),Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B0','A')
    assert result['outcome']=='parse_error'


def test_tool_chatter_stalls_without_50_paid_calls(session):
    seed,task,sandbox=session;calls=[]
    def model(*a,**k): calls.append(1);return {'text':'{"tool":"list"}','usage_tokens':20}
    result=coding_session(seed,task,sandbox,model,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B0','A')
    assert result['outcome']=='model_wrong' and len(calls)==6  # initial inventory + five repeats


def test_bad_candidate_import_is_model_wrong_not_environment(session):
    seed,task,sandbox=session;task['smoke_imports']=['fixture']
    sandbox.exec=lambda args:{'returncode':1,'text':'candidate SyntaxError'}
    result=coding_session(seed,task,sandbox,provider(['{"tool":"finish"}']),Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='model_wrong' and 'candidate' in result['reason']


def test_calibration_27_fresh_mock_sandboxes(session):
    seed,task,sandbox=session;created=[]
    def fresh(c): created.append(c);return FakeSandbox(sandbox.repo)
    report=calibrate_coding(seed,task,provider(['{"tool":"finish"}']*27),Utf8BoundTokenizer(),BudgetGuard(1000000,enabled=True),config(),fresh)
    assert len(created)==27 and report['complete'] and not report['passed'] # B0 high must be rejected
    assert all(v==1 for row in report['scores'].values() for v in row.values())


def test_env_error_not_imputed_as_zero(session):
    seed,task,sandbox=session
    def unavailable(c): raise EnvError('fixture container unavailable')
    with pytest.raises(EnvError):
        calibrate_coding(seed,task,provider([]),Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config(),unavailable)


def ready_factory():
    f=Factory(case_id='fixture');f.advance(1,lambda _:True);return f


def test_stage2_two_business_failures_and_gate_lock():
    f=ready_factory()
    def bad(_): raise CalibrationFailed('fixture wrong')
    with pytest.raises(ValueError,match='approve'): f.run_stage2(bad)
    with pytest.raises(CalibrationFailed): f.run_stage2(bad,approve=True)
    f=Factory(json.loads(json.dumps(f.state)))
    with pytest.raises(CircuitOpen): f.run_stage2(bad,approve=True)
    assert f.state['stage']==1 and f.state['attempts']['fixture']['2']['attempts']==2


def test_stage2_infrastructure_two_retries_without_business_failures():
    f=ready_factory();calls=[]
    def unavailable(_): calls.append(1);raise EnvError('fixture 5xx')
    with pytest.raises(CircuitOpen): f.run_stage2(unavailable,approve=True)
    counter=f.state['attempts']['fixture']['2']
    assert len(calls)==3 and counter['env_error']==3 and counter['attempts']==0
    assert f.state['status']=='NEEDS_HUMAN' and f.state['failures']=={}


def test_stage2_success_stops_before_stage3():
    f=ready_factory();f.run_stage2(lambda _:True,approve=True)
    assert f.state['stage']==2 and f.state['gate'] and f.state['status']=='GATE'


def test_runner_disabled_cannot_open_transport(tmp_path,seed):
    runner=CodingRunner(tmp_path,seed,BudgetGuard(1500000),config=config())
    with pytest.raises(RuntimeError,match='opt-in'): runner(2)


def test_judge_reads_tmpfs_xml_via_exec_and_preserves_pytest_output(tmp_path,monkeypatch):
    import benchmark4.harness.coding_sandbox as module
    sandbox=module.Sandbox(tmp_path,tmp_path/'profiles.yaml','A_static',workspace_image='mock',service_image='mock')
    sandbox.stage=lambda *args:None
    sandbox.checked=lambda args:{'returncode':0,'text':'created'}
    calls=[]
    xml='<testsuites><testsuite>'+''.join(f'<testcase classname="fixture" name="test_{i}"><failure message="expected baseline failure"/></testcase>' for i in range(3))+'</testsuite></testsuites>'
    def fake(args,**kwargs):
        calls.append(args)
        if 'pytest' in args: return {'returncode':1,'text':'3 failed','truncated':False,'total_bytes':8}
        if '/tmp/result.xml' in ' '.join(args): return {'returncode':0,'text':xml,'truncated':False,'total_bytes':len(xml)}
        return {'returncode':0,'text':'','truncated':False,'total_bytes':0}
    monkeypatch.setattr(module,'command',fake)
    report=tmp_path/'negative.xml'
    result=sandbox.judge(tmp_path,report=report,test_name='test_A.py')
    assert result['collected']==result['failed']==3 and result['errors']==0
    assert report.read_text()==xml
    assert json.loads(report.with_suffix('.pytest.json').read_text())['returncode']==1
    assert not any('cp' in args for args in calls)
    assert any(args[:2]==['docker','exec'] and 'read_text' in ' '.join(args) for args in calls)


def test_judge_missing_xml_keeps_raw_pytest_error_evidence(tmp_path,monkeypatch):
    import benchmark4.harness.coding_sandbox as module
    sandbox=module.Sandbox(tmp_path,tmp_path/'profiles.yaml','A_static',workspace_image='mock',service_image='mock')
    sandbox.stage=lambda *args:None
    sandbox.checked=lambda args:{'returncode':0,'text':'created'}
    def fake(args,**kwargs):
        if 'pytest' in args: return {'returncode':2,'text':'fixture collection error','truncated':False,'total_bytes':24}
        if '/tmp/result.xml' in ' '.join(args): return {'returncode':1,'text':'FileNotFoundError','truncated':False,'total_bytes':17}
        return {'returncode':0,'text':'','truncated':False,'total_bytes':0}
    monkeypatch.setattr(module,'command',fake)
    report=tmp_path/'missing.xml'
    with pytest.raises(EnvError,match='XML read failed'): sandbox.judge(tmp_path,report=report)
    assert json.loads(report.with_suffix('.pytest.json').read_text())['text']=='fixture collection error'
    assert not report.exists()


def test_responses_usage_cache_and_coding_log_are_preserved(session):
    from benchmark4.harness.stage1_provider import OpenAIResponsesProvider
    seed,task,sandbox=session
    usage=SimpleNamespace(input_tokens=12,output_tokens=8,total_tokens=20,
                          input_tokens_details=SimpleNamespace(cached_tokens=10))
    response=SimpleNamespace(id='mock-cache',status='completed',output_text='',usage=usage,
        output=[SimpleNamespace(type='function_call',name='finish',arguments='{}',call_id='call-cache')])
    client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs:response))
    model=OpenAIResponsesProvider(model='fixture',enabled=True,client=client)
    result=coding_session(seed,task,sandbox,model,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    row=result['log'][0]
    assert result['outcome']=='pass'
    assert (row['input_tokens'],row['output_tokens'],row['cached_input_tokens'])==(12,8,10)
    assert row['usage_tokens']==20  # cached tokens are already part of input


def test_native_replay_associates_actual_call_id_with_full_result(session):
    from benchmark4.harness.stage1_provider import OpenAIResponsesProvider
    seed,task,sandbox=session;sent=[]
    def create(**kwargs):
        sent.append(kwargs);i=len(sent)
        call=SimpleNamespace(type='function_call',name='read' if i==1 else 'finish',
            arguments='{"path":"slot.py"}' if i==1 else '{}',call_id=f'actual-call-{i}')
        return SimpleNamespace(id=f'response-{i}',status='completed',output_text='',output=[call],
            usage=SimpleNamespace(input_tokens=12,output_tokens=8,total_tokens=20))
    model=OpenAIResponsesProvider(model='fixture',enabled=True,client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    result=coding_session(seed,task,sandbox,model,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='pass' and len(sent)==3
    history=sent[1]['input'];assert history[0]['role']=='user'
    assert history[1]['type']=='function_call' and history[2]['type']=='function_call_output'
    assert history[1]['call_id']==history[2]['call_id']=='actual-call-1'
    feedback=json.loads(history[2]['output'])
    assert 'return 1' in feedback['content'] and not feedback['truncated']
    assert sent[1]['tool_choice']=='required' and sent[1]['parallel_tool_calls'] is False
    assert sent[1]['extra_body']=={'thinking':{'type':'disabled'}} and sent[1]['temperature']==0
    assert result['log'][0]['provider_output']['arguments']=='{"path":"slot.py"}'


def test_new_file_exploration_does_not_prematurely_stall(session):
    seed,task,sandbox=session;actions=[]
    for i in range(6):
        name=f'discover_{i}.py';(sandbox.repo/name).write_text(f'value = {i}\n')
        actions.append(json.dumps({'tool':'read','arguments':{'path':name}}))
    actions.extend([json.dumps({'tool':'write','arguments':{'path':'slot.py','content':'def f():\n    return 2\n'}}),'{"tool":"finish"}'])
    result=coding_session(seed,task,sandbox,provider(actions),Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='pass' and result['turns']==8
    assert [r['progress']['kind'] for r in result['log'][:6]]==['exploration']*6
    assert result['log'][6]['progress']['kind']=='engineering'


def test_repeated_unchanged_file_reads_stop(session):
    seed,task,sandbox=session;calls=[]
    def model(*a,**k):
        calls.append(1);return {'text':'{"tool":"read","arguments":{"path":"slot.py"}}','usage_tokens':20}
    result=coding_session(seed,task,sandbox,model,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='model_wrong' and len(calls)==6
    assert result['log'][0]['progress']['exploration_used']==1
    assert result['log'][1]['progress']['kind']=='none'


def test_exploration_is_finite_even_with_many_new_files(session):
    seed,task,sandbox=session;actions=[]
    for i in range(20):
        name=f'discover_{i}.py';(sandbox.repo/name).write_text(f'value = {i}\n')
        actions.append(json.dumps({'tool':'read','arguments':{'path':name}}))
    result=coding_session(seed,task,sandbox,provider(actions),Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='model_wrong' and result['turns']==24  # discovery 20 is the first uncredited action for this legacy cap


def test_repeat_pages_do_not_reset_exploration_via_new_output_id(session):
    seed,task,sandbox=session;(sandbox.repo/'large.txt').write_text('a'*4096+'b'*4096+'c'*10)
    actions=[{'tool':'read','arguments':{'path':'large.txt'}},
             {'tool':'page','arguments':{'output_id':'1','page':1}},
             {'tool':'page','arguments':{'output_id':'1','page':0}},
             {'tool':'read','arguments':{'path':'large.txt'}},
             {'tool':'page','arguments':{'output_id':'2','page':1}}, {'tool':'finish'}]
    result=coding_session(seed,task,sandbox,provider([json.dumps(x) for x in actions]),Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],'B2','A')
    assert result['outcome']=='pass'
    assert [r['progress']['exploration_used'] for r in result['log'][:5]]==[1,2,2,2,2]


def test_trim_never_orphans_native_call_and_output():
    header={'instruction':'fixed'}
    history=[{'action':{'tool':'read','arguments':{'path':f'f{i}.py'}},'call_id':f'id-{i}',
              'result':{'content':'x'*10000}} for i in range(10)]
    raw=coding_prompt(header,history,Utf8BoundTokenizer(),cap=24000)
    value=json.loads(raw);items=value['input']
    assert len(raw.encode())+64<=24000 and len(items)%2==1
    assert len(items)<21
    for i in range(1,len(items),2):
        assert items[i]['type']=='function_call' and items[i+1]['type']=='function_call_output'
        assert items[i]['call_id']==items[i+1]['call_id']


def test_fifty_turn_limit_survives_constant_ast_changes(session):
    seed,task,sandbox=session;calls=[]
    def model(*a,**k):
        calls.append(1)
        return {'text':json.dumps({'tool':'write','arguments':{'path':'slot.py','content':f'def f():\n    return {len(calls)+1}\n'}}),'usage_tokens':20}
    result=coding_session(seed,task,sandbox,model,Utf8BoundTokenizer(),BudgetGuard(1500000,enabled=True),config()['stage2'],'B2','A')
    assert len(calls)==50 and result['outcome']=='model_wrong' and result['reason']=='turn limit'


def test_action_docs_are_anchor_neutral_and_placeholder_only(session):
    seed,task,sandbox=session;headers=[]
    for anchor in ['B0','B1','B2']:
        def capture(prompt,*,max_output):
            value=json.loads(prompt);header=json.loads(value['input'][0]['content'])
            headers.append(header)
            names={t['name'] for t in value['tools']};assert 'run_cmd' not in names
            assert 'slot.py' not in json.dumps(header['examples'])
            return {'text':'{"tool":"finish"}','usage_tokens':20}
        coding_session(seed,task,sandbox,capture,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),config()['stage2'],anchor,'A')
    for h in headers:
        assert h['workspace_root']=='/home/worker/workspace'
        h.pop('team_record')
    assert headers[0]==headers[1]==headers[2]
