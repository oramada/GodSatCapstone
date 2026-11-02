"""Check the import graph and the reproducible pinned-cohort setup workflow."""
import ast
import hashlib
from importlib.util import find_spec
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.data import prepare_iridium_next_cohort as cohort


ROOT = Path(__file__).resolve().parents[2]


def test_grouped_script_import_graph_resolves_without_legacy_aliases():
    checked = set()
    for directory in ['godsat', 'scripts', 'tests']:
        for path in (ROOT/directory).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                         [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                for name in names:
                    if name.startswith('scripts.'):
                        assert find_spec(name) is not None, (path, name)
                        checked.add(name)
    assert len(checked) > 30


def test_cohort_export_uses_committed_membership_without_raw_download_or_policy_reset(tmp_path, monkeypatch):
    (tmp_path/'configs').mkdir()
    (tmp_path/'data').mkdir()
    members = {'members': [{'norad_id': 41917, 'name': 'IRIDIUM 106'},
                           {'norad_id': 41918, 'name': 'IRIDIUM 103'}],
               'scope': 'Pinned test snapshot'}
    member_path = tmp_path/'configs/iridium-next-membership.json'
    member_path.write_text(json.dumps(members))
    member_bytes = member_path.read_bytes()
    policy_path = tmp_path/'configs/active-study-scope.json'
    policy_path.write_text(json.dumps({'iridium_next_membership_sha256': hashlib.sha256(member_bytes).hexdigest(),
                                     'ground_system_role': 'tracking_sensors', 'ground_systems_required': True}))
    policy_bytes = policy_path.read_bytes()
    pq.write_table(pa.table({'norad_id': [41917, 41918, 99], 'epoch': [1, 1, 1]}),
                   tmp_path/'data/current_payload_orbit_history.parquet')
    monkeypatch.setattr(cohort, 'ROOT', tmp_path)
    cohort.run()
    output = pq.read_table(tmp_path/'data/iridium_next_orbit_history.parquet')
    assert output['norad_id'].to_pylist() == [41917, 41918]
    assert policy_path.read_bytes() == policy_bytes
    assert member_path.read_bytes() == member_bytes
    assert not (tmp_path/'data/constellations').exists()
