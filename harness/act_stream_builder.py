"""Trusted controller: speaker-private facts, public event timeline, bounded turns."""
from copy import deepcopy
import re
from .run_qa_calibration import score
from .stream_vocabulary import (BASICS, scalar_tokens, identifiers, future_only,
                                validate_references, TurnValidationError)

BANNED = ('团队记忆','关键前提','适用边界','废案','反事实','锚点','总结')


class ActExhausted(ValueError): pass


def t0_vocabulary(payload):
    """Compatibility return shape; all JSON keys and scalars share one set."""
    return scalar_tokens(payload), set()


def owner(fact):
    if fact.get('owner', fact.get('role')) != fact.get('role', fact.get('owner')):
        raise ValueError('conflicting fact owner')
    return fact.get('owner', fact.get('role'))


class FactLedger:
    def __init__(self, facts):
        self.__facts = deepcopy(facts)
        if len({f['id'] for f in facts}) != len(facts): raise ValueError('duplicate fact id')
        for f in facts:
            if not owner(f): raise ValueError('fact owner required')

    def view(self, act, speaker=None):
        # speaker=None is trusted controller inspection, never a generation view.
        return deepcopy([f for f in self.__facts if f['unlock_act'] <= act
                         and (speaker is None or owner(f) == speaker)])


class ActStateMachine:
    def __init__(self, acts):
        self.acts, self.index, self.turns, self.covered = deepcopy(acts), 0, 0, set()
        if not acts or any(not 1 <= a['min_turns'] <= a['max_turns'] for a in acts):
            raise ValueError('invalid act bounds')

    @property
    def done(self): return self.index == len(self.acts)

    @property
    def act(self):
        if self.done: raise ValueError('stream already complete')
        return self.acts[self.index]

    def advance(self, facts):
        act = self.act
        if act['exit_condition'] != 'fact_ids': raise ValueError('unsupported exit condition')
        self.turns += 1
        self.covered.update(facts)
        ready = set(act['required_facts']) <= self.covered
        if self.turns >= act['min_turns'] and ready:
            self.index += 1; self.turns = 0; self.covered.clear()
        elif self.turns >= act['max_turns']:
            raise ActExhausted('act exhausted without exit condition')


def validate_turn(text, symbols, banned=(), literals=(), denied=()):
    if not isinstance(text,str): raise ValueError('text required')
    if re.search(r'(?m)(?:^|\s)(?:[-*+•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*', text):
        raise TurnValidationError('bullet/list summary',re.findall(r'(?:\d+[.)、]|[-*+•])',text))
    hits=[w for w in (*BANNED,*banned) if w.casefold() in text.casefold()]
    if hits:raise TurnValidationError('banned meta word',hits)
    sentences = [s.strip() for s in re.split(r'[。！？!?]|(?<!\w)\.(?!\w)|\.(?=\s|$)', text) if s.strip()]
    if not 1 <= len(sentences) <= 3 or any(len(s) > 160 for s in sentences):
        raise TurnValidationError('requires 1..3 short sentences',[f'sentences={len(sentences)}',f'max_chars={max(map(len,sentences),default=0)}'])
    return validate_references(text,set(symbols)|set(literals),denied)


