"""Observable metrics with explicit denominators; no missing-value imputation."""
from .common import read, selector, seeds, write
from .run_qa_calibration import score
from .validate_seed import GOLD


def run(adapter, stream, tasks, solve, extract):
    adapter.ingest(stream)
    answers = [solve(task, adapter.retrieve(task['query'])) for task in tasks]
    return {'answers': answers, 'extracted': extract(adapter.dump_memories())}


def summarize(records):
    if not records: raise ValueError('empty metric denominator')
    for r in records:
        if not all(r['gold'].get(k) for k in GOLD) or set(r['extracted']) != set(GOLD): raise ValueError('incomplete gold/extraction')
        for field in ('qa_b2','coding_b2','coding_b0_c','coding_b1_c'): score(r[field])
        for field in ('tokens','communication_bytes'):
            if type(r[field]) is not int or r[field] < 0: raise ValueError('invalid cost')
    n = len(records)
    return {'denominator': n, 'whitebox': {k: sum(r['gold'][k] == r['extracted'][k] for r in records)/n for k in GOLD},
            'blackbox_utility': sum(r['coding_b2'] for r in records)/n,
            'qa_coding_gap': sum(r['qa_b2']-r['coding_b2'] for r in records)/n,
            'stale_negative_transfer': sum(r['coding_b0_c']-r['coding_b1_c'] for r in records)/n,
            'cost': {k: sum(r[k] for r in records) for k in ('tokens','communication_bytes')},
            'interpretation': 'observational paired differences; causal attribution requires controlled evidence'}


# Real Stage 4 path below. Legacy summarize/run above remain technical fixture APIs.
import json
import hashlib
from copy import deepcopy
from pathlib import Path
from .memory_scoring import whitebox_score, paired_metrics, save_leaderboard
from .memory_adapters.baselines import LongContextConcatAdapter, NaiveChunkRAGAdapter, public_events
from .run_qa_calibration import make_prompt, parse_exact
from .budget_guard import BudgetExceeded
from .stage1_errors import EnvError


def verify_lock(base):
    manifest=read(Path(base)/'LOCKED.json')
    if manifest['status']!='LOCKED':raise ValueError('LOCKED case required')
    for p,h in manifest['frozen_hashes'].items():
        if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:raise ValueError('locked artifact changed: '+p)
    return manifest


def frozen_anchors(base):
    qa=read(Path(base)/'qa_calibration.json');coding=read(Path(base)/'coding_calibration.json')
    for report in (qa,coding):
        if not report.get('complete') or not report.get('passed') or len(report['records'])!=27:
            raise ValueError('complete formal 27-run anchors required')
        expected={(a,c,n) for a in ('B0','B1','B2') for c in 'ABC' for n in (1,2,3)}
        if {(r['anchor'],r['context'],r['repeat']) for r in report['records']}!=expected:raise ValueError('anchor cells missing')
        for a in ('B0','B1','B2'):
            for c in 'ABC':
                rows=[r for r in report['records'] if r['anchor']==a and r['context']==c]
                if any(r['outcome'] not in ('pass','model_wrong','parse_error') for r in rows):raise ValueError('incomplete anchor outcome')
                if sum(r['outcome']=='pass' for r in rows)/3!=report['scores'][a][c]:raise ValueError('anchor score mismatch')
    if qa['provider_model']!=coding['model']:raise ValueError('anchor model mismatch')
    return {'qa':qa['scores'],'coding':coding['scores'],'denominator_per_cell':3,
            'model':coding['model'],'qa_config':qa['request_config'],'coding_config':coding['coding_config'],
            'source_files':{n:hashlib.sha256((Path(base)/n).read_bytes()).hexdigest() for n in ('qa_calibration.json','coding_calibration.json')},
            'comparison':'QA/Coding anchors are independent frozen runs; only new memory trials are paired'}


