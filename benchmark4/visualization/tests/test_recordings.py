from http.server import ThreadingHTTPServer
import json
import threading
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest
from benchmark4.visualization.recordings import Recordings
from benchmark4.visualization.server import make_handler
from benchmark4.visualization.control import Controller
from benchmark4.visualization.store import Store


@pytest.fixture
def saved(tmp_path):
    root=tmp_path/'datasets';base=root/'pilot'/'cases'/'technical';folder=base/'qa_calibration_runs';folder.mkdir(parents=True)
    prompt='{"message": "exact saved prompt", "spacing":  1}'
    report={'case_id':'technical','stage':1,'provider_type':'FakeProvider','provider_model':'fake',
            'complete':True,'passed':True,'denominator_per_cell':3,'usage_tokens':100,
            'request_config':{'repeats':3,'api_key':'SECRET_CONFIG'},
            'records':[{'anchor':'B1','context':'C','repeat':1,'prompt':prompt,'raw_answer':'RAW ANSWER\n',
                        'expected':{'ids':['x']},'parsed':{'ids':['y']},'outcome':'model_wrong','usage_tokens':100,
                        'provider_secret':'NEVER_EXPOSE'}], 'scores':{'B1':{'C':0}}}
    path=folder/'0001.json';path.write_text(json.dumps(report))
    (base/'run_info.json').write_text(json.dumps({'model':'fake','api_key':'SECRET_INFO','started_at_utc':'2026-01-01T00:00:00Z'}))
    (base/'factory_state.json').write_text(json.dumps({'stage':1,'status':'GATE','gate':True,'private':'SECRET_STATE'}))
    return root,path,report


def test_verbatim_prompt_answer_and_no_reconstruction(saved):
    root,path,report=saved;catalog=Recordings(root);id=catalog.list()[0]['id']
    row=catalog.call(id,0)
    assert row['prompt']==report['records'][0]['prompt'] and row['raw_answer']=='RAW ANSWER\n'
    before=path.read_bytes()
    for name in ('prompt','raw_answer','expected','parsed'):del report['records'][0][name]
    path.write_text(json.dumps(report));row=catalog.call(id,0)
    assert not any(row['availability'].values()) and 'prompt' not in row
    assert path.read_bytes()!=before
    untouched=path.read_bytes();catalog.summary(id);catalog.calls(id);assert path.read_bytes()==untouched


def test_summary_filters_and_secret_whitelist(saved):
    root,_,_=saved;catalog=Recordings(root);id=catalog.list()[0]['id'];summary=catalog.summary(id)
    assert summary['call_count']==1 and summary['outcomes']=={'model_wrong':1}
    assert summary['current_case_state']=={'stage':1,'status':'GATE','gate':True}
    assert catalog.calls(id,anchor='B1',context='C',outcome='model_wrong')[0]['index']==0
    assert catalog.calls(id,anchor='B0')==[]
    for value in (summary,catalog.calls(id),catalog.call(id,0)):
        assert 'SECRET' not in json.dumps(value) and 'NEVER_EXPOSE' not in json.dumps(value)
    assert 'prompt' not in catalog.calls(id)[0]


def test_saved_scores_are_not_silently_rescored(saved):
    root,path,report=saved;report['scores']['B1']['C']=1;path.write_text(json.dumps(report))
    c=Recordings(root);s=c.summary(c.list()[0]['id']);cell=next(x for x in s['cells'] if x['anchor']=='B1' and x['context']=='C')
    assert cell['saved_score']==1 and cell['passed']==0 and cell['recorded']==1
    assert cell['declared_denominator']==3 and s['warnings']


def test_unreadable_deleted_and_unknown_files(saved):
    root,path,_=saved;c=Recordings(root);id=c.list()[0]['id'];path.write_text('invalid')
    assert c.list()[0]['error']
    with pytest.raises(ValueError):c.load(id)
    path.unlink();assert c.list()==[]
    with pytest.raises(KeyError):c.call(id,0)


def test_symlinks_outside_datasets_are_not_exposed(saved,tmp_path):
    root,path,_=saved;outside=tmp_path/'outside.json';outside.write_text('{"secret":"private"}')
    (path.parent/'leak.json').symlink_to(outside)
    (path.parent.parent/'run_info.json').unlink();(path.parent.parent/'run_info.json').symlink_to(outside)
    c=Recordings(root);assert len(c.list())==1
    assert c.summary(c.list()[0]['id'])['run_info']=={}


def test_recordings_http_is_readonly(saved,tmp_path):
    root,path,report=saved;before=path.read_bytes();catalog=Recordings(root);id=catalog.list()[0]['id']
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(Controller(Store(tmp_path/'runtime')),catalog))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def get(p):
        with urlopen(base+p,timeout=3) as response:return response.read()
    try:
        assert b'READ ONLY' in get('/records')
        assert json.loads(get('/api/recordings'))[0]['id']==id
        assert json.loads(get('/api/recordings/'+id))['call_count']==1
        assert len(json.loads(get('/api/recordings/'+id+'/calls?anchor=B1&context=C')))==1
        assert json.loads(get('/api/recordings/'+id+'/calls/0'))['prompt']==report['records'][0]['prompt']
        for p in ['/api/recordings/unknown','/api/recordings/'+id+'/calls/-1','/api/recordings/'+id+'/calls/100']:
            with pytest.raises(HTTPError):get(p)
        assert path.read_bytes()==before
    finally:server.shutdown();server.server_close();thread.join(3)
