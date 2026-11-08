"""HTTP boundary shared by the original experiment server and standalone studio."""
import json
import hashlib
import datetime as dt
import mimetypes
import threading
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote
from .catalog import Catalog, clean
from .scene import demo_scene, load_scene
from .sequence import load_window


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
            if path == '/api/studio/scene':
                if arg('demo'):
                    scene = demo_scene(self.root, arg('demo') == 'system')
                else:
                    scene=self.read_scene(arg('id'))
                key = (scene['frame'], tuple(scene['times']))
                if key not in self.sky_cache:
                    if len(self.sky_cache) >= 8: self.sky_cache.clear()
                    self.sky_cache[key] = astronomy(scene['times'], scene['frame'])
                scene['celestial'] = self.sky_cache[key]
                return self.json(handler, scene)
            if path == '/api/studio/window':
                scene=load_window(self.catalog.get(arg('id')),int(arg('index')),arg('id'))
                return self.json(handler,scene)
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
            relative = 'index.html' if path in {'/', '/studio', '/studio/'} else path.removeprefix('/studio/')
            file = (self.web/relative).resolve()
            if not file.is_relative_to(self.web) or not file.is_file(): raise FileNotFoundError('Unknown studio asset')
            return self.send(handler, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            return self.json(handler, {'error': str(exc)}, 400)
        except FileNotFoundError as exc:
            return self.json(handler, {'error': str(exc)}, 404)
        except (OSError, ImportError) as exc:
            return self.json(handler, {'error': 'Artifact unavailable: '+str(exc)}, 503)

    def handle_post(self,handler):
        path=urlsplit(handler.path).path
        if not path.startswith('/api/studio/experiments/'):return False
        try:
            # Rebinding and cross-origin requests cannot launch local processes.
            host=handler.headers.get('Host','')
            hostname=urlsplit('http://'+host).hostname
            if hostname not in {'localhost','127.0.0.1','::1'}:raise ValueError('Local host required')
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

    def json(self, handler, value, status=200):
        return self.send(handler, json.dumps(clean(value), allow_nan=False).encode(), 'application/json', status)

    @staticmethod
    def send(handler, body, mime, status=200):
        handler.send_response(status)
        handler.send_header('Content-Type', mime)
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.end_headers(); handler.wfile.write(body)
        return True
