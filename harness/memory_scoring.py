"""Auditable local rubric scores and paired task metrics; no model or Docker."""
import json
import re
from copy import deepcopy

BUSINESS={'pass','model_wrong','parse_error'}
OUTCOMES=('pass','model_wrong','parse_error','env_error','budget_stop','not_run')


def whitebox_score(memories,gold,rubric):
    fields=('rule','key_premise','scope_boundary','dead_end')
    if any(not gold.get(k) or not rubric.get(k) for k in fields):raise ValueError('complete Gold-aligned rubric required')
    if not isinstance(memories,(list,str)):raise ValueError('dump_memories must be text or JSON list')
    units=[{'text':memories}] if isinstance(memories,str) else deepcopy(memories)
    for r in units:
        if isinstance(r,str):continue
        if not isinstance(r,dict) or not isinstance(r.get('text'),str):raise ValueError('memory text required')
    texts=[r if isinstance(r,str) else r['text'] for r in units]
    corpus='\n'.join(texts);details={};rates={}
    for field in fields[:3]:
        atoms=rubric[field]
        if len({a['id'] for a in atoms})!=len(atoms):raise ValueError('duplicate rubric atom')
        found=[]
        for atom in atoms:
            match=re.search(atom['pattern'],corpus,re.I|re.S)
            excluded=bool(atom.get('exclude_pattern') and re.search(atom['exclude_pattern'],corpus,re.I|re.S))
            found.append({'id':atom['id'],'supported':bool(match) and not excluded,
                          'evidence':match.group() if match and not excluded else None,
                          'status':'supported' if match and not excluded else 'unmatched_or_ambiguous'})
        details[field]=found;rates[field]=sum(x['supported'] for x in found)/len(found)
    dead=[]
    for atom in rubric['dead_end']:
        verdict='unknown';evidence=None
        for row,text in zip(units,texts):
            # Tool responses and diffs are observations/code, not active policies.
            if isinstance(row,dict) and row.get('kind') not in (None,'dialogue','memory'):continue
            for sentence in re.split(r'[。！？!?\n]',text):
                denial=re.search(atom['denied_pattern'],sentence,re.I)
                affirmation=re.search(atom['active_pattern'],sentence,re.I)
                if denial:verdict,evidence='denied',sentence
                elif affirmation and not re.search(r'不|否决|拒绝|不能|别|先不|提议|候选|是否|\?',sentence):
                    verdict,evidence='active',sentence
        dead.append({'id':atom['id'],'status':verdict,'evidence':evidence})
    details['dead_end']=dead
    return {'rule_recall':rates['rule'],'key_premise_completeness':rates['key_premise'],
            'scope_boundary_completeness':rates['scope_boundary'],
            'dead_end_pollution_rate':sum(x['status']=='active' for x in dead)/len(dead),
            'dead_end_assessed_coverage':sum(x['status']!='unknown' for x in dead)/len(dead),
            'denominators':{k:len(rubric[k]) for k in fields},'evidence':details,
            'method':'versioned deterministic regex atoms; unmatched is unproven, not semantic falsity; last explicit chat/memory verdict per rejected option',
            'scope':'stored memory support, not retrieval quality; raw history baselines retain original messages'}


