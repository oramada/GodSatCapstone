import datetime as dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq
import pyarrow as pa
import pytest

import godsat.catalog_trajectory as catalog
import scripts.validation.audit_catalog_trajectory as trajectory_audit


UTC = dt.timezone.utc


def element(norad_id, epoch):
    return {'norad_id': norad_id, 'epoch': epoch,
        'inclination': 51.64, 'raan': 120.0, 'eccentricity': 0.0005,
        'arg_perigee': 80.0, 'mean_anomaly': 0.0, 'mean_motion': 15.5,
        'mean_motion_dot': 0.0, 'bstar': 0.00001}


def setup_catalog_root(root, start):
    coverage = root/'data/state_vector_object_coverage.csv'
    coverage.parent.mkdir(parents=True)
    coverage.write_text(
        'norad_id,historical_element_rows,first_element_epoch,last_element_epoch\n'
        f'22,5,{start.isoformat()},{start.isoformat()}\n'
        f'23,2,{start.isoformat()},{start.isoformat()}\n'
        f'24,1,2020-01-01T00:00:00+00:00,2020-01-01T00:00:00+00:00\n')
    raw = root/'data/raw'
    raw.mkdir(parents=True)
    (raw/'manifest.json').write_text(json.dumps({'revision':'fixture-revision'}))
    export=root/'data/historical_state_vectors_all'
    export.mkdir(parents=True)
    (export/'manifest.json').write_text(json.dumps({'status':'completed',
        'signature':'fixture-signature','records_written':8}))
    (root/'data/state_vector_object_coverage.json').write_text(json.dumps({
        'status':'completed','export_signature':'fixture-signature',
        'parquet_records_scanned':8,'snapshot_matches_manifest':True}))


def test_catalog_cohort_uses_overlap_and_max_age(tmp_path):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)
    assert catalog.catalog_object_ids(tmp_path,start,start+dt.timedelta(days=1),72)==[22,23]
    assert catalog.catalog_object_ids(tmp_path,start,start+dt.timedelta(days=1),0)==[22,23]


def test_catalog_cohort_parses_duckdb_utc_timestamp_text(tmp_path):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)
    path=tmp_path/'data/state_vector_object_coverage.csv'
    path.write_text(path.read_text().replace('T00:00:00+00:00',' 00:00:00+00'))
    assert catalog.catalog_object_ids(tmp_path,start,start+dt.timedelta(days=1),72)==[22,23]


def test_catalog_cohort_refuses_stale_index(tmp_path):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)
    index=tmp_path/'data/state_vector_object_coverage.json'
    payload=json.loads(index.read_text());payload['export_signature']='old-signature'
    index.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError,match='stale'):
        catalog.catalog_object_ids(tmp_path,start,start+dt.timedelta(days=1),72)


def test_bulk_export_writes_complete_matrix_and_resumes(tmp_path,monkeypatch):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)
    records_calls=[]

    class FakeHistory:
        def __init__(self,root,cohort,window=None,max_age_hours=72):
            assert cohort=='all'
            self.db=SimpleNamespace(close=lambda:None)
        def records(self,lower,upper,max_age=72,ids=None):
            records_calls.append((lower,upper))
            return [element(22,start)]

    monkeypatch.setattr(catalog,'History',FakeHistory)
    output=tmp_path/'ephemeris'
    manifest=catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=2),
        output,step_seconds=3600,root=tmp_path)
    assert manifest['status']=='completed'
    assert manifest['object_count']==2
    assert manifest['projected_rows']==4
    assert manifest['completed_rows']==4
    assert manifest['successful']==2
    assert manifest['stale_or_missing']==2
    part=output/'part-00000.parquet'
    table=pq.read_table(part).to_pylist()
    assert len(table)==4
    assert {row['norad_id'] for row in table}=={22,23}
    assert [row['sgp4_error'] for row in table if row['norad_id']==23]==[-1,-1]
    assert all(row['orbit_regime']=='leo' for row in table if row['norad_id']==22)

    monkeypatch.setattr(trajectory_audit,'History',FakeHistory)
    validation=trajectory_audit.audit(output,tmp_path,samples_per_status=1)
    assert validation['status']=='validated_complete'
    assert validation['rows']==4
    assert validation['source_validation_batches'][0]['source_validation']['max_abs_position_delta_km']==0

    before=len(records_calls)
    resumed=catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=2),
        output,step_seconds=3600,root=tmp_path)
    assert resumed['completed_rows']==4
    assert len(records_calls)==before


