"""Offline tests: no transport credentials, SDK clients, Docker or model calls."""
import json
from copy import deepcopy
from pathlib import Path
import hashlib
import pytest
from benchmark4.harness.act_stream_builder import ActStreamSession, ActExhausted, FactLedger, validate_turn
from benchmark4.harness.run_stage3 import BudgetedCalls, verify_stream, qa_stream_prompt, load_events, run
from benchmark4.harness.stage1_provider import Utf8BoundTokenizer
from benchmark4.harness.budget_guard import BudgetGuard, BudgetExceeded
from benchmark4.harness.common import read
from benchmark4.harness.stage1_errors import EnvError

ROOT=Path(__file__).resolve().parents[2]/'datasets/refund_pilot'
CASE='C01_refund_display_contract'
BASE=ROOT/'cases'/CASE


def test_speaker_act_bytes_and_copy(seed):
    s=deepcopy(seed)
    s['facts'] += [{'id':'foreign','owner':'dev_backend','unlock_act':1,'text':'PRIVATE_OTHER'},
                   {'id':'future','owner':'pm_lead','unlock_act':3,'text':'PRIVATE_FUTURE'}]
    session=ActStreamSession(s,[])
    v=session.view();raw=json.dumps(v)
    assert v['speaker']=='pm_lead' and [f['id'] for f in v['facts']]==['f1']
    assert all(x not in raw for x in ('PRIVATE_OTHER','PRIVATE_FUTURE','SECRET_FUTURE','f2'))
    v['facts'][0]['text']='mutated'
    assert session.view()['facts'][0]['text']=='first visible fact'
    assert FactLedger([{'id':'x','owner':'dev_backend','unlock_act':1}]).view(1,'pm_lead')==[]


def test_real_events_before_act_and_no_private_metadata():
    seed=read(ROOT/'seeds'/f'{CASE}.yaml');events=load_events(ROOT,read(BASE/'stage3_plan.json'))
    s=ActStreamSession(seed,read(BASE/'symbol_manifest.json')['symbols'],events=events)
    views=[]
    def mock(view):
        views.append(view)
        return {'role':view['speaker'],'fact_ids':[view['facts'][-1]['id']],'text':'先按当前约定落实。'}
    while not s.done:s.step(mock)
    for view in views:
        text=json.dumps(view,ensure_ascii=False)
        if view['act']==1:
            assert 'real Docker worker HTTP call' not in text and 'diff --git' not in text
        if view['act']>=2:assert 'real Docker worker HTTP call' in text
        if view['act']==3:assert 'diff --git a/refunds/service.py' in text
        assert all('fact_ids' not in r for r in view['public_history'])
        assert all(f['role']==view['speaker'] and f['unlock_act']<=view['act'] for f in view['facts'])
    assert [r['kind'] for r in s.public_stream]==['dialogue','dialogue','tool_log','dialogue','dialogue','git_diff','dialogue','dialogue']


@pytest.mark.parametrize('bad',['一句。二句。三句。四句。','1. 规则：先这样。','使用 `nonexistent`。',
    '调用 absent_function()。','使用 unknown_field。',*['这里提到'+w+'。' for w in ('团队记忆','关键前提','适用边界','废案','反事实','锚点')]])
def test_invalid_turn_regenerates_once(seed,bad):
    session=ActStreamSession(seed,[]);calls=[]
    def mock(view):
        calls.append(view)
        return {'role':view['speaker'],'fact_ids':['f1'],'text':bad if len(calls)==1 else '已确认当前约定。'}
    session.step(mock)
    assert len(calls)==2 and len(session.rejections)==1 and len(session.stream)==1
    assert 'retry_reason' in calls[1] and calls[1]['facts']==calls[0]['facts']


def test_regeneration_has_bound_and_no_partial_accept(seed):
    s=ActStreamSession(seed,[],max_regenerations=2);n=[]
    def mock(v):n.append(1);return {'role':v['speaker'],'fact_ids':['f1'],'text':'1. 列表。'}
    with pytest.raises(ValueError,match='regeneration exhausted'):s.step(mock)
    assert len(n)==3 and len(s.rejections)==3 and s.stream==[] and s.machine.turns==0


