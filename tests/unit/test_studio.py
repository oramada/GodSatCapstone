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
        def __init__(self, path): self.path=path;self.wfile=io.BytesIO();self.status=None;self.headers={'Host':'127.0.0.1:8765'}
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


class _Request:
    """A BaseHTTPRequestHandler stand-in whose request headers are a real http.client message."""
    def __init__(self, path, host=None, method='GET', body=b'', headers=()):
        import http.client, io
        self.path=path;self.wfile=io.BytesIO();self.rfile=io.BytesIO(body);self.status=None;self.sent={}
        self.headers=http.client.HTTPMessage()
        if host is not None: self.headers['Host']=host
        for key, value in headers: self.headers[key]=value
    def send_response(self, status): self.status=status
    def send_header(self, key, value): self.sent[key]=value
    def end_headers(self): pass
    def reply(self): return json.loads(self.wfile.getvalue())


GOOD_HOSTS = ['127.0.0.1:8765', 'localhost:8765', 'LOCALHOST', '[::1]:8765', '127.0.0.1']
BAD_HOSTS = [None, '', 'evil.test', 'evil.test:8765', '127.0.0.1.evil.test', 'localhost.', 'evil.test@127.0.0.1',
             'evil.test@localhost:8765', '127.0.0.1/x', '[::1', '0.0.0.0:8765', '192.168.1.5:8765', 'localhost evil']


