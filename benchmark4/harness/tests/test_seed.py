from copy import deepcopy
import pytest
from benchmark4.harness.validate_seed import validate, validate_dataset


def test_legal(seed): assert validate(seed) == []


@pytest.mark.parametrize('change,reason', [
    ({'code_mode':'mode_1'}, 'S4'),
    ({'scenario':'agent_onboarding','code_mode':'mode_1','history_evolution':['E1']}, 'historical E1'),
    ({'competing_rules':['a','b','c','d']}, '1..3'),
    ({'fallback':{}}, 'fallback'),
    ({'evolution':['E1','E2','E4']}, 'composite'),
    ({'obstacles':['O1','O2','O3','O4']}, 'cap'),
    ({'dimension':'dynamic_knowledge_supersession'}, 'boundary'),
    ({'roles':['dev_backend','dev_frontend']}, 'authority'),
    ({'alternatives':[]}, 'alternative'),
])
def test_invalid(seed, change, reason):
    seed.update(change)
    assert any(reason in e for e in validate(seed))


def test_slots(seed):
    second = deepcopy(seed); second['id'] = 'other'
    assert 'duplicate target_slot' in validate_dataset([seed, second])
    second['target_slot'] = 'other_slot'
    assert validate_dataset([seed,second]) == []


def test_hard_and_dimension(seed):
    seed.update(difficulty='hard', evolution=['E1','E2','E4'], obstacles=['O1','O2','O3','O4','O5'], dimension='dynamic_knowledge_supersession', history_overwrites=2)
    assert validate(seed) == []


def test_locked_exit(seed):
    seed['acts'][0]['required_facts'] = ['f2']
    assert any('locked' in e for e in validate(seed))