def test_bulk_export_rejects_signature_changes_and_non_daily_cadence(tmp_path):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)
    with pytest.raises(ValueError,match='divisor of 86400'):
        catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=1),
            tmp_path/'bad',step_seconds=7,root=tmp_path)


def test_part_checksum_tampering_is_detected(tmp_path):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)

    class FakeHistory:
        def __init__(self,*args,**kwargs): self.db=SimpleNamespace(close=lambda:None)
        def records(self,*args,**kwargs): return [element(22,start)]

    old=catalog.History
    catalog.History=FakeHistory
    try:
        output=tmp_path/'ephemeris'
        catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=1),
            output,step_seconds=3600,root=tmp_path)
    finally:
        catalog.History=old
    part=output/'part-00000.parquet'
    part.write_bytes(part.read_bytes()+b'tamper')
    with pytest.raises(RuntimeError,match='(checksum|size) mismatch'):
        catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=1),
            output,step_seconds=3600,root=tmp_path)


def test_sampled_catalog_audit_is_explicit_and_does_not_replace_full_report(tmp_path,monkeypatch):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)

    class FakeHistory:
        def __init__(self,*args,**kwargs): self.db=SimpleNamespace(close=lambda:None)
        def records(self,*args,**kwargs): return [element(22,start)]

    monkeypatch.setattr(catalog,'History',FakeHistory)
    monkeypatch.setattr(trajectory_audit,'History',FakeHistory)
    output=tmp_path/'ephemeris'
    catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=1),
        output,step_seconds=3600,root=tmp_path)
    result=trajectory_audit.audit(output,tmp_path,samples_per_status=1,
        sample_parts=1)
    assert result['status']=='validated_sampled'
    assert result['verification_scope']=='stratified manifest part sample'
    assert result['parts_validated']==1
    assert result['manifest_parts']==1
    assert result['sampled_part_indices']==[0]
    assert (output/'validation-sampled.json').is_file()
    assert not (output/'validation.json').exists()


@pytest.mark.parametrize('corruption', ['duplicate_pair', 'nonfinite_success'])
def test_grouped_full_audit_catches_invalid_unsampled_grid_rows(tmp_path, monkeypatch, corruption):
    start=dt.datetime(2025,1,1,tzinfo=UTC)
    setup_catalog_root(tmp_path,start)

    class FakeHistory:
        def __init__(self,*args,**kwargs): self.db=SimpleNamespace(close=lambda:None)
        def records(self,*args,**kwargs): return [element(22,start)]

    monkeypatch.setattr(catalog,'History',FakeHistory)
    monkeypatch.setattr(trajectory_audit,'History',FakeHistory)
    output=tmp_path/'ephemeris'
    catalog.export_catalog_trajectory(start,start+dt.timedelta(hours=2),output,
        step_seconds=3600,root=tmp_path)
    assert trajectory_audit.audit(output,tmp_path,samples_per_status=1)['status']=='validated_complete'
    manifest_path=output/'manifest.json';manifest=json.loads(manifest_path.read_text())
    item=manifest['parts'][0];part=output/item['file']
    table=pq.read_table(part);rows=table.to_pylist()
    successful=[index for index,row in enumerate(rows) if row['sgp4_error']==0]
    if corruption=='duplicate_pair':
        # Preserve row count, all object/time axes and status totals while losing one key.
        rows[successful[1]]=dict(rows[successful[0]])
    else:
        rows[successful[0]]['x_teme_km']=float('nan')
    pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),part)
    # Model an internally checksummed bad export rather than a checksum mismatch.
    item.update(sha256=hashlib.sha256(part.read_bytes()).hexdigest(),size_bytes=part.stat().st_size)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(AssertionError,match='Part integrity/grid/status'):
        trajectory_audit.audit(output,tmp_path,samples_per_status=1)
