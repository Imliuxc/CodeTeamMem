"""Docker execution seam; no daemon or model is contacted on import."""
import subprocess
from .limits import INPUT_CAP,STALL_LIMIT,EXPLORATION_LIMIT,TRIAL_TOKEN_LIMIT,NO_EDIT_WARN,NO_EDIT_STOP
from pathlib import Path
from .budget_guard import ProgressGuard, pages, BudgetExceeded
from .run_qa_calibration import check, score, ANCHORS, CONTEXTS
from .common import read, selector, seeds


class DockerRunner:
    def __init__(self, image, network='none'):
        self.image, self.network = image, network

    def run(self, repository, command, timeout=120):
        repo = Path(repository).resolve()
        if not repo.is_dir(): raise ValueError('repository missing')
        # No service source/config mounts, host networking, or Docker socket.
        args = ['docker','run','--rm','--network',self.network,'--cap-drop=ALL',
                '--security-opt=no-new-privileges','--memory=1g','--cpus=1',
                '-v',f'{repo}:/home/worker/workspace','-w','/home/worker/workspace',self.image,*command]
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        return {'returncode': result.returncode, 'pages': list(pages((result.stdout+result.stderr).decode(errors='replace')))}


def self_check(runner, positive_repo, negative_repo):
    good = runner.run(positive_repo, ['python','-m','pytest','-q'])
    bad = runner.run(negative_repo, ['python','-m','pytest','-q'])
    # pytest 1 means collected tests failed; collection/runtime failures do not count.
    if good['returncode'] != 0 or bad['returncode'] != 1:
        raise ValueError('positive/negative self-check failed')
    return {'positive': good, 'negative': bad}


def evaluate(run_task):
    scores = {a: {c: score(run_task(a, c, ProgressGuard())) for c in CONTEXTS} for a in ANCHORS}
    return {'scores': scores, 'passed': check(scores)}


def check_evidence(evidence):
    if evidence['positive']['returncode'] != 0 or evidence['negative']['returncode'] != 1:
        raise ValueError('self-check evidence failed')
    frames = evidence['keyframes']
    if [f['name'] for f in frames] != ['T0','T1']:
        raise ValueError('T0 -> T1 required')
    for frame in frames:
        if not all(frame.get(k) for k in ('tool_log','git_diff','pytest')):
            raise ValueError('missing keyframe evidence')


class ToolPager:
    def __init__(self, max_bytes=65536): self.outputs, self.sources, self.max_bytes = {}, {}, max_bytes

    def add(self, result, source=None):
        raw = result.get('text','').encode()
        chunks = list(pages(raw[:self.max_bytes].decode(errors='replace')))
        key = str(len(self.outputs)+1); self.outputs[key] = chunks or ['']
        self.sources[key]=source
        return {'output_id':key, 'page':0, 'page_count':len(self.outputs[key]),
                'content':self.outputs[key][0], 'returncode':result.get('returncode',0),
                'truncated':result.get('truncated',False) or len(raw)>self.max_bytes}

    def get(self, key, page):
        if type(page) is not int or page < 0: raise ValueError('invalid page')
        return {'output_id':key,'page':page,'page_count':len(self.outputs[key]),'content':self.outputs[key][page]}


def semantic_state(repository, writable_paths):
    import ast, hashlib
    states = []
    for relative in writable_paths:
        source = (Path(repository)/relative).read_text()
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                body = getattr(node,'body',None)
                if isinstance(body,list) and body and isinstance(body[0],ast.Expr) and isinstance(body[0].value,ast.Constant) and isinstance(body[0].value.value,str): body.pop(0)
            source = ast.dump(tree, include_attributes=False)
        except SyntaxError: source = '<invalid syntax>'
        states.append((relative,source))
    return hashlib.sha256(repr(states).encode()).hexdigest()


def all_valid_python(repo,paths):
    import ast
    try:
        for p in paths:ast.parse((repo/p).read_text())
        return True
    except SyntaxError:return False


