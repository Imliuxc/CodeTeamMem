"""Sequential four-stage controller; providers must be wired explicitly in Python."""
from copy import deepcopy
from pathlib import Path
from .common import read, write, selector, seeds, seed_paths
from .validate_seed import validate_dataset
from .run_qa_calibration import check
from .run_coding_calibration import check_evidence
from .act_stream_builder import build, verify
from .merge_dataset_stream import load_stream, save_stream, merge
from .run_memory_benchmark import summarize
from .stage1_errors import EnvError, CalibrationFailed
from .budget_guard import BudgetExceeded


class CircuitOpen(RuntimeError): pass


class Factory:
    def __init__(self, state=None, *, on_event=None, case_id=None):
        self.on_event = on_event or (lambda event: None)
        self.state = deepcopy(state) if state else {'stage': 0, 'status': 'READY', 'failures': {}, 'gate': False}
        if case_id and self.state.get('case_id') not in (None, case_id):
            raise ValueError('state belongs to a different case')
        self.case_id = case_id or self.state.get('case_id') or 'unbound'
        self.state['case_id'] = self.case_id

    def advance(self, stage, runner, *, mode='supervised', approve=False):
        s = self.state
        if mode not in {'auto', 'supervised'}: raise ValueError('unknown mode')
        if s['status'] in {'CIRCUIT_OPEN','NEEDS_HUMAN'}: raise CircuitOpen('Stop patching; propose simplifying this stage')
        if stage != s['stage'] + 1 or stage not in range(1,5): raise ValueError('stages must run in order')
        if s['gate'] and not approve: raise ValueError('Gate requires explicit --approve')
        self.on_event({'kind': 'stage_started', 'stage': stage})
        try:
            result = runner(stage)
            if result is not True: raise ValueError('stage did not explicitly pass')
        except Exception as exc:
            if stage in (1, 2):
                counter = self._stage_counter(stage)
                if isinstance(exc, EnvError):
                    counter['env_error'] += 1
                    s['status'] = 'ENV_RETRY'
                    s['error'] = str(exc)
                    self.on_event({'kind':'stage_failed', 'stage':stage, 'state':deepcopy(s)})
                    raise
                if isinstance(exc, BudgetExceeded):
                    s.update(status='NEEDS_HUMAN', error=str(exc))
                    raise
                category = getattr(exc, 'category', 'model_wrong')
                counter['attempts'] += 1
                counter[category] += 1
            key = str(stage)
            s['failures'][key] = s['failures'].get(key, 0) + 1
            s['status'] = 'CIRCUIT_OPEN' if s['failures'][key] >= 2 else 'FAILED'
            s['error'] = str(exc)
            self.on_event({'kind': 'stage_failed', 'stage': stage, 'state': deepcopy(s)})
            if s['status'] == 'CIRCUIT_OPEN':
                s['proposal'] = 'Stop patching; simplify recipe or stage implementation before a reviewed restart.'
                raise CircuitOpen(s['proposal']) from exc
            raise
        s['stage'], s['gate'] = stage, mode == 'supervised'
        s['status'] = 'COMPLETE' if stage == 4 else 'LOCKED' if stage == 3 else 'GATE' if s['gate'] else 'READY'
        s.pop('error', None)
        self.on_event({'kind': 'stage_completed', 'stage': stage, 'state': deepcopy(s)})
        return deepcopy(s)

    def _stage1_counter(self):
        return self._stage_counter(1)

    def _stage_counter(self, stage):
        return self.state.setdefault('attempts', {}).setdefault(self.case_id, {}).setdefault(str(stage),
            {'attempts':0, 'model_wrong':0, 'parse_error':0, 'env_error':0})

    def run_stage2(self, runner, *, approve=False, mode='supervised', infrastructure_retries=2):
        if self.case_id == 'unbound': raise ValueError('Stage 2 requires a bound case_id')
        if infrastructure_retries != 2: raise ValueError('infrastructure retries are frozen at 2')
        counter = self._stage_counter(2)
        while True:
            try:
                return self.advance(2, runner, mode=mode, approve=approve)
            except EnvError:
                if counter['env_error'] >= 1 + infrastructure_retries:
                    self.state.update(status='NEEDS_HUMAN',proposal='Restore Stage 2 infrastructure before a reviewed restart.')
                    raise CircuitOpen(self.state['proposal']) from None
            finally:
                guard = getattr(runner, 'guard', None)
                if guard is not None: self.state['stage2_budget_accounted_tokens'] = guard.spent

    def run_stage1(self, runner, *, mode='supervised', infrastructure_retries=2):
        if self.case_id == 'unbound': raise ValueError('Stage 1 requires a bound case_id')
        if infrastructure_retries != 2: raise ValueError('infrastructure retries are frozen at 2')
        counter = self._stage1_counter()
        while True:
            try:
                return self.advance(1, runner, mode=mode)
            except EnvError:
                # At most 2 retries after the initial request; persists on resume.
                if counter['env_error'] >= 1 + infrastructure_retries:
                    self.state['status'] = 'NEEDS_HUMAN'
                    self.state['proposal'] = 'Restore infrastructure before a reviewed restart.'
                    raise CircuitOpen(self.state['proposal']) from None
            finally:
                guard = getattr(runner, 'guard', None)
                if guard is not None: self.state['stage1_budget_accounted_tokens'] = guard.spent


