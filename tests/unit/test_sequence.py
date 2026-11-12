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


def test_cached_window_still_rejects_changed_bytes(exported, monkeypatch):
    from godsat.studio import service
    import os
    path, _, _ = exported
    studio = service.StudioService(Path(__file__).parents[2], path.parent)
    identity = next(a['id'] for a in studio.catalog.scan()['artifacts'] if a['name'] == path.name)
    body = studio.scene_response(identity, 1, include_sky=False)
    assert json.loads(body)['sequence']['index'] == 1
    def unexpected_decode(*_args):
        pytest.fail('Repeated window should use the validated encoded response')
    monkeypatch.setattr(service, 'decode_window', unexpected_decode)
    assert studio.scene_response(identity, 1, include_sky=False) is body
    window = path.parent / load_manifest(path)['windows'][1]['file']
    stat = window.stat()
    raw = window.read_bytes()
    window.write_bytes(raw.replace(b'"ITRS"', b'"TEME"', 1))
    os.utime(window, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert window.stat().st_size == stat.st_size
    with pytest.raises(ValueError, match='hash changed'):
        studio.scene_response(identity, 1, include_sky=False)


def test_standalone_cache_tracks_source_bytes_and_excludes_sidecars(tmp_path, monkeypatch):
    from godsat.studio import service
    from godsat.studio.scene import base
    monkeypatch.setattr(service, 'astronomy', lambda *_args: {})
    times = ['2026-01-01T00:00:00Z']
    path = tmp_path / 'scene.json'
    value = base('A', 'ITRS', times, [dict(id='1',name='One',kind='satellite',positions_km=[[7000,0,0]])], dict(kind='modeled'))
    path.write_text(json.dumps(value))
    legacy = tmp_path / 'replay.json'
    legacy.write_text(json.dumps(dict(times=times, ids=[1], positions_km=[[[7000,0,0]]])))
    studio = service.StudioService(Path(__file__).parents[2], tmp_path)
    studio.catalog.scan()
    ids = {path: identity for identity, path in studio.catalog.paths.items()}
    first = studio.scene_response(ids[path])
    assert studio.scene_response(ids[path]) is first
    value['objects'][0]['positions_km'][0][0] = 7100
    path.write_text(json.dumps(value))
    updated = json.loads(studio.scene_response(ids[path]))
    assert updated['objects'][0]['positions_km'] == [[7100,0,0]]
    assert updated['source']['sha256'] != json.loads(first)['source']['sha256']
    config = tmp_path / 'config.json'
    for seconds in (10, 30):
        config.write_text(json.dumps({'custody_seconds': seconds}))
        assert json.loads(studio.scene_response(ids[legacy]))['custody_seconds'] == seconds


def test_window_transport_negotiates_without_changing_json(exported):
    from godsat.studio.service import StudioService
    from godsat.studio.packed_scene import MIME
    from scripts.studio.benchmark_scene_service import Request
    import struct
    path, _, _ = exported
    studio = StudioService(Path(__file__).parents[2], path.parent)
    identity = next(a['id'] for a in studio.catalog.scan()['artifacts'] if a['name'] == path.name)
    route = '/api/studio/window?id=' + identity + '&index=1'
    plain = Request(route)
    studio.handle(plain)
    packed = Request(route)
    packed.headers = {**Request.headers, 'Accept': MIME}
    studio.handle(packed)
    assert plain.status == packed.status == 200
    assert plain.response_headers['Content-Type'] == 'application/json'
    assert packed.response_headers['Content-Type'] == MIME
    expected = json.loads(plain.body)
    assert packed.body[:4] == b'GDS1'
    end = 8 + struct.unpack_from('<I', packed.body, 4)[0]
    header = json.loads(packed.body[8:end])
    values = iter(struct.iter_unpack('<ddd', packed.body[end:]))
    import math
    for obj, velocity in zip(header['scene']['objects'], header['velocities'], strict=True):
        for key in ['positions_km'] + (['velocities_km_s'] if velocity else []):
            obj[key] = [None if all(math.isnan(x) for x in row) else list(row)
                        for row in (next(values) for _ in expected['times'])]
    assert next(values, None) is None
    assert header['scene'] == expected
