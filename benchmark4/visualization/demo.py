"""Synthetic technical fixture; never a business case or measured model result."""
from copy import deepcopy


def fixture():
    return {
        'id': 'technical_demo', 'roles': ['pm_lead', 'dev_backend'],
        'facts': [
            {'id':'f1','role':'pm_lead','unlock_act':1,'text':'第一幕的技术占位事实。'},
            {'id':'f2','role':'dev_backend','unlock_act':2,'text':'第二幕才可见的技术占位事实。'}],
        'acts': [
            {'id':1,'min_turns':2,'max_turns':3,'exit_condition':'fact_ids','required_facts':['f1']},
            {'id':2,'min_turns':2,'max_turns':3,'exit_condition':'fact_ids','required_facts':['f2']}],
        'banned_meta_words':['gold','benchmark','unlock_act'],
    }


def generate(view):
    fact = view['facts'][-1]
    return {'role':fact['role'], 'fact_ids':[fact['id']], 'text':fact['text']}


def verification(seed):
    return {'role_scores':dict.fromkeys(seed['roles'],0), 'full_score':1}
