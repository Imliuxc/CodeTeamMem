"""Budgeted generation + QA verification. Never locks a case or starts Stage 4."""
import json
import hashlib
import re
from pathlib import Path
from .common import read, write, selector, seeds
from .act_stream_builder import ActStreamSession, validate_turn, verify, t0_vocabulary
from .run_qa_calibration import make_prompt, parse_exact, CONTEXTS
from .budget_guard import BudgetGuard, BudgetExceeded
from .stage1_errors import EnvError
from .stream_vocabulary import BASICS, identifiers, file_tokens, future_only


def public_rows(rows):
    """Remove private claim IDs/control metadata from all model-facing history."""
    return [{k:r[k] for k in ('kind','act','role','text') if k in r} for r in rows]


class BudgetedCalls:
    def __init__(self, provider, tokenizer, guard, qa_config, output=None):
        self.provider,self.tokenizer,self.guard=provider,tokenizer,guard
        self.cfg,self.output,self.records=dict(qa_config),output,[]

    def call(self, payload, *, phase, max_output=None):
        prompt=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        row={'phase':phase,'prompt':prompt};self.records.append(row)
        measured={}
        def tracked(text,*,max_output):
            row['provider_called']=True
            result=self.provider(text,max_output=max_output);measured.update(result);return result
        try:
            raw=self.guard.call(tracked,prompt,tokenizer=self.tokenizer,
                max_output=max_output or self.cfg['max_output_tokens'],
                prompt_overhead=self.cfg['prompt_overhead_tokens'],truncate=False)
            row.update(measured);return raw
        except Exception as exc:
            row.update(measured,error=type(exc).__name__);raise
        finally:
            if self.output:write(self.output,{'records':self.records,'budget_accounted_tokens':self.guard.spent})

    def binary(self, statement, message, *, phase):
        raw=self.call({'instruction':'只输出JSON布尔值true或false。判断这一条发言是否明确表达所给陈述；不接受暗示、脑补、提问或未作决定的讨论。',
                       'statement':statement,'message':message},phase=phase,max_output=32)
        value=json.loads(raw)
        if type(value) is not bool:raise ValueError('binary semantic verdict required')
        return value

    def usage(self):
        result={}
        for phase in ('generation','verification'):
            rows=[r for r in self.records if r['phase']==phase]
            result[phase]={'attempts':len(rows),'calls':sum(r.get('provider_called',False) for r in rows),
                          'responses_with_usage':sum('usage_tokens' in r for r in rows),
                          'usage_tokens':sum(r.get('usage_tokens',0) for r in rows),
                          'unconfirmed_usage':any(r.get('provider_called') and 'usage_tokens' not in r for r in rows)}
        result['total_tokens']=sum(x['usage_tokens'] for x in result.values())
        result['budget_accounted_tokens']=self.guard.spent
        return result


def check_statement(statement, messages, calls, *, phase):
    """Exact regex first; otherwise one binary semantic decision per message."""
    pattern=statement.get('pattern')
    for text in messages:
        if pattern and re.search(pattern,text):return True
    return any(calls.binary(statement['text'],text,phase=phase) for text in messages)


def qa_stream_prompt(seed, context, rows):
    # Reuse the Stage 1 public policy/schema/world/neutral question verbatim.
    # Only the team_record is replaced. Expected answers remain grader-side.
    payload=json.loads(make_prompt(seed,'B0',context))
    payload['team_record']=public_rows(rows)
    return payload


