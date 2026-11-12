"""HTTP boundary shared by the original experiment server and standalone studio."""
import json
import hashlib
import datetime as dt
import mimetypes
import threading
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote
from .catalog import Catalog, MAX_BYTES, clean
from .scene import VERSION, decode_json_scene, demo_scene, load_scene
from .sequence import VERSION as SEQUENCE_VERSION, decode_window, load_manifest, load_window, read_verified_window
from .response_cache import SceneResponseCache
from .packed_scene import MIME as PACKED_MIME, encode_packed_scene

LOCAL_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})


def astronomy(times, frame):
    """Offline Astropy builtin ephemeris in the scene's declared geocentric frame."""
    try:
        import astropy.units as u
        from astropy.coordinates import get_body, TEME, ITRS
        from astropy.time import Time
        from astropy.utils import iers
        with iers.conf.set_temp('auto_download', False):
            t = Time([dt.datetime.fromisoformat(value.replace('Z', '+00:00')) for value in times])
            result = {}
            for name in ('sun', 'moon'):
                body = get_body(name, t, ephemeris='builtin')
                if frame == 'TEME': body = body.transform_to(TEME(obstime=t))
                if frame == 'ITRS': body = body.transform_to(ITRS(obstime=t))
                result[name] = body.cartesian.xyz.to_value(u.km).T.tolist()
            result['source'] = 'Astropy builtin ephemeris; scene UTC and frame. Display sizes exaggerated.'
            return result
    except ImportError:
        return {'source': 'Sun/Moon unavailable: install the ground or awp optional dependencies.'}


