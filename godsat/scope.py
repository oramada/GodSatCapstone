"""Explicit participating-system limits for the current study.

Archived studies retain their old definitions. New preparation in a workspace
with an active scope must honor its allowlists, including before cache reuse.
"""
import hashlib
import json
from pathlib import Path

from .orbits import ROOT


def active_scope(root=ROOT):
    path = Path(root)/'configs/active-study-scope.json'
    return json.loads(path.read_text()) if path.exists() else None


def allowed_ids(root=ROOT, policy=None):
    policy = policy if policy is not None else active_scope(root)
    if policy is None:
        return None
    path = Path(root)/policy['iridium_next_membership']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != policy['iridium_next_membership_sha256']:
        raise ValueError('Iridium NEXT membership differs from the pinned active scope')
    membership = json.loads(raw)
    ids = {int(row['norad_id']) for row in membership['members']}
    if not ids or len(ids) != len(membership['members']):
        raise ValueError('Iridium NEXT membership is empty or contains duplicate IDs')
    return ids


def validate_preparation(config, regime, root=ROOT):
    policy = active_scope(root)
    if policy is None:
        return None
    if regime != 'leo':
        raise ValueError('Active study permits Iridium NEXT LEO only. Optional MEO is disabled until a named constellation and explicit membership are configured; GEO/HEO and mixed all-orbit runs are excluded.')
    if config.get('sensor_cohort') != 'iridium_next' or config.get('target_cohort') != 'iridium_next':
        raise ValueError('Active study requires iridium_next cohorts for orbital participants; mixed-catalogue configurations are archived and cannot be prepared as current-study scenarios.')
    if config.get('allow_non_payload_sensor_hosts', False):
        raise ValueError('Non-payload sensor hosts are outside the active study scope')
    return allowed_ids(root, policy)


def validate_selected(ids, root=ROOT, permitted=None):
    permitted = permitted if permitted is not None else allowed_ids(root)
    if permitted is not None:
        outside = set(map(int, ids))-permitted
        if outside:
            raise ValueError(f'Orbital participants outside Iridium NEXT allowlist: {sorted(outside)}')


def validate_execution(root=ROOT):
    policy = active_scope(root)
    if policy and policy.get('ground_systems_required'):
        raise ValueError('Current study requires ground systems. The existing orbital-only campaign runner cannot represent them. Ground-system roles and a compatible scenario implementation must be established before a new campaign; an orbital-only result must not be labeled Iridium NEXT plus ground.')