def verify_stream(seed, rows, symbols, calls, rejected_options, *, full_repeats=3, output=None):
    if full_repeats not in (1,3):raise ValueError('full repeats must be 1 or 3')
    roles=seed['roles'];chat=[r for r in rows if r['kind']=='dialogue']
    if not rejected_options:raise ValueError('explicit rejected options required')
    report={'complete':False,'passed':False,'blind_scores':{},'full_scores':{},'records':[],
            'blind_denominator':3,'full_denominator':full_repeats,'rejected_options':[]}
    def save():
        report['usage']=calls.usage()
        report['outcomes']={k:sum(r['outcome']==k for r in report['records'])
                            for k in ('pass','model_wrong','parse_error','env_error','budget_stop','interrupted')}
        if output:write(output,report)
    try:
        active,literals=set(symbols),set()
        for row in rows:
            if row['kind']!='dialogue':
                active.update(row.get('public_symbols',[]));literals.update(row.get('public_literals',[]))
            else:
                own=[f for f in seed['facts'] if f.get('owner',f.get('role'))==row['role'] and f['unlock_act']<=row['act']]
                validate_turn(row['text'],active|identifiers([f['text'] for f in own]),
                              seed.get('banned_meta_words',[]),literals,future_only(seed))
                active.update(identifiers([f['text'] for f in own if f['id'] in row.get('fact_ids',[])]))
        if {r['role'] for r in chat}!=set(roles) or 'pm_lead' not in roles or len(roles)<2:
            raise ValueError('missing participating role')
        report.update(symbol_alignment=1.0,symbol_scope='explicit/known/snake_case/call syntax',
                      symbol_reference_count=sum(len(re.findall(r'`([^`]+)`',r['text'])) for r in chat),
                      unknown_symbol_count=0,summary_violations=0,banned_word_violations=0)
        for option in rejected_options:
            ok=check_statement(option,[r['text'] for r in chat],calls,phase='verification')
            report['rejected_options'].append({'id':option['id'],'passed':ok})
            if not ok:raise ValueError('rejected option not explicitly denied: '+option['id'])
        groups=[(role,[r for r in chat if r['role']==role],3) for role in roles]+[('full',rows,full_repeats)]
        for group,evidence,repeats in groups:
            scores={}
            for context in CONTEXTS:
                expected=parse_exact(json.dumps(seed['qa']['expected'][context]),seed['qa']['output_schema'])
                passed=0
                for repeat in range(1,repeats+1):
                    row={'group':group,'context':context,'repeat':repeat,'expected':expected}
                    try:
                        raw=calls.call(qa_stream_prompt(seed,context,evidence),phase='verification')
                    except Exception as exc:
                        outcome='env_error' if isinstance(exc,EnvError) else 'budget_stop' if isinstance(exc,BudgetExceeded) else 'interrupted'
                        row.update(outcome=outcome,error=type(exc).__name__)
                        report['records'].append(row);raise
                    row['raw_answer']=raw
                    try:
                        row['parsed']=parse_exact(raw,seed['qa']['output_schema'])
                        row['outcome']='pass' if row['parsed']==expected else 'model_wrong'
                    except (ValueError,TypeError):row['outcome']='parse_error'
                    passed+=row['outcome']=='pass'
                    report['records'].append(row);save()
                scores[context]=passed/repeats
            if group=='full':report['full_scores']=scores
            else:report['blind_scores'][group]=scores
        low=all(s<=1/3 for row in report['blind_scores'].values() for s in row.values())
        high=all(s>=(1 if full_repeats==1 else 2/3) for s in report['full_scores'].values())
        report.update(complete=True,passed=low and high,
                      role_scores={r:max(v.values()) for r,v in report['blind_scores'].items()},
                      full_score=min(report['full_scores'].values()))
        if report['passed']:
            verify(rows,symbols,seed.get('banned_meta_words',[]),report['role_scores'],report['full_score'],roles,seed=seed)
        return report
    finally:save()


def load_events(dataset, plan):
    root=Path(dataset).resolve();events=[]
    for item in plan['events']:
        path=(root/item['path']).resolve()
        if not path.is_relative_to(root):raise ValueError('event path outside dataset')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('event hash changed')
        value=json.loads(raw)
        if item['kind']=='tool_log':
            if value.get('profile')!='T0_history' or 'response' not in value:raise ValueError('T0 HTTP evidence required')
            text=json.dumps(value,ensure_ascii=False)
        elif item['kind']=='git_diff':
            if not all(value.get(k) for k in ('T0','T1','diff')):raise ValueError('T0/T1 diff evidence required')
            text=value['diff']
        else:raise ValueError('unsupported source event')
        events.append({'kind':item['kind'],'act':item['act'],'text':text,
                       'source_sha256':item['sha256'],'source':item['path']})
        if item['kind']=='tool_log':
            names,literals=t0_vocabulary(value['response'])
            events[-1].update(public_symbols=sorted(names),public_literals=sorted(literals))
        else:events[-1]['public_symbols']=sorted(identifiers(text))
    return events


def generate_stream(seed, symbols, events, calls, plan, *, output=None):
    def check_fact(fact,text):
        statement={'text':fact['text'],**plan.get('fact_checks',{}).get(fact['id'],{})}
        return check_statement(statement,[text],calls,phase='generation')
    session=ActStreamSession(seed,symbols,events=events,
        max_regenerations=plan.get('max_regenerations',2),fact_check=check_fact)
    def generate(view):
        view['public_history']=public_rows(view['public_history'])
        raw=calls.call({'instruction':'你是当前speaker。只依据自己的facts和已公开的聊天/事件接着说，回应前面的同事，不替别人公布私事。'
                          '只输出JSON对象role、fact_ids、text；fact_ids只能引用本次可见事实且必须在发言中真实表达。'
                          'text为1至3句简短口语，不列条目或归纳，不出现团队记忆、关键前提、适用边界、废案、反事实、锚点、总结或评测术语。'
                          '普通文本和反引号引用共用allowed_symbols，均可使用其中的真实标识、路径及数据值，不发明符号。'
                          '若view中有retry_feedback，必须根据具体rule和hits修正previous_output，不要原样重发。',
                        'allowed_symbols':sorted(session.allowed_symbols()),'view':view},phase='generation',max_output=plan.get('generation_max_output_tokens',512))
        turn=json.loads(raw)
        if not isinstance(turn,dict) or set(turn)!={'role','fact_ids','text'}:raise ValueError('turn JSON fields invalid')
        return turn
    try:
        while not session.done:
            session.step(generate)
            if output:write(output,{'complete':False,**session.snapshot(),'public_stream':session.public_stream})
        session._inject()
        if len(session.injected)!=len(events):raise ValueError('unreached event')
        # Persist control-side fact IDs for replay, not in QA or generation history.
        rows=deepcopy_rows(session)
        return rows,session.rejections
    finally:
        if output:write(output,{'complete':session.done,**session.snapshot(),'public_stream':session.public_stream})