class StudioService:
    def __init__(self, root, output, data_roots=()):
        self.root = Path(root).resolve()
        self.web = self.root/'web'/'studio'
        self.catalog = Catalog(root, output, data_roots)
        self.sky_cache = {}
        self.scene_responses = SceneResponseCache()
        self.link_lock=threading.Lock()
        from .experiments import ExperimentJobs
        self.experiments=ExperimentJobs(self.root,self.catalog)

    def read_scene(self,identity,index=0):
        source_path=self.catalog.get(identity)
        header=json.loads(source_path.read_text()) if source_path.suffix=='.json' and source_path.stat().st_size<2*1024*1024 else None
        if isinstance(header,dict) and header.get('schema')=='godsat.sequence.v1':
            scene=load_window(source_path,index,identity)
            scene['source']['manifest_sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
        else:
            if index!=0:raise ValueError('Scene is not a windowed sequence')
            scene=load_scene(source_path)
            scene['source']['sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
        scene['source']['artifact_id']=identity
        return scene

    def scene_response(self, identity, index=0, *, include_sky=True, packed=False):
        """Serialize once per verified snapshot. Legacy sidecar inputs stay uncached."""
        path = self.catalog.get(identity)
        if path.suffix != '.json':
            if not include_sky: raise ValueError('Not a playback sequence')
            return self.encode_scene(self.read_scene(identity), include_sky, packed)
        if path.stat().st_size > MAX_BYTES: raise ValueError('Export a scene window below 64 MiB before replay')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES: raise ValueError('JSON exceeds 64 MiB')
        digest = hashlib.sha256(raw).hexdigest()
        key = (identity, digest, index, include_sky, packed)
        if include_sky:
            # Only canonical standalone scenes use the source-only key. A sequence
            # must first verify its window bytes, even on repeated requests.
            cached = self.scene_responses.get(key)
            if cached is not None: return cached
        value = json.loads(raw)
        if isinstance(value, dict) and value.get('schema') == SEQUENCE_VERSION:
            manifest = load_manifest(path, json_bytes=raw)
            file, window_raw = read_verified_window(path, index, manifest)
            key += (manifest['windows'][index]['sha256'],)
            cached = self.scene_responses.get(key)
            if cached is not None: return cached
            value = json.loads(window_raw)
            scene = decode_window(manifest, index, identity, file, window_raw, value=value)
            if include_sky: scene['source']['manifest_sha256'] = digest
            cacheable = isinstance(value, dict) and value.get('schema') == VERSION
        else:
            if not include_sky: raise ValueError('Not a playback sequence')
            scene = decode_json_scene(path, value)
            scene['source']['sha256'] = digest
            scene['source']['artifact_id'] = identity
            cacheable = isinstance(value, dict) and value.get('schema') == VERSION
        body = self.encode_scene(scene, include_sky, packed)
        if cacheable: self.scene_responses.put(key, body)
        return body

    def encode_scene(self, scene, include_sky, packed=False):
        if include_sky:
            key = (scene['frame'], tuple(scene['times']))
            if key not in self.sky_cache:
                if len(self.sky_cache) >= 8: self.sky_cache.clear()
                self.sky_cache[key] = clean(astronomy(scene['times'], scene['frame']))
            scene['celestial'] = self.sky_cache[key]
        if packed: return encode_packed_scene(scene)
        # The scene adapters already sanitize the validated tree.
        return json.dumps(scene, separators=(',', ':'), allow_nan=False).encode()

    def handle(self, handler):
        parsed = urlsplit(handler.path); path = unquote(parsed.path)
        if path in {'/legacy', '/index.html', '/studio', '/studio/', '/studio/index.html'}:
            handler.send_response(308)
            handler.send_header('Location', '/')
            handler.send_header('Content-Length', '0')
            handler.end_headers()
            return True
        if not (path in {'/'} or path.startswith('/studio/') or path.startswith('/api/studio/')):
            return False
        # DNS rebinding: a page on another name that resolves here must not read artifacts or the token.
        if self.local_host(handler) is None:
            return self.json(handler, {'error': 'Local host required'}, 403)
        try:
            query = parse_qs(parsed.query)
            def arg(key, default=''): return query.get(key, [default])[0]
            if path == '/api/studio/experiments/options':
                return self.json(handler,self.experiments.options())
            if path == '/api/studio/experiments/template':
                return self.json(handler,self.experiments.template(arg('id')))
            if path == '/api/studio/experiments/job':
                return self.json(handler,self.experiments.get(arg('id')))
            if path == '/api/studio/catalog':
                return self.json(handler, self.catalog.scan())
            if path == '/api/studio/inspect':
                return self.json(handler, self.catalog.inspect(arg('id')))
            if path in {'/api/studio/scene', '/api/studio/window'}:
                packed = any(part.strip() == PACKED_MIME for part in (handler.headers.get('Accept') or '').split(','))
                mime = PACKED_MIME if packed else 'application/json'
            if path == '/api/studio/scene':
                if arg('demo'):
                    body = self.encode_scene(demo_scene(self.root, arg('demo') == 'system'), True, packed)
                else:
                    body = self.scene_response(arg('id'), packed=packed)
                return self.send(handler, body, mime)
            if path == '/api/studio/window':
                body = self.scene_response(arg('id'), int(arg('index')), include_sky=False, packed=packed)
                return self.send(handler, body, mime)
            if path == '/api/studio/links':
                from godsat.simulation.links import evaluate_links
                with self.link_lock:
                    scene=self.read_scene(arg('id'),int(arg('window','0')))
                    result=evaluate_links(scene,arg('object'),arg('station'))
                return self.json(handler,result)
            if path == '/api/studio/artifact':
                file = self.catalog.get(arg('id'))
                if file.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.pdf'}: raise ValueError('Inline serving is limited to report images and PDFs')
                if file.stat().st_size > 64*1024*1024: raise ValueError('Artifact too large for inline preview')
                return self.send(handler, file.read_bytes(), mimetypes.guess_type(file.name)[0])
            if path.startswith('/api/'): raise FileNotFoundError('Unknown studio endpoint')
            # The window is the built React app (web/ui, built into web/studio/app); its page is the root.
            relative = 'app/index.html' if path == '/' else path.removeprefix('/studio/')
            file = (self.web/relative).resolve()
            if not file.is_relative_to(self.web) or not file.is_file(): raise FileNotFoundError('Unknown studio asset')
            body = file.read_bytes()
            mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            # Hash the bytes actually served. Revalidate even on reload so a rebuilt
            # UI or changed local texture never appears under a stale validator.
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            validators = (handler.headers.get('If-None-Match') or '').split(',')
            if any(tag.strip().removeprefix('W/') in {etag, '*'} for tag in validators):
                return self.send(handler, b'', mime, 304, etag=etag)
            return self.send(handler, body, mime, etag=etag)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            return self.json(handler, {'error': str(exc)}, 400)
        except FileNotFoundError as exc:
            return self.json(handler, {'error': str(exc)}, 404)
        except (OSError, ImportError) as exc:
            return self.json(handler, {'error': 'Artifact unavailable: '+str(exc)}, 503)

    def handle_post(self,handler):
        path=urlsplit(handler.path).path
        if not path.startswith('/api/studio/experiments/'):return False
        # Rebinding and cross-origin requests cannot launch local processes.
        host=self.local_host(handler)
        if host is None:return self.json(handler,{'error':'Local host required'},403)
        try:
            origin=handler.headers.get('Origin')
            if origin and origin!='http://'+host:raise ValueError('Same-origin request required')
            if not secrets.compare_digest(handler.headers.get('X-Studio-Token',''),self.experiments.token):
                raise ValueError('Session changed. Reload Studio before launching a run.')
            if handler.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON request required')
            from .experiments import MAX_REQUEST
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<length<=MAX_REQUEST:raise ValueError('Invalid experiment request size')
            payload=json.loads(handler.rfile.read(length))
            if not isinstance(payload,dict):raise ValueError('Expected experiment object')
            if path.endswith('/validate'):
                _,_,summary=self.experiments.prepare(payload)
                return self.json(handler,{'valid':True,'summary':summary})
            if path.endswith('/run'):return self.json(handler,self.experiments.start(payload),202)
            if path.endswith('/cancel'):return self.json(handler,self.experiments.cancel(payload.get('id')))
            return self.json(handler,{'error':'Unknown experiment endpoint'},404)
        except (ValueError,KeyError,TypeError,ImportError,OSError) as exc:
            return self.json(handler,{'error':str(exc)},400)

    @staticmethod
    def local_host(handler):
        """The request's Host header when it names this machine's loopback, else None."""
        host=(getattr(handler,'headers',None) or {}).get('Host') or ''
        if not host or any(c in host for c in '@/\\?# '):return None
        try:hostname=urlsplit('http://'+host).hostname
        except ValueError:return None
        return host if hostname in LOCAL_HOSTS else None

    def json(self, handler, value, status=200):
        return self.send(handler, json.dumps(clean(value), allow_nan=False).encode(), 'application/json', status)

    @staticmethod
    def send(handler, body, mime, status=200, *, etag=None):
        handler.send_response(status)
        handler.send_header('Content-Type', mime)
        if status != 304: handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Cache-Control', 'private, no-cache' if etag else 'no-store')
        if etag: handler.send_header('ETag', etag)
        handler.send_header('X-Content-Type-Options', 'nosniff')
        # Only Studio may frame Studio (its own PDF preview): another page can't overlay it and steer clicks.
        handler.send_header('Content-Security-Policy', "frame-ancestors 'self'")
        handler.send_header('X-Frame-Options', 'SAMEORIGIN')
        handler.end_headers()
        if body: handler.wfile.write(body)
        return True
