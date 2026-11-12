"""Measure bytes sent on a first load and a conditional reload of local Studio assets."""
from html.parser import HTMLParser
from http.client import HTTPConnection
import json
import sys
import time
from urllib.parse import urlsplit


class PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        path = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' and attrs.get('rel') == 'stylesheet' else None
        if path and path.startswith('/studio/'):
            self.paths.append(path)


def measure(url):
    host = urlsplit(url)
    if host.scheme != 'http' or host.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Benchmark requires a local HTTP Studio service')
    conn = HTTPConnection(host.hostname, host.port or 80, timeout=10)
    def read(path, etag=None):
        start = time.perf_counter()
        conn.request('GET', path, headers={'If-None-Match': etag} if etag else {})
        response = conn.getresponse()
        body = response.read()
        return body, response.getheader('ETag'), response.status, time.perf_counter() - start
    assets = PageAssets()
    root = read('/')
    assets.feed(root[0].decode())
    paths = list(dict.fromkeys(['/', *assets.paths, '/studio/wasm/godsat_studio_core.wasm', '/studio/assets/earth-day.jpg']))
    rows = []
    for path in paths:
        body, tag, status, cold = root if path == '/' else read(path)
        warm, _, repeat, hot = read(path, tag)
        assert status == 200 and repeat in (200, 304)
        assert repeat == 304 or body == warm
        rows.append(dict(path=path, first_bytes=len(body), repeat_bytes=len(warm), repeat_status=repeat,
                         first_ms=cold*1000, repeat_ms=hot*1000))
    conn.close()
    print(json.dumps(dict(origin=url, assets=rows, first_bytes=sum(x['first_bytes'] for x in rows),
                          repeat_bytes=sum(x['repeat_bytes'] for x in rows)), indent=2))


if __name__ == '__main__':
    measure(sys.argv[1])