def test_max_turns_immediately_fails_without_regeneration(seed):
    s=ActStreamSession(seed,[]);calls=[]
    def mock(v):calls.append(1);return {'role':v['speaker'],'fact_ids':[],'text':'再看看其他情况。'}
    s.step(mock)
    with pytest.raises(ActExhausted):s.step(mock)
    assert len(calls)==2 and len(s.rejections)==0 and not s.done


def test_claim_cannot_unlock_without_expression(seed):
    s=ActStreamSession(seed,[],max_regenerations=0,fact_check=lambda f,t:False)
    with pytest.raises(ValueError,match='not expressed'):
        s.step(lambda v:{'role':v['speaker'],'fact_ids':['f1'],'text':'没有相关信息。'})
    assert s.machine.covered==set() and s.stream==[]


def test_wrong_speaker_and_foreign_fact_rejected(seed):
    s=ActStreamSession(seed,[],max_regenerations=0)
    with pytest.raises(ValueError,match='speaker'):
        s.step(lambda v:{'role':'dev_backend','fact_ids':['f2'],'text':'已确认。'})
    assert s.stream==[]


def test_env_error_not_regenerated(seed):
    s=ActStreamSession(seed,[]);n=[]
    def mock(v):n.append(1);raise EnvError('offline infrastructure mock')
    with pytest.raises(EnvError):s.step(mock)
    assert len(n)==1 and s.rejections==[]


def test_event_integrity_hash_rejects(tmp_path):
    p=tmp_path/'event.json';p.write_text('{}')
    with pytest.raises(ValueError,match='hash changed'):
        load_events(tmp_path,{'events':[{'act':1,'kind':'tool_log','path':'event.json','sha256':'wrong'}]})


def harness_calls(provider,budget=200000):
    return BudgetedCalls(provider,Utf8BoundTokenizer(),BudgetGuard(budget,enabled=True),
                         {'max_output_tokens':512,'prompt_overhead_tokens':64})


def seed_and_chat():
    seed=read(ROOT/'seeds'/f'{CASE}.yaml')
    rows=[{'kind':'dialogue','role':r,'act':1,'text':'这个提议不采用。'} for r in seed['roles']]
    rows.insert(0,{'kind':'tool_log','act':1,'text':'real public fixture event'})
    return seed,rows


def verifier_provider(seed, *, full_pattern=None, blind_override=None):
    counts={}
    def provider(prompt,*,max_output):
        p=json.loads(prompt)
        if 'statement' in p:answer='true'
        else:
            roles={r.get('role') for r in p['team_record'] if r['kind']=='dialogue'}
            full=len(roles)==4
            context='C' if p['current_snapshot']['protocol']['name']=='receipt_v2' else 'B' if 'ui_theme' in p['current_snapshot'] else 'A'
            group='full' if full else next(iter(roles));key=(group,context)
            n=counts.get(key,0);counts[key]=n+1
            ok=(full_pattern or [True,True,False])[n%3] if full else False
            if not full and blind_override==key:ok=True
            answer=json.dumps(seed['qa']['expected'][context] if ok else {'exec_ids':[]})
        return {'text':answer,'usage_tokens':10,'input_tokens':8,'output_tokens':2}
    return provider


def test_real_qa_chain_45_calls_thresholds_and_no_spoiler():
    seed,rows=seed_and_chat();calls=harness_calls(verifier_provider(seed))
    proof=verify_stream(seed,rows,[],calls,[{'id':'x','text':'提议被否决','pattern':'不采用'}])
    assert proof['complete'] and proof['passed'] and len(proof['records'])==45
    assert all(v==dict.fromkeys('ABC',0) for v in proof['blind_scores'].values())
    assert proof['full_scores']==dict.fromkeys('ABC',2/3)
    for r in calls.records:
        p=json.loads(r['prompt'])
        assert not any(k in p for k in ('expected','gold','anchor','context'))
        if len({x.get('role') for x in p['team_record'] if x['kind']=='dialogue'})==1:
            assert all(x['kind']=='dialogue' for x in p['team_record'])
            assert len(p['team_record'])==1
    assert calls.usage()['verification']['usage_tokens']==450


@pytest.mark.parametrize('kind',['blind','full'])
def test_threshold_violation_fails(kind):
    seed,rows=seed_and_chat()
    provider=verifier_provider(seed,full_pattern=[True,False,False] if kind=='full' else None,
                                 blind_override=('pm_lead','C') if kind=='blind' else None)
    proof=verify_stream(seed,rows,[],harness_calls(provider),[{'id':'x','text':'明确否决','pattern':'不采用'}])
    assert proof['complete'] and not proof['passed'] and len(proof['records'])==45


