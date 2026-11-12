"""Measure local scene service work, excluding HTTP transfer and browser parsing.

Usage: python -m scripts.studio.benchmark_scene_service SCENE_JSON MANIFEST_JSON
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
from godsat.studio.service import StudioService


class Request:
    headers = {'Host': '127.0.0.1:8765'}

    def __init__(self, path):
        self.path = path
        self.wfile = self
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass

    def write(self, body):
        self.body = body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    studio = StudioService(Path.cwd(), args.scene.parent, [args.manifest.parent])
    studio.catalog.scan()
    ids = {path: identity for identity, path in studio.catalog.paths.items()}
    scene, manifest = ids[args.scene.resolve()], ids[args.manifest.resolve()]
    for label, route in [('standalone', f'scene?id={scene}'), ('sequence_start', f'scene?id={manifest}'), ('next_window', f'window?id={manifest}&index=1')]:
        for attempt in ('first', 'repeat'):
            request = Request('/api/studio/' + route)
            started = time.perf_counter()
            assert studio.handle(request) and request.status == 200
            elapsed = time.perf_counter() - started
            value = json.loads(request.body)
            # A digest of compact canonical JSON makes data equality checkable across encodings.
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            print(json.dumps(dict(workload=label, attempt=attempt, seconds=elapsed, bytes=len(request.body),
                objects=len(value['objects']), frames=len(value['times']), semantic_sha256=digest)), flush=True)


if __name__ == '__main__':
    main()
