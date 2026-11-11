import io
import json
from pathlib import Path
import pytest
from godsat.simulation.catalog import load_catalog, make_times, build_scene
from godsat.simulation.sequence import export_sequence
from godsat.studio.sequence import load_manifest, load_window


@pytest.fixture
def exported(tmp_path):
    records,source=load_catalog(Path(__file__).parents[1]/'fixtures/sgp4-interpolation-omm.json')
    path=tmp_path/'scene-sequence.json'
    export_sequence(records,source,'2026-11-08T18:55:00Z',70,10,30,path)
    return path,records,source


def test_sequence_matches_one_shot_export_and_shared_boundaries(exported):
    path,records,source=exported; manifest=load_manifest(path)
    assert manifest['total_frames']==8 and len(manifest['windows'])==3
    whole=build_scene(records,make_times('2026-11-08T18:55:00Z',70,10),source)
    previous=None
    for i,w in enumerate(manifest['windows']):
        scene=load_window(path,i,'fixture')
        for actual,expected in zip(scene['objects'],whole['objects']):
            for key in ['positions_km','velocities_km_s']:
                assert actual[key]==expected[key][w['offset']:w['offset']+w['frames']]
        if previous:
            assert previous['times'][-1]==scene['times'][0]
            assert previous['objects'][0]['positions_km'][-1]==scene['objects'][0]['positions_km'][0]
        previous=scene


def test_hash_tampering_path_escape_and_missing_later_window(exported):
    path,_,_=exported; manifest=load_manifest(path)
    final=path.parent/manifest['windows'][-1]['file']; final.unlink()
    assert load_window(path,0,'fixture')['sequence']['index']==0
    with pytest.raises(FileNotFoundError):load_window(path,2,'fixture')
    first=path.parent/manifest['windows'][0]['file']; first.write_text('{}')
    with pytest.raises(ValueError,match='hash'):load_window(path,0,'fixture')
    manifest['windows'][0]['file']='../escape.json';path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='directory'):load_manifest(path)


def test_read_only_http_loads_requested_window_and_rejects_bad_index(exported,monkeypatch):
    from godsat.studio import service
    path,_,_=exported
    monkeypatch.setattr(service,'astronomy',lambda *args:{})
    studio=service.StudioService(Path(__file__).parents[2],path.parent)
    identity=next(a['id'] for a in studio.catalog.scan()['artifacts'] if a['name']==path.name)
    class Handler:
        def __init__(self,url):self.path=url;self.wfile=io.BytesIO();self.headers={'Host':'127.0.0.1:8765'}
        def send_response(self,status):self.status=status
        def send_header(self,*args):pass
        def end_headers(self):pass
    first=Handler('/api/studio/scene?id='+identity); assert studio.handle(first)
    assert json.loads(first.wfile.getvalue())['sequence']['index']==0
    second=Handler('/api/studio/window?id='+identity+'&index=1');assert studio.handle(second)
    assert second.status==200 and json.loads(second.wfile.getvalue())['sequence']['offset']==3
    bad=Handler('/api/studio/window?id='+identity+'&index=-1');assert studio.handle(bad)
    assert bad.status==400


def test_manifest_cannot_hide_a_discontinuous_boundary_or_changed_roster(exported):
    path,_,_=exported; manifest=load_manifest(path)
    manifest['windows'][1]['start_state_sha256']='0'*64;path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='boundary state changed'):load_manifest(path)
    manifest['windows'][1]['start_state_sha256']=manifest['windows'][0]['end_state_sha256']
    manifest['roster_sha256']='0'*64;path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='roster'):load_window(path,0,'fixture')
