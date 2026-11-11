import copy
import io
import json
from pathlib import Path
import pytest
from godsat.studio.catalog import Catalog
from godsat.studio.experiments import ExperimentJobs,worker
from godsat.studio.service import StudioService

ROOT=Path(__file__).parents[2]

def config():
    value=json.loads((ROOT/'configs/numerical-extended.json').read_text())
    value.update(duration_seconds=30,integration_step_seconds=10,output_step_seconds=30)
    return value


def test_validation_enforces_interactive_work_and_driver_requirements(tmp_path):
    jobs=ExperimentJobs(tmp_path,Catalog(tmp_path,tmp_path/'outputs'))
    value=config();_,_,summary=jobs.prepare({'config':value})
    assert summary['frames']==2 and summary['objects']==1
    value['forces']['drag']=True
    with pytest.raises(ValueError,match='space-weather'):jobs.prepare({'config':value})
    value=config();value['duration_seconds']=86400;value['output_step_seconds']=3600
    value['objects']=[dict(value['objects'][0],id=str(i)) for i in range(300)]
    with pytest.raises(ValueError,match='Interactive limit'):jobs.prepare({'config':value})


def test_worker_preserves_inputs_and_exports_validated_scene(tmp_path):
    from godsat.studio.scene import load_scene
    initial=json.dumps(config());(tmp_path/'initial.json').write_text(initial)
    worker(tmp_path)
    assert (tmp_path/'initial.json').read_text()==initial
    result=json.loads((tmp_path/'result.json').read_text())
    scene=load_scene(tmp_path/'scene.json')
    assert result['status']=='succeeded' and result['frames']==2
    assert scene['source']['kind']=='illustrative'
    assert scene['source']['force_model']['solar_radiation_pressure']


class Request:
    def __init__(self,token=None,origin='http://localhost:8765',host='localhost:8765'):
        self.path='/api/studio/experiments/validate';self.wfile=io.BytesIO()
        raw=json.dumps({'config':config()}).encode();self.rfile=io.BytesIO(raw)
        self.headers={'Host':host,'Origin':origin,'Content-Type':'application/json','Content-Length':str(len(raw))}
        if token:self.headers['X-Studio-Token']=token
    def send_response(self,status):self.status=status
    def send_header(self,*args):pass
    def end_headers(self):pass


def test_execution_boundary_requires_same_origin_token_and_loopback_host(tmp_path):
    service=StudioService(tmp_path,tmp_path/'outputs')
    for token,origin,host,status in [(None,'http://localhost:8765','localhost:8765',400),
                                     (service.experiments.token,'http://evil.test','localhost:8765',400),
                                     (service.experiments.token,'http://evil.test','evil.test',403),
                                     (service.experiments.token,'http://evil.test:8765','evil.test:8765',403)]:
        request=Request(token,origin,host);service.handle_post(request);assert request.status==status
    request=Request(service.experiments.token);service.handle_post(request)
    assert request.status==200 and json.loads(request.wfile.getvalue())['valid']
    request=Request(service.experiments.token);request.headers['Content-Length']='999999999'
    service.handle_post(request);assert request.status==400


def test_cancel_and_single_job_ownership(tmp_path,monkeypatch):
    import godsat.studio.experiments as module
    class Process:
        def __init__(self,*args,**kwargs):self.code=None
        def poll(self):return self.code
        def terminate(self):self.code=-15
        def kill(self):self.code=-9
        def wait(self,**kwargs):return self.code
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    jobs=ExperimentJobs(tmp_path,Catalog(tmp_path,tmp_path/'outputs'))
    first=jobs.start({'config':config()})
    assert first['status']=='running'
    with pytest.raises(ValueError,match='already running'):jobs.start({'config':config()})
    assert jobs.cancel(first['id'])['status']=='cancelled'
    assert jobs.get(first['id'])['status']=='cancelled'
    second=jobs.start({'config':config()});assert second['id']!=first['id']
    assert jobs.cancel(second['id'])['status']=='cancelled'
    with pytest.raises(ValueError,match='Unknown'):jobs.cancel('../scene.json')


def test_catalog_keeps_previous_index_available_during_rescan(tmp_path,monkeypatch):
    output=tmp_path/'outputs';output.mkdir();file=output/'initial.json';file.write_text('{}')
    catalog=Catalog(tmp_path,output);identity=catalog.scan()['artifacts'][0]['id']
    original=Path.rglob;checked=[]
    def scanning(path,pattern):
        if path==output:
            assert catalog.paths.get(identity)==file.resolve()
            checked.append(True)
        yield from original(path,pattern)
    monkeypatch.setattr(Path,'rglob',scanning)
    catalog.scan();assert checked
