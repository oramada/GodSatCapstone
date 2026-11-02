import datetime as dt
import hashlib
import json
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from godsat import server
from godsat.server import (object_coverage_payload, quarterly_dropout_output,
                           monthly_dropout_output, monthly_dropout_progress,
                           detection_sensitivity_output,
                           detection_sensitivity_payload,
                           full_catalog_seed_sensitivity_payload,
                           full_catalog_weekly_tasking_payload,
                           full_catalog_empirical_block_tasking_payload,
                           cassiope_attitude_telemetry_payload,
                           on_orbit_dropout_payload,
                           on_orbit_attitude_payload,
                           awp_historical_payload,
                           awp_nbody_payload,
                           catalog_trajectory_progress,
                           catalog_trajectory_refresh_info,
                           catalog_trajectory_refresh_csv_payload,
                           catalog_ephemeris_csv_payload,
                           random_search_payload,
                           state_vector_index_payload,
                           trajectory_csv_payload,
                           current_active_snapshot_payload,
                           current_active_snapshot_csv,
                           ztf_opportunity_payload,
                           ztf_fullnight_payload,
                           ztf_exposure_path_payload,
                           ztf_edge_crossing_payload,
                           ztf_image_sample_payload,
                           ztf_injected_streak_payload,
                           ztf_real_image_association_payload)


def test_latest_source_trajectory_endpoint_uses_audited_grid_only(tmp_path):
    folder=tmp_path/'outputs/catalog-trajectory-source-refresh-2026-10-08-10'
    folder.mkdir(parents=True)
    source=tmp_path/'data/raw/snapshots/2026-10-11/tle_2026.parquet'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'fixture source')
    source_manifest={"revision":"r1","sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
                     "dataset_last_modified_utc":"2026-10-10T18:08:19Z"}
    source_manifest_path=source.parent/'source_manifest.json'
    source_manifest_path.write_text(json.dumps(source_manifest))
    part=folder/'part-00000.parquet'
    table=pa.table({
        'norad_id':pa.array([25544],type=pa.int32()),
        'time_utc':['2026-10-08T00:00:00+00:00'],
        'element_epoch':['2026-10-07T23:00:00+00:00'],
        'element_age_hours':pa.array([1.0],type=pa.float64()),
        'orbit_regime':['leo'],'sgp4_error':pa.array([0],type=pa.int16()),
        'x_teme_km':pa.array([1.0],type=pa.float64()),'y_teme_km':pa.array([2.0],type=pa.float64()),
        'z_teme_km':pa.array([3.0],type=pa.float64()),'vx_teme_km_s':pa.array([4.0],type=pa.float64()),
        'vy_teme_km_s':pa.array([5.0],type=pa.float64()),'vz_teme_km_s':pa.array([6.0],type=pa.float64()),
    })
    pq.write_table(table,part)
    part_hash=hashlib.sha256(part.read_bytes()).hexdigest()
    manifest={"status":"completed","source_revision":"r1","source_file_sha256":source_manifest['sha256'],
              "start_inclusive":"2026-10-08T00:00:00+00:00","end_exclusive":"2026-10-10T00:00:00+00:00",
              "step_seconds":14400,"objects":1,"rows":12,"status_counts":{},
              "part":{"file":part.name,"sha256":part_hash}}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    (folder/'independent_audit.json').write_text(json.dumps({
        "status":"passed_source_and_baseline_reconciliation","source_sha256":source_manifest['sha256'],
        "trajectory_rows_checked":12,"independent_state_replays":1,"comparison_to_pinned_archive":{},
        "checks":{"hashes":True,"rows":True}}))

    info=catalog_trajectory_refresh_info(tmp_path)
    csv_text,metadata=catalog_trajectory_refresh_csv_payload(
        25544,'2026-10-08T00:00:00Z','2026-10-08T04:00:00Z',tmp_path)
    assert info['source_revision']=='r1'
    assert metadata['status']=='passed_source_and_baseline_reconciliation'
    assert '2026-10-08T00:00:00+00:00' in csv_text
    with pytest.raises(ValueError,match='align'):
        catalog_trajectory_refresh_csv_payload(25544,'2026-10-08T01:00:00Z','2026-10-08T04:00:00Z',tmp_path)
    with pytest.raises(ValueError,match='within'):
        catalog_trajectory_refresh_csv_payload(25544,'2026-10-07T20:00:00Z','2026-10-08T04:00:00Z',tmp_path)


def test_ztf_opportunity_payload_requires_reproducible_five_track_set(tmp_path):
    folder=tmp_path/'outputs/ztf-palomer-opportunity-poc'
    folder.mkdir(parents=True)
    payload={'candidates':[
        {'expid':exposure,'image_sha256':'a'*64,'image_url':'https://irsa.example/image.fits'}
        for exposure in ('one','one','two','three','four')]}
    (folder/'audit.json').write_text(json.dumps(payload))
    assert len(ztf_opportunity_payload(tmp_path)['candidates'])==5

    payload['candidates'].pop()
    (folder/'audit.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='five candidate tracks'):
        ztf_opportunity_payload(tmp_path)


def test_ztf_fullnight_payload_reconciles_source_and_crossing_counts(tmp_path):
    metadata=tmp_path/'data/ground_sensor/ztf_palomer_poc/ztf_metadata_2024-07-10_fullnight.csv'
    metadata.parent.mkdir(parents=True)
    metadata.write_text('expid,obsdate\none,2024-07-10T00:00:00+00:00\ntwo,2024-07-10T00:01:00+00:00\n')
    candidates=[{'expid':'one','norad_id':123,'sunlit_midpoint':True}]
    payload={
        'source_metadata_file':'data/ground_sensor/ztf_palomer_poc/ztf_metadata_2024-07-10_fullnight.csv',
        'metadata_sha256':hashlib.sha256(metadata.read_bytes()).hexdigest(),
        'metadata_rows':2,'exposures':2,'catalog_ids_considered':1,
        'totals':{'candidate_footprint_tracks':1,'sunlit_candidate_footprint_tracks':1,
                  'exposures_with_midpoint_tracks':1},
        'exposure_summary':[{'expid':'one','footprint_tracks':1},
                            {'expid':'two','footprint_tracks':0}],
        'candidates':candidates,
    }
    audit=tmp_path/'outputs/ztf-palomer-fullnight-2024-07-10/midpoint_crossing_audit.json'
    audit.parent.mkdir(parents=True)
    audit.write_text(json.dumps(payload))
    assert ztf_fullnight_payload(tmp_path)['candidates']==candidates
    metadata.write_text(metadata.read_text().replace('one,', 'new,'))
    with pytest.raises(ValueError,match='checksum'):
        ztf_fullnight_payload(tmp_path)


def test_ztf_exposure_path_payload_matches_all_midpoint_candidate_keys(tmp_path):
    folder=tmp_path/'outputs/ztf-palomer-fullnight-2024-07-10'
    folder.mkdir(parents=True)
    candidate={'expid':'one','ccdid':4,'qid':2,'norad_id':123}
    midpoint={'metadata_sha256':'a'*64,'candidates':[candidate]}
    midpoint_path=folder/'midpoint_crossing_audit.json'
    midpoint_path.write_text(json.dumps(midpoint))
    path_candidate={**candidate,'any_path_sunlit_observable_inside':True}
    audit={
        'status':'completed_full_exposure_paths_for_midpoint_candidates',
        'metadata_sha256':'a'*64,
        'midpoint_audit_sha256':hashlib.sha256(midpoint_path.read_bytes()).hexdigest(),
        'totals':{
            'midpoint_candidates_replayed':1,'candidates_with_path_inside':1,
                'candidates_with_observable_path_inside':1,
                'candidates_with_sunlit_observable_path_inside':1,
                'exposures_with_any_sunlit_observable_path_inside':1,
                'maximum_midpoint_direction_error_arcsec':0.01,
        },
        'candidates':[path_candidate],
    }
    path=folder/'exposure_path_audit.json'
    path.write_text(json.dumps(audit))
    assert ztf_exposure_path_payload(tmp_path)['candidates']==[path_candidate]
    audit['candidates'][0]['qid']=3
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError,match='do not reconcile'):
        ztf_exposure_path_payload(tmp_path)


