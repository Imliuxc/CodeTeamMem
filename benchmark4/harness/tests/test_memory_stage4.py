import json
from copy import deepcopy
from pathlib import Path
import pytest
from benchmark4.harness.common import read
from benchmark4.harness.memory_adapters.baselines import LongContextConcatAdapter,NaiveChunkRAGAdapter
from benchmark4.harness.memory_scoring import whitebox_score,paired_metrics,save_leaderboard
from benchmark4.harness.run_memory_benchmark import evaluate_memories,verify_lock,frozen_anchors
from benchmark4.harness.stage1_provider import Utf8BoundTokenizer
from benchmark4.harness.budget_guard import BudgetGuard
from benchmark4.harness.stage1_errors import EnvError

ROOT=Path(__file__).resolve().parents[2]/'datasets/refund_pilot'
CASE='C01_refund_display_contract';BASE=ROOT/'cases'/CASE


def rubric():
 return {k:[{'id':k,'pattern':k}] for k in ('rule','key_premise','scope_boundary')}|{'dead_end':[{'id':'bad','active_pattern':'use bad','denied_pattern':'reject bad'}]}


def gold():return {k:k for k in ('rule','key_premise','scope_boundary','dead_end')}


def test_concat_keeps_entire_chronological_stream_and_private_metadata_out():
 events=[{'sequence':i,'kind':'dialogue','text':str(i),'fact_ids':['SECRET']} for i in range(15)]
 a=LongContextConcatAdapter();a.ingest(list(reversed(events)));text=a.retrieve('ignored',limit=1)
 assert text.index('[0 /')<text.index('[14 /') and 'SECRET' not in text
 assert len(a.dump_memories())==15 and a.retrieve('',limit=0)==''
 a.dump_memories()[0]['text']='mutated';assert a.events[0]['text']=='0'


def test_rag_chunking_chinese_search_and_reproducibility():
 events=[{'sequence':0,'kind':'tool_log','text':'天气与颜色无关。'*20},{'sequence':1,'kind':'dialogue','text':'退款执行回执协议，失败记录保留。'}]
 a=NaiveChunkRAGAdapter(chunk_chars=50,overlap=8,top_k=1);a.ingest(events)
 text=a.retrieve('退款回执失败记录');assert '退款执行回执' in text and len(a.dump_memories())>2
 b=NaiveChunkRAGAdapter(chunk_chars=50,overlap=8,top_k=1);b.ingest(events)
 assert text==b.retrieve('退款回执失败记录') and a.last_retrieval==b.last_retrieval
 assert a.retrieve('',limit=0)==''


def test_whitebox_support_missing_and_dead_end_polarity():
 r=rubric();g=gold()
 m=[{'kind':'dialogue','text':'rule key_premise scope_boundary. reject bad'}]
 s=whitebox_score(m,g,r)
 assert s['rule_recall']==s['key_premise_completeness']==s['scope_boundary_completeness']==1
 assert s['dead_end_pollution_rate']==0 and s['dead_end_assessed_coverage']==1
 m.append({'kind':'memory','text':'use bad'})
 assert whitebox_score(m,g,r)['dead_end_pollution_rate']==1
 assert whitebox_score([{'kind':'git_diff','text':'use bad'}],g,r)['dead_end_assessed_coverage']==0
 s=whitebox_score([],g,r);assert s['rule_recall']==0 and s['dead_end_assessed_coverage']==0
 assert s['evidence']['rule'][0]['status']=='unmatched_or_ambiguous'


def records():
 return [{'context':c,'repeat':1,'qa':{'outcome':'pass'},'coding':{'outcome':'model_wrong' if c=='C' else 'pass'}} for c in 'ABC']


def anchors():return {p:{a:dict.fromkeys('ABC',0 if a=='B0' else 1) for a in ('B0','B1','B2')} for p in ('qa','coding')}


def test_paired_gap_exports_and_negative_transfer_denominators(tmp_path):
 m=paired_metrics(records(),anchors(),1)
 assert m['complete'] and m['paired_qa_minus_coding']==pytest.approx(1/3)
 assert len(m['qa_pass_coding_fail'])==1 and m['qa_pass_coding_fail'][0]['context']=='C'
 assert m['coding_net_gain_over_b0']['A']==1 and m['coding_gap_to_b2']['C']==1
 assert m['negative_transfer']['matched_b0_harm_count'] is None
 board=save_leaderboard(tmp_path,{'mock':{'blackbox':m,'whitebox':{},'cost':{'total_tokens':12}}},anchors())
 assert board['rows'][0]['eligible'] and len(read(tmp_path/'qa_pass_coding_fail.json'))==1
 assert 'mock' in (tmp_path/'leaderboard.md').read_text()


def test_environment_errors_not_failed_business_or_gap():
 rows=records();rows[-1]['coding']['outcome']='env_error'
 m=paired_metrics(rows,anchors(),1)
 assert not m['complete'] and m['rates']['coding']['C']['rate'] is None
 assert m['paired_denominator']==2 and m['paired_qa_minus_coding']==0 and not m['qa_pass_coding_fail']
 rows[-1]['coding']['outcome']='parse_error';m=paired_metrics(rows,anchors(),1)
 assert m['complete'] and m['rates']['coding']['C']['denominator']==1
 with pytest.raises(ValueError):paired_metrics(rows+[rows[0]],anchors(),1)


class MockProvider:
 model='deepseek-v4-1-flash-260910'
 def __init__(self):self.prompts=[]
 def __call__(self,prompt,*,max_output):
  self.prompts.append(json.loads(prompt))
  return {'text':'{"exec_ids":["E01","E02","E05"]}','usage_tokens':10,'input_tokens':8,'output_tokens':2,'cached_input_tokens':0}