def test_single_full_round_requires_all_three_contexts_correct():
    seed,rows=seed_and_chat()
    proof=verify_stream(seed,rows,[],harness_calls(verifier_provider(seed,full_pattern=[True])),
                        [{'id':'x','text':'明确否决','pattern':'不采用'}],full_repeats=1)
    assert proof['passed'] and len(proof['records'])==39
    assert proof['full_scores']==dict.fromkeys('ABC',1)


def test_rejected_option_requires_explicit_denial(tmp_path):
    seed,rows=seed_and_chat();calls=harness_calls(lambda *a,**kw:{'text':'false','usage_tokens':1})
    out=tmp_path/'proof.json'
    with pytest.raises(ValueError,match='not explicitly denied'):
        verify_stream(seed,rows,[],calls,[{'id':'x','text':'明确否决'}],output=out)
    assert not read(out)['passed'] and len(calls.records)==4


def test_parse_error_in_denominator_and_env_error_aborts(tmp_path):
    seed,rows=seed_and_chat()
    proof=verify_stream(seed,rows,[],harness_calls(lambda *a,**kw:{'text':'broken','usage_tokens':1}),
                        [{'id':'x','text':'明确否决','pattern':'不采用'}])
    assert len(proof['records'])==45 and all(r['outcome']=='parse_error' for r in proof['records'])
    assert not proof['passed']
    def env(*a,**kw):raise EnvError('offline')
    out=tmp_path/'proof.json'
    with pytest.raises(EnvError):verify_stream(seed,rows,[],harness_calls(env),[{'id':'x','text':'否决','pattern':'不采用'}],output=out)
    assert read(out)['complete'] is False and len(read(out)['records'])==1


def test_shared_hard_budget_blocks_before_provider():
    seed,rows=seed_and_chat();n=[]
    def provider(*a,**kw):n.append(1);return {'text':'true','usage_tokens':1}
    calls=harness_calls(provider,budget=10)
    with pytest.raises(BudgetExceeded):calls.call({'text':'too long'},phase='generation')
    assert n==[]


def test_mock_end_to_end_pending_review_and_frozen_hashes(tmp_path):
    seed=read(ROOT/'seeds'/f'{CASE}.yaml');plan=read(BASE/'stage3_plan.json')
    qa=verifier_provider(seed)
    def provider(prompt,*,max_output):
        p=json.loads(prompt)
        if 'view' in p:
            v=p['view'];text='按当前已说明的约定处理。'
            return {'text':json.dumps({'role':v['speaker'],'fact_ids':[v['facts'][-1]['id']],'text':text}),
                    'usage_tokens':10,'input_tokens':8,'output_tokens':2}
        return qa(prompt,max_output=max_output)
    hashes=read(BASE/'coding_calibration.json')['source_hashes']
    original_factory=read(BASE/'factory_state.json')
    out=tmp_path/'mock_run'
    result=run(seed,ROOT,provider,Utf8BoundTokenizer(),BudgetGuard(200000,enabled=True),
        plan=plan,qa_config={'max_output_tokens':512,'prompt_overhead_tokens':64},output=out)
    assert result['status']=='GATE_3_REVIEW' and not result['locked'] and result['passed']
    assert (out/'raw_stream.jsonl').exists() and read(out/'stream_verification.json')['complete']
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items() if not Path(p).is_relative_to(Path(__file__).resolve().parents[1]))
    assert read(BASE/'factory_state.json')==original_factory


def test_t0_vocabulary_sources_exclude_future_profiles():
    from benchmark4.harness.act_stream_builder import t0_vocabulary
    seed=read(ROOT/'seeds'/f'{CASE}.yaml')
    t0=read(ROOT/'artifacts'/CASE/'tool_log.json')['response']
    names,literals=t0_vocabulary(t0)
    assert {'receipt_ref','acceptance_ack','receipt_v1','after_acceptance','ACCEPTED','UNKNOWN','FAILED'}<=names
    assert {'E03','CH01','null','None','200'}<=names and literals==set()
    assert not {'receipt_v2','on_request_registration','REG03'} & (names|literals)
    # Changing future profiles cannot affect extraction from the T0 response.
    seed['external_profiles']['C_changed']['default']['future_only_key']='FUTURE_ONLY'
    assert t0_vocabulary(t0)==(names,literals) and 'future_only_key' not in names
    assert {'E03','CH01'}<=names  # quoted and plain data values share membership


