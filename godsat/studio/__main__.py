"""Start the local frontend without importing the training stack."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .service import StudioService

parser = argparse.ArgumentParser(description='GoDSAT experimental studio (local experiments)')
parser.add_argument('--output', type=Path, default=Path('outputs/iridium-next-ground'))
parser.add_argument('--data-root', type=Path, action='append', default=[], help='Additional local artifacts; repeatable')
parser.add_argument('--port', type=int, default=8765)
args = parser.parse_args()
service = StudioService(Path(__file__).resolve().parents[2], args.output, args.data_root)
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not service.handle_post(self): self.send_error(404)
    def do_GET(self):
        if not service.handle(self): self.send_error(404)
print(f'GoDSAT Studio: http://127.0.0.1:{args.port}', flush=True)
ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