def test_full_offline_pairing_anchor_reuse_and_board(tmp_path):
 config=read(Path('benchmark4/harness/config.yaml'));provider=MockProvider();contexts=[]
 def coding(seed,memory,context,provider,tokenizer,guard,output):
  contexts.append(memory)
  # Probe the actual shared model/budget seam with a Mock response.
  guard.call(provider,'{"coding_probe":true}',tokenizer=tokenizer,max_output=32)
  return {'outcome':'model_wrong' if context=='C' else 'pass','turns':1}
 adapters={'long_context':LongContextConcatAdapter(),'rag':NaiveChunkRAGAdapter(top_k=2)}
 out=tmp_path/'run'
 board=evaluate_memories(ROOT,CASE,adapters,provider,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),
  repeats=1,config=config,rubric=read(BASE/'whitebox_rubric.json'),output=out,coding_executor=coding)
 assert len(provider.prompts)==12  # six new QA+Coding pairs; zero anchor calls
 assert len(board['rows'])==2 and len(read(out/'qa_pass_coding_fail.json'))==2
 report=read(out/'report.json');assert report['complete'] and report['usage']['total_tokens']==120
 qa=[p for p in provider.prompts if 'team_record' in p]
 assert [p['team_record'] for p in qa]==contexts
 assert all('expected' not in p and 'gold' not in p for p in qa)
 assert board['anchors_reused']['qa']['B2']==dict.fromkeys('ABC',1)
 assert verify_lock(BASE)['status']=='LOCKED'


def test_env_abort_saves_partial_board_and_frozen_config_enforced(tmp_path):
 def coding(*args):return {'outcome':'env_error','turns':0}
 config=read(Path('benchmark4/harness/config.yaml'));provider=MockProvider()
 evaluate_memories(ROOT,CASE,{'long_context':LongContextConcatAdapter()},provider,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),
  repeats=1,config=config,rubric=read(BASE/'whitebox_rubric.json'),output=tmp_path/'env',coding_executor=coding)
 report=read(tmp_path/'env/report.json');assert not report['complete'] and len(provider.prompts)==1
 assert not read(tmp_path/'env/leaderboard.json')['rows'][0]['eligible']
 changed=deepcopy(config);changed['stage2']['temperature']=1
 with pytest.raises(ValueError,match='parameters'):
  evaluate_memories(ROOT,CASE,{},provider,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),repeats=1,config=changed,rubric=rubric(),output=tmp_path/'bad')


def test_locked_snapshot_and_anchor_counts():
 lock=verify_lock(BASE);assert len(lock['stage2_frozen_hashes'])==21
 a=frozen_anchors(BASE);assert a['denominator_per_cell']==3 and a['coding']['B1']['A']==2/3


def test_provider_failure_usage_unknown_not_zero(tmp_path):
 class Broken(MockProvider):
  def __call__(self,*args,**kwargs):raise EnvError('offline provider failure')
 guard=BudgetGuard(100000,enabled=True)
 evaluate_memories(ROOT,CASE,{'lc':LongContextConcatAdapter()},Broken(),Utf8BoundTokenizer(),guard,
  repeats=1,config=read(Path('benchmark4/harness/config.yaml')),rubric=read(BASE/'whitebox_rubric.json'),output=tmp_path/'error',coding_executor=lambda *a:pytest.fail('must not start coding'))
 report=read(tmp_path/'error/report.json')
 assert report['usage']['total_tokens'] is None and report['usage']['known_tokens']==0
 assert report['usage']['unconfirmed_usage'] and report['budget_accounted_tokens']>0
 assert report['methods']['lc']['blackbox']['outcomes']['qa']['env_error']==1


@pytest.mark.parametrize('judge_env_error',[False,True])
def test_frozen_coding_bridge_uses_memory_and_cleans_without_docker(tmp_path,monkeypatch,judge_env_error):
 import benchmark4.harness.memory_coding as module
 closed=[];prompts=[]
 class FakeSandbox:
  def __init__(self,repository,profile_config,profile,**kwargs):
   self.repo=Path(repository);self.worker='ctm-offline-worker'
   assert profile=='A_static' and kwargs['workspace_image'].startswith('sha256:')
  def __enter__(self):return self
  def __exit__(self,*args):self.close()
  def close(self):closed.append(True)
  def exec(self,args):return {'returncode':0,'text':''}
  def judge(self,*args,**kwargs):
   if judge_env_error:raise EnvError('mock judge unavailable')
   return {'returncode':0,'collected':3,'failed':0,'skipped':0,'errors':0,'passed_tests':['one','two','three']}
 monkeypatch.setattr(module,'EvidenceSandbox',FakeSandbox)
 monkeypatch.setattr(module,'cleanup_probe',lambda prefix:{'prefix':prefix,'passed':True,'residue':{'container':[],'network':[],'volume':[]}})
 def provider(prompt,*,max_output):
  prompts.append(prompt)
  return {'text':'{"tool":"finish","arguments":{}}','usage_tokens':4}
 executor=module.FrozenCodingExecutor(ROOT,CASE)
 seed=read(ROOT/'seeds'/f'{CASE}.yaml')
 result=executor(seed,'MEMORY_CONTEXT_UNIQUE','A',provider,Utf8BoundTokenizer(),BudgetGuard(100000,enabled=True),tmp_path/'coding')
 assert result['outcome']==('env_error' if judge_env_error else 'pass')
 assert closed and result['cleanup']['passed']
 assert 'MEMORY_CONTEXT_UNIQUE' in prompts[0]
 assert seed['qa']['anchor_contexts'].get('MEMORY') is None
 assert (tmp_path/'coding/candidate.patch').exists()
 assert len(read(tmp_path/'coding/candidate_hashes.json'))==10
