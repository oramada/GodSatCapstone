"""Bounded, read-only artifact discovery and inspection.

No model pickle, archive member or executable is ever loaded by the studio.
"""
import csv
import hashlib
import json
import math
import zipfile
from pathlib import Path

FORMATS = {
    '.json': 'JSON / manifests / replays', '.csv': 'Tabular measurements / trajectories',
    '.parquet': 'Columnar states / telemetry', '.npz': 'Scenario arrays',
    '.npy': 'Numerical array', '.pt': 'Model checkpoint (metadata only)',
    '.pth': 'Model checkpoint (metadata only)', '.ckpt': 'Model checkpoint (metadata only)',
    '.cdf': 'CDF source (metadata only)', '.fits': 'FITS image source (metadata only)',
    '.fit': 'FITS image source (metadata only)', '.h5': 'HDF5 source (metadata only)',
    '.hdf5': 'HDF5 source (metadata only)', '.xml': 'XML source', '.txt': 'Text source',
    '.md': 'Report', '.png': 'Figure', '.jpg': 'Image', '.jpeg': 'Image',
    '.pdf': 'PDF report', '.fz': 'Compressed FITS source (metadata only)',
    '.bsp': 'SPICE kernel (metadata only)', '.crd': 'Laser ranging source',
    '.cpf': 'Prediction ephemeris source', '.tle': 'Orbital elements source',
    '.dat': 'Text source', '.sp3': 'Orbit source', '.gz': 'Source archive (metadata only)', '.zip': 'Source archive (metadata only)',
}
MAX_BYTES = 64 * 1024 * 1024


def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return None
    if hasattr(value, 'item'): return clean(value.item())
    if hasattr(value, 'isoformat'): return value.isoformat()
    return value


class Catalog:
    def __init__(self, root, output, data_roots=()):
        self.root = Path(root).resolve()
        folders = [Path(output).resolve(), self.root/'outputs', self.root/'data', self.root/'reports', self.root/'configs']
        folders += [Path(p).expanduser().resolve() for p in data_roots]
        self.roots = list(dict.fromkeys(folders))
        self.paths = {}

    def scan(self):
        artifacts = []
        paths = {}
        seen = set()
        for folder in self.roots:
            if not folder.is_dir(): continue
            for path in sorted(folder.rglob('*')):
                if len(artifacts) >= 10000: break
                if path.suffix.lower() not in FORMATS or path.is_symlink() or not path.is_file(): continue
                resolved = path.resolve()
                if not resolved.is_relative_to(folder) or resolved in seen: continue
                seen.add(resolved)
                stat = path.stat()
                identity = hashlib.sha256(str(resolved).encode()).hexdigest()[:20]
                paths[identity] = resolved
                artifacts.append({'id': identity, 'name': path.name,
                    'path': str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path.relative_to(folder)),
                    'root': str(folder), 'format': path.suffix[1:].lower(),
                    'kind': FORMATS[path.suffix.lower()], 'bytes': stat.st_size,
                    'modified': stat.st_mtime, 'local': not bool(getattr(stat, 'st_flags', 0) & 0x40000000)})
        self.paths = paths
        return {'artifacts': artifacts, 'roots': [str(p) for p in self.roots],
                'limit': 10000, 'truncated': len(artifacts) >= 10000}

    def get(self, identity):
        if identity not in self.paths: self.scan()
        path = self.paths.get(identity)
        if path is None or not any(path.resolve().is_relative_to(p) for p in self.roots):
            raise ValueError('Unknown artifact id')
        if not path.is_file(): raise FileNotFoundError('Artifact no longer exists')
        # UF_DATALESS files can block on a cloud download. Never hydrate implicitly.
        if getattr(path.stat(), 'st_flags', 0) & 0x40000000:
            raise ValueError('Cloud placeholder: download this artifact locally before opening it')
        return path

    def inspect(self, identity):
        path = self.get(identity)
        result = {'name': path.name, 'bytes': path.stat().st_size, 'kind': FORMATS[path.suffix.lower()]}
        suffix = path.suffix.lower()
        if path.stat().st_size > MAX_BYTES and suffix not in {'.parquet', '.npz'}:
            return {**result, 'note': 'Preview limited to files below 64 MiB.'}
        if suffix == '.json':
            value = json.loads(path.read_text())
            result['data'] = clean(value)
            # Avoid sending entire large nested arrays in the inspector.
            encoded = json.dumps(result['data'])
            if len(encoded) > 180000: result['data'] = {'keys': list(value) if isinstance(value, dict) else None, 'preview': encoded[:160000], 'truncated': True}
        elif suffix == '.csv':
            with path.open(newline='') as f:
                reader = csv.DictReader(f)
                result['columns'] = reader.fieldnames
                result['rows'] = [row for _, row in zip(range(200), reader)]
            result['note'] = 'First 200 rows; source file is unchanged.'
        elif suffix == '.parquet':
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(path)
            result['schema'] = str(pf.schema_arrow)
            result['total_rows'] = pf.metadata.num_rows
            result['rows'] = clean(next(pf.iter_batches(batch_size=100), []).to_pylist()) if pf.metadata.num_rows else []
        elif suffix in {'.npz', '.npy'}:
            import numpy as np
            if suffix == '.npz':
                with zipfile.ZipFile(path) as archive:
                    if sum(info.file_size for info in archive.infolist()) > 256*1024*1024:
                        return {**result, 'note': 'Uncompressed arrays exceed 256 MiB. Export a smaller window.'}
                with np.load(path, allow_pickle=False) as a:
                    result['arrays'] = {}
                    for k in a.files:
                        array = a[k]
                        result['arrays'][k] = {'shape': list(array.shape), 'dtype': str(array.dtype)}
            else:
                a = np.load(path, mmap_mode='r', allow_pickle=False)
                result['arrays'] = {'array': {'shape': list(a.shape), 'dtype': str(a.dtype)}}
        elif suffix in {'.md', '.txt', '.xml', '.tle', '.cpf', '.crd', '.sp3', '.dat'}:
            with path.open(errors='replace') as f: result['text'] = f.read(100000)
        elif suffix in {'.png', '.jpg', '.jpeg', '.pdf'}:
            result['media'] = '/api/studio/artifact?id=' + identity
        else:
            result['note'] = 'Raw source or checkpoint. Metadata only; use its processed JSON, CSV, Parquet or NPZ product for inspection and replay.'
        return result
