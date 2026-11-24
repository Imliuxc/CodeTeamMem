"""Opt-in OpenAI-compatible transport. No client is constructed on import."""
import os
from .stage1_errors import EnvError


class Utf8BoundTokenizer:
    """Conservative byte-BPE input bound, NOT a measured token count.

    Provider usage is the measured token account. A provider with a different
    tokenization must inject its own tokenizer instead of using this bound.
    """
    conservative_bound = True

    def encode(self, text): return list(text.encode('utf-8'))
    def decode(self, tokens): return bytes(tokens).decode('utf-8')


class OpenAIChatProvider:
    def __init__(self, *, model, api_key=None, base_url=None, temperature=0,
                 enabled=False, client=None):
        if not enabled: raise RuntimeError('real model calls require explicit opt-in')
        if not model: raise EnvError('model is not configured')
        self.model, self.temperature = model, temperature
        if client is None:
            if not api_key: raise EnvError('API key is not configured')
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise EnvError('install the optional openai package before real runs') from exc
            client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60)
        self.client = client

    @classmethod
    def from_env(cls, *, enabled=False, temperature=0):
        provider = OpenAIResponsesProvider if os.environ.get('CODETEAMMEM_API_STYLE') == 'responses' else cls
        return provider(model=os.environ.get('CODETEAMMEM_MODEL'),
                   api_key=os.environ.get('CODETEAMMEM_API_KEY') or os.environ.get('ARK_API_KEY') or os.environ.get('OPENAI_API_KEY'),
                   base_url=os.environ.get('CODETEAMMEM_BASE_URL') or os.environ.get('OPENAI_BASE_URL'),
                   temperature=temperature, enabled=enabled)

    def __call__(self, prompt, *, max_output):
        from .coding_protocol import unpack
        if unpack(prompt) is not None:
            raise EnvError('native Coding tool replay requires the Responses provider')
        try:
            kwargs = dict(model=self.model, messages=[{'role':'user', 'content':prompt}],
                          max_completion_tokens=max_output)
            if self.temperature is not None: kwargs['temperature'] = self.temperature
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Transport/provider/config failures are not wrong business answers.
            # Never put an SDK exception (possibly containing credentials) in logs.
            raise EnvError(f'provider request failed ({type(exc).__name__})') from None
        usage = getattr(response, 'usage', None)
        if usage is None or any(type(getattr(usage, k, None)) is not int for k in ('prompt_tokens','completion_tokens','total_tokens')):
            raise EnvError('provider did not return a valid measured token account')
        if min(usage.prompt_tokens, usage.completion_tokens) < 0 or usage.total_tokens != usage.prompt_tokens + usage.completion_tokens:
            raise EnvError('inconsistent provider token account')
        try: text = response.choices[0].message.content or ''
        except (AttributeError, IndexError, TypeError): raise EnvError('provider response has no answer message') from None
        return {'text':text, 'usage_tokens':usage.total_tokens,
                'input_tokens':usage.prompt_tokens, 'output_tokens':usage.completion_tokens}


class OpenAIResponsesProvider(OpenAIChatProvider):
    """Ark-compatible Responses transport; text only, no search/tools/session."""
    def __call__(self, prompt, *, max_output):
        from .coding_protocol import unpack
        envelope=unpack(prompt)
        try:
            kwargs = dict(model=self.model, input=[{'role':'user','content':prompt}],
                          max_output_tokens=max_output, store=False,
                          extra_body={'thinking':{'type':'disabled'}})
            if envelope is not None:
                kwargs.update(input=envelope['input'],tools=envelope['tools'],
                              tool_choice='required',parallel_tool_calls=False)
            if self.temperature is not None: kwargs['temperature'] = self.temperature
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            raise EnvError(f'provider request failed ({type(exc).__name__})') from None
        usage = getattr(response, 'usage', None)
        if usage is None or any(type(getattr(usage,k,None)) is not int for k in ('input_tokens','output_tokens','total_tokens')):
            raise EnvError('provider did not return a valid measured token account')
        if min(usage.input_tokens,usage.output_tokens) < 0 or usage.total_tokens != usage.input_tokens + usage.output_tokens:
            raise EnvError('inconsistent provider token account')
        cached=getattr(getattr(usage,'input_tokens_details',None),'cached_tokens',None)
        result={'text':response.output_text or '', 'usage_tokens':usage.total_tokens,
                'input_tokens':usage.input_tokens,'output_tokens':usage.output_tokens,
                'cached_input_tokens':cached,
                'provider_usage':usage.model_dump() if hasattr(usage,'model_dump') else None,
                'response_id':response.id,'response_status':response.status}
        if envelope is not None:
            import json
            calls=[item for item in getattr(response,'output',[]) if getattr(item,'type',None)=='function_call']
            if len(calls)!=1:
                result['protocol_error']='expected exactly one native function call'
            else:
                call=calls[0]
                result['provider_output']={'type':'function_call','name':call.name,
                    'arguments':call.arguments,'call_id':call.call_id}
                result['tool_call_id']=call.call_id
                try:
                    result['text']=json.dumps({'tool':call.name,'arguments':json.loads(call.arguments)},ensure_ascii=False)
                except (ValueError,TypeError): result['protocol_error']='invalid function arguments JSON'
        return result