def test_schema_and_t0_union_follows_event_injection():
    seed=read(ROOT/'seeds'/f'{CASE}.yaml');plan=read(BASE/'stage3_plan.json')
    events=load_events(ROOT,plan)
    ast=set(read(BASE/'symbol_manifest.json')['symbols']);base=ast|set(seed['data_schema'])
    assert 'receipt_ref' not in ast and 'receipt_ref' in base
    s=ActStreamSession(seed,base,events=events)
    assert 'receipt_v1' not in s.symbols
    def mock(v):return {'role':v['speaker'],'fact_ids':[v['facts'][-1]['id']],'text':'已确认当前约定。'}
    s.step(mock);s.step(mock);v=s.view()
    assert v['act']==2 and {'receipt_v1','receipt_ref','acceptance_ack'}<=s.symbols
    validate_turn('当前 `receipt_v1` 的 `receipt_ref` 可结合 `acceptance_ack` 核对。',s.symbols,[],s.literals)
    validate_turn('E03 需要再核实。',s.symbols,[],s.literals)


@pytest.mark.parametrize('bad',['使用 `fabricated_snake_case`。','使用 fabricated_snake_case。',
    '切到 `receipt_v2`。','切到 receipt_v2。','使用 `on_request_registration`。',
    '使用 on_request_registration。','查询 `REG03`。','查询 REG03。'])
def test_unobserved_symbols_still_regenerate(bad):
    seed=read(ROOT/'seeds'/f'{CASE}.yaml')
    symbols=set(read(BASE/'symbol_manifest.json')['symbols'])|set(seed['data_schema'])
    s=ActStreamSession(seed,symbols,events=load_events(ROOT,read(BASE/'stage3_plan.json')))
    def accept(v):return {'role':v['speaker'],'fact_ids':[v['facts'][-1]['id']],'text':'当前约定已确认。'}
    s.step(accept);s.step(accept);calls=[]
    def mock(v):
        calls.append(v)
        return {'role':v['speaker'],'fact_ids':['receipt_premise'],
                'text':bad if len(calls)==1 else '核对 `receipt_ref` 和 `acceptance_ack`。'}
    s.step(mock)
    assert len(calls)==2 and len(s.rejections)==1
    assert s.stream[-1]['text']=='核对 `receipt_ref` 和 `acceptance_ack`。'
    assert not any(x in s.symbols for x in ('fabricated_snake_case','receipt_v2','on_request_registration','REG03'))
    assert [r['kind'] for r in s.public_stream].count('tool_log')==1


def test_same_vocabulary_used_by_generation_prompt_and_verification(tmp_path):
    from benchmark4.harness.run_stage3 import generate_stream
    seed=read(ROOT/'seeds'/f'{CASE}.yaml');plan=read(BASE/'stage3_plan.json')
    events=load_events(ROOT,plan)
    base=set(read(BASE/'symbol_manifest.json')['symbols'])|set(seed['data_schema'])
    prompts=[]
    def provider(prompt,*,max_output):
        p=json.loads(prompt)
        if 'view' not in p:return {'text':'true','usage_tokens':1}
        prompts.append(p);v=p['view']
        if v['act']==1:assert 'receipt_v1' not in p['allowed_symbols']
        else:assert {'receipt_v1','receipt_ref','acceptance_ack'}<=set(p['allowed_symbols'])
        assert not {'receipt_v2','on_request_registration','REG03'}&set(p['allowed_symbols'])
        return {'text':json.dumps({'role':v['speaker'],'fact_ids':[v['facts'][-1]['id']],
            'text':'核对 `receipt_ref` 和 `acceptance_ack`。' if v['act']==2 else '按当前约定处理。'}),'usage_tokens':1}
    rows,rejections=generate_stream(seed,base,events,harness_calls(provider),plan)
    assert len(prompts)==6 and rejections==[]
    # The verifier reconstructs the same time-dependent whitelist from events.
    proof=verify_stream(seed,rows,base,harness_calls(verifier_provider(seed)),[{'id':'x','text':'明确否决','pattern':'当前约定'}])
    assert proof['passed'] and proof['symbol_reference_count']==4 and proof['unknown_symbol_count']==0


