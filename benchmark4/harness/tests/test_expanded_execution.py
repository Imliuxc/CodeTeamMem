import json
import pytest
from test_stage2 import session,provider
from benchmark4.harness.run_coding_calibration import coding_session,coding_prompt
from benchmark4.harness.run_qa_calibration import stage1_config
from benchmark4.harness.budget_guard import BudgetGuard,BudgetExceeded
from benchmark4.harness.stage1_provider import Utf8BoundTokenizer
from benchmark4.harness.memory_adapters.baselines import NaiveChunkRAGAdapter
from benchmark4.harness.memory_scoring import whitebox_score


def execute(session,actions):
 s,t,b=session
 return coding_session(s,t,b,provider([json.dumps(a) for a in actions]),Utf8BoundTokenizer(),BudgetGuard(6000000,enabled=True),stage1_config()['stage2'],'B2','A')


def test_large_input_limit_is_used():
 tok=Utf8BoundTokenizer();g=BudgetGuard(6000000,enabled=True)
 assert len(coding_prompt({'instruction':'x'*30000},[],tok).encode())>24000
 g.call(lambda p,**kw:{'text':'ok','usage_tokens':30001},'x'*30000,tokenizer=tok,max_output=2,truncate=False)
 with pytest.raises(BudgetExceeded):g.call(lambda *a,**k:pytest.fail('provider must not run'),'x'*48001,tokenizer=tok,max_output=1,truncate=False)


def test_new_files_do_not_count_as_same_error(session):
 s,t,b=session;acts=[]
 for i in range(20):
  (b.repo/f'f{i}.py').write_text(f'x={i}')
  acts.append({'tool':'read','arguments':{'path':f'f{i}.py'}})
 acts += [{'tool':'write','arguments':{'path':'slot.py','content':'def f():\n    return 2\n'}},{'tool':'finish'}]
 r=execute(session,acts);assert r['outcome']=='pass' and r['turns']==22
 assert r['log'][19]['progress']['stalled']==0 and r['log'][19]['progress']['no_edit_warning']


def test_repeated_read_six_stalls_and_feedback(session):
 act={'tool':'read','arguments':{'path':'slot.py'}}
 r=execute(session,[act]*7);assert 'repeated same' in r['reason'] and r['turns']==7
 f=r['log'][1]['tool_result'];assert f['repeated_observation'] and f['progress']['remaining_stall']==5


def test_fifty_round_hard_stop(session):
 acts=[{'tool':'write','arguments':{'path':'slot.py','content':f'def f():\n    return {i+2}\n'}} for i in range(50)]
 r=execute(session,acts);assert r['turns']==50 and r['reason']=='turn limit'


def test_feedback_and_finish_confirmation_reach_native_history(session):
 s,t,b=session;seen=[];n=[]
 acts=[{'tool':'write','arguments':{'path':'slot.py','content':'\n'+(b.repo/'slot.py').read_text()}},{'tool':'finish'},{'tool':'finish','arguments':{'reason':'No functional change intended in this fixture.'}}]
 def model(prompt,**kwargs):
  seen.append(json.loads(prompt));a=acts[len(seen)-1]
  return {'text':json.dumps(a),'usage_tokens':20}
 r=coding_session(s,t,b,model,Utf8BoundTokenizer(),BudgetGuard(6000000,enabled=True),stage1_config()['stage2'],'B2','A')
 assert r['outcome']=='pass' and not r['semantic_modified'] and r['no_change_reason']
 f=json.loads(seen[1]['input'][-1]['output']);assert f['semantic_changed'] is False and 'AST' in f['notice'] and f['written_content_preview']
 assert 'No semantic change' in json.loads(seen[2]['input'][-1]['output'])['notice']
 for request in seen:
  for i in range(1,len(request['input']),2):assert request['input'][i]['call_id']==request['input'][i+1]['call_id']


def test_retrieved_support_distinct_from_store_and_fragments_labeled():
 a=NaiveChunkRAGAdapter(chunk_chars=600,top_k=1)
 a.ingest([{'sequence':0,'kind':'dialogue','text':'rule rule rule'},{'sequence':1,'kind':'dialogue','text':'premise boundary reject bad'}])
 text=a.retrieve('rule');assert 'FRAGMENT' in text and 'chars=' in text and 'may be incomplete' in text
 rubric={k:[{'id':k,'pattern':v}] for k,v in [('rule','rule'),('key_premise','premise'),('scope_boundary','boundary')]}
 rubric['dead_end']=[{'id':'bad','denied_pattern':'reject bad','active_pattern':'use bad'}]
 gold={k:k for k in rubric}
 stored=whitebox_score(a.dump_memories(),gold,rubric);retrieved=whitebox_score(a.retrieved_memories,gold,rubric)
 assert stored['key_premise_completeness']==1 and retrieved['key_premise_completeness']==0
 assert retrieved['dead_end_assessed_coverage']==0 and retrieved['evidence']['dead_end'][0]['status']=='unknown'


def test_no_edit_warn15_stop25_with_distinct_reads(session):
 s,t,b=session;acts=[]
 for i in range(25):
  (b.repo/f'new{i}.py').write_text('x=1')
  acts.append({'tool':'read','arguments':{'path':f'new{i}.py'}})
 r=execute(session,acts)
 assert r['turns']==25 and 'no valid code edit' in r['reason']
 assert r['log'][14]['progress']['no_edit_warning']
 assert r['log'][23]['progress']['stalled']==0


def test_trial_budget_and_batch_budget_both_enforced():
 g=BudgetGuard(1000000,enabled=True);child=g.scope(300000);tok=Utf8BoundTokenizer()
 child.call(lambda *a,**k:{'text':'ok','usage_tokens':100},'x',tokenizer=tok,max_output=100)
 assert g.spent==child.spent==100
 child.spent=299999
 with pytest.raises(BudgetExceeded):child.call(lambda *a,**k:pytest.fail('must stop before call'),'xx',tokenizer=tok,max_output=1)
 assert g.spent==100


def test_six_identical_public_errors_stop_exactly():
 from benchmark4.harness.run_coding_calibration import CodingProgress
 p=CodingProgress('base',stall_limit=6,exploration_limit=None)
 for i in range(5):
  row=p.observe('base',['base::one'],error_key=('same_failure','base'),valid_edit=False,is_error=True)
  assert row['stalled']==i+1
 with pytest.raises(BudgetExceeded,match='repeated same'):
  p.observe('base',['base::one'],error_key=('same_failure','base'),valid_edit=False,is_error=True)


def test_shared_frozen_config():
 import hashlib
 from pathlib import Path
 from benchmark4.harness.common import read
 p=Path(__file__).resolve().parents[1]/'config.yaml'
 cfg=read(p);f=read(p.with_name('config.freeze.json'))
 assert hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256']
 assert cfg['stage1']['max_input_tokens']==cfg['stage2']['max_input_tokens']==48000
 assert cfg['stage2']['max_turns']==50 and cfg['execution']['trial_token_limit']==300000
 assert cfg['stage2']['no_edit_warn']==15 and cfg['stage2']['no_edit_stop']==25 and cfg['stage2']['stall_limit']==6
