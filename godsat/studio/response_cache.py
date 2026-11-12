"""Small, byte-bounded cache of immutable, validated scene responses."""
from collections import OrderedDict
from threading import Lock


class SceneResponseCache:
    def __init__(self, limit=64 * 1024 * 1024):
        self.limit = limit
        self.size = 0
        self.entries = OrderedDict()
        self.lock = Lock()

    def get(self, key):
        with self.lock:
            body = self.entries.get(key)
            if body is not None:
                self.entries.move_to_end(key)
            return body

    def put(self, key, body):
        if len(body) > self.limit:
            return
        with self.lock:
            old = self.entries.pop(key, b'')
            self.size -= len(old)
            while self.size + len(body) > self.limit:
                _, evicted = self.entries.popitem(last=False)
                self.size -= len(evicted)
            self.entries[key] = body
            self.size += len(body)
