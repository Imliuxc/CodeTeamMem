"""Zero-token structural validation. Semantic claims still require calibration."""
from .common import read, selector, seeds, seed_paths
from ..docker.external_world_service.app import check_profiles

SCENARIOS = {'fe_be_coordination', 'feature_evolution', 'cross_role_debugging', 'task_handoff', 'agent_onboarding'}
DIMENSIONS = {'cross_role_contract', 'unwritten_business_constraint', 'architectural_rationale', 'procedural_debugging_reuse', 'dynamic_knowledge_supersession'}
ROLES = {'pm_lead', 'dev_backend', 'dev_frontend', 'dev_infra_ops', 'qa_engineer'}
GOLD = ('rule', 'key_premise', 'scope_boundary', 'dead_end')


def _validate(seed):
    errors = []
    def need(ok, message):
        if not ok: errors.append(message)
    need(bool(seed.get('id')), 'id required')
    need(seed.get('scenario') in SCENARIOS, 'unknown scenario')
    need(seed.get('dimension') in DIMENSIONS, 'unknown dimension')
    mode = seed.get('code_mode') or ('mode_1' if seed.get('scenario') == 'agent_onboarding' else 'mode_2')
    need(mode in {'mode_1', 'mode_2'}, 'unknown code mode')
    need(not (seed.get('scenario') == 'task_handoff' and mode != 'mode_2'), 'S4 requires mode_2')
    evolution, history, obstacles = (seed.get(k, []) for k in ('evolution', 'history_evolution', 'obstacles'))
    need(set(evolution) <= {'E1','E2','E3','E4'} and len(set(evolution)) == len(evolution), 'invalid evolution')
    need(set(history) <= {'E1','E2','E3','E4'}, 'invalid history evolution')
    need(not (mode == 'mode_1' and 'E1' in history), 'mode_1 conflicts with historical E1')
    need(set(obstacles) <= {'O1','O2','O3','O4','O5'} and len(set(obstacles)) == len(obstacles), 'invalid obstacles')
    level = seed.get('difficulty')
    need(level in {'easy','medium','hard'}, 'unknown difficulty')
    main = set(evolution) - {'E4'}
    need('E4' in evolution and bool(main), 'main evolution plus E4 required')
    if level in {'easy','medium'}:
        need(len(main) == 1, 'composite evolution requires hard')
        need(len(obstacles) <= (3 if level == 'easy' else 4), 'obstacle cap exceeded')
    need(1 <= len(seed.get('competing_rules', [])) <= 3, 'competing rules must be 1..3')
    need(bool(seed.get('target_slot')), 'target_slot required')
    need(bool(seed.get('alternatives')), 'reasonable alternative required')
    roles = seed.get('roles', [])
    need(set(roles) <= ROLES and len(set(roles)) == len(roles) and len(roles) >= 2 and 'pm_lead' in roles, 'invalid role pool or missing authority')
    need(all(seed.get('gold', {}).get(k) for k in GOLD), 'four gold fields required')
    overwrites = seed.get('history_overwrites', 0)
    need(isinstance(overwrites, int) and overwrites >= 0, 'invalid overwrite count')
    if isinstance(overwrites, int):
        need((overwrites >= 2) == (seed.get('dimension') == 'dynamic_knowledge_supersession'), 'dimension/history boundary conflict')
    if {'E2','E3'} & (set(evolution) | set(history)):
        f = seed.get('fallback') or {}
        need(bool(f.get('rule')) and f.get('source') in {'public_document','new_environment'} and bool(f.get('reference')), 'explicit public/environment fallback required')
    acts = seed.get('acts', [])
    need(bool(acts) and [a.get('id') for a in acts] == list(range(1, len(acts)+1)), 'acts must be consecutive from 1')
    fact_ids = [f.get('id') for f in seed.get('facts', [])]
    need(bool(fact_ids) and len(set(fact_ids)) == len(fact_ids), 'facts required with unique ids')
    for fact in seed.get('facts', []):
        need(fact.get('role') in roles and bool(fact.get('text')) and type(fact.get('unlock_act')) is int and 1 <= fact['unlock_act'] <= len(acts), 'invalid fact')
    for act in acts:
        need(type(act.get('min_turns')) is int and type(act.get('max_turns')) is int and 1 <= act['min_turns'] <= act['max_turns'], 'invalid turn bounds')
        need(act.get('exit_condition') == 'fact_ids' and bool(act.get('required_facts')), 'explicit exit_condition required')
        available = {f.get('id') for f in seed.get('facts', []) if type(f.get('unlock_act')) is int and f['unlock_act'] <= act.get('id', 0)}
        need(set(act.get('required_facts', [])) <= available, 'exit requires locked/unknown fact')
    try: check_profiles(seed.get('external_profiles', {}))
    except (ValueError, KeyError, TypeError) as exc: errors.append(str(exc))
    partition=seed.get('entity_partition',{})
    if partition.get('require_disjoint'):
        fields=set(partition.get('id_fields',[]))
        need(bool(fields),'entity id_fields required')
        def entity_ids(value):
            found=set()
            if isinstance(value,dict):
                for k,v in value.items():
                    if k in fields and isinstance(v,str):found.add(v)
                    found.update(entity_ids(v))
            elif isinstance(value,list):
                for v in value:found.update(entity_ids(v))
            return found
        profiles=seed.get('external_profiles',{})
        historical=entity_ids(profiles.get('T0_history',{}))
        need(bool(historical),'history entities required')
        for context in ('A_static','B_irrelevant','C_changed'):
            evaluated=entity_ids(profiles.get(context,{}))
            need(bool(evaluated) and not historical & evaluated,'history/evaluation entity overlap or missing entities')
    if 'qa' in seed:
        import re
        qa = seed['qa']
        need(bool(seed.get('public_policy')) and bool(seed.get('data_schema')), 'Stage 1 public policy/schema required')
        need(set(qa['anchor_contexts']) == {'B0','B1','B2'} and qa['anchor_contexts']['B0'] == '', 'B0 must have no team memory')
        need(bool(qa['anchor_contexts']['B1']) and bool(qa['anchor_contexts']['B2']), 'B1/B2 team contexts required')
        need(set(qa['dialogues']) == {'A','B','C'} and set(qa['expected']) == {'A','B','C'}, 'A/B/C QA coverage required')
        need(len({qa['dialogues'][c]['turn_1'] for c in 'ABC'}) == 1, 'Turn 1 must be identical')
        need(len({qa['dialogues'][c]['turn_2'] for c in 'ABC'}) == 1, 'neutral Turn 2 must be identical')
        for c in 'ABC':
            text = qa['dialogues'][c]['turn_1'] + qa['dialogues'][c]['turn_2']
            need(bool(text.strip()) and not re.search(r'gold|B[012]|E[1-4]|O[1-5]|unlock_act', text), 'QA instruction contains meta leakage')
        from .run_qa_calibration import parse_exact
        import json
        need(bool(qa['output_schema']), 'output schema required')
        for value in qa['expected'].values(): parse_exact(json.dumps(value), qa['output_schema'])
        paths = seed.get('watched_files', [])
        need(bool(paths) and len(set(paths)) == len(paths), 'watched_files required and unique')
        from pathlib import PurePosixPath
        need(all(not PurePosixPath(p).is_absolute() and '..' not in PurePosixPath(p).parts for p in paths), 'unsafe watched_files path')
    return errors


def validate(seed):
    try:
        return _validate(seed)
    except (TypeError, KeyError, AttributeError, ValueError) as exc:
        return [f'invalid seed structure: {exc}']


def validate_dataset(items):
    errors, slots, ids = [], set(), set()
    for s in items:
        errors.extend(f"{s.get('id')}: {e}" for e in validate(s))
        if s.get('target_slot') in slots: errors.append('duplicate target_slot')
        if s.get('id') in ids: errors.append('duplicate id')
        slots.add(s.get('target_slot')); ids.add(s.get('id'))
    return errors


if __name__ == '__main__':
    args = selector(__doc__).parse_args()
    selected = seeds(args)
    errors = validate_dataset([read(p) for p in seed_paths(args.dataset)])
    if errors: raise SystemExit('\n'.join(errors))
    print(f'Validated {len(selected)} selected seeds; dataset slots checked')