def test_ztf_edge_payload_requires_complete_disjoint_reconciled_ledger(tmp_path):
    folder=tmp_path/'outputs/ztf-palomer-fullnight-2024-07-10'
    folder.mkdir(parents=True)
    midpoint={'metadata_sha256':'a'*64,'candidates':[{'expid':'one','ccdid':4,'qid':2,'norad_id':1}]}
    midpoint_path=folder/'midpoint_crossing_audit.json'
    midpoint_path.write_text(json.dumps(midpoint))
    candidate={'expid':'two','ccdid':4,'qid':2,'norad_id':2,
               'crosses_quadrant_during_exposure':True,
               'observable_crossing_above_10deg':True,'sunlit_observable_crossing':True}
    payload={'status':'completed_screened_edge_crossing_replay','scope_complete':True,
             'metadata_sha256':'a'*64,
             'midpoint_audit_sha256':hashlib.sha256(midpoint_path.read_bytes()).hexdigest(),
             'totals':{'screened_candidates':1,'exact_path_edge_crossings':1,
                       'observable_edge_crossings_above_10deg':1,'sunlit_observable_edge_crossings':1,
                       'exposures_with_edge_crossing':1,
                       'exposures_with_sunlit_observable_edge_crossing':1},
             'candidates':[candidate]}
    (folder/'edge_crossing_audit.json').write_text(json.dumps(payload))
    assert ztf_edge_crossing_payload(tmp_path)['candidates']==[candidate]
    payload['scope_complete']=False
    (folder/'edge_crossing_audit.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='do not reconcile'):
        ztf_edge_crossing_payload(tmp_path)


def test_ztf_image_sample_payload_checks_source_keys_and_image_hashes(tmp_path):
    import hashlib
    folder=tmp_path/'outputs/ztf-palomer-fullnight-2024-07-10'
    folder.mkdir(parents=True)
    key={'expid':'one','ccdid':4,'qid':2,'norad_id':123}
    midpoint={'metadata_sha256':'a'*64,'candidates':[key]}
    (folder/'midpoint_crossing_audit.json').write_text(json.dumps(midpoint))
    path_audit={'candidates':[{**key,'any_path_sunlit_observable_inside':True}]}
    (folder/'exposure_path_audit.json').write_text(json.dumps(path_audit))
    (folder/'edge_crossing_audit.json').write_text(json.dumps({'candidates':[]}))
    image=tmp_path/'data/image.fits';image.parent.mkdir();image.write_bytes(b'fake image bytes')
    row={**key,'path_source':'midpoint_candidate','tle_epoch_utc':'2024-01-01T00:00:00+00:00'}
    hashes={'midpoint_audit_sha256':hashlib.sha256((folder/'midpoint_crossing_audit.json').read_bytes()).hexdigest(),
            'exposure_path_audit_sha256':hashlib.sha256((folder/'exposure_path_audit.json').read_bytes()).hexdigest(),
            'edge_crossing_audit_sha256':hashlib.sha256((folder/'edge_crossing_audit.json').read_bytes()).hexdigest()}
    payload={'status':'completed_profile_audit','metadata_sha256':'a'*64,
             'images_completed':1,'opportunity_count':1,**hashes,
             'image_results':[{'image_path':'data/image.fits','image_bytes':image.stat().st_size,
                'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                'candidate_count':1,'candidate_results':[row]}]}
    (folder/'image_sample_audit.json').write_text(json.dumps(payload))
    assert ztf_image_sample_payload(tmp_path)['opportunity_count']==1
    payload['image_results'][0]['image_sha256']='0'*64
    (folder/'image_sample_audit.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='checksum'):
        ztf_image_sample_payload(tmp_path)


def test_ztf_injected_streak_payload_requires_leave_one_exposure_out_sample(tmp_path):
    folder=tmp_path/'outputs/ztf-palomer-fullnight-2024-07-10';folder.mkdir(parents=True)
    sample={'status':'completed_profile_audit','images_completed':1,
            'image_results':[{'expid':'one','image_sha256':'b'*64}]}
    sample_path=folder/'image_sample_audit.json';sample_path.write_text(json.dumps(sample))
    trial={'maglimit_offset':-3.0,'score_over_global_sigma':2.0,
           'above_training_thresholds':{'0.9':True}}
    candidate={'norad_id':123,'injection_trials':[trial]}
    payload={'status':'completed_image_level_injection_benchmark',
             'image_sample_sha256':hashlib.sha256(sample_path.read_bytes()).hexdigest(),
             'heldout_image_results':[{'expid':'one','image_sha256':'b'*64,
                 'training_exposure_ids':[],'candidate_results':[candidate]}],
             'summary_by_magnitude':[{'maglimit_offset':-3.0,'trials':1,
                 'detection_fraction_at_training_null_quantile':{'0.9':1.0}}]}
    (folder/'injected_streak_detection_benchmark.json').write_text(json.dumps(payload))
    assert ztf_injected_streak_payload(tmp_path)['status']=='completed_image_level_injection_benchmark'
    payload['heldout_image_results'][0]['training_exposure_ids']=['one']
    (folder/'injected_streak_detection_benchmark.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='leakage'):
        ztf_injected_streak_payload(tmp_path)


def test_ztf_real_image_association_payload_checks_sample_provenance(tmp_path):
    import hashlib
    folder=tmp_path/'outputs/ztf-palomer-fullnight-2024-07-10'
    folder.mkdir(parents=True)
    sample_path=folder/'image_sample_audit.json'
    sample_path.write_text(json.dumps({'opportunity_count':2}))
    payload={'status':'completed_descriptive_real_image_path_association_audit',
             'image_sample_sha256':hashlib.sha256(sample_path.read_bytes()).hexdigest(),
             'selection_and_measurement':{'profiled_opportunities':1,'profile_unavailable':1},
             'opportunity_results':[{},{}]}
    result_path=folder/'real_image_path_association_audit.json'
    result_path.write_text(json.dumps(payload))
    assert ztf_real_image_association_payload(tmp_path)['opportunity_results']==[{},{}]
    payload['selection_and_measurement']['profile_unavailable']=0
    result_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='do not match'):
        ztf_real_image_association_payload(tmp_path)


def test_quarterly_dropout_endpoint_prefers_latest_completed_study(tmp_path):
    outputs=tmp_path/'outputs'
    v4=outputs/'four-year-quarterly-dropout-v4'
    v5=outputs/'four-year-quarterly-dropout-v5-multiseed'
    v6=outputs/'four-year-quarterly-dropout-v6-active-hosts'
    v4.mkdir(parents=True)
    v5.mkdir(parents=True)
    v6.mkdir(parents=True)
    (v4/'dropout_summary.json').write_text('{}')
    (v5/'dropout_summary.json').write_text('{}')
    (v6/'dropout_summary.json').write_text('{}')

    assert quarterly_dropout_output(tmp_path)==v6

    (v6/'dropout_summary.json').unlink()
    assert quarterly_dropout_output(tmp_path)==v5
    (v5/'dropout_summary.json').unlink()
    assert quarterly_dropout_output(tmp_path)==v4


def test_monthly_dropout_endpoint_uses_48_date_extension_output(tmp_path):
    outputs=tmp_path/'outputs'
    active=outputs/'four-year-monthly-dropout-v3-active-hosts'
    legacy=outputs/'four-year-monthly-dropout-v1-multiseed'
    legacy.mkdir(parents=True)
    (legacy/'dropout_summary.json').write_text(json.dumps({'status':'completed'}))
    assert monthly_dropout_output(tmp_path)==legacy
    active.mkdir(parents=True)
    (active/'dropout_summary.json').write_text(json.dumps({'status':'completed'}))
    assert monthly_dropout_output(tmp_path)==active


def test_detection_sensitivity_payload_requires_all_row_audits(tmp_path):
    root=tmp_path/'outputs/four-year-quarterly-detection-sensitivity-v3-active-hosts'
    folder=root/'pbase-0.50'
    folder.mkdir(parents=True)
    signature='design-sha'
    design={'design_signature':signature,'design':{
        'dates':['2026-01-01'],'regimes':['leo'],'modes':['burst'],'rates':[0.0],
        'replicates':1,'model_seeds':[101],'config':{'detection_probability':0.5}}}
    (folder/'dropout_design.json').write_text(json.dumps(design))
    (folder/'dropout_summary.json').write_text(json.dumps({'status':'completed','design_signature':signature}))
    (folder/'dropout_integrity_audit.json').write_text(json.dumps({
        'status':'completed_valid','design_signature':signature,'expected_treatment_rows':1,
        'rows_read':1,'unique_valid_rows':1,'missing_rows':0,'duplicate_rows':0,
        'unexpected_rows':0,'malformed_rows':0}))
    (root/'sensitivity_summary.json').write_text(json.dumps({'status':'completed','results':{
        'pbase-0.50':{'status':'completed','design_signature':signature,
                      'detection_probability_base_assumption':0.5}}}))
    assert detection_sensitivity_payload(tmp_path)['results']['pbase-0.50']['design_signature']==signature

    audit=json.loads((folder/'dropout_integrity_audit.json').read_text())
    audit['missing_rows']=1
    (folder/'dropout_integrity_audit.json').write_text(json.dumps(audit))
    with pytest.raises(ValueError,match='audit failed'):
        detection_sensitivity_payload(tmp_path)


def test_detection_sensitivity_uses_latest_saved_complete_summary(tmp_path):
    outputs=tmp_path/'outputs'
    legacy=outputs/'four-year-quarterly-detection-sensitivity-v1'
    legacy.mkdir(parents=True)
    (legacy/'sensitivity_summary.json').write_text(json.dumps({'status':'completed'}))
    assert detection_sensitivity_output(tmp_path)==legacy
    active=outputs/'four-year-quarterly-detection-sensitivity-v3-active-hosts'
    active.mkdir()
    (active/'sensitivity_summary.json').write_text(json.dumps({'status':'in_progress'}))
    assert detection_sensitivity_output(tmp_path)==legacy
    (active/'sensitivity_summary.json').write_text(json.dumps({'status':'completed'}))
    assert detection_sensitivity_output(tmp_path)==active


def test_dust_anchored_detection_sensitivity_is_preferred_and_requires_independent_audit(tmp_path):
    root=tmp_path/'outputs/four-year-quarterly-dust-anchored-detection-sensitivity'
    levels=[0.9762,0.9890,0.9972]
    dates=[f'2026-01-{day:02d}T00:00:00Z' for day in range(1,18)]
    results={}
    for probability in levels:
        label=f'pbase-{probability:.2f}';signature=f'signature-{label}';folder=root/label
        folder.mkdir(parents=True)
        design={'design_signature':signature,'design':{
            'dates':dates,'regimes':['leo','meo','geo','heo'],
            'modes':['independent','burst'],'rates':[0.0,0.2],
            'replicates':1,'model_seeds':[101],
            'config':{'detection_probability':probability}}}
        (folder/'dropout_design.json').write_text(json.dumps(design))
        (folder/'dropout_summary.json').write_text(json.dumps({
            'status':'completed','design_signature':signature}))
        (folder/'dropout_integrity_audit.json').write_text(json.dumps({
            'status':'completed_valid','design_signature':signature,
            'expected_treatment_rows':272,'rows_read':272,'unique_valid_rows':272,
            'missing_rows':0,'duplicate_rows':0,'unexpected_rows':0,'malformed_rows':0}))
        results[label]={'status':'completed','design_signature':signature,
            'detection_probability_base_assumption':probability}
    (root/'sensitivity_summary.json').write_text(json.dumps({
        'status':'completed','probability_levels':levels,'dates':dates,'results':results,
        'interpretation_note':'DUST conditional continuity proxy; not calibrated probability.'}))
    (root/'independent_sensitivity_audit.json').write_text(json.dumps({
        'status':'completed_valid','probability_levels':levels,'date_clusters':17,
        'independent_regime_mode_effect_checks':24,'independent_interaction_checks':24}))

    assert detection_sensitivity_output(tmp_path)==root
    payload=detection_sensitivity_payload(tmp_path)
    assert payload['evidence_basis']['measured_conditional_frame_continuity']==0.989
    assert payload['evidence_basis']['independent_sensitivity_audit_status']=='completed_valid'

    audit=json.loads((root/'independent_sensitivity_audit.json').read_text())
    audit['status']='failed'
    (root/'independent_sensitivity_audit.json').write_text(json.dumps(audit))
    with pytest.raises(ValueError,match='independent audit'):
        detection_sensitivity_payload(tmp_path)


def test_current_active_snapshot_api_requires_audited_hash_and_serves_csv(tmp_path):
    import hashlib
    import pyarrow as pa
    import pyarrow.parquet as pq

    folder=tmp_path/'data/current_active_catalog_snapshot_2026-10-10'
    folder.mkdir(parents=True)
    parquet=folder/'active_payload_common_epoch.parquet'
    pq.write_table(pa.table({'norad_id':[12345],'state_status':['success'],
        'x_teme_km':[1.0],'y_teme_km':[2.0],'z_teme_km':[3.0]}),parquet)
    digest=hashlib.sha256(parquet.read_bytes()).hexdigest()
    source_hash='snapshot-source';satcat_hash='satcat-source'
    manifest={'status':'completed','state_output':parquet.name,'parquet_sha256':digest,
        'source_snapshot_sha256':source_hash,'satcat_sha256':satcat_hash,
        'query_epoch_utc':'2026-10-10T09:11:18+00:00','cohort_definition':'fixture',
        'current_payload_candidates':1,'current_payload_states_written':1,
        'state_status_counts':{'success':1},'historical_archive_ids':100,
        'current_payload_ids_with_archived_history':0,
        'current_payload_ids_without_archived_history':1,
        'interpretation':'current snapshot only','limitations':['no backfill'],
        'frame':'TEME','units':{'position':'km','velocity':'km/s'}}
    audit={'status':'passed_structural_and_sampled_state_reproduction',
        'output_sha256':digest,'output_rows_checked':1,
        'historical_archive_ids':100,
        'source_snapshot_sha256':source_hash,'satcat_sha256':satcat_hash,
        'successful_current_states_without_historical_elements':1,
        'independent_sample_rows':1,
        'independent_sample_max_abs_position_difference_km':0.0,
        'independent_sample_max_abs_velocity_difference_km_s':0.0}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    (folder/'independent_audit.json').write_text(json.dumps(audit))

    payload=current_active_snapshot_payload(tmp_path)
    assert payload['status']=='completed_valid'
    assert payload['successful_current_states_without_archived_history']==1
    csv=current_active_snapshot_csv(tmp_path)
    assert 'norad_id,state_status,x_teme_km' in csv
    assert '12345,success,1.0' in csv

    manifest['parquet_sha256']='bad-hash'
    (folder/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='hash or independent-audit'):
        current_active_snapshot_payload(tmp_path)


def test_on_orbit_dropout_payload_requires_completed_audited_summary(tmp_path):
    folder=tmp_path/'data/onboard_sensor/dust_star_tracker/dropout_study'
    summary=folder/'frame_dropout_summary.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps({'status':'completed','results':[{'mode':'burst'}]}))
    import hashlib
    gap_csv=b'session,track_id,frame,score\n'
    (folder/'internal_gap_image_signal.csv').write_bytes(gap_csv)
    (folder/'dataset_audit.json').write_text(json.dumps({'status':'completed',
        'archive_md5':'dust-md5',
        'image_frames':1378,'annotated_detection_rows':4237,'annotated_transits':160,
        'internal_transit_frame_coverage':{'recorded_frame_fraction':0.98,
            'unannotated_internal_frames':47,
            'custody_sensitivity_if_internal_gaps_are_misses':{'results':[{'grace_seconds':1}]}}}))
    (folder/'internal_gap_image_signal_audit.json').write_text(json.dumps({
        'status':'completed','archive_md5':'dust-md5','internal_gap_frames_scored':47,
        'csv':'internal_gap_image_signal.csv','csv_sha256':hashlib.sha256(gap_csv).hexdigest(),
        'labeled_rso_instances_scored':4237,'background_control_positions_scored':100,
        'annotation_set_summary':{'SET 1':{'gap_frames_scored':0},'SET 2':{'gap_frames_scored':47}},
        'positive_labeled_distribution':{'median':12.7},
        'gap_interpolated_distribution':{'median':5.0},
        'background_control_distribution':{'median':1.6},'positive_vs_background_auc':0.97,
        'gap_score_fraction_at_or_above_positive_p10':0.6,
        'gap_score_fraction_at_or_above_background_p95':0.53,
        'same_frame_background_test':{'tested_gaps':47,'gaps_bh_q_below_0_05':10},
        'limitations':[]}))
    metadata_csv=b'norad_id,platform,epoch_utc\n39265,CASSIOPE,2023-01-01T00:00:00Z\n'
    (folder/'spacecraft_attitude_ephemeris.csv').write_bytes(metadata_csv)
    metadata_hash=hashlib.sha256(metadata_csv).hexdigest()
    cadence={'status':'completed','archive_md5':'dust-md5',
        'metadata_csv_sha256':metadata_hash,'image_frames_checked':1378}
    cadence_path=folder/'capture_cadence_audit.json'
    cadence_path.write_text(json.dumps(cadence))
    cadence_hash=hashlib.sha256(cadence_path.read_bytes()).hexdigest()
    custody={'status':'completed_conditional_cadence_custody_sensitivity',
        'archive_md5':'dust-md5','metadata_csv_sha256':metadata_hash,
        'cadence_audit_sha256':cadence_hash,'sessions':22,'annotated_transits':160,
        'transit_weighted_expected_1hz_slots':4378,
        'missing_capture_slots_inside_annotated_transits':94,
        'captured_but_unlabeled_slots_inside_annotated_transits':47,
        'manual_label_coverage_of_transit_slots':4237/4378,
        'bootstrap':{'replicates':10000},
        'results':[{'grace_seconds':5,'equal_weight_session_mean_custody':{
            'observed_manual_labels':0.982,'fill_missing_capture_slots_with_perfect_detections':0.999},
            'paired_custody_effect_percentage_points':{'capture_gap_fill_minus_observed':{
                'mean':1.71,'ci95_session_cluster_bootstrap':[0.0,4.98]}}}],
        'interpretation':'Conditional sensitivity only.','limitations':['No hardware attempt log.']}
    custody_path=folder/'capture_cadence_custody.json'
    custody_path.write_text(json.dumps(custody))
    (folder/'capture_cadence_custody_audit.json').write_text(json.dumps({
        'status':'passed_independent_source_and_statistical_reproduction',
        'archive_md5':'dust-md5','metadata_csv_sha256':metadata_hash,
        'cadence_audit_sha256':cadence_hash,
        'custody_result_sha256':hashlib.sha256(custody_path.read_bytes()).hexdigest(),
        'zero_mismatches':True,'sessions_checked':22,'transits_checked':160,
        'transit_weighted_expected_slots':4378,'missing_capture_slots_reproduced':94,
        'captured_but_unlabeled_slots_reproduced':47}))
    interpolation_csv=b'session,track_id,error_px\nSET1,1,0.5\n'
    (folder/'gap_interpolation_cross_validation.csv').write_bytes(interpolation_csv)
    (folder/'gap_interpolation_cross_validation.json').write_text(json.dumps({
        'status':'completed_labeled_track_interpolation_cross_validation',
        'archive_md5':'dust-md5',
        'validation_design':{'heldout_frames':48410,
            'csv_sha256':hashlib.sha256(interpolation_csv).hexdigest()},
        'by_gap_length':[{'gap_length_frames':1,'pixel_error_p95':0.83},
                         {'gap_length_frames':13,'pixel_error_p95':7.21}],
        'interpretation_limit':'Localization validation only.'}))
    payload=on_orbit_dropout_payload(tmp_path)
    assert payload['results'][0]['mode']=='burst'
    assert payload['image_frames']==1378
    assert payload['internal_transit_frame_coverage']['recorded_frame_fraction']==0.98
    assert payload['internal_transit_frame_coverage']['custody_sensitivity_if_internal_gaps_are_misses']['results'][0]['grace_seconds']==1
    assert payload['internal_gap_image_signal']['gap_interpolated_distribution']['median']==5.0
    assert payload['internal_gap_image_signal']['same_frame_background_test']['gaps_bh_q_below_0_05']==10
    assert payload['capture_cadence_custody']['missing_capture_slots_inside_annotated_transits']==94
    assert payload['capture_cadence_custody']['independent_audit_status']=='passed_independent_source_and_statistical_reproduction'
    assert payload['gap_interpolation_validation']['validation_design']['heldout_frames']==48410

    (folder/'internal_gap_image_signal.csv').write_text('tampered')
    with pytest.raises(ValueError,match='checksum mismatch'):
        on_orbit_dropout_payload(tmp_path)

    summary.write_text(json.dumps({'status':'running','results':[]}))
    with pytest.raises(ValueError,match='not complete'):
        on_orbit_dropout_payload(tmp_path)


def test_full_catalog_seed_sensitivity_payload_requires_fresh_independent_audit(tmp_path):
    import hashlib
    base=tmp_path/'outputs/full-catalog-tasking-monthly-2022-2026'
    extra=tmp_path/'outputs/full-catalog-tasking-seed-sensitivity-2022-2026'
    base.mkdir(parents=True)
    extra.mkdir(parents=True)
    primary=base/'summary.json';primary.write_text('{}')
    primary_audit=base/'independent_audit.json';primary_audit.write_text('{}')
    effects=[{'sensor_host_regime':regime} for regime in ('leo','meo','geo','heo')]
    interactions=[{'sensor_host_regime':regime,'metrics':{'custody_continuity':{}}}
                  for regime in ('leo','meo','geo','heo')]
    (extra/'seed_sensitivity.json').write_text(json.dumps({
        'status':'completed','seed':90210,'dates':[f'month-{i}' for i in range(48)],
        'response_rows':[{} for _ in range(384)],
        'primary_summary_sha256':hashlib.sha256(primary.read_bytes()).hexdigest(),
        'primary_integrity_audit_sha256':hashlib.sha256(primary_audit.read_bytes()).hexdigest()}))
    (extra/'independent_audit.json').write_text(json.dumps({
        'status':'passed_source_design_and_statistical_reproduction','dates_checked':48,
        'paired_date_regime_cells_checked':192,'response_rows_checked':384,
        'scenario_cache_hashes_verified':192,
        'checks':{'paired_seed_by_outage_interactions_recomputed':True},
        'date_clustered_effects':effects,'seed_by_outage_interaction':interactions}))
    payload=full_catalog_seed_sensitivity_payload(tmp_path)
    assert payload['seed']==90210
    assert payload['paired_responses']==384
    assert len(payload['effects_by_regime'])==4

    primary_audit.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='provenance is stale'):
        full_catalog_seed_sensitivity_payload(tmp_path)


def test_full_catalog_weekly_tasking_payload_requires_complete_independent_audit(tmp_path):
    folder=tmp_path/'outputs/full-catalog-tasking-weekly-2022-2026'
    folder.mkdir(parents=True)
    from datetime import date, timedelta
    start=date(2022,10,15)
    dates=[(start+timedelta(days=7*i)).isoformat()+'T00:00:00Z' for i in range(208)]
    rows=[]
    for when in dates:
        for regime in ('leo','meo','geo','heo'):
            for rate in (0.0,0.2):
                rows.append({'date':when,'orbit_regime_sensor_hosts':regime,
                    'requested_outage_rate':rate,'catalog_objects_in_episode':25000,
                    'sensor_actions':350,'custody_continuity':0.001 if rate==0 else 0.0008})
    effects=[{'sensor_host_regime':regime,
        'custody_change_20pct_minus_0':{'mean':-0.0002,'ci95_date_clustered':[-0.0003,-0.0001]},
        'observable_custody_change_20pct_minus_0':{'mean':-0.01,'ci95_date_clustered':[-0.02,-0.005]}}
        for regime in ('leo','meo','geo','heo')]
    (folder/'summary.json').write_text(json.dumps({'status':'completed','target_cohort':'all',
        'dates':dates,'completed_date_regime_groups':832,'rows':rows,'paired_effects':effects}))
    (folder/'independent_audit.json').write_text(json.dumps({
        'status':'passed_structural_and_statistical','dates_checked':208,
        'paired_date_regime_cells_checked':832,'response_rows_checked':1664,
        'sensor_host_scenario_hashes_verified':832,
        'historical_host_state_availability':{'cells_recomputed':832},
        'scenario_metadata_checksum_mismatches':[]}))
    payload=full_catalog_weekly_tasking_payload(tmp_path)
    assert payload['dates']==208
    assert payload['paired_responses']==1664
    assert payload['mean_candidate_catalog_ids_per_episode']==25000
    assert len(payload['effects_by_regime'])==4

    audit=folder/'independent_audit.json'
    changed=json.loads(audit.read_text());changed['response_rows_checked']=1600
    audit.write_text(json.dumps(changed))
    with pytest.raises(ValueError,match='audit has not passed'):
        full_catalog_weekly_tasking_payload(tmp_path)


def test_full_catalog_empirical_block_payload_requires_source_matched_audit(tmp_path):
    from datetime import date, timedelta
    start=date(2022,10,15)
    dates=[(start+timedelta(days=7*i)).isoformat()+'T00:00:00Z' for i in range(208)]
    weekly=tmp_path/'outputs/full-catalog-tasking-weekly-2022-2026'
    empirical=tmp_path/'outputs/full-catalog-tasking-epop-empirical-block-weekly-2022-2026'
    telemetry=tmp_path/'data/attitude/cassiope_epop'
    for folder in (weekly,empirical,telemetry): folder.mkdir(parents=True)
    (weekly/'summary.json').write_text(json.dumps({'dates':dates}))
    mask=telemetry/'dropout_masks_1minute.npz';mask.write_bytes(b'audited compact masks')
    mask_hash=hashlib.sha256(mask.read_bytes()).hexdigest()
    profile_file=telemetry/'dropout_profile_1minute.json';profile_file.write_text('{"status":"completed"}')
    profile_hash=hashlib.sha256(profile_file.read_bytes()).hexdigest()
    (telemetry/'dropout_masks_independent_audit.json').write_text(json.dumps({
        'status':'passed_independent_source_replay','mask_archive_sha256':mask_hash,
        'source_profile_sha256':profile_hash}))
    effects=[{'sensor_host_regime':regime} for regime in ('leo','meo','geo','heo')]
    (empirical/'summary.json').write_text(json.dumps({
        'status':'completed','target_cohort':'all','dates':dates,
        'completed_date_regime_groups':832,'rows':[{} for _ in range(1664)],
        'dropout_profile':{'mode':'empirical_block','rate':0.25,
            'source_profile_sha256':profile_hash,'mask_archive_sha256':mask_hash},
        'paired_effects':effects,'limits':['one spacecraft']}))
    (empirical/'independent_audit.json').write_text(json.dumps({
        'status':'passed_structural_and_statistical','dates_checked':208,
        'paired_date_regime_cells_checked':832,'response_rows_checked':1664,
        'date_cluster_effects_independently_recomputed':True,
        'checks':{'empirical_mask_archive_hash_and_source_audit':True}}))
    payload=full_catalog_empirical_block_tasking_payload(tmp_path)
    assert payload['dates']==208
    assert payload['paired_responses']==1664
    assert payload['dropout_rate']==0.25
    assert payload['mask_archive_sha256']==mask_hash
    assert len(payload['effects_by_regime'])==4

    mask.write_bytes(b'changed')
    with pytest.raises(ValueError,match='provenance is stale'):
        full_catalog_empirical_block_tasking_payload(tmp_path)


def test_cassiope_attitude_telemetry_payload_requires_independent_audit(tmp_path):
    folder=tmp_path/'data/attitude/cassiope_epop'
    folder.mkdir(parents=True)
    (folder/'manifest.json').write_text(json.dumps({'status':'running','days_processed':1}))
    (folder/'independent_audit.json').write_text(json.dumps({
        'status':'passed_structural_and_statistical','coverage_status':'fetch_in_progress_or_interrupted',
        'manifest_days_processed_at_audit':1,'downloaded_days':1,'requested_days':1462,
        'validated_dates':['2022-10-09'],
        'first_day':'2022-10-09','last_day':'2022-10-09','not_published_days':[],
        'totals':{'samples':86400,'valid_quaternion_seconds':78075,
            'invalid_quaternion_seconds':8325,'dropout_events':44},
        'longest_solution_dropout_seconds':230,
        'sensor_source_code_counts':{'previous':{'0':8325},'next':{'0':8325}},
        'sensor_source_code_labels':{'0':'dropout'},'yearly':{'2022':{'days':1,'samples':86400}},
        'limitations':['single spacecraft']}))
    (folder/'dropout_profile_1minute.json').write_text(json.dumps({
        'status':'completed','source_audit_status':'passed_structural_and_statistical',
        'published_days_analyzed':1,'source_date_range':['2022-10-09','2022-10-09'],
        'one_minute_samples':1440,'one_minute_attitude_solution_dropout_rate':0.1,
        'one_minute_dropout_rate_date_cluster_bootstrap_ci95':[0.05,0.15],
        'simulator_markov_persistence_parameter':0.7,
        'dropout_run_length_minutes':{'mean':2,'median':1,'p95':3,'max':10},
        'per_day':[{'date':'2022-10-09'}]}))
    import hashlib
    profile_hash=hashlib.sha256((folder/'dropout_profile_1minute.json').read_bytes()).hexdigest()
    (folder/'solution_quality_1minute.json').write_text(json.dumps({
        'status':'completed','source_audit_status':'passed_structural_and_statistical',
        'source_profile_sha256':profile_hash,'sampled_days':1,'sampled_minutes':1440,
        'quality_class_counts':{'dropout':144,'coarse_sun_magnetometer':0,
            'star_tracker':1296,'unknown':0}}))
    payload=cassiope_attitude_telemetry_payload(tmp_path)
    assert payload['audited_days']==1
    assert payload['samples']==86400
    assert payload['invalid_quaternion_seconds']==8325
    assert payload['longest_solution_dropout_seconds']==230
    assert payload['one_minute_dropout_rate']==0.1
    assert payload['one_minute_persistence']==0.7
    assert payload['attitude_solution_quality']['quality_class_counts']['star_tracker']==1296
    (folder/'independent_audit.json').write_text('{"status":"failed"}')
    with pytest.raises(ValueError,match='independent audit'):
        cassiope_attitude_telemetry_payload(tmp_path)


def test_on_orbit_attitude_payload_reconciles_full_metadata_rows_and_summary(tmp_path):
    folder=tmp_path/'data/onboard_sensor/dust_star_tracker/dropout_study'
    folder.mkdir(parents=True)
    rows=[
        '39265,CASSIOPE,DUST/SET 1/2023_01_16,1,2023-01-16T21:27:05.303000Z,a.h5,1,1,-2,10,400',
        '39265,CASSIOPE,DUST/SET 1/2023_01_16,2,2023-01-16T21:27:06.303000Z,b.h5,2,3,2,30,410',
    ]
    fields='norad_id,platform,session,frame_index,epoch_utc,h5_filename,attitude_determination_mode,pitch_deg,roll_deg,yaw_deg,sc_altitude_km'
    (folder/'spacecraft_attitude_ephemeris.csv').write_text(fields+'\n'+'\n'.join(rows)+'\n')
    metadata={
        'status':'completed','metadata_source_md5':'source-md5','spacecraft':'CASSIOPE (NORAD 39265)',
        'matched_metadata_rows':2,'matched_h5_files':2,
        'utc_start':'2023-01-16T21:27:05.303000Z','utc_end':'2023-01-16T21:27:06.303000Z',
        'pitch_deg':{'count':2,'min':1.0,'median':2.0,'max':3.0},
        'roll_deg':{'count':2,'min':-2.0,'median':0.0,'max':2.0},
        'yaw_deg':{'count':2,'min':10.0,'median':20.0,'max':30.0},
        'altitude_km':{'count':2,'min':400.0,'median':405.0,'max':410.0},
        'attitude_mode_counts':{'1':1,'2':1},'limitations':['No reference frame asserted.']}
    (folder/'dataset_audit.json').write_text(json.dumps({
        'status':'completed','dataset':'DUST','observation_sessions':1,
        'spacecraft_attitude_ephemeris':metadata}))
    payload=on_orbit_attitude_payload(tmp_path)
    assert payload['status']=='completed_valid'
    assert payload['frame_count']==2
    assert payload['session_count']==1
    assert payload['ranges']['sc_altitude_km']['median']==405
    assert payload['sessions'][0]['frames']==2

    (folder/'spacecraft_attitude_ephemeris.csv').write_text(fields+'\n'+rows[0]+'\n')
    with pytest.raises(ValueError,match='row count'):
        on_orbit_attitude_payload(tmp_path)
    (folder/'spacecraft_attitude_ephemeris.csv').write_text(
        fields+'\n'+rows[0].replace(',1,-2,10,400',',99,-2,10,400')+'\n'+rows[1]+'\n')
    with pytest.raises(ValueError,match='pitch_deg does not match'):
        on_orbit_attitude_payload(tmp_path)


def test_awp_historical_payload_requires_completed_comparison(tmp_path):
    path=tmp_path/'outputs/awp-historical-sensitivity-2022-2026/summary.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'status':'completed',
        'summary_by_regime_model_and_lead':[{'orbit_regime':'leo'}]}))
    assert awp_historical_payload(tmp_path)['status']=='completed'

    path.write_text(json.dumps({'status':'running','summary_by_regime_model_and_lead':[]}))
    with pytest.raises(ValueError,match='not complete'):
        awp_historical_payload(tmp_path)


def test_awp_nbody_payload_requires_four_regime_complete_comparison(tmp_path):
    path=tmp_path/'outputs/awp-nbody-sensitivity-2026-10-01/summary.json'
    path.parent.mkdir(parents=True)
    csv_path=path.parent/'awp_nbody_comparisons.csv'
    csv_path.write_text('comparison rows')
    import hashlib
    path.write_text(json.dumps({'status':'completed','comparison_rows':32,
        'csv':csv_path.name,'csv_sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'summary_by_regime_model_and_lead':[]}))
    assert awp_nbody_payload(tmp_path)['comparison_rows']==32
    path.write_text(json.dumps({'status':'running','comparison_rows':16}))
    with pytest.raises(ValueError,match='incomplete'):
        awp_nbody_payload(tmp_path)


def test_catalog_trajectory_progress_reports_pending_and_live_totals(tmp_path):
    pending=catalog_trajectory_progress(tmp_path)
    assert pending['status']=='pending'
    assert pending['records_written']==0

    output=tmp_path/'outputs/catalog-trajectory-all-4hour-2022-2026'
    output.mkdir(parents=True)
    manifest={'status':'running','start':'2025-01-01T00:00:00+00:00',
        'end_exclusive':'2025-01-03T00:00:00+00:00','step_seconds':14400,
        'object_count':100,'projected_rows':1200,'records_written':600,
        'frame':'TEME','model':'SGP4 test model','parts':[
            {'rows':600,'size_bytes':1024,'successful':590,
             'sgp4_errors':2,'stale_or_missing':8}]}
    (output/'manifest.json').write_text(json.dumps(manifest))
    progress=catalog_trajectory_progress(tmp_path)
    assert progress['status']=='running'
    assert progress['projected_parts']==2
    assert progress['progress_fraction']==0.5
    assert progress['records_written']==600
    assert progress['bytes_written']==1024
    assert progress['stale_or_missing']==8


def test_audited_catalog_ephemeris_csv_is_bounded_and_filterable(tmp_path):
    output=tmp_path/'outputs/catalog-trajectory-all-4hour-2022-2026'
    output.mkdir(parents=True)
    start=dt.datetime(2025,1,1,tzinfo=dt.timezone.utc)
    end=start+dt.timedelta(days=1)
    rows=[]
    for norad_id in (22,23):
        for hour in (0,4):
            rows.append({'norad_id':norad_id,
                'time_utc':(start+dt.timedelta(hours=hour)).isoformat(),
                'element_epoch':start.isoformat(),'element_age_hours':float(hour),
                'orbit_regime':'leo','sgp4_error':0,'x_teme_km':1.0,
                'y_teme_km':2.0,'z_teme_km':3.0,'vx_teme_km_s':4.0,
                'vy_teme_km_s':5.0,'vz_teme_km_s':6.0})
    pq.write_table(pa.Table.from_pylist(rows),output/'part-00000.parquet')
    signature='fixture-signature'
    manifest={'status':'completed','signature':signature,
        'start':start.isoformat(),'end_exclusive':end.isoformat(),
        'step_seconds':14400,'object_count':2,'projected_rows':4,
        'completed_rows':4,'parts_written':1,
        'parts':[{'file':'part-00000.parquet',
            'start_inclusive':start.isoformat(),'end_exclusive':end.isoformat()}]}
    (output/'manifest.json').write_text(json.dumps(manifest))
    (output/'validation.json').write_text(json.dumps({
        'status':'validated_complete','signature':signature,
        'rows':4,'parts_validated':1}))

    all_rows=catalog_ephemeris_csv_payload(start,end,root=tmp_path)
    assert all_rows.count('\n')==5
    assert all_rows.splitlines()[0].startswith('norad_id,time_utc,element_epoch')
    one_object=catalog_ephemeris_csv_payload(start,end,norad_id=22,root=tmp_path)
    assert one_object.count('\n')==3
    assert all(line.startswith('22,') for line in one_object.splitlines()[1:])
    with pytest.raises(ValueError,match='24 hours'):
        catalog_ephemeris_csv_payload(start,end+dt.timedelta(seconds=1),root=tmp_path)
    (output/'validation.json').write_text(json.dumps({'status':'running'}))
    with pytest.raises(ValueError,match='not passed validation'):
        catalog_ephemeris_csv_payload(start,end,root=tmp_path)


def test_random_search_payload_requires_completed_integrity_audit(tmp_path):
    output=tmp_path/'outputs/all-orbits-random-search-31'
    output.mkdir(parents=True)
    (output/'summary.json').write_text(json.dumps({'status':'completed',
        'test_metrics':{'custody_continuity':{'mean':0.2}}}))
    (output/'random_search_integrity_audit.json').write_text(json.dumps({
        'status':'validated_complete','search_trials':31}))
    payload=random_search_payload(tmp_path)
    assert payload['integrity_audit']['search_trials']==31

    (output/'random_search_integrity_audit.json').write_text(json.dumps({'status':'running'}))
    with pytest.raises(ValueError,match='incomplete or unaudited'):
        random_search_payload(tmp_path)


def test_monthly_dropout_progress_reports_complete_cells_and_expected_rows(tmp_path):
    output=monthly_dropout_output(tmp_path)
    output.mkdir(parents=True)
    design={'dates':['2022-10-09','2022-11-09'],'regimes':['leo','geo'],
        'rates':[0.0,0.05],'modes':['independent','burst'],'replicates':2,
        'model_seeds':[101,211,307,401,503]}
    (output/'dropout_design.json').write_text(json.dumps({'design':design}))
    with (output/'dropout_responses.csv').open('w') as stream:
        stream.write('date,regime\n')
        stream.writelines('2022-10-09,leo\n' for _ in range(40))

    progress=monthly_dropout_progress(tmp_path)
    assert progress['status']=='running'
    assert progress['completed_cells']==1
    assert progress['total_cells']==4
    assert progress['rows_written']==40
    assert progress['expected_rows']==4*2*2*2*5


def test_state_vector_index_freshness_is_checked_against_live_manifest(tmp_path):
    data=tmp_path/'data'
    export=data/'historical_state_vectors_all'
    export.mkdir(parents=True)
    index={'status':'completed','export_signature':'same-signature',
           'manifest_records_written':10,'parquet_records_scanned':10,
           'snapshot_matches_manifest':True}
    manifest={'signature':'same-signature','status':'running','records_written':11}
    (data/'state_vector_object_coverage.json').write_text(json.dumps(index))
    manifest_path=export/'manifest.json'
    manifest_path.write_text(json.dumps(manifest))

    stale=state_vector_index_payload(tmp_path)
    assert stale['snapshot_matches_manifest'] is True
    assert stale['snapshot_matches_current_export'] is False
    assert stale['current_export_records_written']==11

    manifest['records_written']=10
    manifest_path.write_text(json.dumps(manifest))
    current=state_vector_index_payload(tmp_path)
    assert current['snapshot_matches_current_export'] is True


def test_object_coverage_includes_state_and_live_export_status(tmp_path):
    data=tmp_path/'data'
    export=data/'historical_state_vectors_all'
    export.mkdir(parents=True)
    (data/'state_vector_object_coverage.csv').write_text(
        'norad_id,historical_element_rows,first_element_epoch,last_element_epoch,'
        'state_vector_rows,first_state_epoch,last_state_epoch,successful_states,'
        'failed_states,materialized_fraction,historical_element_rows_2022,'
        'state_vector_rows_2022,historical_element_rows_2023,state_vector_rows_2023\n'
        '25544,20,2022-01-01,2026-01-01,10,2022-01-01,2024-01-01,10,0,0.5,20,10,0,0\n'
        '25545,3,2022-01-01,2023-01-01,1,2022-01-01,2022-01-01,1,0,0.333,1,1,2,0\n')
    index={'export_signature':'sig','parquet_records_scanned':10,'model':'SGP4','frame':'TEME'}
    (data/'state_vector_object_coverage.json').write_text(json.dumps(index))
    manifest={'signature':'sig','status':'running','records_written':10,
              'years':{'2022':{'complete':True,'records':1}}}
    manifest_path=export/'manifest.json'
    manifest_path.write_text(json.dumps(manifest))

    manifest['records_written']=11
    manifest_path.write_text(json.dumps(manifest))
    stale=object_coverage_payload(25544,tmp_path)
    assert stale['state_coverage_status']=='stale_index'
    assert all(year['status']=='index_stale' for year in stale['yearly_coverage'])

    manifest['records_written']=10
    manifest_path.write_text(json.dumps(manifest))

    row=object_coverage_payload(25544,tmp_path)
    assert row['historical_element_rows']==20
    assert row['state_vector_rows']==10
    assert row['materialized_fraction']==0.5
    assert row['coverage_index_matches_current_export'] is True
    assert row['model']=='SGP4'
    assert row['state_coverage_status']=='missing_state_rows_in_completed_years'
    assert row['yearly_coverage']==[
        {'year':2022,'historical_element_rows':20,'state_vector_rows':10,
         'status':'missing_state_rows_in_completed_year'},
        {'year':2023,'historical_element_rows':0,'state_vector_rows':0,
         'status':'no_archived_records'},
    ]

    pending=object_coverage_payload(25545,tmp_path)
    assert pending['state_coverage_status']=='export_in_progress'
    assert pending['yearly_coverage'][1]['status']=='export_not_started'


def test_trajectory_csv_is_bounded_and_contains_explicit_sample_rows(tmp_path,monkeypatch):
    import datetime as dt
    from types import SimpleNamespace

    epoch=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
    record={'norad_id':25544,'epoch':epoch,'inclination':51.64,'raan':120.0,
        'eccentricity':0.0005,'arg_perigee':80.0,'mean_anomaly':0.0,
        'mean_motion':15.5,'mean_motion_dot':0.0,'bstar':0.00001}

    class FakeHistory:
        def __init__(self,root,cohort,window=None,max_age_hours=None):
            assert cohort=='all'
            assert window==(epoch,epoch+dt.timedelta(minutes=2))
            assert max_age_hours==72.0
            self.db=SimpleNamespace(close=lambda:None)
        def records(self,*args,**kwargs):
            assert kwargs['ids']==[25544]
            return [record]

    monkeypatch.setattr(server,'History',FakeHistory)
    text=trajectory_csv_payload(25544,epoch,epoch+dt.timedelta(minutes=2),60,root=tmp_path)
    assert text.startswith('norad_id,time_utc,element_epoch')
    assert text.count('\n')==3
    with pytest.raises(ValueError,match='maximum is 100000'):
        trajectory_csv_payload(25544,epoch,epoch+dt.timedelta(days=2),1,root=tmp_path)