def coding_prompt(header, history, tokenizer, cap=INPUT_CAP, overhead=64):
    import json
    from .coding_protocol import request
    # Drop oldest complete tool exchanges; never split JSON or cut task/memory.
    retained = list(history)
    while True:
        prompt = json.dumps(request(header,retained), ensure_ascii=False)
        if len(tokenizer.encode(prompt))+overhead <= cap: return prompt
        if not retained:
            from .budget_guard import BudgetExceeded
            raise BudgetExceeded('fixed Coding task exceeds input cap')
        retained.pop(0)


class CodingProgress:
    """Novel discovery is not a loop; code-edit starvation is a separate gate."""
    def __init__(self, baseline, stall_limit=STALL_LIMIT, exploration_limit=EXPLORATION_LIMIT,
                 no_edit_warn=NO_EDIT_WARN,no_edit_stop=NO_EDIT_STOP):
        self.states={baseline};self.tests=set();self.discovered=set()
        self.stall_limit=stall_limit;self.exploration_limit=exploration_limit
        self.exploration_used=0;self.stalled=0;self.no_edit=0
        self.no_edit_warn=no_edit_warn;self.no_edit_stop=no_edit_stop;self.last_loop=None
    def observe(self,state,passed_tests,discovery=None,error_key=None,valid_edit=None,is_error=False):
        code_edit=state not in self.states and valid_edit is not False
        novel=discovery is not None and discovery not in self.discovered
        tests_new=bool(set(passed_tests)-self.tests)
        self.states.add(state);self.tests.update(passed_tests)
        if discovery is not None:self.discovered.add(discovery)
        self.no_edit=0 if code_edit else self.no_edit+1
        available=self.exploration_limit is None or self.exploration_used<self.exploration_limit
        if is_error and not code_edit:
            kind='error';self.stalled=self.stalled+1 if error_key==self.last_loop else 1;self.last_loop=error_key
        elif code_edit or tests_new:
            kind='engineering';self.stalled=0;self.last_loop=None
        elif novel and available:
            kind='exploration';self.exploration_used+=1;self.stalled=0;self.last_loop=None
        else:
            kind='none';key=error_key if error_key is not None else discovery
            self.stalled=self.stalled+1 if key==self.last_loop else 1
            self.last_loop=key
        value={'kind':kind,'stalled':self.stalled,'exploration_used':self.exploration_used,
               'no_edit_turns':self.no_edit,'no_edit_warning':self.no_edit>=self.no_edit_warn}
        if self.no_edit>=self.no_edit_stop:raise BudgetExceeded('no valid code edit for configured maximum turns')
        if self.stalled>=self.stall_limit:raise BudgetExceeded('repeated same error/action without improvement')
        return value


