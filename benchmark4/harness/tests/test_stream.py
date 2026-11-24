import json
import pytest
from benchmark4.harness.act_stream_builder import FactLedger, ActStateMachine, validate_turn, build, verify
from benchmark4.harness.symbol_extract import extract, clean_why, scan_leaks


def test_physical_isolation(seed):
    ledger = FactLedger(seed['facts'])
    view = ledger.view(1)
    assert 'SECRET_FUTURE' not in json.dumps(view) and 'f2' not in json.dumps(view)
    view[0]['text'] = 'changed'
    assert ledger.view(1)[0]['text'] == 'first visible fact'
    assert len(ledger.view(2)) == 2


@pytest.mark.parametrize('text', ['- 总结。','1. 总结。','一、总结。','gold 已确定。','使用 `missing`。','一句。二句。三句。四句。','', 'x'*161])
def test_hard_reject(text):
    with pytest.raises(ValueError): validate_turn(text, ['handler'], ['gold'])


def test_symbols_and_cleaning():
    code = '# WHY secret\ndef handler(value):\n    """secret rationale"""\n    return value\n'
    assert set(extract(code)) == {'handler','value'}
    assert not scan_leaks(clean_why(code), ['secret','WHY'])
    validate_turn('调用 `handler`。随后检查结果。', extract(code), ['gold'])
    validate_turn('调用 handler。随后检查结果。', extract(code), ['gold'])


def test_min_max(seed):
    act = dict(seed['acts'][0], min_turns=2)
    sm = ActStateMachine([act]); sm.advance(['f1']); assert not sm.done
    sm.advance([]); assert sm.done
    sm = ActStateMachine([act]); sm.advance([])
    with pytest.raises(ValueError): sm.advance([])


def test_build_and_verify(seed):
    calls = []
    def mock(view):
        calls.append(view)
        role, fact = ('pm_lead','f1') if view['act'] == 1 else ('dev_backend','f2')
        return {'role':role, 'fact_ids':[fact], 'text':'已确认当前条件。'}
    rows = build(seed, [], mock, [{'kind':'tool_log','after_turn':1,'text':'real fixture tool output'}])
    assert 'SECRET_FUTURE' not in json.dumps(calls[0])
    assert [r['kind'] for r in rows] == ['dialogue','tool_log','dialogue']
    assert verify(rows, [], [], {'pm_lead':0,'dev_backend':0}, 1, seed['roles'])['passed']
    with pytest.raises(ValueError): verify(rows, [], [], {'pm_lead':1,'dev_backend':0}, 1, seed['roles'])
    with pytest.raises(ValueError): verify(rows, [], [], {'pm_lead':0}, 1, seed['roles'])


def test_locked_reference(seed):
    with pytest.raises(ValueError, match='locked'):
        build(seed, [], lambda view: {'role':'pm_lead','fact_ids':['f2'],'text':'已确认。'})