class ActStreamSession:
    def __init__(self, seed, symbols, *, snapshot=None, on_event=None, events=(),
                 max_regenerations=2, fact_check=None):
        self.seed, self.base_symbols = deepcopy(seed), set(symbols)
        self.symbols, self.literals = set(symbols), set()
        self.denied = future_only(seed)
        self.ledger = FactLedger(seed['facts'])
        self.machine = ActStateMachine(seed['acts'])
        self.stream, self.public_stream, self.rejections = [], [], []
        self.events = deepcopy(list(events)); self.injected = set()
        self.on_event = on_event or (lambda event: None)
        self.max_regenerations, self.fact_check = max_regenerations, fact_check
        if type(max_regenerations) is not int or max_regenerations < 0: raise ValueError('invalid regeneration bound')
        for e in self.events:
            if e['kind'] not in {'tool_log','git_diff','pytest','pr_review'}: raise ValueError('unknown event')
            if 'act' in e:
                if e['act'] not in {a['id'] for a in seed['acts']}: raise ValueError('unknown event act')
            elif type(e.get('after_turn')) is not int or e['after_turn'] < 0: raise ValueError('invalid event position')
        for row in (snapshot or {}).get('dialogue', []):
            self._inject(); self._accept(deepcopy(row))
        self.rejections = deepcopy((snapshot or {}).get('rejections',[]))

    @property
    def done(self): return self.machine.done

    def _inject(self):
        for i,event in enumerate(self.events):
            due = (not self.done and event.get('act') == self.machine.act['id']) if 'act' in event else event['after_turn'] == len(self.stream)
            if due and i not in self.injected:
                self.injected.add(i)
                row=dict(deepcopy(event),sequence=len(self.public_stream))
                self.public_stream.append(row)
                self.symbols.update(event.get('public_symbols',[]))
                self.literals.update(event.get('public_literals',[]))
                self.on_event({'kind':'evidence_injected','event':deepcopy(row)})

    def speaker(self):
        act = self.machine.act
        missing = [f for f in act['required_facts'] if f not in self.machine.covered]
        facts = {f['id']: f for f in self.ledger.view(act['id'])}
        if missing: return owner(facts[missing[0]])
        # Satisfy min_turns without exposing another speaker's notes.
        return owner(facts[act['required_facts'][0]]) if act['required_facts'] else self.seed['roles'][self.machine.turns % len(self.seed['roles'])]

    def view(self):
        self._inject()
        speaker=self.speaker()
        return {'act':self.machine.act['id'],'speaker':speaker,
                'facts':self.ledger.view(self.machine.act['id'],speaker),
                'roles':list(self.seed['roles']), 'public_history':deepcopy(self.public_stream)}

    def allowed_symbols(self, speaker=None, act=None):
        speaker=speaker or self.speaker();act=act or self.machine.act['id']
        own=[f['text'] for f in self.ledger.view(act,speaker)]
        return (self.symbols|self.literals|BASICS|identifiers(own))-self.denied

    def _accept(self, turn, fact_check=None):
        act = self.machine.act['id']
        if turn.get('act',act) != act: raise ValueError('act timeline mismatch')
        if turn['role'] != self.speaker(): raise ValueError('unexpected speaker')
        facts = {f['id']:f for f in self.ledger.view(act,turn['role'])}
        if not isinstance(turn['fact_ids'],list) or len(set(turn['fact_ids']))!=len(turn['fact_ids']): raise ValueError('invalid fact ids')
        if not set(turn['fact_ids']) <= facts.keys(): raise ValueError('locked/foreign fact reference')
        validate_turn(turn['text'],self.allowed_symbols(turn['role'],act),
                      self.seed.get('banned_meta_words',[]),denied=self.denied)
        # In the real runner this checks public expression, not self-reported IDs.
        checker=fact_check or self.fact_check
        if checker and any(checker(facts[f],turn['text']) is not True for f in turn['fact_ids']):
            raise ValueError('fact not expressed in message')
        self.machine.advance(turn['fact_ids'])
        for fid in turn['fact_ids']:self.symbols.update(identifiers(facts[fid]['text']))
        row=dict(turn,kind='dialogue',act=act,sequence=len(self.stream))
        self.stream.append(row)
        self.public_stream.append({'kind':'dialogue','act':act,'role':row['role'],
                                   'text':row['text'],'sequence':len(self.public_stream)})

    def step(self, generate):
        if self.done: raise ValueError('stream already complete')
        view = self.view()
        for attempt in range(self.max_regenerations+1):
            before = self.snapshot()
            turn=None
            try:
                turn=generate(deepcopy(view))
                self._accept(turn)
                break
            except ActExhausted:
                self._restore(before)
                raise  # never regenerate/continue a max_turns failure
            except (ValueError,KeyError,TypeError) as exc:
                self._restore(before)
                self.rejections.append({'act':view['act'],'speaker':view['speaker'],
                                        'attempt':attempt+1,'reason':str(exc),
                                        'rule':getattr(exc,'rule',type(exc).__name__),
                                        'hits':getattr(exc,'hits',[])})
                if attempt == self.max_regenerations: raise ValueError('turn regeneration exhausted: '+str(exc)) from exc
                view['retry_reason']=str(exc)
                view['retry_feedback']={'rule':getattr(exc,'rule',type(exc).__name__),
                    'hits':getattr(exc,'hits',[]),'previous_output':deepcopy(turn),
                    'next_attempt':attempt+2,
                    'instruction':'修改上述命中内容；不要逐字重发被拒绝文本。重新输出完整JSON，保留正确内容且不增加不可见信息。'}
        event={'kind':'turn_completed','turn':deepcopy(self.stream[-1]),'progress':self.progress()}
        self.on_event(deepcopy(event));return event

    def _restore(self, snapshot):
        clean=ActStreamSession(self.seed,self.base_symbols,snapshot=snapshot,events=self.events,
                               max_regenerations=self.max_regenerations)
        clean._inject()
        self.machine,self.stream,self.public_stream,self.injected=clean.machine,clean.stream,clean.public_stream,clean.injected
        self.symbols,self.literals=clean.symbols,clean.literals
        self.rejections=clean.rejections

    def snapshot(self): return {'dialogue':deepcopy(self.stream),'rejections':deepcopy(self.rejections)}

    def progress(self):
        if self.done:
            return {'act':self.seed['acts'][-1]['id'],'turns':None,'total_turns':len(self.stream),
                    'done':True,'facts_met':True,'exit_met':True}
        a=self.machine.act
        return {'act':a['id'],'turns':self.machine.turns,'total_turns':len(self.stream),
                'min_turns':a['min_turns'],'max_turns':a['max_turns'],'exit_condition':a['exit_condition'],
                'facts_met':set(a['required_facts'])<=self.machine.covered,
                'exit_met':self.machine.turns>=a['min_turns'] and set(a['required_facts'])<=self.machine.covered,'done':False}