def coding_session(seed, task, sandbox, provider, tokenizer, guard, cfg, anchor, context):
    """Model only emits a JSON tool action. No keys/hidden tests enter its Docker."""
    import json
    from .budget_guard import BudgetExceeded
    header = {'instruction':task['instruction'], 'public_policy':seed['public_policy'],
              'data_schema':seed['data_schema'], 'team_record':seed['qa']['anchor_contexts'][anchor],
              'writable_paths':task['writable_paths'],
              'workspace_root':'/home/worker/workspace',
              'workflow':'Continue from the executed tool history. Select one NEXT function call. '
                         'Do not reread unchanged content already returned. All paths are relative to workspace_root. '
                         'write replaces the entire file, not a diff. After editing, run test_base, then finish '
                         'to submit the current files to the hidden judge. No run_cmd tool exists. '
                         'Tool results include progress feedback; fix reported failed public tests rather than resubmitting identical code. '
                         'Examples below use placeholder paths, not actual repository files.',
              'examples':[{'tool':'read','arguments':{'path':'src/example.py'}},
                          {'tool':'write','arguments':{'path':'src/example.py','content':'value = 1\n'}},
                          {'tool':'test_base','arguments':{}},{'tool':'finish','arguments':{}}]}
    if type(cfg['max_turns']) is not int or cfg['max_turns']<1: raise ValueError('positive turn cap required')
    if guard.total_tokens>cfg.get('trial_token_limit',TRIAL_TOKEN_LIMIT):guard=guard.scope(cfg.get('trial_token_limit',TRIAL_TOKEN_LIMIT))
    initial_state=semantic_state(sandbox.repo,task['writable_paths'])
    finish_warned=False; writes=set()
    progress = CodingProgress(initial_state,cfg['stall_limit'],cfg.get('exploration_limit',EXPLORATION_LIMIT),cfg.get('no_edit_warn',NO_EDIT_WARN),cfg.get('no_edit_stop',NO_EDIT_STOP))
    pager, history, log, passed = ToolPager(cfg['tool_max_bytes']), [], [], []
    repo = sandbox.repo
    def safe_path(relative):
        if not isinstance(relative,str) or Path(relative).is_absolute(): raise ValueError('relative path required')
        path = (repo/relative).resolve()
        if not path.is_relative_to(repo): raise ValueError('path escapes workspace')
        return path
    for turn in range(1,cfg['max_turns']+1):
        prompt = coding_prompt(header,history,tokenizer,cfg['max_input_tokens'],cfg['prompt_overhead_tokens'])
        measured = {}
        def tracked(text, *, max_output):
            result = provider(text,max_output=max_output); measured.update(result); return result
        raw = guard.call(tracked,prompt,tokenizer=tokenizer,max_output=cfg['max_output_tokens'],
                         prompt_overhead=cfg['prompt_overhead_tokens'],truncate=False)
        row = {'turn':turn,'prompt':prompt,'raw_answer':raw,'usage_tokens':measured['usage_tokens']}
        for key in ('input_tokens','output_tokens','cached_input_tokens','provider_usage','response_id','response_status','tool_call_id','provider_output','protocol_error'):
            if key in measured: row[key]=measured[key]
        log.append(row)
        try:
            if measured.get('protocol_error'): raise ValueError(measured['protocol_error'])
            action = json.loads(raw)
            name = action['tool']; args = action.get('arguments',{})
            discovery=None;source=None
            if name == 'finish' and not finish_warned and semantic_state(repo,task['writable_paths'])==initial_state:
                finish_warned=True
                feedback={'notice':'No semantic change from the initial baseline. Modify the implementation if required, or submit finish again with an optional reason explaining why no change is needed. The hidden judge still decides correctness.', 'progress':{'remaining_turns':cfg['max_turns']-turn,'remaining_tokens':guard.total_tokens-guard.spent}}
                row['tool_result']=feedback
                history.append({'action':action,'result':feedback,'call_id':measured.get('tool_call_id') or f'offline_call_{turn}'})
                continue
            if name == 'finish':
                imports=task.get('smoke_imports',[])
                if imports:
                    smoke=sandbox.exec(['python','-c',';'.join('import '+m for m in imports)])
                    if smoke['returncode'] in (1,124):
                        return {'outcome':'model_wrong','turns':turn,'log':log,'reason':'candidate import/runtime failure','smoke':smoke}
                    if smoke['returncode']:
                        from .stage1_errors import EnvError
                        raise EnvError('candidate import probe infrastructure failure')
                result = sandbox.judge(task['hidden_tests'],test_name=task['test_files'][context])
                ok = result['returncode']==0 and result['failed']==0 and not result['skipped']
                return {'outcome':'pass' if ok else 'model_wrong','turns':turn,'log':log,'judge':result,'semantic_modified':semantic_state(repo,task['writable_paths'])!=initial_state,'no_change_reason':args.get('reason') if finish_warned else None}
            if name == 'list':
                output = {'text':'\n'.join(str(p.relative_to(repo)) for p in sorted(repo.rglob('*')) if p.is_file())};source=('list',)
            elif name == 'read':
                path=safe_path(args['path']);output = {'text':path.read_text()};source=('read',str(path.relative_to(repo)))
            elif name == 'write':
                if args['path'] not in task['writable_paths']: raise ValueError('file is not writable')
                before_state=semantic_state(repo,task['writable_paths'])
                repeated_write=(args['path'],args['content']) in writes
                writes.add((args['path'],args['content']))
                safe_path(args['path']).write_text(args['content'])
                sandbox.sync_file(args['path'])
                output = {'text':'written','semantic_changed':semantic_state(repo,task['writable_paths'])!=before_state,'repeated_identical_write':repeated_write}
            elif name == 'snapshot':
                output = {'text':json.dumps(sandbox.snapshot(),ensure_ascii=False)};source=('snapshot',)
            elif name == 'test_base':
                result = sandbox.exec(['python','-m','pytest','-q','-p','no:cacheprovider','tests_base'])
                # Use trusted judge's base-node identities for progress, never stdout claims.
                verified = sandbox.judge(task['hidden_tests'],base=True)
                passed = verified['passed_tests']; output = result
            elif name == 'page':
                feedback = pager.get(args['output_id'],args['page']); output = None
                source=pager.sources[args['output_id']]
            else: raise ValueError('unknown tool')
            if output is not None: feedback = pager.add(output,source)
            if source is not None:
                import hashlib
                discovery=(source,feedback['page'],hashlib.sha256(feedback['content'].encode()).hexdigest())
            row['tool_result'] = feedback
            history.append({'action':action,'result':feedback,'call_id':measured.get('tool_call_id') or f'offline_call_{turn}'})
        except (ValueError,TypeError,KeyError,IndexError,OSError) as exc:
            row['error'] = type(exc).__name__
            return {'outcome':'parse_error','turns':turn,'log':log,'reason':'invalid tool action'}
        known_discovery=discovery in progress.discovered if discovery is not None else False
        try:
            row['progress']=progress.observe(semantic_state(repo,task['writable_paths']),passed,discovery,error_key=(name,discovery if discovery is not None else source,semantic_state(repo,task['writable_paths']),tuple(passed)),valid_edit=(name=='write' and all_valid_python(repo,task['writable_paths'])),is_error=(name=='test_base' and output['returncode']!=0))
            feedback['progress']=dict(row['progress'],remaining_turns=cfg['max_turns']-turn,remaining_tokens=guard.total_tokens-guard.spent,remaining_exploration=None if progress.exploration_limit is None else max(0,progress.exploration_limit-progress.exploration_used),remaining_stall=max(0,progress.stall_limit-progress.stalled))
            if discovery is not None:feedback['repeated_observation']=known_discovery
            if row['progress']['no_edit_warning']:feedback['no_edit_notice']='No valid semantic code edit for '+str(progress.no_edit)+' turns. Implement a required change or explicitly submit your no-change rationale; public base tests alone do not establish completion.'
            if name=='write':
                feedback.update(semantic_changed=output['semantic_changed'],repeated_identical_write=output['repeated_identical_write'],written_path=args['path'],written_content_preview=args['content'][:512])
                if not output['semantic_changed']:feedback['notice']='This write did not change the AST (whitespace/comments/docstrings only or identical content). Repeating the same write will not fix failing tests.'
            if name=='test_base' and output['returncode']!=0:feedback['notice']='Public base tests failed. Read the failure output and change the implementation; repeating identical writes does not count as progress.'
        except BudgetExceeded as exc:
            row['stop_reason']=str(exc)
            return {'outcome':'model_wrong','turns':turn,'log':log,'reason':str(exc)}
    return {'outcome':'model_wrong','turns':cfg['max_turns'],'log':log,'reason':'turn limit'}


