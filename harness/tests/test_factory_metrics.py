from copy import deepcopy
import json
import pytest
from benchmark4.harness.factory import Factory, CircuitOpen, artifact_runner
from benchmark4.harness.common import write, read
from benchmark4.harness.merge_dataset_stream import merge, save_stream
from benchmark4.harness.act_stream_builder import build
from benchmark4.harness.run_memory_benchmark import summarize, run
from benchmark4.harness.memory_adapters.baselines import B0, B1, B2, LongContext, NaiveRAG


def test_transitions_and_gates():
    f = Factory()
    called = []
    def success(stage): called.append(stage); return True
    assert f.advance(1, success)['status'] == 'GATE'
    with pytest.raises(ValueError, match='approve'): f.advance(2, success)
    assert called == [1]
    f.advance(2, success, approve=True)
    assert f.advance(3, success, approve=True)['status'] == 'LOCKED'
    assert f.advance(4, success, approve=True)['status'] == 'COMPLETE'
    with pytest.raises(ValueError): f.advance(4, success, approve=True)
    assert called == [1,2,3,4]


def test_two_failures_persist():
    f = Factory()
    with pytest.raises(ValueError): f.advance(2, lambda _: True)
    assert f.state['failures'] == {}
    with pytest.raises(ValueError): f.advance(1, lambda _: False, mode='auto')
    assert f.state['status'] == 'FAILED'
    f = Factory(json.loads(json.dumps(f.state)))
    with pytest.raises(CircuitOpen): f.advance(1, lambda _: False, mode='auto')
    assert f.state['stage'] == 0 and f.state['status'] == 'CIRCUIT_OPEN'
    calls = []
    with pytest.raises(CircuitOpen): f.advance(1, lambda s: calls.append(s))
    assert calls == []


def test_auto():
    f = Factory()
    for stage in range(1,5): f.advance(stage, lambda _: True, mode='auto')
    assert f.state['status'] == 'COMPLETE' and not f.state['gate']


def record(seed):
    return {'gold':seed['gold'], 'extracted':dict(seed['gold']), 'qa_b2':1,'coding_b2':0.75,
            'coding_b0_c':0.5,'coding_b1_c':0.25,'tokens':100,'communication_bytes':42}


def test_metrics(seed):
    value = record(seed)
    report = summarize([value])
    assert report['denominator'] == 1 and set(report['whitebox'].values()) == {1}
    assert report['qa_coding_gap'] == 0.25 and report['stale_negative_transfer'] == 0.25
    assert report['cost']['tokens'] == 100
    for broken in [[], [dict(value, qa_b2=float('nan'))], [dict(value, tokens=-1)]]:
        with pytest.raises(ValueError): summarize(broken)
    del value['extracted']['rule']
    with pytest.raises(ValueError): summarize([value])


def test_adapters():
    events = [{'text':'alpha'}, {'text':'beta'}]
    for adapter in [B0(), B1([events[0]]), B2(), LongContext(), NaiveRAG()]:
        adapter.ingest(events)
        assert isinstance(adapter.dump_memories(), list)
    oracle = B2(); oracle.ingest(events)
    assert oracle.retrieve('irrelevant', limit=1) == events
    rag = NaiveRAG(); rag.ingest(events)
    assert rag.retrieve('beta', 1) == [events[1]]
    assert B0().retrieve('alpha') == []
    stale = B1([events[0]]); stale.ingest([events[1]])
    assert stale.dump_memories() == [events[0]]
    value = run(LongContext(), events, [{'query':'alpha'}], lambda task, mem: len(mem), lambda mem: len(mem))
    assert value == {'answers':[2], 'extracted':2}


def test_merge():
    cases = [{'id':'a','target_slot':'a','status':'LOCKED','stream':[{'text':'a1'},{'text':'a2'}]},
             {'id':'b','target_slot':'b','status':'LOCKED','stream':[{'text':'b1'}]}]
    rows = merge(cases)
    assert [r['text'] for r in rows] == ['a1','b1','a2']
    assert [r['source_sequence'] for r in rows] == [0,0,1]
    cases[0]['status'] = 'READY'
    with pytest.raises(ValueError): merge(cases)
    cases[0]['status'] = 'LOCKED'; cases[1]['target_slot'] = 'a'
    with pytest.raises(ValueError): merge(cases)


def test_four_stage_artifacts_in_tmp_only(seed, tmp_path):
    base = tmp_path/'cases'/seed['id']; base.mkdir(parents=True)
    scores = {'B0':dict.fromkeys('ABC',0), 'B1':dict.fromkeys('ABC',0.5), 'B2':dict.fromkeys('ABC',1)}
    write(base/'qa_calibration.json', {'scores':scores})
    write(base/'coding_calibration.json', {'scores':scores})
    write(base/'coding_evidence.json', {'positive':{'returncode':0}, 'negative':{'returncode':1},
        'keyframes':[{'name':name,'tool_log':'fixture','git_diff':'fixture','pytest':'fixture'} for name in ['T0','T1']]})
    write(base/'symbol_manifest.json', {'symbols':[]})
    def mock(view):
        fact = view['facts'][-1]
        return {'role':fact['role'], 'fact_ids':[fact['id']], 'text':'当前条件已确认。'}
    save_stream(base/'raw_stream.jsonl', build(seed, [], mock))
    write(base/'stream_verification.json', {'role_scores':dict.fromkeys(seed['roles'],0), 'full_score':1})
    write(base/'benchmark_records.json', [record(seed)])
    f = Factory(); runner = artifact_runner(tmp_path, seed)
    for stage in range(1,5): f.advance(stage, runner, mode='auto')
    assert f.state['status'] == 'COMPLETE'
    assert read(base/'benchmark_metrics.json')['denominator'] == 1


def test_missing_artifacts_fail_closed(seed, tmp_path):
    f = Factory()
    with pytest.raises(FileNotFoundError): f.advance(1, artifact_runner(tmp_path, seed), mode='auto')
    assert f.state['stage'] == 0
