"""Conversation-side commands and the single-command controller. No model/Docker imports."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from . import demo
from .store import Store
from ..harness.common import read, write, seeds
from ..harness.factory import Factory, artifact_runner
from ..harness.act_stream_builder import ActStreamSession, interleave, verify
from ..harness.merge_dataset_stream import load_stream, save_stream, merge
from ..harness.run_memory_benchmark import summarize
from ..harness.validate_seed import validate_dataset
from ..harness.budget_guard import pages


class Conflict(ValueError): pass


def initial():
    return {'status':'READY', 'completed_stage':0, 'active_stage':None, 'gate':False,
            'failures':{}, 'revision':0, 'progress':None, 'dialogue':[], 'facts':[],
            'results':{}, 'error':None, '_factory':Factory().state, '_session':None,
            '_input_hash':None, '_attempts':{}}


class Controller:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()

    def command(self, action, **args):
        if not self.lock.acquire(blocking=False): raise Conflict('Service busy; command was not queued')
        try:
            if action == 'create': return self.create(**args)
            if action not in {'step','approve','retry'}: raise ValueError('unknown control command')
            return self.change(action, **args)
        finally: self.lock.release()

    def create(self, *, demo_mode=False, dataset=None, case=None, all_cases=False, fail_stage=None):
        if demo_mode:
            if dataset or case or all_cases: raise ValueError('demo and dataset selectors are exclusive')
            if fail_stage is not None and fail_stage not in range(1,5): raise ValueError('invalid injected stage')
            selected = [demo.fixture()]
            config = {'demo':True, 'fail_stage':fail_stage, 'seeds':selected}
            source = 'mock'
        else:
            if fail_stage is not None: raise ValueError('failure injection is demo-only')
            if not dataset or bool(case) == bool(all_cases): raise ValueError('dataset needs --case OR --all')
            path = Path(dataset).resolve()
            if path == self.store.root or self.store.root.is_relative_to(path):
                raise ValueError('runtime directory must be outside the input dataset')
            selected = seeds(argparse.Namespace(dataset=path, case=case, all=all_cases))
            config = {'demo':False, 'dataset':str(path), 'seeds':selected,
                      'all_seeds':[read(p) for p in sorted((path/'seeds').glob('*.yaml'))]}
            source = 'artifact'
        run = self.store.create(source, config, {s['id']:initial() for s in selected})
        return self.store.view(run)

    def change(self, action, *, run, case=None, expected_revision=None):
        view = self.store.view(run)
        if case is None:
            if len(view['cases']) != 1: raise ValueError('multi-case run requires explicit --case')
            case = view['cases'][0]['id']
        state = self.store.state(run, case)
        if expected_revision is None or expected_revision != state['revision']:
            raise Conflict('stale revision; refresh status before controlling')
        if state['status'] == 'CIRCUIT_OPEN': raise Conflict('Circuit open; stop patching and simplify the stage')
        if action == 'approve':
            if not state['gate']: raise Conflict('no Gate awaiting approval')
            state['gate'] = state['_factory']['gate'] = False
            state['status'] = 'LOCKED' if state['completed_stage'] == 3 else 'READY'
            state['revision'] += 1
            self.store.save(run, case, state, 'gate_approved')
        elif action == 'retry':
            if state['status'] not in {'FAILED','INTERRUPTED'}: raise Conflict('only a failed/interrupted stage can retry')
            state.update(status='READY', error=None)
            if state['active_stage'] == 3:
                state.update(_session=None, _input_hash=None, progress=None, dialogue=[], facts=[])
            state['revision'] += 1
            self.store.save(run, case, state, 'retry_prepared', {'stage':state['active_stage']})
        else:
            if state['gate']: raise Conflict('approve Gate first; approval does not execute the next stage')
            if state['status'] not in {'READY','WAITING_STEP','LOCKED'}: raise Conflict('stage is not ready for step')
            if state['completed_stage'] == 4: raise Conflict('run complete')
            config = self.store.config(run)
            seed = next(s for s in config['seeds'] if s['id'] == case)
            self.step(run, case, config, seed, state)
        return self.store.view(run)

    def step(self, run, case, config, seed, state):
        stage = state['completed_stage'] + 1
        continuing = state['status'] == 'WAITING_STEP'
        state.update(status='RUNNING', active_stage=stage, error=None)
        state['revision'] += 1
        if not continuing:
            key = str(stage)
            state['_attempts'][key] = state['_attempts'].get(key,0)+1
        self.store.save(run, case, state, 'turn_started' if continuing else 'stage_started', {'stage':stage, 'attempt':state['_attempts'][str(stage)]})
        factory = Factory(state['_factory'])
        try:
            if config['demo'] and config['fail_stage'] == stage: raise ValueError('Explicit Mock failure injection')
            if stage == 3:
                done = self.stream_step(run, case, config, seed, state)
                if not done:
                    state['status'] = 'WAITING_STEP'
                    self.store.save(run, case, state, 'waiting_step', {'stage':3})
                    return
            elif config['demo']:
                state['results'][str(stage)] = {'source':'mock', 'summary':'离线技术夹具通过；不是模型测量结果。'}
            elif stage in {1,2}:
                if stage == 1:
                    errors = validate_dataset(config['all_seeds'])
                    if errors: raise ValueError('; '.join(errors))
                artifact_runner(Path(config['dataset']), seed)(stage)
                state['results'][str(stage)] = {'source':'artifact', 'summary':'已有产物结构与门槛校验通过；未独立重跑实验。'}
            elif stage == 4:
                base = Path(config['dataset'])/'cases'/case
                metrics = summarize(read(base/'benchmark_records.json'))
                output = self.store.root/'runs'/run/case
                output.mkdir(parents=True, exist_ok=True)
                # Use the verified frozen stream, not a potentially changed source file.
                rows = state['_verified_stream']
                save_stream(output/'merged_stream.jsonl', merge([dict(seed,status='LOCKED',stream=rows)]))
                write(output/'benchmark_metrics.json', metrics)
                state['results']['4'] = {'source':'artifact', 'summary':'已有记录指标汇总完成；非独立实测。', 'metrics':metrics}
            factory.advance(stage, lambda _: True, mode='supervised')
            state.update(completed_stage=stage, active_stage=None, gate=stage < 4,
                         status='COMPLETE' if stage == 4 else 'LOCKED' if stage == 3 else 'GATE')
            if stage == 4: factory.state['gate'] = False
            state['_factory'] = factory.state
            self.store.save(run, case, state, 'stage_completed', {'stage':stage, 'gate':state['gate']})
        except Exception as exc:
            def failure(_): raise exc
            try: factory.advance(stage, failure, mode='supervised')
            except Exception: pass
            state['_factory'] = factory.state
            state.update(status=factory.state['status'], failures=deepcopy(factory.state['failures']), error=str(exc), gate=False)
            # Errors are operator-visible; never serialize input seed or future dialogue.
            self.store.save(run, case, state, 'circuit_open' if state['status'] == 'CIRCUIT_OPEN' else 'stage_failed',
                            {'stage':stage, 'error':str(exc), 'proposal':factory.state.get('proposal')})

    def stream_step(self, run, case, config, seed, state):
        rows, events, symbols = None, [], []
        if not config['demo']:
            base = Path(config['dataset'])/'cases'/case
            # Hash before parsing, so changed future text is never surfaced on resume.
            inputs = [base/'raw_stream.jsonl', base/'symbol_manifest.json', base/'stream_verification.json']
            digest = hashlib.sha256(b'\0'.join(p.read_bytes() for p in inputs)).hexdigest()
            if state['_input_hash'] and state['_input_hash'] != digest:
                raise ValueError('Stage 3 artifacts changed; explicit retry must restart stage')
            state['_input_hash'] = digest
            rows = load_stream(inputs[0]); symbols = read(inputs[1])['symbols']
            turns = [r for r in rows if r['kind'] == 'dialogue']
            events = [r for r in rows if r['kind'] != 'dialogue']
        session = ActStreamSession(seed, symbols, snapshot=state['_session'])
        current_act = session.machine.act['id']
        visible = session.ledger.view(current_act)
        round_in_act = session.machine.turns + 1
        index = len(session.stream)
        if config['demo']: generate = demo.generate
        else:
            def generate(view):
                if index >= len(turns): raise ValueError('stream ended before exit condition')
                return turns[index]
        def emit_evidence(at_turn):
            for event in events:
                if event.get('after_turn') != at_turn: continue
                if event['kind'] not in {'tool_log','git_diff','pytest','pr_review'}: raise ValueError('unknown evidence kind')
                for number, chunk in enumerate(pages(json.dumps(event, ensure_ascii=False))):
                    self.store.save(run, case, state, 'evidence_page', {'kind':event['kind'], 'page':number+1,'text':chunk})
        if index == 0: emit_evidence(0)
        session.step(generate)
        state['_session'] = session.snapshot()
        state['dialogue'] = deepcopy(session.stream)
        state['facts'] = visible
        state['progress'] = dict(session.progress(), last_act=current_act, last_turn=round_in_act)
        self.store.save(run, case, state, 'turn_completed', {'stage':3, 'act':current_act,
            'turn_in_act':round_in_act, 'turn':session.stream[-1], 'done':session.done})
        emit_evidence(index+1)
        if not session.done: return False
        if config['demo']:
            proof = demo.verification(seed)
        else:
            if len(session.stream) != len(turns): raise ValueError('extra dialogue after stream exit')
            rebuilt = interleave(session.stream, events)
            if rebuilt != rows: raise ValueError('stream sequence/evidence mismatch')
            state['_verified_stream'] = rebuilt
            proof = read(base/'stream_verification.json')
        result = verify(session.stream, symbols, seed.get('banned_meta_words',[]), proof['role_scores'],proof['full_score'],seed['roles'])
        state['results']['3'] = {'source':'mock' if config['demo'] else 'artifact',
            'summary':'Mock 验真通过（合成分数）' if config['demo'] else '整段产物校验通过（使用已有盲测分数）', 'verification':result}
        return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', default='http://127.0.0.1:8764')
    commands = p.add_subparsers(dest='action', required=True)
    create = commands.add_parser('create')
    source = create.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true'); source.add_argument('--dataset')
    select = create.add_mutually_exclusive_group()
    select.add_argument('--case'); select.add_argument('--all', action='store_true')
    create.add_argument('--fail-stage', type=int, choices=range(1,5))
    for name in ['step','approve','retry','status']:
        q = commands.add_parser(name)
        q.add_argument('--run', required=name != 'status'); q.add_argument('--case')
    args = p.parse_args()
    # The control channel is local only; browser requests never issue commands.
    from urllib.parse import urlparse
    target = urlparse(args.url)
    if target.scheme != 'http' or target.hostname not in {'127.0.0.1','localhost','::1'}:
        p.error('control URL must be loopback HTTP')
    def request(path, data=None):
        req = Request(args.url.rstrip('/')+path, data=json.dumps(data).encode() if data is not None else None,
                      headers={'Content-Type':'application/json'})
        with urlopen(req, timeout=120) as response: return json.load(response)
    try:
        if args.action == 'status':
            result = request('/api/runs/'+args.run if args.run else '/api/runs')
        else:
            if args.action == 'create':
                payload = {'action':'create', 'demo_mode':args.demo, 'dataset':args.dataset,
                           'case':args.case, 'all_cases':args.all, 'fail_stage':args.fail_stage}
            else:
                view = request('/api/runs/'+args.run)
                choices = [c for c in view['cases'] if args.case is None or c['id'] == args.case]
                if len(choices) != 1: p.error('select one existing Case with --case')
                payload = {'action':args.action, 'run':args.run, 'case':choices[0]['id'], 'expected_revision':choices[0]['revision']}
            result = request('/control',payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except HTTPError as exc:
        raise SystemExit(exc.read().decode())


if __name__ == '__main__': main()
