"""Deterministic round-robin merge; preserve per-case order and provenance."""
import json
from .common import read, selector, seeds


def merge(cases):
    if not cases: raise ValueError('empty dataset')
    if any(c['status'] not in {'LOCKED','COMPLETE'} or not c['stream'] for c in cases):
        raise ValueError('only nonempty LOCKED cases may be merged')
    ids = [c['id'] for c in cases]
    slots = [c['target_slot'] for c in cases]
    if len(set(ids)) != len(ids) or len(set(slots)) != len(slots): raise ValueError('case/slot conflict')
    rows = []
    for index in range(max(len(c['stream']) for c in cases)):
        for case in cases:
            if index < len(case['stream']):
                rows.append(dict(case['stream'][index], case_id=case['id'], source_sequence=index, sequence=len(rows)))
    return rows


def save_stream(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))


def load_stream(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


if __name__ == '__main__':
    args = selector(__doc__).parse_args()
    cases = []
    for seed in seeds(args):
        base = args.dataset/'cases'/seed['id']
        state = read(base/'factory_state.json')
        cases.append(dict(seed, status=state['status'], stream=load_stream(base/'raw_stream.jsonl')))
    save_stream(args.dataset/'merged_stream.jsonl', merge(cases))
