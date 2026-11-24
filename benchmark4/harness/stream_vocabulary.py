"""Source-backed tokens; no model calls or future tokens in generation prompts."""
import re
from pathlib import PurePosixPath

BASICS = {'null','None','True','False','true','false','HTTP','JSON'}
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
PATH = re.compile(r'(?:\.?\.?/|/)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_-]+\.(?:py|jsonl?|ya?ml|md|txt|ini)\b')


def scalar_tokens(value):
    """Every JSON key and scalar, with stable JSON/Python boolean/null spellings."""
    result=set()
    def walk(v):
        if isinstance(v,dict):
            for k,x in v.items():result.add(str(k));walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
        elif v is None:result.update(('null','None'))
        elif type(v) is bool:result.update(('true','True') if v else ('false','False'))
        else:result.add(str(v))
    walk(value)
    return {x for x in result if x}


def identifiers(value):
    """Identifiers in public text/keys; entire prose is not a code identifier."""
    result=set()
    for text in scalar_tokens(value):
        result.update(IDENTIFIER.findall(text));result.update(PATH.findall(text))
    return result


def file_tokens(files):
    result=set()
    for name in files:
        p=PurePosixPath(name)
        result.update((p.as_posix(),p.name))
        if p.suffix=='.py':result.add('.'.join(p.with_suffix('').parts))
    return result


def future_only(seed):
    """Controller-only deny set, never serialized as generation instructions."""
    profiles=seed.get('external_profiles',{})
    old=profiles.get('T0_history',{}).get('default',{})
    changed=profiles.get('C_changed',{}).get('default',{})
    return scalar_tokens(changed)-scalar_tokens(old)-BASICS


class TurnValidationError(ValueError):
    def __init__(self,rule,hits=()):
        self.rule,self.hits=rule,sorted(set(hits))
        super().__init__(rule+(': '+', '.join(self.hits) if self.hits else ''))


def validate_references(text,symbols,denied=()):
    allowed=set(symbols)|BASICS
    forbidden=[v for v in denied if re.search(r'(?<![A-Za-z0-9_])'+re.escape(v)+r'(?![A-Za-z0-9_])',text)]
    if forbidden:raise TurnValidationError('not supported by current public sources',forbidden)
    marked=re.findall(r'`([^`]+)`',text)
    if text.count('`')!=2*len(marked):raise TurnValidationError('malformed symbol markup',['`'])
    unknown=set(marked)-allowed
    if unknown:raise TurnValidationError('symbol/path not in source-backed whitelist',unknown)
    plain=re.sub(r'`[^`]+`','',text)
    # Plain and quoted references use exactly the same membership rule.
    paths=PATH.findall(plain)
    for path in paths:plain=plain.replace(path,' ')
    code_like=set(paths)
    for token in IDENTIFIER.findall(plain):
        if ('_' in token or token.isupper() or re.search(r'[a-z][A-Z]',token)
                or (any(c.isdigit() for c in token) and token[0].isupper())):
            code_like.add(token)
    code_like.update(re.findall(r'([A-Za-z_]\w*)\s*\(',plain))
    unknown=code_like-allowed
    if unknown:raise TurnValidationError('symbol/path not in source-backed whitelist',unknown)
    return marked+sorted(code_like)