def evaluate_memories(dataset,case_id,adapters,provider,tokenizer,guard,*,repeats,config,rubric,output,coding_executor=None):
    """Explicit provider injection; never runs or regenerates B0/B1/B2."""
    from .merge_dataset_stream import load_stream
    from .memory_coding import FrozenCodingExecutor
    if not guard.enabled:raise RuntimeError('memory model calls disabled')
    if type(repeats) is not int or repeats<1:raise ValueError('positive repeat count required')
    base=Path(dataset)/'cases'/case_id;lock=verify_lock(base);anchors=frozen_anchors(base)
    allowed={'stage1':{'max_input_tokens'},'stage2':{'max_input_tokens','max_turns','stall_limit','exploration_limit','no_edit_warn','no_edit_stop','trial_token_limit'}}
    differences={}
    for stage,old in [('stage1',anchors['qa_config']),('stage2',anchors['coding_config'])]:
        differences[stage]={k:{'old':old.get(k),'new':config[stage].get(k)} for k in set(old)|set(config[stage]) if old.get(k)!=config[stage].get(k)}
        if set(differences[stage])-allowed[stage]:raise ValueError('frozen evaluation parameters differ outside authorized limits')
    anchors['execution_compatible']=not any(differences.values())
    anchors['execution_differences']=differences
    anchors['comparison']='historical references only when execution_compatible=false; not a matched or same-condition comparison'
    if getattr(provider,'model',None)!=anchors['model']:raise ValueError('frozen model required')
    if getattr(provider,'temperature',config['stage1']['temperature'])!=config['stage1']['temperature']:
        raise ValueError('frozen provider temperature required')
    seed=read(Path(dataset)/'seeds'/f'{case_id}.yaml');stream=public_events(load_stream(base/lock['stream']))
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    executor=coding_executor or FrozenCodingExecutor(dataset,case_id)
    reports={};all_calls=[];active={};spent_before=guard.spent
    def tracked(prompt,*,max_output):
        row=dict(active,prompt=prompt);all_calls.append(row)
        try:
            result=provider(prompt,max_output=max_output);row.update(result);return result
        except Exception as exc:row['error']=type(exc).__name__;raise
        finally:write(output/'model_calls.json',{'records':all_calls,'budget_accounted_tokens':guard.spent})
    def usage(rows):
        value={'calls':len(rows),'total_tokens':sum(r.get('usage_tokens',0) for r in rows),
               'unconfirmed_usage':any('usage_tokens' not in r for r in rows)}
        value['known_tokens']=value['total_tokens']
        if value['unconfirmed_usage']:value['total_tokens']=None
        for k in ('input_tokens','output_tokens','cached_input_tokens'):
            value[k]=sum(r[k] for r in rows) if all(type(r.get(k)) is int for r in rows) else None
        return value
    stop=False
    try:
        for name,adapter in adapters.items():
            verify_lock(base);adapter.ingest(deepcopy(stream));memories=adapter.dump_memories()
            folder=output/name;folder.mkdir()
            write(folder/'memories.json',memories)
            records=[];report={'store_support':whitebox_score(memories,seed['gold'],rubric),'case_id':case_id,'records':records,'whitebox':whitebox_score(memories,seed['gold'],rubric),'structured_extraction':{'status':'not_applicable','reason':'raw history storage, no structured extraction'}}
            reports[name]=report
            for c in 'ABC':
                if stop:break
                for repeat in range(1,repeats+1):
                    trial_guard=guard.scope(config['execution']['trial_token_limit'])
                    qa_payload=json.loads(make_prompt(seed,'B0',c))
                    query=qa_payload['turn_1']+'\n'+json.dumps(qa_payload['current_snapshot'],ensure_ascii=False)
                    memory=adapter.retrieve(query)
                    if not isinstance(memory,str):raise ValueError('retrieve must return model context text')
                    trial=folder/f'{c}_{repeat}';trial.mkdir()
                    write(trial/'retrieval.json',{'query':query,'context':memory,'trace':getattr(adapter,'last_retrieval',None)})
                    retrieval_support=whitebox_score(getattr(adapter,'retrieved_memories',[{'kind':'memory','text':memory}]),seed['gold'],rubric)
                    row={'retrieval_support':retrieval_support,'context':c,'repeat':repeat,'qa':{'outcome':'not_run'},'coding':{'outcome':'not_run'},'context_bytes':len(memory.encode())}
                    records.append(row);active.update(method=name,context=c,repeat=repeat,phase='qa')
                    qa_payload['team_record']=memory
                    try:
                        raw=trial_guard.call(tracked,json.dumps(qa_payload,ensure_ascii=False,sort_keys=True),tokenizer=tokenizer,
                            max_output=config['stage1']['max_output_tokens'],prompt_overhead=config['stage1']['prompt_overhead_tokens'],truncate=False)
                        row['qa']['raw_answer']=raw
                        try:
                            answer=parse_exact(raw,seed['qa']['output_schema'])
                            expected=parse_exact(json.dumps(seed['qa']['expected'][c]),seed['qa']['output_schema'])
                            row['qa'].update(parsed=answer,outcome='pass' if answer==expected else 'model_wrong')
                        except (ValueError,TypeError):row['qa']['outcome']='parse_error'
                        active['phase']='coding'
                        row['coding']=executor(seed,memory,c,tracked,tokenizer,trial_guard,trial/'coding')
                    except EnvError as exc:row[active['phase']].update(outcome='env_error',error=str(exc))
                    except BudgetExceeded as exc:row[active['phase']].update(outcome='budget_stop',error=str(exc))
                    stop=any(row[p]['outcome'] in ('env_error','budget_stop') for p in ('qa','coding'))
                    report['blackbox']=paired_metrics(records,anchors,repeats)
                    used=[r for r in all_calls if r['method']==name];report['cost']=usage(used)
                    report['cost'].update(coding_turns=sum(r['coding'].get('turns',0) for r in records),
                        ingested_bytes=len(json.dumps(stream,ensure_ascii=False).encode()),retrieved_bytes=sum(r['context_bytes'] for r in records),
                        context_presentation_bytes=sum(r['context_bytes']*(int(r['qa']['outcome']!='not_run')+int(r['coding']['outcome']!='not_run')) for r in records))
                    write(folder/'report.json',report);write(trial/'result.json',row)
                    if stop:break
            if stop:break
    finally:
        for name,report in reports.items():
            report.setdefault('blackbox',paired_metrics(report['records'],anchors,repeats))
            report.setdefault('cost',usage([r for r in all_calls if r['method']==name]))
        board=save_leaderboard(output,reports,anchors)
        write(output/'report.json',{'case_id':case_id,'methods':reports,'anchors':anchors,
            'usage':usage(all_calls),'budget_accounted_tokens':guard.spent-spent_before,'complete':len(reports)==len(adapters) and all(r['blackbox']['complete'] for r in reports.values())})
        verify_lock(base)
    return board


