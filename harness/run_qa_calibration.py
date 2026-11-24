"""Data-driven paired calibration; injected answerer/grader only."""
import math
from pathlib import Path
from .common import read, selector, seeds, seed_paths
from .budget_guard import BudgetExceeded

ANCHORS = ('B0','B1','B2')
CONTEXTS = ('A','B','C')


def score(value):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('score must be finite in [0,1]')
    return value


def check(scores):
    if set(scores) != set(ANCHORS): raise ValueError('missing/extra anchor')
    for row in scores.values():
        if set(row) != set(CONTEXTS): raise ValueError('missing/extra context')
        for value in row.values(): score(value)
    return all(scores['B0'][c] <= 1/3 and scores['B2'][c] >= 2/3 for c in CONTEXTS) and scores['B1']['C'] < scores['B2']['C']


def evaluate(questions, answerer, grader, world, query, contexts):
    if not questions: raise ValueError('empty denominator')
    result = {a: {} for a in ANCHORS}
    for a in ANCHORS:
        for c in CONTEXTS:
            snapshot = world.snapshot({'A':'A_static','B':'B_irrelevant','C':'C_changed'}[c], query)
            values = [score(grader(q, answerer(q, contexts[a], snapshot))) for q in questions]
            result[a][c] = sum(values)/len(values)
    return {'scores': result, 'passed': check(result), 'denominator_per_cell': len(questions)}


# Keep check()/evaluate() above unchanged: Stage 2 still imports their legacy
# contract. Only this Stage 1 path adopts the newly approved frozen thresholds.
def check_stage1(scores):
    check(scores)  # validates shape and finite values, independent of pass/fail
    if any(v not in (0, 1/3, 2/3, 1) for row in scores.values() for v in row.values()):
        raise ValueError('Stage 1 cell rate must derive from exactly 3 runs')
    from fractions import Fraction
    # Rates derive from three runs; rational comparison avoids 1 - 1/3 drift.
    f = lambda value: Fraction(value).limit_denominator(1000000)
    return (all(f(scores['B0'][c]) <= Fraction(1,3) and f(scores['B2'][c]) >= Fraction(2,3) for c in CONTEXTS)
            and all(f(scores['B1'][c]) >= Fraction(2,3) for c in ('A','B'))
            and f(scores['B1']['C']) + Fraction(1,3) <= f(scores['B2']['C']))


def stage1_config(path=None):
    from pathlib import Path
    return read(path or Path(__file__).with_name('config.yaml'))


def make_prompt(seed, anchor, context):
    import json
    from ..docker.external_world_service.app import World
    qa = seed['qa']
    snapshot = World(seed['external_profiles']).snapshot(
        {'A':'A_static','B':'B_irrelevant','C':'C_changed'}[context], qa.get('query', {}))
    # Whitelist only. Never serialize seed/gold/expected/axis labels/future facts.
    payload = {'instruction':'依据公开说明、团队记录和当前观测回答；团队记录可能不完整或过时。仅输出指定 JSON，不要解释。',
               'public_policy':seed['public_policy'], 'data_schema':seed['data_schema'],
               'team_record':qa['anchor_contexts'][anchor], 'current_snapshot':snapshot,
               'turn_1':qa['dialogues'][context]['turn_1'], 'turn_2':qa['dialogues'][context]['turn_2'],
               'output_schema':qa['output_schema']}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_exact(text, schema):
    import json
    # Accept exactly the schema, no markdown stripping, extra keys or coercion.
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result: raise ValueError('duplicate JSON key')
            result[k] = v
        return result
    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != set(schema): raise ValueError('wrong output fields')
    for key, kind in schema.items():
        if kind != 'unique_string_list' or not isinstance(value[key], list) or any(type(v) is not str for v in value[key]):
            raise ValueError('wrong output type')
        if len(set(value[key])) != len(value[key]): raise ValueError('duplicate output identifier')
        value[key] = sorted(value[key])  # identity set, order is not scored
    return value