class Stage1Runner:
    """Only Stage 1 generates results; stages 2–4 retain artifact runners."""
    def __init__(self, seed, guard, output, *, config=None, provider=None, tokenizer=None, dataset_root=None):
        from .run_qa_calibration import stage1_config
        self.seed, self.guard, self.output = seed, guard, output
        self.config = config or stage1_config()
        self.provider, self.tokenizer = provider, tokenizer
        self.dataset_root = dataset_root
        self.invocations = 0

    def __call__(self, stage):
        if stage != 1: raise ValueError('Stage1Runner cannot execute another stage')
        if 'qa' not in self.seed: raise ValueError('Stage 1 execution requires a QA recipe')
        from .run_qa_calibration import calibrate_stage1
        from .stage1_provider import OpenAIChatProvider, Utf8BoundTokenizer
        if self.provider is None:
            self.provider = OpenAIChatProvider.from_env(enabled=self.guard.enabled,
                temperature=self.config['stage1']['temperature'])
        self.invocations += 1
        # Preserve every run, including partial infrastructure failures.
        from pathlib import Path
        history = Path(self.output).with_name(Path(self.output).stem + '_runs')
        history.mkdir(parents=True, exist_ok=True)
        index = len(list(history.glob('*.json'))) + 1
        try:
            result = calibrate_stage1(self.seed, self.provider, self.tokenizer or Utf8BoundTokenizer(),
                self.guard, config=self.config, output=history/f'{index:04d}.json', dataset_root=self.dataset_root)
        finally:
            if (history/f'{index:04d}.json').exists():
                write(self.output, read(history/f'{index:04d}.json'))
        if not result['passed']:
            category = 'parse_error' if result['outcomes']['parse_error'] else 'model_wrong'
            raise CalibrationFailed('Stage 1 QA threshold gate failed', category)
        return True


