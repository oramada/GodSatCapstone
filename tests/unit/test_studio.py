import json
from pathlib import Path
import pytest
from godsat.studio.catalog import Catalog
from godsat.studio.scene import base, demo_scene, load_scene, replay_scene, table_scene
ROOT = Path(__file__).resolve().parents[2]


def test_demo_labels_constructed_geometry_and_preserves_pinned_membership():
    small = demo_scene(ROOT)
    full = demo_scene(ROOT, True)
    assert small['source']['kind'] == 'illustrative'
    assert small['observations'][4]['detected'] == []
    assert len(full['objects']) == 86
    assert small['objects'][1]['id'] == '41917'


def test_replay_maps_target_local_indices_and_keeps_invalid_states():
    value = dict(frame='TEME', times=['2026-01-01T00:00:00Z','2026-01-01T00:01:00Z'],
        ids=[-7090,41917], agents=1, positions_km=[[[6000,0,0],[7000,0,0]],[[6000,0,0],[0,0,0]]],
        valid=[[True,True],[True,False]],trace=[dict(step=0,actions=[0],detected=[0])])
    scene = replay_scene(value, 'fixture')
    assert scene['observations'][0]['detected'] == ['41917']
    assert scene['observations'][0]['actions'] == [{'sensor':'-7090','target':'41917'}]
    assert scene['observations'][1] is None
    assert scene['objects'][1]['positions_km'][1] is None


def test_trajectory_csv_explicit_frame_and_gaps(tmp_path):
    path = tmp_path/'trajectory.csv'
    path.write_text('norad_id,time_utc,x_teme_km,y_teme_km,z_teme_km,sgp4_error\n1,2026-01-01T00:00:00Z,7000,0,0,0\n1,2026-01-01T00:01:00Z,,,,2\n')
    scene = load_scene(path)
    assert scene['frame'] == 'TEME'
    assert scene['objects'][0]['positions_km'] == [[7000,0,0],None]
    assert scene['observations'] is None


def test_unknown_frame_and_naive_time_rejected():
    with pytest.raises(ValueError): base('x','unknown',['2026-01-01T00:00:00Z'],[],{})
    with pytest.raises(ValueError): base('x','TEME',['2026-01-01'],[],{})
    with pytest.raises(ValueError): table_scene([{'ra': 3, 'dec': 4}], 'angular')


def test_catalog_does_not_follow_symlinks_or_allow_arbitrary_paths(tmp_path):
    output=tmp_path/'outputs';output.mkdir();(output/'test.json').write_text('{"a": 1}')
    outside=tmp_path/'secret.json';outside.write_text('{}');(output/'link.json').symlink_to(outside)
    catalog=Catalog(tmp_path/'repo',output)
    artifacts=catalog.scan()['artifacts']
    assert [a['name'] for a in artifacts] == ['test.json']
    assert catalog.inspect(artifacts[0]['id'])['data'] == {'a': 1}
    with pytest.raises(ValueError): catalog.get('../secret.json')


def test_npz_scenario_without_observations(tmp_path):
    import numpy as np
    path=tmp_path/'scenario.npz'
    np.savez(path,states=np.array([[[7000,0,0,0,1,0]],[[float('nan')]*6]]),ids=[1],agents=0,times=['2026-01-01T00:00:00Z','2026-01-01T00:01:00Z'])
    scene=load_scene(path)
    assert scene['objects'][0]['positions_km'][1] is None
    assert scene['observations'] is None


def test_canonical_rejects_wrong_units_and_unknown_detection(tmp_path):
    value = demo_scene(ROOT)
    path = tmp_path/'scene.json'
    value['units'] = 'm';path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='kilometers'): load_scene(path)
    value['units'] = 'km';value['observations'][0]['detected'] = ['absent']
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Detected IDs'): load_scene(path)


def test_service_reads_canonical_scene_and_blocks_traversal(tmp_path, monkeypatch):
    from godsat.studio import service
    import io
    monkeypatch.setattr(service, 'astronomy', lambda times, frame: {'source':'test fixture'})
    folder = tmp_path/'artifacts';folder.mkdir()
    path = folder/'scene.json';path.write_text(json.dumps(demo_scene(ROOT)))
    studio = service.StudioService(ROOT, folder)
    identity = next(a['id'] for a in studio.catalog.scan()['artifacts'] if a['name']=='scene.json')
    class Handler:
        def __init__(self, path): self.path=path;self.wfile=io.BytesIO();self.status=None
        def send_response(self, status): self.status=status
        def send_header(self, *args): pass
        def end_headers(self): pass
    request = Handler('/api/studio/scene?id='+identity)
    assert studio.handle(request)
    data=json.loads(request.wfile.getvalue())
    assert request.status == 200 and data['source']['artifact_id']==identity
    assert len(data['source']['sha256']) == 64
    request=Handler('/studio/%2e%2e/%2e%2e/configs/ground-tracking-sites.json')
    assert studio.handle(request) and request.status==404


def test_builtin_ephemeris_accepts_timezone_aware_scene_times():
    pytest.importorskip('astropy')
    from godsat.studio.service import astronomy
    import math
    result=astronomy(['2026-09-15T00:00:00+00:00','2026-09-15T00:01:00Z'], 'ITRS')
    assert len(result['sun']) == len(result['moon']) == 2
    assert 1e8 < math.sqrt(sum(x*x for x in result['sun'][0])) < 2e8
    assert 3e5 < math.sqrt(sum(x*x for x in result['moon'][0])) < 5e5


@pytest.mark.parametrize('url', ['/legacy', '/index.html', '/studio', '/studio/', '/studio/index.html'])
def test_previous_visualization_routes_redirect_to_one_studio(url):
    import io
    from godsat.studio.service import StudioService
    class Handler:
        def __init__(self): self.path=url;self.wfile=io.BytesIO();self.headers={}
        def send_response(self, status): self.status=status
        def send_header(self, key, value): self.headers[key]=value
        def end_headers(self): pass
    request=Handler()
    assert StudioService(ROOT, ROOT/'outputs/iridium-next-ground').handle(request)
    assert request.status == 308
    assert request.headers['Location'] == '/'
    assert not request.wfile.getvalue()


def test_studio_has_one_renderer_and_no_legacy_navigation():
    page=(ROOT/'web/studio/index.html').read_text()
    app=(ROOT/'web/studio/app.js').read_text()
    assert 'id="engine"' not in page
    assert 'legacy-link' not in page
    assert 'id="globe"' not in page
    assert "from './renderer.js'" not in app
    assert not (ROOT/'web/studio/renderer.js').exists()
    assert '/studio/' in (ROOT/'web/index.html').read_text()