def paired_metrics(records,anchors,repeats):
    if type(repeats) is not int or repeats<1:raise ValueError('positive repeats required')
    keys=[(r['context'],r['repeat']) for r in records]
    if len(set(keys))!=len(keys) or any(c not in 'ABC' or not 1<=n<=repeats for c,n in keys):raise ValueError('invalid/duplicate trial')
    tables={};outcomes={};complete=len(records)==3*repeats
    for phase in ('qa','coding'):
        tables[phase]={};outcomes[phase]={k:0 for k in OUTCOMES}
        for c in 'ABC':
            rows=[r[phase] for r in records if r['context']==c]
            if any(x['outcome'] not in OUTCOMES for x in rows):raise ValueError('unknown outcome')
            for row in rows:outcomes[phase][row['outcome']]+=1
            eligible=[r for r in rows if r['outcome'] in BUSINESS]
            n=len(eligible);passed=sum(r['outcome']=='pass' for r in eligible)
            done=n==repeats
            tables[phase][c]={'passed':passed,'denominator':n,'planned':repeats,'rate':passed/n if n else None,'complete':done}
            complete=complete and done
    pairs=[r for r in records if r['qa']['outcome'] in BUSINESS and r['coding']['outcome'] in BUSINESS]
    gap=sum((r['qa']['outcome']=='pass')-(r['coding']['outcome']=='pass') for r in pairs)/len(pairs) if pairs else None
    failures=[deepcopy(r) for r in pairs if r['qa']['outcome']=='pass' and r['coding']['outcome']!='pass']
    def differences(phase,anchor,sign):
        return {c:sign*(tables[phase][c]['rate']-anchors[phase][anchor][c]) if tables[phase][c]['rate'] is not None else None for c in 'ABC'}
    cc=tables['coding']['C']['rate'];cq=tables['qa']['C']['rate']
    return {'complete':complete,'rates':tables,'outcomes':outcomes,
            'qa_net_gain_over_b0':differences('qa','B0',1),'coding_net_gain_over_b0':differences('coding','B0',1),
            'qa_gap_to_b2':differences('qa','B2',-1),'coding_gap_to_b2':differences('coding','B2',-1),
            'paired_qa_minus_coding':gap,'paired_denominator':len(pairs),'qa_pass_coding_fail':failures,
            'c_failure_counts':{p:{k:sum(r['context']=='C' and r[p]['outcome']==k for r in records) for k in OUTCOMES if k!='pass'} for p in ('qa','coding')},
            'negative_transfer':{'qa_b0_minus_memory_c':anchors['qa']['B0']['C']-cq if cq is not None else None,
                                 'coding_b0_minus_memory_c':anchors['coding']['B0']['C']-cc if cc is not None else None,
                                 'matched_b0_harm_count':None,'interpretation':'signed aggregate difference from independent frozen anchors; no paired causal harm estimate'},
            'interpretation':'single case, finite repeated trials; incomplete cells provisional and excluded from ranking'}


def save_leaderboard(output,methods,anchors):
    from pathlib import Path
    from .common import write
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    rows=[];errors=[]
    for name,report in methods.items():
        m=report['blackbox'];errors.extend(dict(r,method=name) for r in m['qa_pass_coding_fail'])
        coding=sum(m['rates']['coding'][c]['rate'] for c in 'ABC')/3 if m['complete'] else None
        qa=sum(m['rates']['qa'][c]['rate'] for c in 'ABC')/3 if m['complete'] else None
        rows.append({'method':name,'eligible':m['complete'],'coding_macro':coding,'qa_macro':qa,
                     'paired_qa_minus_coding':m['paired_qa_minus_coding'],'whitebox':report['whitebox'],'store_support':report.get('store_support',report['whitebox']),'retrieval_support':[{'context':x['context'],'repeat':x['repeat'],'scores':x.get('retrieval_support')} for x in report.get('records',[])],'structured_extraction':report.get('structured_extraction',{'status':'not_applicable'}),'cost':report['cost']})
    rows.sort(key=lambda r:(not r['eligible'],-(r['coding_macro'] or 0),-(r['qa_macro'] or 0),r['method']))
    board={'rows':rows,'anchors_reused':anchors,'case_count':1,'interpretation':'descriptive single-case leaderboard; no population/generalization claim'}
    write(output/'leaderboard.json',board);write(output/'qa_pass_coding_fail.json',errors)
    lines=['| Method | QA | Coding | Paired QA−Coding | Tokens |','|---|---:|---:|---:|---:|']
    for r in rows:
        values=[r[k] for k in ('qa_macro','coding_macro','paired_qa_minus_coding')]
        lines.append('| '+r['method']+' | '+' | '.join('incomplete' if v is None else f'{v:.3f}' for v in values)+' | '+str(r['cost'].get('total_tokens'))+' |')
    (output/'leaderboard.md').write_text('\n'.join(lines)+'\n')
    return board