def artifact_runner(dataset, seed):
    base = dataset/'cases'/seed['id']
    def run(stage):
        if stage == 1:
            from .run_qa_calibration import check_stage1
            result = read(base/'qa_calibration.json')
            checker = check_stage1 if 'qa' in seed else check  # legacy technical replays only
            if 'qa' in seed and not result.get('complete'): raise ValueError('incomplete Stage 1 artifact')
            if not checker(result['scores']): raise ValueError('QA anchor gate failed')
        elif stage == 2:
            check_evidence(read(base/'coding_evidence.json'))
            result = read(base/'coding_calibration.json')
            if 'qa' in seed:
                from .run_qa_calibration import check_stage1
                if not result.get('complete') or not check_stage1(result['scores']): raise ValueError('Coding anchor gate failed')
            elif not check(result['scores']): raise ValueError('Coding anchor gate failed')
        elif stage == 3:
            rows = load_stream(base/'raw_stream.jsonl')
            symbols = read(base/'symbol_manifest.json')['symbols']
            turns = iter(r for r in rows if r['kind'] == 'dialogue')
            def replay(view):
                row = next(turns)
                if row['act'] != view['act']: raise ValueError('act timeline mismatch')
                return row
            rebuilt = build(seed, symbols, replay)
            if len(rebuilt) != sum(r['kind'] == 'dialogue' for r in rows): raise ValueError('extra dialogue after exit')
            # Verify evidence timeline by reweaving only recognized event kinds.
            events = [r for r in rows if r['kind'] != 'dialogue']
            replay_turns = iter(r for r in rows if r['kind'] == 'dialogue')
            rebuilt = build(seed, symbols, lambda view: next(replay_turns), events)
            if rebuilt != rows: raise ValueError('stream sequence/evidence mismatch')
            evidence = read(base/'stream_verification.json')
            verify(rows, symbols, seed.get('banned_meta_words', []), evidence['role_scores'], evidence['full_score'], seed['roles'])
        elif stage == 4:
            metrics = summarize(read(base/'benchmark_records.json'))
            save_stream(base/'merged_stream.jsonl', merge([dict(seed, status='LOCKED', stream=load_stream(base/'raw_stream.jsonl'))]))
            write(base/'benchmark_metrics.json', metrics)
        return True
    return run


def main():
    p = selector(__doc__)
    p.add_argument('--mode', choices=['supervised','auto'], default='supervised')
    p.add_argument('--stage', type=int, choices=range(1,5))
    p.add_argument('--approve', action='store_true', help='approve the previous supervised Gate')
    p.add_argument('--execute-stage1', action='store_true', help='explicit opt-in for real Stage 1 calls only')
    p.add_argument('--config', type=Path)
    args = p.parse_args()
    if args.execute_stage1 and args.stage != 1:
        raise SystemExit('--execute-stage1 requires --stage 1; never starts stages 2–4')
    selected = seeds(args)
    errors = validate_dataset([read(f) for f in seed_paths(args.dataset)])
    if errors: raise SystemExit('\n'.join(errors))
    for seed in selected:
        path = args.dataset/'cases'/seed['id']/'factory_state.json'
        factory = Factory(read(path) if path.exists() else None, case_id=seed['id'])
        try:
            if args.execute_stage1:
                from .run_qa_calibration import stage1_config
                from .budget_guard import BudgetGuard
                config = stage1_config(args.config)
                guard = BudgetGuard(config['stage_token_limits']['1'], enabled=True,
                    spent=factory.state.get('stage1_budget_accounted_tokens',0), input_cap=config['stage1']['max_input_tokens'])
                runner = Stage1Runner(seed, guard, path.with_name('qa_calibration.json'), config=config, dataset_root=args.dataset)
                factory.run_stage1(runner, mode=args.mode, infrastructure_retries=config['stage1']['infrastructure_retries'])
                write(path, factory.state)
                print(f"{seed['id']}: stage 1 {factory.state['status']}")
                continue
            while factory.state['stage'] < 4:
                stage = args.stage or factory.state['stage'] + 1
                factory.advance(stage, artifact_runner(args.dataset, seed), mode=args.mode, approve=args.approve)
                write(path, factory.state)
                print(f"{seed['id']}: stage {stage} {factory.state['status']}")
                if args.stage or args.mode == 'supervised': break
        except Exception as exc:
            write(path, factory.state)
            raise SystemExit(f"{seed['id']}: {factory.state['status']}: {exc}")


if __name__ == '__main__': main()
