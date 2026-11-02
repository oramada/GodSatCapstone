import hashlib
import json

import numpy as np
import pytest

from godsat.scenario import cache_key, prepare
from godsat.scope import allowed_ids, validate_execution, validate_preparation, validate_selected


@pytest.fixture
def scoped(tmp_path):
    configs = tmp_path/'configs'
    configs.mkdir()
    member_path = configs/'members.json'
    member_path.write_text(json.dumps({'members': [{'norad_id': 41917}, {'norad_id': 41918}]}))
    policy = {'iridium_next_membership': 'configs/members.json',
              'iridium_next_membership_sha256': hashlib.sha256(member_path.read_bytes()).hexdigest(),
              'ground_systems_required': True,
              'optional_meo': {'enabled': False}}
    (configs/'active-study-scope.json').write_text(json.dumps(policy))
    config = {'sensor_cohort': 'iridium_next', 'target_cohort': 'iridium_next',
              'agents': 1, 'targets': 1, 'duration_minutes': 2, 'step_seconds': 60,
              'max_element_age_hours': 72, 'max_range_km': 6000}
    return tmp_path, config


@pytest.mark.parametrize('field', ['sensor_cohort', 'target_cohort'])
def test_scope_rejects_mixed_catalogue_roles(scoped, field):
    root, config = scoped
    with pytest.raises(ValueError, match='mixed-catalogue'):
        validate_preparation({**config, field: 'current_payload'}, 'leo', root)


@pytest.mark.parametrize('regime', ['meo', 'geo', 'heo', 'all'])
def test_optional_meo_is_not_silently_enabled(scoped, regime):
    root, config = scoped
    with pytest.raises(ValueError, match='Optional MEO is disabled'):
        validate_preparation(config, regime, root)


def test_catalogue_identity_not_name_or_orbit_controls_membership(scoped):
    root, _ = scoped
    validate_selected([41917, 41918], root)
    with pytest.raises(ValueError, match='24793'):
        validate_selected([41917, 24793], root)  # Legacy Iridium ID, also in LEO.


def test_changed_membership_cannot_reuse_existing_pin(scoped):
    root, config = scoped
    (root/'configs/members.json').write_text(json.dumps({'members': [{'norad_id': 24793}]}))
    with pytest.raises(ValueError, match='differs from the pinned'):
        validate_preparation(config, 'leo', root)


@pytest.mark.parametrize('ids,accepted', [([41917, 41918], True), ([41917, 24793], False)])
def test_scope_checked_on_actual_cached_arrays_before_reuse(scoped, ids, accepted):
    root, config = scoped
    date = '2026-10-01T00:00:00Z'
    folder = root/'data/scenarios'
    folder.mkdir(parents=True)
    path = folder/(cache_key(date, config, root=root)+'.npz')
    np.savez(path, ids=ids)
    path.with_suffix('.json').write_text('{}')
    if accepted:
        assert prepare(date, config, root=root) == path
    else:
        with pytest.raises(ValueError, match='outside Iridium NEXT'):
            prepare(date, config, root=root)


def test_scope_policy_invalidates_previously_unscoped_cache_key(scoped):
    root, config = scoped
    before = cache_key('2026-10-01', config, root=root)
    (root/'configs/active-study-scope.json').unlink()
    assert cache_key('2026-10-01', config, root=root) != before


def test_ground_requirement_blocks_orbital_only_study(scoped):
    root, _ = scoped
    with pytest.raises(ValueError, match='orbital-only campaign runner'):
        validate_execution(root)


def test_original_apis_remain_available_in_workspaces_without_current_scope(tmp_path):
    assert allowed_ids(tmp_path) is None
    assert validate_preparation({'sensor_cohort': 'all'}, 'geo', tmp_path) is None
    validate_execution(tmp_path)