def calibrate_coding(seed, task, provider, tokenizer, guard, config, sandbox_factory, *, output=None):
    """Fresh sandbox per cell/repeat. Must be explicitly invoked after approval."""
    from .common import write
    from .stage1_errors import EnvError
    from .run_qa_calibration import check_stage1
    if not guard.enabled: raise RuntimeError('Coding model calls disabled')
    cfg = config['stage2']
    if cfg['repeats'] != 3: raise ValueError('Coding denominator is frozen at 3')
    records, scores = [], {a:{} for a in ANCHORS}
    report = {'case_id':seed['id'],'stage':2,'complete':False,'passed':False,'scores':scores,
              'records':records,'denominator_per_cell':3,'model':getattr(provider,'model',None)}
    try:
        for a in ANCHORS:
            for c in CONTEXTS:
                cell = []
                for repeat in range(3):
                    try:
                        with sandbox_factory(c) as sandbox:
                            result = coding_session(seed,task,sandbox,provider,tokenizer,guard,cfg,a,c)
                    except EnvError as exc:
                        records.append({'anchor':a,'context':c,'repeat':repeat+1,'outcome':'env_error','error':str(exc)})
                        raise
                    records.append(dict(result,anchor=a,context=c,repeat=repeat+1))
                    cell.append(int(result['outcome']=='pass'))
                    if output: write(output,dict(report,budget_accounted_tokens=guard.spent))
                scores[a][c] = sum(cell)/3
        report.update(complete=True,passed=check_stage1(scores))
        return report
    finally:
        report['budget_accounted_tokens'] = guard.spent
        report['outcomes'] = {k:sum(r['outcome']==k for r in records) for k in ('pass','model_wrong','parse_error','env_error')}
        if output: write(output,report)


