from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError('network access forbidden in offline tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture
def seed():
    return {
        'id': 'fixture', 'scenario': 'task_handoff', 'dimension': 'cross_role_contract',
        'code_mode': 'mode_2', 'difficulty': 'easy', 'target_slot': 'fixture_slot',
        'roles': ['pm_lead','dev_backend'], 'alternatives': ['fixture alternative'],
        'evolution': ['E2','E4'], 'history_evolution': [], 'history_overwrites': 0,
        'obstacles': ['O1','O2','O3'], 'competing_rules': ['candidate_a','candidate_b'],
        'fallback': {'rule': 'fixture fallback', 'source': 'public_document', 'reference': 'fixture.md'},
        'gold': {k: 'fixture_'+k for k in ['rule','key_premise','scope_boundary','dead_end']},
        'external_profiles': {k: {'default': {'available': k != 'C_changed'}, 'routes': []} for k in ['T0_history','A_static','B_irrelevant','C_changed']},
        'facts': [{'id':'f1','role':'pm_lead','unlock_act':1,'text':'first visible fact'},
                  {'id':'f2','role':'dev_backend','unlock_act':2,'text':'SECRET_FUTURE'}],
        'acts': [{'id':1,'min_turns':1,'max_turns':2,'exit_condition':'fact_ids','required_facts':['f1']},
                 {'id':2,'min_turns':1,'max_turns':2,'exit_condition':'fact_ids','required_facts':['f2']}],
        'banned_meta_words': ['gold','benchmark','unlock_act']}