def interleave(stream, events=()):
    """Legacy artifact formatting only; generation uses ActStreamSession.events."""
    for event in events:
        if event['kind'] not in {'tool_log','git_diff','pytest','pr_review'} or not 0 <= event['after_turn'] <= len(stream): raise ValueError('invalid timeline event')
    merged=[]
    for i in range(len(stream)+1):
        merged.extend(deepcopy(e) for e in events if e['after_turn']==i)
        if i<len(stream): merged.append(deepcopy(stream[i]))
    for i,event in enumerate(merged):event['sequence']=i
    return merged


def build(seed, symbols, generate, events=(), *, on_event=None, max_regenerations=2, fact_check=None):
    session=ActStreamSession(seed,symbols,on_event=on_event,events=events,
                             max_regenerations=max_regenerations,fact_check=fact_check)
    while not session.done: session.step(generate)
    session._inject()
    if len(session.injected)!=len(session.events):raise ValueError('unreached timeline event')
    # Artifact rows retain fact_ids for deterministic controller replay.
    rows=deepcopy(session.public_stream);turns=iter(session.stream)
    for i,row in enumerate(rows):
        if row['kind']=='dialogue':rows[i]=dict(next(turns),sequence=i)
    return rows


def verify(stream, symbols, banned, role_scores, full_score, expected_roles, *, seed=None):
    if len(expected_roles)<2 or 'pm_lead' not in expected_roles or set(role_scores)!=set(expected_roles): raise ValueError('blind-test role coverage required')
    dialogue=[r for r in stream if r['kind']=='dialogue']
    if not dialogue:raise ValueError('empty stream')
    active,literals=set(symbols),set()
    ledger=FactLedger(seed['facts']) if seed else None
    for row in stream:
        if row['kind']!='dialogue':
            active.update(row.get('public_symbols',[]));literals.update(row.get('public_literals',[]))
        else:
            own=ledger.view(row['act'],row['role']) if ledger else []
            validate_turn(row['text'],active|identifiers([f['text'] for f in own]),banned,literals,
                          future_only(seed) if seed else ())
            active.update(identifiers([f['text'] for f in own if f['id'] in row.get('fact_ids',[])]))
    if {r['role'] for r in dialogue}!=set(expected_roles):raise ValueError('missing participating role')
    if any(score(v)>1/3 for v in role_scores.values()) or score(full_score)<2/3:raise ValueError('single-role/full-stream information test failed')
    return {'symbol_alignment':1.0,'symbol_scope':'explicit backticks, known identifiers, snake_case and call syntax',
            'role_scores':role_scores,'full_score':full_score,'passed':True}
