"""Business-neutral native Responses function calls and complete-pair replay."""
import json

PROTOCOL = 'codeteammem.responses_tools.v1'


def tool_schemas():
    text = lambda description: {'type':'string','description':description}
    specs = {
        'list': ('List repository files relative to workspace_root.', {}),
        'read': ('Read a repository file; results may be paginated.', {'path':text('Path relative to workspace_root.')}),
        'write': ('Replace the ENTIRE allowed file with UTF-8 content; not a diff or append.',
                  {'path':text('Allowed path relative to workspace_root.'),'content':text('Complete replacement file content.')}),
        'snapshot': ('Fetch the current external-world facts over HTTP.', {}),
        'test_base': ('Run the provided public base tests; does not expose hidden tests.', {}),
        'page': ('Read another page of a prior tool output.',
                 {'output_id':text('Output id returned by a prior tool.'),'page':{'type':'integer','minimum':0}}),
        'finish': ('Submit the current files to the hidden judge. An unchanged baseline receives one confirmation prompt. This does not imply a passing grade.', {'reason':text('Optional explanation if no semantic change is needed.')} ),
    }
    return [{'type':'function','name':name,'description':description,
             'parameters':{'type':'object','properties':properties,'required':[] if name=='finish' else list(properties),'additionalProperties':False}}
            for name,(description,properties) in specs.items()]


def request(header, history):
    items = [{'role':'user','content':json.dumps(header,ensure_ascii=False)}]
    for i, turn in enumerate(history):
        call_id = turn.get('call_id') or f'offline_call_{i+1}'
        items.append({'type':'function_call','call_id':call_id,'name':turn['action']['tool'],
                      'arguments':json.dumps(turn['action'].get('arguments',{}),ensure_ascii=False)})
        items.append({'type':'function_call_output','call_id':call_id,
                      'output':json.dumps(turn['result'],ensure_ascii=False)})
    return {'protocol':PROTOCOL,'input':items,'tools':tool_schemas()}


def unpack(prompt):
    try: value=json.loads(prompt)
    except (ValueError,TypeError): return None
    return value if isinstance(value,dict) and value.get('protocol')==PROTOCOL else None
