"""Opt-in, provider-injected budget guard; importing never calls a model."""
from dataclasses import dataclass
import hashlib
from .limits import INPUT_CAP,MAX_TURNS,STALL_LIMIT


class BudgetExceeded(RuntimeError): pass


@dataclass
class BudgetGuard:
    total_tokens: int
    enabled: bool = False
    spent: int = 0
    input_cap: int = INPUT_CAP
    tripped: bool = False
    parent: object = None

    def scope(self, limit):
        return BudgetGuard(limit,enabled=self.enabled,input_cap=self.input_cap,parent=self)

    def call(self, provider, prompt, *, tokenizer, max_output=1024, prompt_overhead=0, truncate=True):
        if not self.enabled: raise RuntimeError('model calls disabled')
        if self.tripped: raise BudgetExceeded('budget circuit open')
        if type(prompt_overhead) is not int or not 0 <= prompt_overhead < self.input_cap:
            raise ValueError('invalid prompt overhead')
        encoded = tokenizer.encode(prompt)
        cap = self.input_cap - prompt_overhead
        if not truncate and len(encoded) > cap:
            raise BudgetExceeded('input too long; refusing to truncate Stage 1 evidence')
        ids = encoded[:cap]
        prompt = tokenizer.decode(ids)
        # Retokenization protects against a non-roundtripping tokenizer.
        count = len(tokenizer.encode(prompt))
        reserve = count + prompt_overhead + max_output
        if max_output <= 0 or count > self.input_cap or self.spent + reserve > self.total_tokens:
            raise BudgetExceeded('token budget exhausted')
        chain=[]; node=self
        while node is not None:
            if node.tripped or node.spent+reserve>node.total_tokens:raise BudgetExceeded('token budget exhausted')
            chain.append(node);node=node.parent
        for node in chain:node.spent+=reserve
        result = provider(prompt, max_output=max_output)
        used = result['usage_tokens']
        minimum = 0 if getattr(tokenizer, 'conservative_bound', False) else count
        if type(used) is not int or not minimum <= used <= reserve:
            for node in chain:node.tripped=True
            if type(used) is int and used > reserve:
                for node in chain:node.spent+=used-reserve  # never hide measured overrun
            raise BudgetExceeded('invalid/excess provider usage')
        for node in chain:node.spent-=reserve-used
        return result['text']


def pages(text, size=4096):
    if not 1 <= size <= 4096: raise ValueError('page cap is 4KB')
    # Split by Unicode codepoint while keeping every encoded page within cap.
    page = ''
    for char in text:
        if len(char.encode()) > size: raise ValueError('page too small for character')
        if len((page + char).encode()) > size:
            yield page; page = ''
        page += char
    if page: yield page


class ProgressGuard:
    def __init__(self, max_turns=MAX_TURNS, stall_limit=STALL_LIMIT):
        if type(max_turns) is not int or max_turns < 1: raise ValueError('positive turn cap required')
        self.max_turns, self.stall_limit = max_turns, stall_limit
        self.turns = self.stalled = 0
        self.seen = set()

    def observe(self, *, diff, passed_tests):
        self.turns += 1
        # Tool chatter is excluded; repeated/cycling diffs are not progress.
        key = (hashlib.sha256(diff.encode()).hexdigest(), tuple(sorted(passed_tests)))
        if key in self.seen: self.stalled += 1
        else: self.seen.add(key); self.stalled = 0
        if self.turns > self.max_turns or self.stalled >= self.stall_limit:
            raise BudgetExceeded('turn/stall circuit open')
