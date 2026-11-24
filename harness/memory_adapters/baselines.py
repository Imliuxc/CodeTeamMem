"""Minimal controls; B2 privileged full history is an oracle, not a memory method."""
from copy import deepcopy
import re
from .base import MemoryAdapter


class LongContext(MemoryAdapter):
    def __init__(self): self.events = []
    def ingest(self, events): self.events.extend(deepcopy(list(events)))
    def retrieve(self, query, limit=10): return deepcopy(self.events[-limit:]) if limit > 0 else []
    def dump_memories(self): return deepcopy(self.events)


class B0(LongContext):
    def ingest(self, events): pass


class B1(LongContext):
    """Initialize with frozen earlier consensus; later history cannot overwrite it."""
    def __init__(self, stale_events):
        super().__init__()
        self.events = deepcopy(list(stale_events))
    def ingest(self, events): pass


class B2(LongContext):
    def retrieve(self, query, limit=None): return self.dump_memories()


class NaiveRAG(LongContext):
    def retrieve(self, query, limit=10):
        terms = set(re.findall(r'\w+', query.casefold()))
        ranked = sorted(enumerate(self.events), key=lambda p: (-len(terms & set(re.findall(r'\w+', p[1].get('text','').casefold()))), p[0]))
        return deepcopy([e for _,e in ranked[:max(0,limit)]])


# Real, dependency-free Memory baselines. Legacy controls above remain technical fixtures.
def public_events(events):
    rows=[]
    for event in events:
        if not isinstance(event.get('text'),str):raise ValueError('public event text required')
        rows.append(deepcopy({k:event[k] for k in ('sequence','kind','role','act','text') if k in event}))
    if rows and all(type(r.get('sequence')) is int for r in rows):
        if len({r['sequence'] for r in rows})!=len(rows):raise ValueError('duplicate timeline sequence')
        rows.sort(key=lambda r:r['sequence'])
    return rows


def render_event(event):
    return '['+' / '.join(str(event[k]) for k in ('sequence','kind','role') if k in event)+']\n'+event['text']


class LongContextConcatAdapter(MemoryAdapter):
    def __init__(self):self.events=[]
    def ingest(self,events):self.events.extend(public_events(events))
    def retrieve(self,query,limit=10):
        self.retrieved_memories=deepcopy(self.events) if limit is None or limit>0 else []
        return '\n\n'.join(render_event(r) for r in self.retrieved_memories)
    def dump_memories(self):return deepcopy(self.events)


class NaiveChunkRAGAdapter(MemoryAdapter):
    """Unicode character chunks + ASCII terms/CJK bigrams + cosine TF-IDF.

    Ties use ingestion order. Selected chunks are returned in historical order.
    No model, embedding service, randomized hash or third-party tokenizer.
    """
    def __init__(self,chunk_chars=600,overlap=80,top_k=6):
        if not 0<=overlap<chunk_chars or top_k<1:raise ValueError('invalid chunk/RAG limits')
        self.chunk_chars,self.overlap,self.top_k=chunk_chars,overlap,top_k
        self.chunks=[];self.last_retrieval=[]
    @staticmethod
    def terms(text):
        terms=re.findall(r'[a-z0-9_]+',text.casefold())
        for span in re.findall(r'[\u3400-\u9fff]+',text):
            terms.extend(span);terms.extend(span[i:i+2] for i in range(len(span)-1))
        return terms
    def ingest(self,events):
        for event in public_events(events):
            text=render_event(event)
            for start in range(0,len(text),self.chunk_chars-self.overlap):
                row={k:v for k,v in event.items() if k!='text'}
                row.update(id=len(self.chunks),start=start,end=min(start+self.chunk_chars,len(text)),source_chars=len(text),text=text[start:start+self.chunk_chars])
                self.chunks.append(row)
                if start+self.chunk_chars>=len(text):break
    def retrieve(self,query,limit=10):
        import math
        from collections import Counter
        k=self.top_k if limit is None else min(self.top_k,max(0,limit))
        if not k or not self.chunks:self.last_retrieval=[];return ''
        docs=[Counter(self.terms(c['text'])) for c in self.chunks];q=Counter(self.terms(query))
        df=Counter(t for doc in docs for t in doc);n=len(docs)
        idf={t:math.log((n+1)/(count+1))+1 for t,count in df.items()}
        def vector(counts):return {t:(1+math.log(c))*idf[t] for t,c in counts.items() if t in idf}
        qv=vector(q);qn=math.sqrt(sum(x*x for x in qv.values()))
        ranked=[]
        for i,doc in enumerate(docs):
            v=vector(doc);norm=math.sqrt(sum(x*x for x in v.values()))
            value=sum(x*qv.get(t,0) for t,x in v.items())/(norm*qn) if norm and qn else 0
            ranked.append((i,value))
        selected=sorted(sorted(ranked,key=lambda x:(-x[1],x[0]))[:k])
        self.last_retrieval=[{'chunk_id':i,'score':v} for i,v in selected]
        self.retrieved_memories=deepcopy([self.chunks[i] for i,_ in selected])
        return '\n\n'.join(f"[FRAGMENT chunk={c['id']} event={c.get('sequence')} kind={c.get('kind')} role={c.get('role')} chars={c['start']}:{c['end']}/{c['source_chars']}; may be incomplete, including JSON/code]\n"+c['text']+'\n[END FRAGMENT]' for c in self.retrieved_memories)
    def dump_memories(self):return deepcopy(self.chunks)