@pytest.mark.parametrize('token',['E02','S01','CH01','null','None','True','False','true','false',
    'HTTP','JSON','ACCEPTED','FAILED','UNKNOWN','receipt_v1','after_acceptance','200'])
def test_unified_quoted_and_plain_values(token):
    from benchmark4.harness.act_stream_builder import t0_vocabulary
    names,_=t0_vocabulary(read(ROOT/'artifacts'/CASE/'tool_log.json')['response'])
    validate_turn('核对 `'+token+'`。',names)
    validate_turn('核对 '+token+'。',names)


def test_all_json_scalars_and_real_paths():
    from benchmark4.harness.stream_vocabulary import scalar_tokens,file_tokens
    names=scalar_tokens({'nested':[None,False,True,2.5,200,'arbitrary-value']})
    assert {'nested','null','None','false','False','true','True','2.5','200','arbitrary-value'}<=names
    files=read(BASE/'symbol_manifest.json')['files'];names.update(file_tokens(files))
    validate_turn('请查看 `refunds/service.py`。',names)
    validate_turn('请查看 refunds/service.py。',names)
    for text in ['请查看 `invented/service.py`。','请查看 invented/service.py。']:
        with pytest.raises(ValueError,match='invented/service.py'):validate_turn(text,names)


@pytest.mark.parametrize('token',['REG03','REG04','receipt_v2','on_request_registration'])
@pytest.mark.parametrize('quoted',[True,False])
def test_future_only_denied_even_if_accidentally_added_to_union(token,quoted):
    from benchmark4.harness.stream_vocabulary import future_only
    seed=read(ROOT/'seeds'/f'{CASE}.yaml')
    text='核对 '+('`'+token+'`' if quoted else token)+'。'
    with pytest.raises(ValueError,match=token):validate_turn(text,{token},denied=future_only(seed))


@pytest.mark.parametrize('text,hit', [('使用 `fabricated_snake_case`。','fabricated_snake_case'),
    ('查看 invented/service.py。','invented/service.py'),('这里写团队记忆。','团队记忆')])
def test_retry_feedback_contains_actual_bad_output_rule_and_hit(seed,text,hit):
    s=ActStreamSession(seed,[]);seen=[]
    def mock(v):
        seen.append(deepcopy(v))
        if len(seen)==1:return {'role':v['speaker'],'fact_ids':['f1'],'text':text}
        f=v['retry_feedback']
        assert hit in f['hits'] and hit in v['retry_reason']
        assert f['rule'] and f['previous_output']['text']==text and f['next_attempt']==2
        return {'role':v['speaker'],'fact_ids':['f1'],'text':'当前约定已确认。'}
    s.step(mock)
    assert len(seen)==2 and seen[1]!=seen[0] and len(s.rejections)==1


def test_retry_feedback_reaches_actual_model_prompt():
    from benchmark4.harness.run_stage3 import generate_stream
    seed=read(ROOT/'seeds'/f'{CASE}.yaml');plan=read(BASE/'stage3_plan.json');seen=[]
    def provider(prompt,*,max_output):
        p=json.loads(prompt)
        if 'view' not in p:return {'text':'true','usage_tokens':1}
        seen.append(p);v=p['view']
        text='使用 `fabricated_snake_case`。' if len(seen)==1 else '当前约定已确认。'
        if len(seen)==2:
            assert v['retry_feedback']['hits']==['fabricated_snake_case']
            assert v['retry_feedback']['previous_output']['text']=='使用 `fabricated_snake_case`。'
        return {'text':json.dumps({'role':v['speaker'],'fact_ids':[v['facts'][-1]['id']],'text':text}),'usage_tokens':1}
    rows,rejections=generate_stream(seed,[],load_events(ROOT,plan),harness_calls(provider),plan)
    assert len(rejections)==1 and len(seen)==7 and len([r for r in rows if r['kind']=='dialogue'])==6


def test_fact_identifier_vocabulary_remains_speaker_private(seed):
    seed=deepcopy(seed)
    seed['facts'].append({'id':'private','role':'dev_backend','unlock_act':1,'text':'PRIVATE_BACKEND_ONLY'})
    s=ActStreamSession(seed,[])
    assert 'PRIVATE_BACKEND_ONLY' not in s.allowed_symbols()
    assert 'SECRET_FUTURE' not in s.allowed_symbols()
