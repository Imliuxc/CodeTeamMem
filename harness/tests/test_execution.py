import pytest
from benchmark4.docker.external_world_service.app import World
from benchmark4.harness.budget_guard import BudgetGuard, BudgetExceeded, ProgressGuard, pages
from benchmark4.harness.run_qa_calibration import check, evaluate
from benchmark4.harness.run_coding_calibration import self_check, DockerRunner


class Tokenizer:
    def encode(self, text): return list(text)
    def decode(self, tokens): return ''.join(tokens)


def test_profiles(seed):
    seed['external_profiles']['A_static']['routes'] = [{'match':{'amount':7,'channel':'test','protocol':'v1','date':'2026-01-01'},'response':{'available':False}}]
    world = World(seed['external_profiles'])
    assert world.snapshot('A_static', {}) != world.snapshot('C_changed', {})
    assert world.snapshot('A_static', {'amount':7,'channel':'test','protocol':'v1','date':'2026-01-01'}) == {'available':False}
    out = world.snapshot('A_static', {}); out['available'] = 'mutated'
    assert world.snapshot('A_static', {})['available'] is True
    seed['external_profiles']['A_static']['default']['history'] = 'leak'
    with pytest.raises(ValueError): World(seed['external_profiles'])


def test_budget():
    calls = []
    def mock(prompt, max_output):
        calls.append(prompt); return {'text':'ok','usage_tokens':len(prompt)+1}
    guard = BudgetGuard(25000,input_cap=24000)
    with pytest.raises(RuntimeError): guard.call(mock, 'abc', tokenizer=Tokenizer())
    assert calls == []
    guard.enabled = True
    assert guard.call(mock, 'x'*25000, tokenizer=Tokenizer(), max_output=2) == 'ok'
    assert len(calls[0]) == 24000 and guard.spent == 24001
    with pytest.raises(BudgetExceeded): guard.call(mock, 'x'*1000, tokenizer=Tokenizer())
    assert len(calls) == 1


def test_failure_reserves_budget():
    guard = BudgetGuard(100, enabled=True)
    def fail(*args, **kwargs): raise RuntimeError('provider failed')
    with pytest.raises(RuntimeError): guard.call(fail, 'x', tokenizer=Tokenizer(), max_output=9)
    assert guard.spent == 10


def test_pages_progress():
    text = '中'*5000
    chunks = list(pages(text))
    assert ''.join(chunks) == text and all(len(c.encode()) <= 4096 for c in chunks)
    guard = ProgressGuard(stall_limit=2)
    guard.observe(diff='a', passed_tests=[]); guard.observe(diff='a', passed_tests=[])
    with pytest.raises(BudgetExceeded): guard.observe(diff='a', passed_tests=[])
    guard = ProgressGuard(max_turns=40, stall_limit=100)
    for i in range(40): guard.observe(diff=str(i), passed_tests=[])
    with pytest.raises(BudgetExceeded): guard.observe(diff='41', passed_tests=[])


def test_calibration(seed):
    result = evaluate(['q'], lambda q, ctx, snapshot: ctx, lambda q, ans: ans,
                      World(seed['external_profiles']), {}, {'B0':0,'B1':0.5,'B2':1})
    assert result['passed'] and result['denominator_per_cell'] == 1
    scores = result['scores']; scores['B1']['C'] = 1
    assert not check(scores)
    del scores['B0']['A']
    with pytest.raises(ValueError): check(scores)


def test_selfcheck():
    class FakeRunner:
        def run(self, repo, command): return {'returncode': 0 if repo == 'good' else 1}
    assert self_check(FakeRunner(),'good','bad')['negative']['returncode'] == 1
    with pytest.raises(ValueError): self_check(FakeRunner(),'bad','good')


def test_docker_no_real_launch(tmp_path, monkeypatch):
    import subprocess
    seen = []
    def fake(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, b'ok', b'')
    monkeypatch.setattr(subprocess, 'run', fake)
    assert DockerRunner('fixture-image').run(tmp_path,['python','--version'])['returncode'] == 0
    assert seen[0][seen[0].index('--network')+1] == 'none'
    assert 'docker.sock' not in str(seen)