class CodingRunner:
    def __init__(self,dataset,seed,guard,*,config,provider=None,tokenizer=None):
        self.dataset,self.seed,self.guard=Path(dataset).resolve(),seed,guard
        self.config,self.provider,self.tokenizer=config,provider,tokenizer

    def __call__(self,stage):
        import contextlib,hashlib,shutil,tempfile
        from .coding_sandbox import Sandbox
        from .stage1_errors import CalibrationFailed
        from .stage1_provider import OpenAIChatProvider,Utf8BoundTokenizer
        if stage!=2 or not self.guard.enabled: raise RuntimeError('Coding requires explicit Stage 2 model opt-in')
        base=self.dataset/'cases'/self.seed['id']
        prep=read(base/'stage2_preparation.json')
        if not prep['passed']: raise ValueError('preparation has not passed')
        repo=self.dataset/'repo_base'
        for name,digest in prep['snapshots'].items():
            if hashlib.sha256((repo/name).read_bytes()).hexdigest()!=digest: raise ValueError('frozen repository changed; redo affected checks')
        task=read(base/'coding_task.json');cfg=self.config['stage2']
        if self.provider is None:
            self.provider=OpenAIChatProvider.from_env(enabled=True,temperature=cfg['temperature'])
        @contextlib.contextmanager
        def fresh(context):
            with tempfile.TemporaryDirectory(prefix='ctm-coding-') as tmp:
                candidate=Path(tmp)/'workspace';shutil.copytree(repo,candidate)
                with Sandbox(candidate,self.dataset/'artifacts'/self.seed['id']/'world_profile.yaml',
                    {'A':'A_static','B':'B_irrelevant','C':'C_changed'}[context],
                    workspace_image=cfg['workspace_image'],service_image=cfg['service_image'],
                    network_subnet=cfg.get('network_subnet')) as sandbox:
                    yield sandbox
        history=base/'coding_calibration_runs';history.mkdir(exist_ok=True)
        path=history/f'{len(list(history.glob("*.json")))+1:04d}.json'
        try:
            report=calibrate_coding(self.seed,task,self.provider,self.tokenizer or Utf8BoundTokenizer(),
                self.guard,self.config,fresh,output=path)
        finally:
            if path.exists():
                from .common import write
                write(base/'coding_calibration.json',read(path))
        if not report['passed']:
            raise CalibrationFailed('Coding anchors failed','parse_error' if report['outcomes']['parse_error'] else 'model_wrong')
        return True


def main():
    p=selector(__doc__)
    p.add_argument('--execute-coding',action='store_true',help='explicit real Coding opt-in, only after approval')
    p.add_argument('--approve',action='store_true',help='approve Gate 1 to run Stage 2 calibration')
    args = p.parse_args()
    for seed in seeds(args):
        base = args.dataset/'cases'/seed['id']
        result = read(base/'stage2_preparation.json')
        if not result['passed']: raise SystemExit('Stage 2 preparation failed')
        if args.execute_coding:
            from .factory import Factory
            from .common import write
            from .budget_guard import BudgetGuard
            from .run_qa_calibration import stage1_config
            config=stage1_config();state_path=base/'factory_state.json'
            factory=Factory(read(state_path),case_id=seed['id'])
            guard=BudgetGuard(config['stage_token_limits']['2'],enabled=True,
                spent=factory.state.get('stage2_budget_accounted_tokens',0),input_cap=config['stage2']['max_input_tokens'])
            runner=CodingRunner(args.dataset,seed,guard,config=config)
            try: factory.run_stage2(runner,approve=args.approve)
            finally: write(state_path,factory.state)
            print(seed['id'],'stage 2',factory.state['status'])
            continue
        print(seed['id'],'READY_FOR_CODING_APPROVAL; no model called')


if __name__ == '__main__': main()
