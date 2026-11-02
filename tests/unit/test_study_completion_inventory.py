import hashlib
import json

from scripts.validation.audit_study_completion import inspect_artifact, inventory


def test_a_sampled_catalog_validation_does_not_satisfy_full_history_audit(tmp_path):
    path = tmp_path/'validation.json'
    path.write_text(json.dumps({'status': 'validated_sampled', 'parts_validated': 5}))
    row = inspect_artifact(tmp_path, 'full catalog', path.name, 'validated_complete',
                           {'parts_validated': 1462})
    assert row['state'] == 'incomplete'
    assert row['field_checks']['parts_validated']['matches'] is False


def test_protocol_claim_without_source_pdf_and_changed_evidence_cannot_establish_completion(tmp_path):
    output = tmp_path/'outputs/study-execution'; output.mkdir(parents=True)
    (output/'source-protocol-audit.json').write_text(json.dumps({
        'status': 'requirement_by_requirement_verified', 'source_pdf_sha256': None,
        'requirements': [{'text': 'claimed protocol requirement'}], 'remaining_requirements': []}))
    evidence = tmp_path/'measured.json'; evidence.write_text('{"status":"partial"}')
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    (output/'evidence-index.json').write_text(json.dumps({'artifacts': {
        'measured': {'path': evidence.name, 'sha256': digest}}}))
    evidence.write_text('{"status":"completed"}')
    result = inventory(tmp_path)
    assert result['source_pdf']['state'] == 'missing'
    assert result['requirements'][0]['state'] == 'unverified_protocol_binding'
    assert result['stale_or_missing_index_entries'] == [{'name': 'measured', 'path': evidence.name}]
    assert result['all_required_recorded_audits_passed'] is False
