"""Offline Stage 1 contracts. Network is blocked by conftest's autouse fixture."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

from benchmark4.harness.common import read, write, seed_paths
from benchmark4.harness.budget_guard import BudgetGuard, BudgetExceeded
from benchmark4.harness.factory import Factory, Stage1Runner, CircuitOpen
from benchmark4.harness.stage1_errors import EnvError, CalibrationFailed
from benchmark4.harness.stage1_provider import OpenAIChatProvider, Utf8BoundTokenizer
from benchmark4.harness.run_qa_calibration import (check, check_stage1, stage1_config,
    calibrate_stage1, make_prompt, parse_exact)
from benchmark4.harness.validate_seed import validate, validate_dataset


@pytest.fixture
def c01():
    return read(Path(__file__).resolve().parents[2]/'seeds/C01_refund_display_contract.yaml')


def good_scores():
    return {'B0':dict.fromkeys('ABC',0), 'B1':{'A':1,'B':1,'C':0}, 'B2':dict.fromkeys('ABC',1)}


class AnswerPlan:
    """Predetermined responses; no model or outcome claims about real B1."""
    def __init__(self, *, malformed=False, wrong=False, env_calls=0):
        self.calls = []; self.malformed = malformed; self.wrong = wrong; self.env_calls = env_calls
        self.successful = 0

    def __call__(self, prompt, *, max_output):
        self.calls.append(prompt)
        if len(self.calls) <= self.env_calls: raise EnvError('fixture network outage')
        index = self.successful; self.successful += 1
        anchor, context = index//9 % 3, index//3 % 3
        correct = anchor == 2 or (anchor == 1 and context < 2)
        text = json.dumps({'exec_ids':['E01','E02','E05'] if correct and not self.wrong else []})
        if self.malformed: text = 'not JSON'
        return {'text':text, 'usage_tokens':20, 'input_tokens':12, 'output_tokens':8}


def guard(total=150000): return BudgetGuard(total, enabled=True)


def test_draft_static_and_examples(c01):
    assert validate(c01) == [] and validate_dataset([c01]) == []
    assert 'C01_refund_display_contract.yaml' in [p.name for p in seed_paths(Path(__file__).resolve().parents[2])]
    assert 'seed_template.yaml' not in [p.name for p in seed_paths(Path(__file__).resolve().parents[2])]
    # Independently derive the agreed identity set from objective evidence.
    for profile in ('A_static','B_irrelevant','C_changed'):
        rows = c01['external_profiles'][profile]['default']['executions']
        selected = sorted(r['exec_id'] for r in rows if r['acceptance_ack'] == 'ACCEPTED' or r['query_acceptance'] == 'ACCEPTED')
        assert selected == ['E01','E02','E05']
    assert c01['external_profiles']['A_static']['default']['executions'] == c01['external_profiles']['B_irrelevant']['default']['executions']


@pytest.mark.parametrize('anchor', ['B0','B1','B2'])
def test_prompt_whitelist(c01, anchor):
    prompt = make_prompt(c01, anchor, 'A')
    value = json.loads(prompt)
    assert value['team_record'] == c01['qa']['anchor_contexts'][anchor]
    for forbidden in ('DRAFT_PENDING_APPROVAL','expected_evidence','control_reference','target_slot','watched_files','unlock_act','C01_refund_display_contract'):
        assert forbidden not in prompt
    assert set(value) == {'instruction','public_policy','data_schema','team_record','current_snapshot','turn_1','turn_2','output_schema'}
    assert make_prompt(c01, anchor, 'A') != make_prompt(c01, anchor, 'C')


def test_27_answers_and_measured_budget(c01, tmp_path):
    model, budget = AnswerPlan(), guard()
    report = calibrate_stage1(c01, model, Utf8BoundTokenizer(), budget, output=tmp_path/'qa.json')
    assert len(model.calls) == len(report['records']) == 27
    assert report['complete'] and report['passed'] and report['denominator_per_cell'] == 3
    assert report['usage_tokens'] == budget.spent == 540
    assert report['outcomes'] == {'pass':15,'model_wrong':12,'parse_error':0,'env_error':0}
    assert read(tmp_path/'qa.json') == report
    assert len({(r['anchor'],r['context'],r['repeat']) for r in report['records']}) == 27


@pytest.mark.parametrize('anchor,context,value', [('B0','A',2/3),('B2','B',1/3),('B1','A',1/3),('B1','B',1/3),('B1','C',1)])
def test_frozen_thresholds(anchor, context, value):
    scores = good_scores(); scores[anchor][context] = value
    assert not check_stage1(scores)


def test_exact_thirds_and_legacy_unchanged():
    scores = good_scores(); scores['B2']['C'] = 2/3; scores['B1']['C'] = 1/3
    assert check_stage1(scores)
    scores['B1']['A'] = scores['B1']['B'] = 0.5
    assert check(scores)  # Stage 2 wasn't modified
    with pytest.raises(ValueError, match='exactly 3'): check_stage1(scores)


@pytest.mark.parametrize('raw', ['not JSON', '```json\n{"exec_ids": []}\n```','{"exec_ids": [1]}', '{"exec_ids": ["x","x"]}',
    '{"exec_ids": [], "extra": 0}', '{"exec_ids": [], "exec_ids": []}'])
def test_parse_error_is_not_wrong_business_answer(raw):
    with pytest.raises((ValueError, TypeError)): parse_exact(raw, {'exec_ids':'unique_string_list'})


def test_parse_errors_keep_denominator_and_raw(c01):
    report = calibrate_stage1(c01, AnswerPlan(malformed=True), Utf8BoundTokenizer(), guard())
    assert report['complete'] and not report['passed']
    assert report['outcomes']['parse_error'] == 27 and report['outcomes']['model_wrong'] == 0
    assert report['scores']['B2']['C'] == 0 and report['records'][0]['raw_answer'] == 'not JSON'


def test_budget_blocks_before_network_and_never_truncates(c01):
    model = AnswerPlan()
    with pytest.raises(BudgetExceeded): calibrate_stage1(c01, model, Utf8BoundTokenizer(), guard(10))
    assert model.calls == []
    budget = guard(); budget.input_cap = 100
    with pytest.raises(BudgetExceeded): calibrate_stage1(c01, model, Utf8BoundTokenizer(), budget)
    assert model.calls == []
    budget = BudgetGuard(150000)
    with pytest.raises(RuntimeError): calibrate_stage1(c01, model, Utf8BoundTokenizer(), budget)
    assert model.calls == []


def runner(c01, tmp_path, model):
    return Stage1Runner(c01, guard(), tmp_path/'qa.json', provider=model, tokenizer=Utf8BoundTokenizer())


def test_factory_stage1_gate_only(c01, tmp_path):
    f = Factory(case_id=c01['id'])
    r = runner(c01, tmp_path, AnswerPlan())
    f.run_stage1(r)
    assert f.state['stage'] == 1 and f.state['gate'] and f.state['status'] == 'GATE'
    assert len(read(tmp_path/'qa.json')['records']) == 27
    with pytest.raises(ValueError, match='approve'): f.advance(2, lambda _:True)
    assert f.state['stage1_budget_accounted_tokens'] == 540


def test_business_two_failure_circuit_persists(c01, tmp_path):
    r = runner(c01, tmp_path, AnswerPlan(wrong=True))
    f = Factory(case_id=c01['id'])
    with pytest.raises(CalibrationFailed): f.run_stage1(r)
    f = Factory(json.loads(json.dumps(f.state)), case_id=c01['id'])
    with pytest.raises(CircuitOpen): f.run_stage1(r)
    counter = f.state['attempts'][c01['id']]['1']
    assert counter == {'attempts':2,'model_wrong':2,'parse_error':0,'env_error':0}
    assert f.state['stage'] == 0 and f.state['status'] == 'CIRCUIT_OPEN'
    n = len(r.provider.calls)
    with pytest.raises(CircuitOpen): f.run_stage1(r)
    assert len(r.provider.calls) == n


def test_parse_failure_classification(c01, tmp_path):
    f = Factory(case_id=c01['id'])
    with pytest.raises(CalibrationFailed): f.run_stage1(runner(c01, tmp_path, AnswerPlan(malformed=True)))
    assert f.state['attempts'][c01['id']]['1']['parse_error'] == 1


def test_env_initial_plus_two_retries_no_business_failures(c01, tmp_path):
    f = Factory(case_id=c01['id']); r = runner(c01, tmp_path, AnswerPlan(env_calls=100))
    with pytest.raises(CircuitOpen): f.run_stage1(r)
    counter = f.state['attempts'][c01['id']]['1']
    assert counter['attempts'] == 0 and counter['env_error'] == 3
    assert len(r.provider.calls) == 3 and f.state['failures'] == {} and f.state['status'] == 'NEEDS_HUMAN'
    assert len(list((tmp_path/'qa_runs').glob('*.json'))) == 3
    artifact = read(tmp_path/'qa.json')
    assert artifact['outcomes']['env_error'] == 1 and not artifact['complete']
    assert 'A' not in artifact['scores']['B0']  # environment errors are never zero scores
    f = Factory(f.state, case_id=c01['id'])
    with pytest.raises(CircuitOpen): f.run_stage1(r)
    assert len(r.provider.calls) == 3


def test_env_then_success_preserves_reservations(c01, tmp_path):
    f = Factory(case_id=c01['id']); r = runner(c01, tmp_path, AnswerPlan(env_calls=1))
    f.run_stage1(r)
    assert f.state['attempts'][c01['id']]['1']['env_error'] == 1
    assert f.state['attempts'][c01['id']]['1']['attempts'] == 0
    assert len(r.provider.calls) == 28 and r.guard.spent > 540
    assert f.state['stage'] == 1


def test_cases_do_not_share_failure_counts(c01):
    f = Factory(case_id=c01['id'])
    with pytest.raises(CalibrationFailed): f.advance(1, lambda _: (_ for _ in ()).throw(CalibrationFailed('bad')))
    second = Factory(case_id='other')
    second.advance(1, lambda _: True)
    assert f.state['attempts'][c01['id']]['1']['attempts'] == 1
    assert second.state['failures'] == {}
    with pytest.raises(ValueError): Factory(f.state, case_id='other')


def test_real_transport_shape_but_fake_client():
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return NS(usage=NS(prompt_tokens=12,completion_tokens=8,total_tokens=20), choices=[NS(message=NS(content='{"exec_ids": []}'))])
    client = NS(chat=NS(completions=NS(create=create)))
    with pytest.raises(RuntimeError): OpenAIChatProvider(model='fixture', client=client)
    provider = OpenAIChatProvider(model='fixture', enabled=True, client=client)
    result = provider('fixture prompt', max_output=50)
    assert result['usage_tokens'] == 20 and sent[0]['model'] == 'fixture'
    assert sent[0]['messages'] == [{'role':'user','content':'fixture prompt'}]
    assert sent[0]['max_completion_tokens'] == 50


def test_network_errors_are_sanitized():
    def broken(**kwargs): raise TimeoutError('secret-token-must-not-leak')
    client = NS(chat=NS(completions=NS(create=broken)))
    provider = OpenAIChatProvider(model='fixture',enabled=True,client=client)
    with pytest.raises(EnvError, match='TimeoutError') as error: provider('x', max_output=10)
    assert 'secret-token' not in str(error.value)


@pytest.mark.parametrize('mutation', ['turn','expected','b0','watch'])
def test_stage1_recipe_validation(c01, mutation):
    if mutation == 'turn': c01['qa']['dialogues']['C']['turn_1'] += 'changed'
    if mutation == 'expected': c01['qa']['expected']['A'] = {'exec_ids':[1]}
    if mutation == 'b0': c01['qa']['anchor_contexts']['B0'] = 'leaked memory'
    if mutation == 'watch': c01['watched_files'] = ['../outside']
    assert validate(c01)


def test_factory_cli_mock_closure_stops_after_stage1(c01, tmp_path, monkeypatch, capsys):
    import sys
    import yaml
    from benchmark4.harness.factory import main
    (tmp_path/'seeds').mkdir()
    (tmp_path/'seeds/c01.yaml').write_text(yaml.safe_dump(c01, allow_unicode=True))
    fake = AnswerPlan()
    monkeypatch.setattr(OpenAIChatProvider, 'from_env', classmethod(lambda cls, **kwargs: fake))
    monkeypatch.setattr(sys, 'argv', ['factory','--dataset',str(tmp_path),'--case',c01['id'],'--stage','1','--execute-stage1'])
    main()
    base = tmp_path/'cases'/c01['id']
    state = read(base/'factory_state.json')
    assert state['stage'] == 1 and state['gate'] and state['status'] == 'GATE'
    assert len(fake.calls) == 27 and read(base/'qa_calibration.json')['complete']
    assert not (base/'coding_calibration.json').exists()
    assert 'stage 1 GATE' in capsys.readouterr().out


def test_cli_execute_cannot_start_other_stages(tmp_path, monkeypatch):
    import sys
    from benchmark4.harness.factory import main
    monkeypatch.setattr(sys, 'argv', ['factory','--dataset',str(tmp_path),'--all','--stage','2','--execute-stage1'])
    with pytest.raises(SystemExit, match='requires --stage 1'): main()
    assert list(tmp_path.iterdir()) == []


def test_watched_hashes_distinguish_missing_from_real(c01, tmp_path):
    path = tmp_path/c01['watched_files'][0]
    path.write_text('public policy fixture')
    report = calibrate_stage1(c01, AnswerPlan(), Utf8BoundTokenizer(), guard(), dataset_root=tmp_path)
    assert report['watched_hashes'][c01['watched_files'][0]] is not None
    assert report['watched_hashes'][c01['watched_files'][1]] is None


def test_ark_responses_transport_uses_text_only_fake_client():
    from benchmark4.harness.stage1_provider import OpenAIResponsesProvider
    sent=[]
    def create(**kwargs):
        sent.append(kwargs)
        return NS(id='fixture-response',status='completed',output_text='{"exec_ids":[]}',
                  usage=NS(input_tokens=12,output_tokens=8,total_tokens=20))
    provider=OpenAIResponsesProvider(model='fixture',enabled=True,client=NS(responses=NS(create=create)))
    result=provider('fixture prompt',max_output=50)
    assert result['usage_tokens']==20 and result['response_status']=='completed'
    assert sent[0]['max_output_tokens']==50 and not sent[0]['store']
    assert sent[0]['extra_body']=={'thinking':{'type':'disabled'}}
    assert 'tools' not in sent[0] and 'previous_response_id' not in sent[0]


def test_b2_has_no_future_protocol_in_unchanged_contexts(c01):
    for c in 'AB':
        assert 'receipt_v2' not in make_prompt(c01,'B2',c)
        assert 'on_request_registration' not in make_prompt(c01,'B2',c)