def _host_service(tmp_path, monkeypatch):
    from godsat.studio import service
    monkeypatch.setattr(service, 'astronomy', lambda times, frame: {'source':'test fixture'})
    folder=tmp_path/'artifacts';folder.mkdir()
    (folder/'scene.json').write_text(json.dumps(demo_scene(ROOT)))
    (folder/'figure.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
    studio=service.StudioService(ROOT, folder)
    ids={a['name']:a['id'] for a in studio.catalog.scan()['artifacts']}
    return studio, ids


def _get_paths(ids):
    return ['/api/studio/catalog', f"/api/studio/inspect?id={ids['scene.json']}", f"/api/studio/artifact?id={ids['figure.png']}",
            '/api/studio/experiments/options', '/api/studio/experiments/job?id=x', f"/api/studio/scene?id={ids['scene.json']}",
            '/api/studio/scene?demo=single', '/api/studio/nowhere', '/', '/studio/app/index.html', '/studio/model.js']


@pytest.mark.parametrize('host', BAD_HOSTS)
def test_studio_get_refuses_a_foreign_host(tmp_path, monkeypatch, host):
    studio, ids = _host_service(tmp_path, monkeypatch)
    for path in _get_paths(ids):
        request=_Request(path, host)
        assert studio.handle(request), path
        assert request.status == 403, (path, host)
        assert request.reply() == {'error': 'Local host required'}
        assert studio.experiments.token.encode() not in request.wfile.getvalue()


@pytest.mark.parametrize('host', GOOD_HOSTS)
def test_studio_get_serves_a_loopback_host(tmp_path, monkeypatch, host):
    studio, ids = _host_service(tmp_path, monkeypatch)
    for path in _get_paths(ids):
        request=_Request(path, host)
        assert studio.handle(request), path
        expected = {'/api/studio/nowhere': 404, '/api/studio/experiments/job?id=x': 400}.get(path, 200)
        assert request.status == expected, (path, host, request.wfile.getvalue()[:200])
    request=_Request('/api/studio/experiments/options', host);studio.handle(request)
    assert request.reply()['token'] == studio.experiments.token


@pytest.mark.parametrize('status_path', ['/', '/studio/app/index.html', '/api/studio/catalog', '/api/studio/nowhere'])
def test_studio_replies_refuse_foreign_framing_and_sniffing(tmp_path, monkeypatch, status_path):
    studio, ids = _host_service(tmp_path, monkeypatch)
    for path in (status_path, f"/api/studio/artifact?id={ids['figure.png']}"):
        for host in ('127.0.0.1:8765', 'evil.test'):
            request=_Request(path, host)
            assert studio.handle(request)
            assert request.sent['Content-Security-Policy'] == "frame-ancestors 'self'", (path, host)
            assert request.sent['X-Frame-Options'] == 'SAMEORIGIN', (path, host)
            assert request.sent['X-Content-Type-Options'] == 'nosniff', (path, host)


def test_studio_host_check_leaves_other_paths_and_redirects_alone(tmp_path, monkeypatch):
    studio, _ = _host_service(tmp_path, monkeypatch)
    assert not studio.handle(_Request('/api/current-active-snapshot', 'evil.test'))
    assert not studio.handle_post(_Request('/api/other', 'evil.test', 'POST'))
    request=_Request('/legacy', 'evil.test');assert studio.handle(request) and request.status == 308


@pytest.mark.parametrize('host,status', [(h, 403) for h in BAD_HOSTS] + [(h, 200) for h in GOOD_HOSTS])
def test_studio_post_requires_a_loopback_host(tmp_path, monkeypatch, host, status):
    from godsat.studio.experiments import ExperimentJobs
    studio, _ = _host_service(tmp_path, monkeypatch)
    monkeypatch.setattr(ExperimentJobs, 'prepare', lambda self, payload: (None, None, {'fixture': True}))
    body=json.dumps({'config': {}}).encode()
    headers=[('Content-Type','application/json'),('Content-Length',str(len(body))),('X-Studio-Token',studio.experiments.token)]
    if host: headers.append(('Origin','http://'+host))
    request=_Request('/api/studio/experiments/validate', host, 'POST', body, headers)
    assert studio.handle_post(request)
    assert request.status == status, (host, request.wfile.getvalue())
    if status == 200: assert request.reply() == {'valid': True, 'summary': {'fixture': True}}
    else: assert request.reply() == {'error': 'Local host required'}


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
        def __init__(self): self.path=url;self.wfile=io.BytesIO();self.headers={'Host':'127.0.0.1:8765'}
        def send_response(self, status): self.status=status
        def send_header(self, key, value): self.headers[key]=value
        def end_headers(self): pass
    request=Handler()
    assert StudioService(ROOT, ROOT/'outputs/iridium-next-ground').handle(request)
    assert request.status == 308
    assert request.headers['Location'] == '/'
    assert not request.wfile.getvalue()


def _studio_files(directory, keep):
    """The files scripts/stamp-build.mjs hashes: no dotfiles, no node_modules."""
    found = []
    for path in sorted(directory.rglob('*')):
        parts = path.relative_to(directory).parts
        if any(part.startswith('.') or part == 'node_modules' for part in parts): continue
        if path.is_file() and keep(path): found.append(path)
    return found


def _sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_studio_window_is_the_built_app_and_the_old_page_is_gone():
    page = (ROOT/'web/studio/app/index.html').read_text()
    assert '<div id="root"></div>' in page
    assert '/studio/app/assets/' in page
    assert '/studio/vendor/cesium/Cesium.js' in page
    for gone in ('index.html', 'app.js', 'workspace-ui.js', 'analysis-panel.js', 'experiment-panel.js',
                 'charts.js', 'style.css', 'globe-layout.css', 'renderer.js'):
        assert not (ROOT/'web/studio'/gone).exists(), gone
    assert '/studio/' in (ROOT/'web/index.html').read_text()


def test_studio_root_serves_the_built_app():
    import io
    from godsat.studio.service import StudioService
    class Handler:
        def __init__(self, path): self.path=path;self.wfile=io.BytesIO();self.headers={'Host':'127.0.0.1:8765'}
        def send_response(self, status): self.status=status
        def send_header(self, key, value): self.headers[key]=value
        def end_headers(self): pass
    request=Handler('/')
    assert StudioService(ROOT, ROOT/'outputs/iridium-next-ground').handle(request)
    assert request.status == 200
    assert request.wfile.getvalue().endswith((ROOT/'web/studio/app/index.html').read_bytes())
    # The old page's script, and the React source beside the build, are never served.
    for path in ('/studio/app.js', '/studio/app/../../ui/src/App.tsx', '/studio/%2e%2e/ui/package.json'):
        request=Handler(path)
        assert StudioService(ROOT, ROOT/'outputs/iridium-next-ground').handle(request)
        assert request.status == 404, path
    # Outside /studio/ the service declines and the server answers 404.
    assert not StudioService(ROOT, ROOT/'outputs/iridium-next-ground').handle(Handler('/ui/package.json'))


def test_built_studio_matches_its_source():
    """web/studio/app is committed; build.json must describe today's source and today's bundle."""
    out = ROOT/'web/studio/app'
    build = json.loads((out/'build.json').read_text())
    rel = lambda path: path.relative_to(ROOT).as_posix()
    sources = [
        *_studio_files(ROOT/'web/ui/src', lambda p: p.suffix in {'.ts', '.tsx', '.css'} and not p.name.endswith(('.test.ts', '.test.tsx'))),
        *_studio_files(ROOT/'web/ui/public', lambda p: True),
        *_studio_files(ROOT/'web/ui/vendor/sam-design-system', lambda p: True),
        *_studio_files(ROOT/'web/studio', lambda p: p.suffix == '.js' and not p.is_relative_to(out) and 'vendor' not in p.relative_to(ROOT/'web/studio').parts),
        *(ROOT/name for name in ('web/ui/index.html', 'web/ui/package.json', 'web/ui/bun.lock', 'web/ui/vite.config.ts', 'web/ui/tsconfig.json')),
    ]
    assert build['source_sha256'] == {rel(p): _sha256(p) for p in sources}, 'web/ui changed without `bun run build` in web/ui'
    bundle = _studio_files(out, lambda p: p.name != 'build.json')
    assert build['bundle_sha256'] == {rel(p): _sha256(p) for p in bundle}, 'web/studio/app was edited by hand'


def test_static_asset_revalidates_exact_bytes_without_caching_artifacts(tmp_path):
    import os
    from godsat.studio.service import StudioService
    from scripts.studio.benchmark_scene_service import Request

    assets = tmp_path / 'web' / 'studio' / 'app'
    assets.mkdir(parents=True)
    path = assets / 'index.html'
    path.write_bytes(b'<html>A</html>')
    service = StudioService(tmp_path, tmp_path / 'outputs')
    first = Request('/')
    assert service.handle(first) and first.status == 200
    etag = first.response_headers['ETag']
    assert first.response_headers['Cache-Control'] == 'private, no-cache'
    repeat = Request('/')
    repeat.headers = {**Request.headers, 'If-None-Match': 'W/' + etag}
    assert service.handle(repeat) and repeat.status == 304
    assert not hasattr(repeat, 'body')
    assert 'Content-Length' not in repeat.response_headers
    stat = path.stat()
    path.write_bytes(b'<html>B</html>')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = Request('/')
    changed.headers = repeat.headers
    assert service.handle(changed) and changed.status == 200
    assert changed.body == b'<html>B</html>' and changed.response_headers['ETag'] != etag
    api = Request('/api/studio/catalog')
    api.headers = {**Request.headers, 'If-None-Match': '*'}
    assert service.handle(api) and api.status == 200
    assert api.response_headers['Cache-Control'] == 'no-store' and 'ETag' not in api.response_headers
