"""Portable setup and input-data diagnostics for student machines."""

import json
import pathlib
import platform
import shutil
import sys

from .learning import compute_device
from .orbits import ROOT


def environment_report(config, root=ROOT):
    root = pathlib.Path(root)
    manifest_path = root / 'data/raw/source-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    archive = []
    for item in manifest['files']:
        relative = pathlib.PurePosixPath(item['path']).relative_to('data')
        path = root / 'data' / pathlib.Path(*relative.parts)
        actual_size = path.stat().st_size if path.is_file() else None
        expected_size = item['lfs']['size']
        archive.append({
            'path': str(path.relative_to(root)),
            'expected_bytes': expected_size,
            'actual_bytes': actual_size,
            'size_matches': actual_size == expected_size,
        })

    cohort = config.get('sensor_cohort', 'current_payload')
    cohort_files = {
        'current_payload': root / 'data/current_payload_orbit_history.parquet',
        'current_active_payload': root / 'data/current_active_payload_orbit_history.parquet',
        'all': None,
    }
    if cohort not in cohort_files:
        raise ValueError(f'Unsupported sensor_cohort in config: {cohort}')
    cohort_path = cohort_files[cohort]
    cohort_ready = all(item['size_matches'] for item in archive) if cohort == 'all' else (
        cohort_path is not None and cohort_path.is_file()
    )
    satcat = root / 'data/raw/satcat.csv'
    disk = shutil.disk_usage(root)
    requested_device = config.get('compute_device', 'cpu')
    try:
        selected_device = str(compute_device(config))
        device_error = None
    except (RuntimeError, ValueError) as error:
        selected_device = None
        device_error = str(error)

    return {
        'python': sys.version.split()[0],
        'python_executable': sys.executable,
        'python_supported': sys.version_info >= (3, 11),
        'operating_system': platform.platform(),
        'architecture': platform.machine(),
        'compute_device_requested': requested_device,
        'compute_device_selected': selected_device,
        'compute_device_error': device_error,
        'sensor_cohort': cohort,
        'archive': archive,
        'archive_ready': all(item['size_matches'] for item in archive),
        'catalog_snapshot_ready': satcat.is_file(),
        'cohort_ready': cohort_ready,
        'data_ready': all(item['size_matches'] for item in archive) and satcat.is_file() and cohort_ready,
        'data_download_bytes': sum(item['expected_bytes'] for item in archive),
        'free_disk_bytes': disk.free,
        'recommended_free_disk_bytes': 10_000_000_000,
        'disk_space_recommended': disk.free >= 10_000_000_000,
        'next_data_step': (
            'No download needed; source files match their pinned sizes.'
            if all(item['size_matches'] for item in archive) else
            f'Run: "{sys.executable}" scripts/fetch_four_year_data.py'
        ),
        'next_cohort_step': (
            f'Run: "{sys.executable}" scripts/export_current.py'
            if cohort == 'current_payload' and not cohort_ready else None
        ),
        'note': 'This diagnostic checks file sizes. The fetch script verifies SHA-256 hashes.',
    }