def calibrate_stage1(seed, provider, tokenizer, guard, *, config=None, output=None, dataset_root=None):
    """27 budgeted answers. Env failures abort without inventing score zeros."""
    import hashlib
    import json
    from .common import write
    from .stage1_errors import EnvError
    cfg = (config or stage1_config())['stage1']
    if cfg['repeats'] != 3: raise ValueError('frozen denominator requires exactly 3 repeats')
    records, scores = [], {a:{} for a in ANCHORS}
    report = {'case_id':seed['id'], 'stage':1, 'scope':'QA preliminary screen; no repository evidence',
              'provider_type':type(provider).__name__, 'provider_model':getattr(provider, 'model', None),
              'request_config':dict(cfg),
              'records':records, 'scores':scores, 'denominator_per_cell':3, 'passed':False,
              'complete':False, 'usage_tokens':0, 'budget_accounted_tokens':guard.spent,
              'policy_hash':hashlib.sha256(json.dumps(seed['public_policy'], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              'seed_hash':hashlib.sha256(json.dumps(seed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    report['schema_hash'] = hashlib.sha256(json.dumps(seed['data_schema'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    from pathlib import Path
    report['watched_hashes'] = {p:(hashlib.sha256((Path(dataset_root)/p).read_bytes()).hexdigest()
        if dataset_root is not None and (Path(dataset_root)/p).is_file() else None) for p in seed.get('watched_files', [])}
    report['watched_hash_note'] = 'null means not materialized; Stage 2 dependency scheduling is deferred'
    def save():
        report['budget_accounted_tokens'] = guard.spent
        report['outcomes'] = {k:sum(r['outcome'] == k for r in records) for k in ('pass','model_wrong','parse_error','env_error')}
        if output is not None: write(output, report)
    try:
        for anchor in ANCHORS:
            for context in CONTEXTS:
                prompt = make_prompt(seed, anchor, context)
                expected = parse_exact(json.dumps(seed['qa']['expected'][context]), seed['qa']['output_schema'])
                cell = []
                for repeat in range(3):
                    row = {'anchor':anchor,'context':context,'repeat':repeat+1,'prompt':prompt,'expected':expected}
                    measured = {}
                    def tracked(text, *, max_output):
                        result = provider(text, max_output=max_output)
                        measured.update(result)
                        return result
                    try:
                        raw = guard.call(tracked, prompt, tokenizer=tokenizer, max_output=cfg['max_output_tokens'],
                                         prompt_overhead=cfg['prompt_overhead_tokens'], truncate=False)
                    except EnvError as exc:
                        row.update(outcome='env_error', error=str(exc), raw_answer=None)
                        records.append(row); save()
                        raise
                    except BudgetExceeded as exc:
                        row.update(outcome='env_error', error=str(exc), raw_answer=measured.get('text'), stop_reason='budget_guard')
                        if type(measured.get('usage_tokens')) is int:
                            row['usage_tokens'] = measured['usage_tokens']
                            report['usage_tokens'] += measured['usage_tokens']
                        records.append(row)
                        raise
                    row.update(raw_answer=raw, usage_tokens=measured['usage_tokens'])
                    for k in ('input_tokens','output_tokens','response_id','response_status'):
                        if k in measured: row[k] = measured[k]
                    report['usage_tokens'] += measured['usage_tokens']
                    try:
                        answer = parse_exact(raw, seed['qa']['output_schema'])
                        row.update(parsed=answer, outcome='pass' if answer == expected else 'model_wrong')
                    except (ValueError, TypeError): row.update(outcome='parse_error')
                    cell.append(int(row['outcome'] == 'pass'))
                    records.append(row); save()
                scores[anchor][context] = sum(cell)/3
        report.update(complete=True, passed=check_stage1(scores))
        return report
    finally:
        save()


def main():
    from .common import write
    from .validate_seed import validate_dataset
    from .budget_guard import BudgetGuard
    from .stage1_provider import OpenAIChatProvider, Utf8BoundTokenizer
    from .factory import Factory, Stage1Runner
    p = selector(__doc__)
    p.add_argument('--execute-stage1', action='store_true', help='explicitly permit real provider calls')
    p.add_argument('--config', type=Path)
    args = p.parse_args()
    selected = seeds(args)
    errors = validate_dataset([read(f) for f in seed_paths(args.dataset)])
    if errors: raise SystemExit('\n'.join(errors))
    config = stage1_config(args.config)
    for seed in selected:
        base = args.dataset/'cases'/seed['id']
        if not args.execute_stage1:
            result = read(base/'qa_calibration.json')
            if not result.get('complete') or not check_stage1(result['scores']): raise SystemExit('Stage 1 QA failed/incomplete')
            print(seed['id'], 'Stage 1 artifact checked; no model called')
            continue
        path = base/'factory_state.json'
        factory = Factory(read(path) if path.exists() else None, case_id=seed['id'])
        guard = BudgetGuard(config['stage_token_limits']['1'], enabled=True,
                            spent=factory.state.get('stage1_budget_accounted_tokens',0), input_cap=config['stage1']['max_input_tokens'])
        runner = Stage1Runner(seed, guard, base/'qa_calibration.json', config=config, dataset_root=args.dataset)
        try: factory.run_stage1(runner, infrastructure_retries=config['stage1']['infrastructure_retries'])
        finally: write(path, factory.state)
        print(seed['id'], factory.state['status'])


if __name__ == '__main__': main()
