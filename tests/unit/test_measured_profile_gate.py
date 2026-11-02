import json

import pytest

from scripts.experiments.run_measured_profile_tasking import validate_source_gate


def test_measured_tasking_requires_full_raw_source_and_absence_audits(tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps({'status': 'completed', 'failures': [],
        'products_validated': 2, 'days_not_published': 1, 'requested_days': 3, 'days_processed': 3}))
    audit = {'status': 'passed_structural_and_statistical', 'downloaded_days': 2,
             'source_cdf_replay_requested': True, 'source_cdf_days_replayed': 2,
             'publisher_absence_verification_requested': True,
             'publisher_absence_probes_verified': 1, 'failures': []}
    path = tmp_path/'independent_audit.json'
    path.write_text(json.dumps(audit))
    assert validate_source_gate(tmp_path) == audit
    audit['source_cdf_days_replayed'] = 1
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match='Complete source-CDF replay'):
        validate_source_gate(tmp_path)