def deepcopy_rows(session):
    from copy import deepcopy
    rows=deepcopy(session.public_stream);turns=iter(session.stream)
    for i,row in enumerate(rows):
        if row['kind']=='dialogue':rows[i]=dict(next(turns),sequence=i)
    return rows


def run(seed, dataset, provider, tokenizer, guard, *, plan, qa_config, output):
    """Explicit execution seam; callers must opt in. Gate 3 needs manual review."""
    from .merge_dataset_stream import save_stream
    from .stage1_errors import EnvError
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    base=Path(dataset)/'cases'/seed['id'];frozen=read(base/'coding_calibration.json')
    if not frozen.get('complete') or not frozen.get('passed'):raise ValueError('CODE_CALIBRATED required')
    hashes=frozen['source_hashes']
    def check_frozen():
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in hashes.items() if not Path(p).is_relative_to(Path(__file__).parent)):raise ValueError('Stage 2 frozen hash changed')
    check_frozen()
    if not guard.enabled:raise RuntimeError('Stage 3 model calls disabled')
    def protected(prompt,*,max_output):
        check_frozen();return provider(prompt,max_output=max_output)
    calls=BudgetedCalls(protected,tokenizer,guard,qa_config,output/'model_calls.json')
    report={'case_id':seed['id'],'stage':3,'status':'RUNNING','locked':False,'passed':False,
            'model':getattr(provider,'model',None),'qa_config':dict(qa_config),'token_limit':guard.total_tokens}
    try:
        manifest=read(base/'symbol_manifest.json')
        ast_symbols=set(manifest['symbols'])
        files=manifest.get('files',[])
        if any(not (Path(dataset)/'repo_base'/f).is_file() for f in files):raise ValueError('manifest file missing')
        schema_symbols=set(seed['data_schema'])|identifiers(seed['data_schema'])
        policy_symbols=identifiers(seed['public_policy'])
        symbols=(ast_symbols|schema_symbols|policy_symbols|file_tokens(files)|BASICS)-future_only(seed)
        events=load_events(dataset,plan)
        write(output/'symbol_sources.json',{'ast':sorted(ast_symbols),'public_schema':sorted(schema_symbols),
              'public_policy':sorted(policy_symbols),'real_file_paths':sorted(file_tokens(files)),
              'basic_literals':sorted(BASICS),'private_fact_tokens':'only current speaker unlocked text; publish after fact expression verified',
              'events':[{'act':e['act'],'source_sha256':e['source_sha256'],
                         'symbols':e.get('public_symbols',[]),'data_literals':e.get('public_literals',[])} for e in events]})
        rows,rejections=generate_stream(seed,symbols,events,calls,plan,output=output/'generation.json')
        save_stream(output/'raw_stream.jsonl',rows)
        report['regenerations']=len(rejections)
        proof=verify_stream(seed,rows,symbols,calls,plan['rejected_options'],
            full_repeats=plan.get('full_repeats',3),output=output/'stream_verification.json')
        report.update(passed=proof['passed'],status='GATE_3_REVIEW' if proof['passed'] else 'FAILED')
        check_frozen();return report
    except (EnvError,BudgetExceeded) as exc:
        report.update(status='NEEDS_HUMAN',stop_reason=type(exc).__name__);raise
    except Exception as exc:
        report.update(status='FAILED',stop_reason=str(exc));raise
    finally:
        report['usage']=calls.usage();write(output/'report.json',report)


def main():
    from .stage1_provider import OpenAIChatProvider,Utf8BoundTokenizer
    from .run_qa_calibration import stage1_config
    p=selector(__doc__)
    p.add_argument('--execute-stage3',action='store_true')
    p.add_argument('--token-budget',type=int,default=None)
    args=p.parse_args();selected=seeds(args)
    if not args.execute_stage3:raise SystemExit('No model called; explicit --execute-stage3 required')
    config=stage1_config();guard=BudgetGuard(args.token_budget or config['stage_token_limits']['3'],enabled=True)
    provider=OpenAIChatProvider.from_env(enabled=True,temperature=config['stage1']['temperature'])
    for seed in selected:
        base=args.dataset/'cases'/seed['id'];plan=read(base/'stage3_plan.json')
        run(seed,args.dataset,provider,Utf8BoundTokenizer(),guard,plan=plan,
            qa_config=config['stage1'],output=base/'stage3_runs'/f'{len(list((base/"stage3_runs").glob("*")))+1:04d}')


if __name__=='__main__':main()
