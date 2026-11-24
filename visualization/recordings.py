"""Read-only index of persisted QA requests. Never reconstruct or execute a prompt."""
import hashlib
import json
from pathlib import Path

DATASETS = Path(__file__).resolve().parents[1] / 'datasets'
CALL_FIELDS = ('anchor','context','repeat','prompt','raw_answer','expected','parsed','outcome',
               'usage_tokens','input_tokens','output_tokens','response_id','response_status','error','stop_reason')
CONFIG_FIELDS = ('repeats','max_output_tokens','max_input_tokens','prompt_overhead_tokens','temperature','infrastructure_retries')
INFO_FIELDS = ('started_at_utc','finished_at_utc','model','api_style','thinking','tools','store',
               'temperature','max_output_tokens','stage_token_limit','status')


class Recordings:
    def __init__(self, root=DATASETS): self.root = Path(root).resolve()

    def paths(self):
        return {hashlib.sha256(str(p.relative_to(self.root)).encode()).hexdigest()[:16]:p
                for p in sorted(self.root.glob('**/qa_calibration_runs/*.json'))
                if p.resolve().is_relative_to(self.root) and p.is_file()}

    def load(self, id):
        path = self.paths().get(id)
        if path is None: raise KeyError('unknown recording')
        report = json.loads(path.read_text())
        if not isinstance(report,dict) or not isinstance(report.get('records'),list):
            raise ValueError('recording has no records array')
        if any(not isinstance(r,dict) for r in report['records']): raise ValueError('invalid request record')
        return path,report

    def optional(self, path):
        if not path.is_file() or not path.resolve().is_relative_to(self.root): return {}
        try:
            value=json.loads(path.read_text())
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError): return {}

    def summary(self, id):
        path, report = self.load(id)
        base = path.parent.parent
        info = self.optional(base/'run_info.json')
        state = self.optional(base/'factory_state.json')
        calls = report['records']
        outcomes = {}
        for r in calls:
            key = r.get('outcome','unrecorded')
            outcomes[key] = outcomes.get(key,0)+1
        cells=[]; warnings=[]
        for anchor in ('B0','B1','B2'):
            for context in ('A','B','C'):
                rows=[r for r in calls if r.get('anchor')==anchor and r.get('context')==context]
                rate=report.get('scores',{}).get(anchor,{}).get(context)
                passed=sum(r.get('outcome')=='pass' for r in rows)
                cells.append({'anchor':anchor,'context':context,'recorded':len(rows),'passed':passed,
                              'saved_score':rate,'declared_denominator':report.get('denominator_per_cell')})
                if rate is not None and rows and isinstance(rate,(int,float)) and abs(rate-passed/len(rows))>1e-9:
                    warnings.append(f'{anchor}/{context}: saved score disagrees with recorded outcomes; showing both without rescoring')
        return {'id':id,'path':str(path.relative_to(self.root)), 'case_id':report.get('case_id',base.name),
                'attempt':path.stem,'stage':report.get('stage',1),'scope':report.get('scope'),
                'provider_type':report.get('provider_type'), 'model':report.get('provider_model'),
                'complete':report.get('complete'),'passed':report.get('passed'),
                'call_count':len(calls),'outcomes':outcomes,'usage_tokens':report.get('usage_tokens'),
                'budget_accounted_tokens':report.get('budget_accounted_tokens'),
                'request_config':{k:report['request_config'][k] for k in CONFIG_FIELDS if k in (report.get('request_config') or {})},'cells':cells,'warnings':warnings,
                'run_info':{k:info[k] for k in INFO_FIELDS if k in info},
                # Case state may have advanced after this attempt: keep it explicitly separate.
                'current_case_state':{k:state[k] for k in ('stage','status','gate') if k in state},
                'seed_hash':report.get('seed_hash'),'policy_hash':report.get('policy_hash'),
                'schema_hash':report.get('schema_hash'),
                'source':'persisted_qa_requests','error':None}

    def list(self):
        values=[]
        for id,path in self.paths().items():
            try:
                full=self.summary(id)
                values.append({k:full[k] for k in ('id','path','case_id','attempt','model','call_count','complete','passed','error')})
            except (OSError,ValueError,TypeError,AttributeError) as exc:
                values.append({'id':id,'path':str(path.relative_to(self.root)),'case_id':path.parent.parent.name,
                               'attempt':path.stem,'error':f'Unreadable saved recording ({type(exc).__name__})'})
        return sorted(values,key=lambda r:r['path'],reverse=True)

    def calls(self,id,*,anchor=None,context=None,outcome=None):
        _,report=self.load(id)
        result=[]
        for index,row in enumerate(report['records']):
            if any(v and row.get(k)!=v for k,v in [('anchor',anchor),('context',context),('outcome',outcome)]): continue
            result.append({'index':index,**{k:row[k] for k in CALL_FIELDS if k in row and k not in ('prompt','raw_answer','expected','parsed')}})
        return result

    def call(self,id,index):
        _,report=self.load(id)
        if index<0 or index>=len(report['records']): raise KeyError('unknown request index')
        row=report['records'][index]
        return {'index':index,**{k:row[k] for k in CALL_FIELDS if k in row},
                'availability':{k:k in row and row[k] is not None for k in ('prompt','raw_answer','expected','parsed')},
                'provenance':'Fields are read from saved request record verbatim; missing fields are not reconstructed.'}