def main():
    from .stage1_provider import OpenAIChatProvider,Utf8BoundTokenizer
    from .run_qa_calibration import stage1_config
    from .budget_guard import BudgetGuard
    p=selector(__doc__);p.add_argument('--execute-memory',action='store_true')
    p.add_argument('--repeats',type=int,default=1);p.add_argument('--token-budget',type=int,default=None)
    p.add_argument('--adapters',nargs='+',choices=['long_context','naive_rag'],default=['long_context','naive_rag'])
    args=p.parse_args();selected=seeds(args)
    if not args.execute_memory:raise SystemExit('No model called. Explicit --execute-memory required after approval.')
    config=stage1_config();provider=OpenAIChatProvider.from_env(enabled=True,temperature=config['stage1']['temperature'])
    if provider.__class__.__name__!='OpenAIResponsesProvider':raise SystemExit('Frozen Responses transport required')
    guard=BudgetGuard(args.token_budget or config['stage4']['total_tokens'],enabled=True,input_cap=config['stage2']['max_input_tokens'])
    for seed in selected:
        base=args.dataset/'cases'/seed['id'];history=base/'stage4_runs'
        adapters={n:LongContextConcatAdapter() if n=='long_context' else NaiveChunkRAGAdapter() for n in args.adapters}
        evaluate_memories(args.dataset,seed['id'],adapters,provider,Utf8BoundTokenizer(),guard,
            repeats=args.repeats,config=config,rubric=read(base/'whitebox_rubric.json'),output=history/f'{len(list(history.glob("*")))+1:04d}')


if __name__=='__main__':main()
