import csv
import datetime as dt
import hashlib
import io
import json
import duckdb
import math
import re
import statistics
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .orbits import ROOT, History, utc
from .trajectory import CSV_COLUMNS, trajectory_rows


def full_catalog_daily_tasking_progress_payload(root=ROOT):
    """Serve checkpoint and independently audited prefix as distinct scopes."""
    folder=Path(root)/'outputs/full-catalog-tasking-daily-2022-2026'
    progress=json.loads((folder/'progress.json').read_text())
    audit=json.loads((folder/'completed_prefix_audit.json').read_text())
    effects=json.loads((folder/'preliminary_prefix_effects.json').read_text())
    if progress.get('status') not in {'running_checkpointed','partial','completed'}:
        raise ValueError('Daily all-catalog tasking progress status is invalid')
    if audit.get('status')!='passed_completed_prefix_independent_audit':
        raise ValueError('Daily all-catalog tasking prefix audit has not passed')
    audit_count=int(audit.get('dates_checked',0))
    if (audit_count<1 or audit.get('paired_date_regime_cells_checked')!=audit_count*4
            or audit.get('response_rows_checked')!=audit_count*8
            or effects.get('status')!='preliminary_audited_prefix_effects'
            or effects.get('dates')!=audit_count
            or effects.get('prefix_audit_status')!=audit['status']):
        raise ValueError('Daily tasking prefix effects do not match the audited prefix')
    progress_hashes=progress.get('cell_files_sha256',{})
    audit_hashes=audit.get('cell_files_sha256',{})
    for relative,digest in audit_hashes.items():
        cell=folder/relative
        if not cell.is_file() or hashlib.sha256(cell.read_bytes()).hexdigest()!=digest:
            raise ValueError('Daily tasking cell no longer matches its independent audit hash')
        if progress_hashes and progress_hashes.get(relative)!=digest:
            raise ValueError('Daily tasking progress and independent audit cell hashes disagree')
    return {
        'status':progress['status'],
        'final_results':bool(progress.get('final_results',False)),
        'completed_dates':int(progress.get('complete_date_count',0)),
        'expected_dates':int(progress.get('expected_date_count',0)),
        'completed_groups':int(progress.get('verified_completed_date_regime_groups',
                                             progress.get('completed_date_regime_groups',0))),
        'expected_groups':int(progress.get('expected_date_regime_groups',0)),
        'completed_range':progress.get('completed_date_range'),
        'audited_dates':audit_count,
        'audited_range':audit.get('date_range'),
        'audited_cells':audit['paired_date_regime_cells_checked'],
        'audited_response_rows':audit['response_rows_checked'],
        'custody_effects':{regime:item['custody_continuity']
                           for regime,item in effects.get('effects',{}).items()},
        'interpretation':'Checkpoint and audited-prefix counts are separate. Effects cover only the independently audited prefix and are preliminary simulated sensitivities, not measured ground-sensor dropout effectiveness.',
    }

def quarterly_dropout_output(root=ROOT):
    candidates=[root/'outputs'/name for name in (
        'four-year-quarterly-dropout-v6-active-hosts',
        'four-year-quarterly-dropout-v6-payload-hosts',
        'four-year-quarterly-dropout-v5-multiseed',
        'four-year-quarterly-dropout-v4',
        'four-year-quarterly-dropout-v3',
        'four-year-quarterly-dropout')]
    return next((candidate for candidate in candidates
        if (candidate/'dropout_summary.json').is_file()),candidates[-1])


def monthly_dropout_output(root=ROOT):
    candidates=[Path(root)/'outputs'/name for name in (
        'four-year-monthly-dropout-v3-active-hosts',
        'four-year-monthly-dropout-v2-payload-hosts',
        'four-year-monthly-dropout-v1-multiseed')]
    for candidate in candidates:
        path=candidate/'dropout_summary.json'
        if path.is_file() and json.loads(path.read_text()).get('status')=='completed':
            return candidate
    return candidates[-1]


def detection_sensitivity_output(root=ROOT):
    candidates=[Path(root)/'outputs'/name for name in (
        'four-year-quarterly-dust-anchored-detection-sensitivity',
        'four-year-quarterly-detection-sensitivity-v3-active-hosts',
        'four-year-quarterly-detection-sensitivity-v2-payload-hosts',
        'four-year-quarterly-detection-sensitivity-v1')]
    for candidate in candidates:
        path=candidate/'sensitivity_summary.json'
        if path.is_file() and json.loads(path.read_text()).get('status')=='completed':
            return candidate
    return candidates[-1]


def detection_sensitivity_payload(root=ROOT):
    """Serve detection-probability sensitivity only when every design audit passes."""
    output=detection_sensitivity_output(root)
    payload=json.loads((output/'sensitivity_summary.json').read_text())
    if payload.get('status')!='completed' or not payload.get('results'):
        raise ValueError('Detection-probability sensitivity study is not complete')
    for label,item in payload['results'].items():
        folder=output/label
        design=json.loads((folder/'dropout_design.json').read_text())
        audit=json.loads((folder/'dropout_integrity_audit.json').read_text())
        summary=json.loads((folder/'dropout_summary.json').read_text())
        spec=design.get('design',{})
        expected=(len(spec.get('dates',[]))*len(spec.get('regimes',[]))*len(spec.get('modes',[]))
                  *len(spec.get('rates',[]))*int(spec.get('replicates',0))
                  *len(spec.get('model_seeds',[])))
        expected_probability=float(item['detection_probability_base_assumption'])
        valid=(item.get('status')=='completed'
            and design.get('design_signature')==item.get('design_signature')
            and summary.get('design_signature')==item.get('design_signature')
            and summary.get('status')=='completed'
            and audit.get('status')=='completed_valid'
            and audit.get('design_signature')==item.get('design_signature')
            and audit.get('expected_treatment_rows')==expected
            and audit.get('rows_read')==expected
            and audit.get('unique_valid_rows')==expected
            and audit.get('missing_rows')==0
            and audit.get('duplicate_rows')==0
            and audit.get('unexpected_rows')==0
            and audit.get('malformed_rows')==0
            and float(spec.get('config',{}).get('detection_probability',-1))==expected_probability)
        if not valid:
            raise ValueError(f'Detection-probability audit failed for {label}')
    if output.name=='four-year-quarterly-dust-anchored-detection-sensitivity':
        independent=json.loads((output/'independent_sensitivity_audit.json').read_text())
        expected_levels=[0.9762,0.9890,0.9972]
        if (independent.get('status')!='completed_valid'
                or independent.get('probability_levels')!=expected_levels
                or independent.get('date_clusters')!=17
                or independent.get('independent_regime_mode_effect_checks')!=24
                or independent.get('independent_interaction_checks')!=24
                or payload.get('probability_levels')!=expected_levels
                or len(payload.get('dates',[]))!=17):
            raise ValueError('DUST-anchored detection sensitivity lacks its independent audit')
        payload['evidence_basis']={
            'source':'DUST on-orbit star-tracker annotated transit frames',
            'measured_conditional_frame_continuity':0.9890,
            'session_cluster_bootstrap_ci95':[0.9762,0.9972],
            'interpretation':payload.get('interpretation_note'),
            'independent_sensitivity_audit_status':independent['status'],
        }
    return payload


def on_orbit_dropout_payload(root=ROOT):
    """Return audited DUST dropout, image-signal, and capture-cadence evidence."""
    folder=Path(root)/'data/onboard_sensor/dust_star_tracker/dropout_study'
    path=folder/'frame_dropout_summary.json'
    audit_path=folder/'dataset_audit.json'
    image_path=folder/'internal_gap_image_signal_audit.json'
    payload=json.loads(path.read_text())
    if payload.get('status')!='completed' or not payload.get('results'):
        raise ValueError('On-orbit dropout replay is not complete')
    audit=json.loads(audit_path.read_text())
    if audit.get('status')!='completed':
        raise ValueError('On-orbit dataset audit is not complete')
    payload.update({key:audit[key] for key in
        ('image_frames','annotated_detection_rows','annotated_transits',
         'internal_transit_frame_coverage')})
    image_audit=json.loads(image_path.read_text())
    if (image_audit.get('status')!='completed'
            or image_audit.get('archive_md5')!=audit.get('archive_md5')
            or image_audit.get('internal_gap_frames_scored')
                !=audit['internal_transit_frame_coverage']['unannotated_internal_frames']):
        raise ValueError('DUST raw-image gap audit is incomplete or does not match the source audit')
    image_csv=folder/image_audit['csv']
    if hashlib.sha256(image_csv.read_bytes()).hexdigest()!=image_audit.get('csv_sha256'):
        raise ValueError('DUST raw-image gap CSV checksum mismatch')
    payload['internal_gap_image_signal']={key:image_audit[key] for key in (
        'labeled_rso_instances_scored','internal_gap_frames_scored',
        'background_control_positions_scored','annotation_set_summary','positive_labeled_distribution',
        'gap_interpolated_distribution','background_control_distribution',
        'positive_vs_background_auc','gap_score_fraction_at_or_above_positive_p10',
        'gap_score_fraction_at_or_above_background_p95','same_frame_background_test','limitations')}
    cadence_path=folder/'capture_cadence_audit.json'
    custody_path=folder/'capture_cadence_custody.json'
    custody_audit_path=folder/'capture_cadence_custody_audit.json'
    cadence=json.loads(cadence_path.read_text())
    custody=json.loads(custody_path.read_text())
    custody_audit=json.loads(custody_audit_path.read_text())
    metadata_path=folder/'spacecraft_attitude_ephemeris.csv'
    metadata_hash=hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    cadence_hash=hashlib.sha256(cadence_path.read_bytes()).hexdigest()
    custody_hash=hashlib.sha256(custody_path.read_bytes()).hexdigest()
    if (cadence.get('status')!='completed'
            or cadence.get('archive_md5')!=audit.get('archive_md5')
            or cadence.get('metadata_csv_sha256')!=metadata_hash
            or cadence.get('image_frames_checked')!=audit.get('image_frames')):
        raise ValueError('DUST timestamp cadence audit does not match the audited source data')
    if (custody.get('status')!='completed_conditional_cadence_custody_sensitivity'
            or custody.get('archive_md5')!=audit.get('archive_md5')
            or custody.get('metadata_csv_sha256')!=metadata_hash
            or custody.get('cadence_audit_sha256')!=cadence_hash):
        raise ValueError('DUST timestamp-grid custody sensitivity has invalid source provenance')
    if (custody_audit.get('status')!='passed_independent_source_and_statistical_reproduction'
            or custody_audit.get('archive_md5')!=audit.get('archive_md5')
            or custody_audit.get('metadata_csv_sha256')!=metadata_hash
            or custody_audit.get('cadence_audit_sha256')!=cadence_hash
            or custody_audit.get('custody_result_sha256')!=custody_hash
            or custody_audit.get('zero_mismatches') is not True
            or custody_audit.get('sessions_checked')!=22
            or custody_audit.get('transits_checked')!=160):
        raise ValueError('DUST timestamp-grid custody independent audit is incomplete or stale')
    if (custody.get('annotated_transits')!=custody_audit.get('transits_checked')
            or custody.get('transit_weighted_expected_1hz_slots')!=custody_audit.get('transit_weighted_expected_slots')
            or custody.get('missing_capture_slots_inside_annotated_transits')!=custody_audit.get('missing_capture_slots_reproduced')
            or custody.get('captured_but_unlabeled_slots_inside_annotated_transits')!=custody_audit.get('captured_but_unlabeled_slots_reproduced')):
        raise ValueError('DUST timestamp-grid custody totals disagree with the independent audit')
    payload['capture_cadence_custody']={
        'status':custody['status'],
        'independent_audit_status':custody_audit['status'],
        'sessions':custody['sessions'],
        'annotated_transits':custody['annotated_transits'],
        'transit_weighted_expected_1hz_slots':custody['transit_weighted_expected_1hz_slots'],
        'missing_capture_slots_inside_annotated_transits':custody['missing_capture_slots_inside_annotated_transits'],
        'captured_but_unlabeled_slots_inside_annotated_transits':custody['captured_but_unlabeled_slots_inside_annotated_transits'],
        'manual_label_coverage_of_transit_slots':custody['manual_label_coverage_of_transit_slots'],
        'bootstrap':custody['bootstrap'],
        'results':custody['results'],
        'interpretation':custody['interpretation'],
        'limitations':custody['limitations'],
    }
    interpolation_path=folder/'gap_interpolation_cross_validation.json'
    interpolation=json.loads(interpolation_path.read_text())
    interpolation_csv=folder/'gap_interpolation_cross_validation.csv'
    if (interpolation.get('status')!='completed_labeled_track_interpolation_cross_validation'
            or interpolation.get('archive_md5')!=audit.get('archive_md5')
            or interpolation.get('validation_design',{}).get('heldout_frames')!=48410
            or hashlib.sha256(interpolation_csv.read_bytes()).hexdigest()
                !=interpolation.get('validation_design',{}).get('csv_sha256')):
        raise ValueError('DUST interpolation validation does not match the source archive')
    payload['gap_interpolation_validation']={
        'status':interpolation['status'],
        'validation_design':interpolation['validation_design'],
        'by_gap_length':interpolation['by_gap_length'],
        'interpretation_limit':interpolation['interpretation_limit'],
    }
    return payload


def full_catalog_seed_sensitivity_payload(root=ROOT):
    """Serve the second-seed full-catalog experiment after audit/provenance checks."""
    root=Path(root)
    folder=root/'outputs/full-catalog-tasking-seed-sensitivity-2022-2026'
    result_path=folder/'seed_sensitivity.json'
    audit_path=folder/'independent_audit.json'
    primary=root/'outputs/full-catalog-tasking-monthly-2022-2026'
    primary_summary=primary/'summary.json'
    primary_audit=primary/'independent_audit.json'
    result=json.loads(result_path.read_text())
    audit=json.loads(audit_path.read_text())
    if (result.get('status')!='completed' or result.get('seed')!=90210
            or len(result.get('dates',[]))!=48 or len(result.get('response_rows',[]))!=384):
        raise ValueError('Full-catalog seed-sensitivity study is incomplete')
    if (audit.get('status')!='passed_source_design_and_statistical_reproduction'
            or audit.get('dates_checked')!=48
            or audit.get('paired_date_regime_cells_checked')!=192
            or audit.get('response_rows_checked')!=384
            or audit.get('scenario_cache_hashes_verified')!=192
            or audit.get('checks',{}).get('paired_seed_by_outage_interactions_recomputed') is not True):
        raise ValueError('Full-catalog seed-sensitivity independent audit has not passed')
    if (result.get('primary_summary_sha256')!=hashlib.sha256(primary_summary.read_bytes()).hexdigest()
            or result.get('primary_integrity_audit_sha256')!=hashlib.sha256(primary_audit.read_bytes()).hexdigest()):
        raise ValueError('Full-catalog seed-sensitivity primary-run provenance is stale')
    if len(audit.get('date_clustered_effects',[]))!=4 or len(audit.get('seed_by_outage_interaction',[]))!=4:
        raise ValueError('Full-catalog seed-sensitivity report is incomplete')
    return {'status':result['status'],'independent_audit_status':audit['status'],
        'seed':result['seed'],'dates':audit['dates_checked'],
        'paired_responses':audit['response_rows_checked'],
        'scenario_hashes_verified':audit['scenario_cache_hashes_verified'],
        'effects_by_regime':audit['date_clustered_effects'],
        'seed_by_outage_interaction':audit['seed_by_outage_interaction'],
        'interpretation':'Added random-seed robustness for a one-hour all-catalog simulated tasking study; not a natural sensor failure rate or continuous four-year operation.'}


def full_catalog_weekly_tasking_payload(root=ROOT):
    """Serve the weekly all-catalog tasking study only after its audit passes."""
    root=Path(root)
    folder=root/'outputs/full-catalog-tasking-weekly-2022-2026'
    summary=json.loads((folder/'summary.json').read_text())
    audit=json.loads((folder/'independent_audit.json').read_text())
    dates=summary.get('dates',[])
    rows=summary.get('rows',[])
    if (summary.get('status')!='completed' or summary.get('target_cohort')!='all'
            or len(dates)!=208 or dates[0]!='2022-10-15T00:00:00Z'
            or dates[-1]!='2026-10-03T00:00:00Z'
            or summary.get('completed_date_regime_groups')!=832 or len(rows)!=1664):
        raise ValueError('Weekly all-catalog tasking study is incomplete')
    if (audit.get('status')!='passed_structural_and_statistical'
            or audit.get('dates_checked')!=208
            or audit.get('paired_date_regime_cells_checked')!=832
            or audit.get('response_rows_checked')!=1664
            or audit.get('sensor_host_scenario_hashes_verified')!=832
            or audit.get('historical_host_state_availability',{}).get('cells_recomputed')!=832
            or audit.get('scenario_metadata_checksum_mismatches')!=[]):
        raise ValueError('Weekly all-catalog tasking independent audit has not passed')
    baseline=[row for row in rows if float(row['requested_outage_rate'])==0]
    outage=[row for row in rows if float(row['requested_outage_rate'])==0.2]
    if len(baseline)!=832 or len(outage)!=832:
        raise ValueError('Weekly tasking responses do not contain paired outage conditions')
    effects=summary.get('paired_effects',[])
    if {row.get('sensor_host_regime') for row in effects}!={'leo','meo','geo','heo'}:
        raise ValueError('Weekly tasking regime effects are incomplete')
    return {
        'status':summary['status'],
        'independent_audit_status':audit['status'],
        'dates':len(dates),
        'date_range':[dates[0],dates[-1]],
        'sensor_regime_groups':summary['completed_date_regime_groups'],
        'paired_responses':len(rows),
        'scenario_hashes_verified':audit['sensor_host_scenario_hashes_verified'],
        'mean_candidate_catalog_ids_per_episode':statistics.mean(
            row['catalog_objects_in_episode'] for row in baseline),
        'mean_sensor_actions_per_hour':statistics.mean(row['sensor_actions'] for row in baseline),
        'mean_zero_loss_custody':statistics.mean(row['custody_continuity'] for row in baseline),
        'mean_20pct_burst_loss_custody':statistics.mean(row['custody_continuity'] for row in outage),
        'effects_by_regime':effects,
        'interpretation':'Weekly one-hour all-catalog greedy tasking samples with injected burst loss; not continuous operations, the trained policy, or natural sensor reliability.'}


def full_catalog_empirical_block_tasking_payload(root=ROOT):
    """Serve the measured-block full-catalog extension only after audit passes."""
    root=Path(root)
    folder=root/'outputs/full-catalog-tasking-epop-empirical-block-weekly-2022-2026'
    summary=json.loads((folder/'summary.json').read_text())
    audit=json.loads((folder/'independent_audit.json').read_text())
    dates=summary.get('dates',[])
    profile=summary.get('dropout_profile') or {}
    telemetry=root/'data/attitude/cassiope_epop'
    mask_path=telemetry/'dropout_masks_1minute.npz'
    profile_path=telemetry/'dropout_profile_1minute.json'
    mask_audit=json.loads((telemetry/'dropout_masks_independent_audit.json').read_text())
    weekly=json.loads((root/'outputs/full-catalog-tasking-weekly-2022-2026/summary.json').read_text())
    if (summary.get('status')!='completed' or summary.get('target_cohort')!='all'
            or profile.get('mode')!='empirical_block' or len(dates)!=208
            or dates!=weekly.get('dates') or summary.get('completed_date_regime_groups')!=832
            or len(summary.get('rows',[]))!=1664):
        raise ValueError('Empirical-block weekly full-catalog tasking study is incomplete')
    if (audit.get('status')!='passed_structural_and_statistical'
            or audit.get('dates_checked')!=208
            or audit.get('paired_date_regime_cells_checked')!=832
            or audit.get('response_rows_checked')!=1664
            or audit.get('date_cluster_effects_independently_recomputed') is not True
            or audit.get('checks',{}).get('empirical_mask_archive_hash_and_source_audit') is not True):
        raise ValueError('Empirical-block full-catalog independent audit has not passed')
    mask_hash=hashlib.sha256(mask_path.read_bytes()).hexdigest()
    if (mask_audit.get('status')!='passed_independent_source_replay'
            or profile.get('mask_archive_sha256')!=mask_hash
            or mask_audit.get('mask_archive_sha256')!=mask_hash
            or hashlib.sha256(profile_path.read_bytes()).hexdigest()!=mask_audit.get('source_profile_sha256')
            or profile.get('source_profile_sha256')!=mask_audit.get('source_profile_sha256')
            or profile.get('rate') is None):
        raise ValueError('Empirical dropout source provenance is stale or unaudited')
    return {
        'status':summary['status'],
        'independent_audit_status':audit['status'],
        'dates':len(dates),
        'date_range':[dates[0],dates[-1]],
        'paired_regime_groups':summary['completed_date_regime_groups'],
        'paired_responses':len(summary['rows']),
        'dropout_rate':profile['rate'],
        'dropout_mode':profile['mode'],
        'mask_archive_sha256':mask_hash,
        'effects_by_regime':summary.get('paired_effects',[]),
        'limits':summary.get('limits',[]),
        'interpretation':'Paired one-hour full-catalog greedy tasking sensitivity using sampled 60-minute blocks from one spacecraft attitude-solution telemetry; it does not measure ground-sensor failure rates or continuous operations.'}


def cassiope_attitude_telemetry_payload(root=ROOT):
    """Expose independently audited real CASSIOPE attitude-source dropout telemetry."""
    root=Path(root)
    folder=root/'data/attitude/cassiope_epop'
    manifest=json.loads((folder/'manifest.json').read_text())
    audit=json.loads((folder/'independent_audit.json').read_text())
    profile=json.loads((folder/'dropout_profile_1minute.json').read_text())
    quality=json.loads((folder/'solution_quality_1minute.json').read_text())
    if audit.get('status')!='passed_structural_and_statistical' or audit.get('failures'):
        raise ValueError('CASSIOPE attitude telemetry has not passed its independent audit')
    if audit.get('downloaded_days',0)<1 or audit.get('totals',{}).get('samples',0)!=audit['downloaded_days']*86400:
        raise ValueError('CASSIOPE attitude telemetry coverage is incomplete or inconsistent')
    if manifest.get('days_processed',0)<audit.get('manifest_days_processed_at_audit',0):
        raise ValueError('CASSIOPE telemetry manifest regressed after independent audit')
    profile_dates={row.get('date') for row in profile.get('per_day',[])}
    if (profile.get('status')!='completed'
            or profile.get('source_audit_status')!=audit.get('status')
            or not profile_dates
            or len(profile_dates)!=profile.get('published_days_analyzed')
            or not profile_dates.issubset(set(audit.get('validated_dates',[])))
            or profile.get('one_minute_samples')!=len(profile_dates)*1440):
        raise ValueError('CASSIOPE dropout profile does not match independently audited attitude days')
    quality_counts=quality.get('quality_class_counts',{})
    if (quality.get('status')!='completed'
            or quality.get('source_audit_status')!=audit.get('status')
            or quality.get('source_profile_sha256')!=hashlib.sha256(
                (folder/'dropout_profile_1minute.json').read_bytes()).hexdigest()
            or quality.get('sampled_days')!=audit.get('downloaded_days')
            or quality.get('sampled_minutes')!=profile.get('one_minute_samples')
            or sum(quality_counts.values())!=quality.get('sampled_minutes')):
        raise ValueError('CASSIOPE attitude solution-quality summary is incomplete or stale')
    return {
        'status':manifest.get('status'),
        'independent_audit_status':audit['status'],
        'audit_coverage_status':audit.get('coverage_status'),
        'manifest_days_processed':manifest.get('days_processed'),
        'audited_days':audit['downloaded_days'],
        'date_range':[audit.get('first_day'),audit.get('last_day')],
        'requested_days':audit.get('requested_days'),
        'not_published_days':len(audit.get('not_published_days',[])),
        'samples':audit['totals']['samples'],
        'invalid_quaternion_seconds':audit['totals']['invalid_quaternion_seconds'],
        'valid_quaternion_seconds':audit['totals']['valid_quaternion_seconds'],
        'dropout_events':audit['totals']['dropout_events'],
        'longest_solution_dropout_seconds':audit['longest_solution_dropout_seconds'],
        'sensor_source_code_counts':audit['sensor_source_code_counts'],
        'sensor_source_code_labels':audit['sensor_source_code_labels'],
        'profile_days':profile['published_days_analyzed'],
        'profile_date_range':profile['source_date_range'],
        'one_minute_dropout_rate':profile['one_minute_attitude_solution_dropout_rate'],
        'one_minute_dropout_rate_ci95':profile['one_minute_dropout_rate_date_cluster_bootstrap_ci95'],
        'one_minute_persistence':profile['simulator_markov_persistence_parameter'],
        'dropout_run_length_minutes':profile['dropout_run_length_minutes'],
        'attitude_solution_quality':quality,
        'yearly':audit['yearly'],
        'limitations':audit['limitations'],
    }


def on_orbit_attitude_payload(root=ROOT):
    """Validate and summarize the per-frame DUST spacecraft attitude metadata."""
    root=Path(root)
    folder=root/'data/onboard_sensor/dust_star_tracker/dropout_study'
    dataset=json.loads((folder/'dataset_audit.json').read_text())
    audit=dataset.get('spacecraft_attitude_ephemeris',{})
    path=folder/'spacecraft_attitude_ephemeris.csv'
    if dataset.get('status')!='completed' or audit.get('status')!='completed':
        raise ValueError('DUST attitude metadata audit is incomplete')
    required={'norad_id','platform','session','frame_index','epoch_utc','h5_filename',
        'attitude_determination_mode','pitch_deg','roll_deg','yaw_deg','sc_altitude_km'}
    with path.open(newline='',encoding='utf-8') as stream:
        reader=csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('DUST attitude metadata CSV is missing required columns')
        rows=list(reader)
    expected=int(audit.get('matched_metadata_rows',-1))
    if (len(rows)!=expected or expected!=int(audit.get('matched_h5_files',-2))
            or not rows):
        raise ValueError('DUST attitude metadata row count does not match its source audit')
    sessions=defaultdict(list)
    modes=Counter()
    seen_frames=set()
    angles={key:[] for key in ('pitch_deg','roll_deg','yaw_deg','sc_altitude_km')}
    for row in rows:
        try:
            norad=int(row['norad_id'])
            frame=int(row['frame_index'])
            instant=dt.datetime.fromisoformat(row['epoch_utc'].replace('Z','+00:00'))
            numeric={key:float(row[key]) for key in angles}
        except (TypeError,ValueError,KeyError) as exc:
            raise ValueError('DUST attitude metadata contains a malformed row') from exc
        if (norad!=39265 or row['platform']!='CASSIOPE' or frame<1
                or not row['session'] or not row['h5_filename']
                or any(not math.isfinite(value) for value in numeric.values())):
            raise ValueError('DUST attitude metadata contains invalid platform or numeric values')
        key=(row['session'],frame)
        if key in seen_frames:
            raise ValueError('DUST attitude metadata contains duplicate session/frame rows')
        seen_frames.add(key)
        sessions[row['session']].append((instant,frame))
        modes[row['attitude_determination_mode']]+=1
        for name,value in numeric.items():
            angles[name].append(value)
    if len(sessions)!=int(dataset.get('observation_sessions',-1)):
        raise ValueError('DUST attitude metadata session count does not match its source audit')
    ranges={}
    for name,values in angles.items():
        values.sort()
        measured={'count':len(values),'min':values[0],
            'median':statistics.median(values),'max':values[-1]}
        source=audit.get('altitude_km' if name=='sc_altitude_km' else name,{})
        if any(abs(measured[field]-float(source[field]))>1e-9
                for field in ('min','median','max')) or measured['count']!=source.get('count'):
            raise ValueError(f'DUST attitude metadata {name} does not match its source audit')
        ranges[name]=measured
    if dict(modes)!=audit.get('attitude_mode_counts'):
        raise ValueError('DUST attitude determination mode counts do not match the source audit')
    by_session=[]
    for name,values in sorted(sessions.items()):
        by_session.append({'session':name,'frames':len(values),
            'utc_start':min(item[0] for item in values).isoformat().replace('+00:00','Z'),
            'utc_end':max(item[0] for item in values).isoformat().replace('+00:00','Z')})
    return {'status':'completed_valid','dataset':dataset.get('dataset'),
        'source_archive_md5':audit.get('metadata_source_md5'),
        'spacecraft':audit.get('spacecraft'),'norad_id':39265,
        'frame_count':len(rows),'session_count':len(sessions),
        'utc_start':audit.get('utc_start'),'utc_end':audit.get('utc_end'),
        'attitude_mode_counts':dict(modes),'ranges':ranges,
        'limitations':audit.get('limitations',[]),
        'csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'csv_bytes':path.stat().st_size,'sessions':by_session}


def awp_historical_payload(root=ROOT):
    """Return the completed, provenance-recorded four-year AWP comparison."""
    path=Path(root)/'outputs/awp-historical-sensitivity-2022-2026/summary.json'
    payload=json.loads(path.read_text())
    if payload.get('status')!='completed' or not payload.get('summary_by_regime_model_and_lead'):
        raise ValueError('Historical AWP comparison is not complete')
    return payload


def current_active_snapshot_payload(root=ROOT):
    """Return the current common-epoch payload snapshot after hash/audit checks."""
    folder=Path(root)/'data/current_active_catalog_snapshot_2026-10-10'
    manifest=json.loads((folder/'manifest.json').read_text())
    audit=json.loads((folder/'independent_audit.json').read_text())
    parquet=folder/manifest.get('state_output','')
    if manifest.get('status')!='completed' or not parquet.is_file():
        raise ValueError('Current active payload snapshot is incomplete')
    digest=hashlib.sha256(parquet.read_bytes()).hexdigest()
    if (digest!=manifest.get('parquet_sha256')
            or audit.get('status')!='passed_structural_and_sampled_state_reproduction'
            or audit.get('output_sha256')!=digest
            or audit.get('output_rows_checked')!=manifest.get('current_payload_states_written')
            or audit.get('source_snapshot_sha256')!=manifest.get('source_snapshot_sha256')
            or audit.get('satcat_sha256')!=manifest.get('satcat_sha256')):
        raise ValueError('Current active payload snapshot failed hash or independent-audit checks')
    counts=manifest.get('state_status_counts',{})
    if sum(counts.values())!=manifest.get('current_payload_candidates'):
        raise ValueError('Current active payload state totals do not reconcile')
    return {
        'status':'completed_valid',
        'query_epoch_utc':manifest['query_epoch_utc'],
        'cohort_definition':manifest['cohort_definition'],
        'current_payload_candidates':manifest['current_payload_candidates'],
        'state_status_counts':counts,
        'historical_archive_ids':audit['historical_archive_ids'],
        'current_payload_ids_with_archived_history':manifest['current_payload_ids_with_archived_history'],
        'current_payload_ids_without_archived_history':manifest['current_payload_ids_without_archived_history'],
        'successful_current_states_without_archived_history':audit['successful_current_states_without_historical_elements'],
        'independent_sample_rows':audit['independent_sample_rows'],
        'independent_sample_max_abs_position_difference_km':audit['independent_sample_max_abs_position_difference_km'],
        'independent_sample_max_abs_velocity_difference_km_s':audit['independent_sample_max_abs_velocity_difference_km_s'],
        'frame':manifest['frame'],'units':manifest['units'],
        'interpretation':manifest['interpretation'],'limitations':manifest['limitations'],
        'parquet_sha256':digest,
    }


def current_active_snapshot_csv(root=ROOT):
    """Serialize validated common-epoch active payload states for download."""
    current_active_snapshot_payload(root)
    folder=Path(root)/'data/current_active_catalog_snapshot_2026-10-10'
    manifest=json.loads((folder/'manifest.json').read_text())
    db=duckdb.connect()
    try:
        cursor=db.execute('SELECT * FROM read_parquet(?) ORDER BY norad_id',
                          [str(folder/manifest['state_output'])])
        stream=io.StringIO(newline='')
        writer=csv.writer(stream)
        writer.writerow([column[0] for column in cursor.description])
        writer.writerows(cursor.fetchall())
        return stream.getvalue()
    finally:
        db.close()


def awp_nbody_payload(root=ROOT):
    """Return the completed AWP/SPICE solar-lunar sensitivity comparison."""
    path=Path(root)/'outputs/awp-nbody-sensitivity-2026-10-01/summary.json'
    payload=json.loads(path.read_text())
    if payload.get('status')!='completed' or payload.get('comparison_rows')!=32:
        raise ValueError('Solar/lunar AWP comparison is incomplete')
    csv_path=path.parent/payload.get('csv','')
    if (not csv_path.is_file() or hashlib.sha256(csv_path.read_bytes()).hexdigest()
            !=payload.get('csv_sha256')):
        raise ValueError('Solar/lunar AWP comparison checksum does not match')
    return payload


def catalog_trajectory_progress(root=ROOT):
    """Summarize the resumable all-catalog fixed-cadence export."""
    output=Path(root)/'outputs/catalog-trajectory-all-4hour-2022-2026'
    manifest_path=output/'manifest.json'
    if not manifest_path.is_file():
        return {'status':'pending','parts_written':0,'projected_parts':0,
            'records_written':0,'projected_rows':0,'bytes_written':0}
    manifest=json.loads(manifest_path.read_text())
    parts=manifest.get('parts',[])
    projected_rows=int(manifest.get('projected_rows',0))
    start=dt.datetime.fromisoformat(manifest['start'])
    end=dt.datetime.fromisoformat(manifest['end_exclusive'])
    projected_parts=int((end-start).total_seconds()+86399)//86400
    return {'status':manifest.get('status','unknown'),
        'start':manifest.get('start'),'end_exclusive':manifest.get('end_exclusive'),
        'step_seconds':manifest.get('step_seconds'),
        'object_count':manifest.get('object_count'),
        'parts_written':len(parts),'projected_parts':projected_parts,
        'records_written':int(manifest.get('records_written',0)),
        'projected_rows':projected_rows,
        'progress_fraction':(len(parts)/projected_parts if manifest.get('status')!='completed'
                             else 1.0),
        'bytes_written':sum(int(part.get('size_bytes',0)) for part in parts),
        'successful':sum(int(part.get('successful',0)) for part in parts),
        'sgp4_errors':sum(int(part.get('sgp4_errors',0)) for part in parts),
        'stale_or_missing':sum(int(part.get('stale_or_missing',0)) for part in parts),
        'frame':manifest.get('frame'),'model':manifest.get('model')}


def catalog_ephemeris_csv_payload(start, end, norad_id=None, root=ROOT,
                                  max_rows=250000):
    """Download up to one UTC day from the completed, independently audited catalog export."""
    root=Path(root)
    output=root/'outputs/catalog-trajectory-all-4hour-2022-2026'
    manifest=json.loads((output/'manifest.json').read_text())
    validation=json.loads((output/'validation.json').read_text())
    if (manifest.get('status')!='completed'
            or validation.get('status')!='validated_complete'
            or validation.get('signature')!=manifest.get('signature')
            or validation.get('rows')!=manifest.get('projected_rows')
            or validation.get('parts_validated')!=manifest.get('parts_written')):
        raise ValueError('Catalog ephemeris is incomplete or has not passed validation')
    start_utc,end_utc=utc(start),utc(end)
    if start_utc>=end_utc:
        raise ValueError('start must be before end')
    if (end_utc-start_utc).total_seconds()>86400:
        raise ValueError('Catalog export downloads are limited to 24 hours')
    export_start,export_end=utc(manifest['start']),utc(manifest['end_exclusive'])
    if start_utc<export_start or end_utc>export_end:
        raise ValueError('Requested interval is outside the audited catalog export')
    if norad_id is not None:
        norad_id=int(norad_id)
        if norad_id<=0:
            raise ValueError('NORAD ID must be positive')
    overlapping=[str(output/part['file']) for part in manifest['parts']
        if utc(part['start_inclusive'])<end_utc
        and utc(part['end_exclusive'])>start_utc]
    if not overlapping:
        raise ValueError('No audited catalog partitions overlap this interval')
    columns=['norad_id','time_utc','element_epoch','element_age_hours',
        'orbit_regime','sgp4_error','x_teme_km','y_teme_km','z_teme_km',
        'vx_teme_km_s','vy_teme_km_s','vz_teme_km_s']
    db=duckdb.connect()
    try:
        db.execute("SET TimeZone='UTC'")
        where='time_utc>=? AND time_utc<?'
        params=[overlapping,start_utc.isoformat(),end_utc.isoformat()]
        if norad_id is not None:
            where+=' AND norad_id=?'
            params.append(norad_id)
        query=f"SELECT {','.join(columns)} FROM read_parquet(?) WHERE {where} ORDER BY time_utc,norad_id"
        rows=db.execute(query,params).fetchall()
    finally:
        db.close()
    if not rows:
        if norad_id is not None:
            raise KeyError(f'NORAD {norad_id} is not present in the audited cohort for this interval')
        raise ValueError('No catalog samples exist for this interval')
    if len(rows)>max_rows:
        raise ValueError(f'Request would produce {len(rows)} rows; maximum is {max_rows}')
    stream=io.StringIO(newline='')
    writer=csv.writer(stream)
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue()


def random_search_payload(root=ROOT):
    """Expose the completed random-search result only after its hash audit."""
    folder=Path(root)/'outputs/all-orbits-random-search-31'
    summary=json.loads((folder/'summary.json').read_text())
    audit=json.loads((folder/'random_search_integrity_audit.json').read_text())
    if summary.get('status')!='completed' or audit.get('status')!='validated_complete':
        raise ValueError('Random-search reference is incomplete or unaudited')
    summary['integrity_audit']=audit
    return summary


def monthly_dropout_progress(root=ROOT):
    output=monthly_dropout_output(root)
    summary_path=output/'dropout_summary.json'
    if summary_path.is_file():
        return json.loads(summary_path.read_text())
    design_path=output/'dropout_design.json'
    if not design_path.is_file():
        return {'status':'pending','completed_cells':0,'total_cells':0,'rows_written':0}
    design=json.loads(design_path.read_text()).get('design',{})
    dates=design.get('dates',[]);regimes=design.get('regimes',[])
    rates=design.get('rates',[]);modes=design.get('modes',[])
    replicates=int(design.get('replicates',0))
    model_seeds=design.get('model_seeds',[]) or [design.get('checkpoint')]
    expected_per_cell=replicates*len(rates)*len(modes)*len(model_seeds)
    counts={}
    response_path=output/'dropout_responses.csv'
    rows_written=0
    if response_path.is_file():
        with response_path.open(newline='') as stream:
            for row in csv.DictReader(stream):
                key=(row['date'],row['regime'])
                counts[key]=counts.get(key,0)+1
                rows_written+=1
    return {'status':'running','completed_cells':sum(
            count==expected_per_cell for count in counts.values()),
        'total_cells':len(dates)*len(regimes),'rows_written':rows_written,
        'expected_rows':len(dates)*len(regimes)*expected_per_cell,
        'date_count':len(dates),'regime_count':len(regimes),
        'replicates_per_model':replicates,'model_checkpoint_count':len(model_seeds)}


def state_vector_index_payload(root=ROOT):
    """Return the saved per-object index plus a live manifest freshness check."""
    root=Path(root)
    index=json.loads((root/'data/state_vector_object_coverage.json').read_text())
    manifest=json.loads((root/'data/historical_state_vectors_all/manifest.json').read_text())
    index['current_export_status']=manifest.get('status')
    index['current_export_records_written']=manifest.get('records_written')
    index['current_export_years']=manifest.get('years',{})
    index['snapshot_matches_current_export']=(
        index.get('export_signature')==manifest.get('signature')
        and index.get('parquet_records_scanned')==manifest.get('records_written'))
    return index


def object_coverage_payload(norad_id, root=ROOT):
    """Return archived element and materialized-state coverage for one object."""
    root=Path(root)
    coverage_path=root/'data/state_vector_object_coverage.csv'
    with coverage_path.open(newline='') as stream:
        row=next((item for item in csv.DictReader(stream)
                  if int(item['norad_id'])==int(norad_id)),None)
    if row is None:
        raise KeyError(int(norad_id))
    for key in ('norad_id','historical_element_rows','state_vector_rows',
                'successful_states','failed_states'):
        row[key]=int(row[key])
    row['materialized_fraction']=float(row['materialized_fraction'])
    index=state_vector_index_payload(root)
    row['coverage_index_matches_current_export']=index['snapshot_matches_current_export']
    row['current_export_status']=index['current_export_status']
    row['model']=index.get('model')
    row['frame']=index.get('frame')
    year_statuses=[]
    for key in sorted(row):
        if not key.startswith('historical_element_rows_'):
            continue
        year=key.rsplit('_',1)[1]
        historical_rows=int(row[key])
        state_rows=int(row.get(f'state_vector_rows_{year}',0))
        if not index['snapshot_matches_current_export']:
            status='index_stale'
        elif historical_rows==0:
            status='no_archived_records'
        elif historical_rows==state_rows:
            status='fully_materialized'
        else:
            year_manifest=index['current_export_years'].get(year,{})
            if year_manifest.get('complete'):
                status='missing_state_rows_in_completed_year'
            elif year not in index['current_export_years']:
                status='export_not_started'
            else:
                status='export_in_progress'
        year_statuses.append({'year':int(year),'historical_element_rows':historical_rows,
            'state_vector_rows':state_rows,'status':status})
    statuses={item['status'] for item in year_statuses if item['historical_element_rows']>0}
    if not index['snapshot_matches_current_export']:
        row['state_coverage_status']='stale_index'
    elif 'missing_state_rows_in_completed_year' in statuses:
        row['state_coverage_status']='missing_state_rows_in_completed_years'
    elif 'export_not_started' in statuses or 'export_in_progress' in statuses:
        row['state_coverage_status']='export_in_progress'
    elif 'no_archived_records' in statuses and not statuses.intersection({'fully_materialized'}):
        row['state_coverage_status']='no_states_materialized'
    elif 'fully_materialized' in statuses:
        row['state_coverage_status']='fully_materialized'
    else:
        row['state_coverage_status']='no_archived_records'
    row['yearly_coverage']=year_statuses
    return row


def trajectory_csv_payload(norad_id, start, end, step_seconds=60,
                           max_age_hours=72, root=ROOT, max_samples=100000):
    """Build a bounded, reproducible CSV from the archived element history."""
    norad_id=int(norad_id)
    start_utc,end_utc=utc(start),utc(end)
    step_seconds=int(step_seconds)
    max_age_hours=float(max_age_hours)
    if start_utc>=end_utc:
        raise ValueError('start must be before end')
    if step_seconds<=0:
        raise ValueError('step_seconds must be positive')
    if max_age_hours<0:
        raise ValueError('max_age_hours must be nonnegative')
    samples=(int((end_utc-start_utc).total_seconds())+step_seconds-1)//step_seconds
    if samples>max_samples:
        raise ValueError(f'Request would produce {samples} samples; maximum is {max_samples}')
    history=History(root,cohort='all',window=(start_utc,end_utc),
                    max_age_hours=max_age_hours)
    try:
        records=history.records(start_utc,end_utc,max_age_hours,ids=[norad_id])
    finally:
        history.db.close()
    if not records:
        raise KeyError(f'No archived orbital elements for NORAD {norad_id} near this interval')
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(trajectory_rows(records,norad_id,start_utc,end_utc,
                                     step_seconds,max_age_hours))
    return stream.getvalue()


def catalog_trajectory_refresh_info(root=ROOT):
    """Return verified metadata for the separately pinned late-source overlay."""
    root=Path(root)
    folder=root/'outputs/catalog-trajectory-source-refresh-2026-10-08-10'
    manifest_path=folder/'manifest.json'
    audit_path=folder/'independent_audit.json'
    if not manifest_path.is_file() or not audit_path.is_file():
        raise FileNotFoundError('Latest-source trajectory refresh has not been audited')
    manifest=json.loads(manifest_path.read_text())
    audit=json.loads(audit_path.read_text())
    part=folder/manifest.get('part',{}).get('file','')
    source_manifest_path=root/'data/raw/snapshots/2026-10-11/source_manifest.json'
    source_manifest=json.loads(source_manifest_path.read_text())
    if (manifest.get('status')!='completed'
            or audit.get('status')!='passed_source_and_baseline_reconciliation'
            or not all(audit.get('checks',{}).values())
            or manifest.get('source_revision')!=source_manifest.get('revision')
            or manifest.get('source_file_sha256')!=source_manifest.get('sha256')
            or audit.get('source_sha256')!=source_manifest.get('sha256')
            or not part.is_file()
            or hashlib.sha256(part.read_bytes()).hexdigest()!=manifest.get('part',{}).get('sha256')
            or audit.get('trajectory_rows_checked')!=manifest.get('rows')):
        raise ValueError('Latest-source trajectory refresh failed its source/output audit checks')
    return {
        'status':audit['status'], 'source_revision':manifest['source_revision'],
        'source_last_modified_utc':source_manifest['dataset_last_modified_utc'],
        'start_inclusive':manifest['start_inclusive'], 'end_exclusive':manifest['end_exclusive'],
        'step_seconds':manifest['step_seconds'], 'objects':manifest['objects'], 'rows':manifest['rows'],
        'status_counts':manifest['status_counts'],
        'independent_state_replays':audit['independent_state_replays'],
        'comparison_to_pinned_archive':audit['comparison_to_pinned_archive'],
    }


def catalog_trajectory_refresh_csv_payload(norad_id, start, end, root=ROOT):
    """Export one object's rows from the audited 4-hour late-source overlay."""
    root=Path(root)
    info=catalog_trajectory_refresh_info(root)
    norad_id=int(norad_id)
    start_utc,end_utc=utc(start),utc(end)
    lower,upper=utc(info['start_inclusive']),utc(info['end_exclusive'])
    if start_utc>=end_utc or start_utc<lower or end_utc>upper:
        raise ValueError(f'Refresh interval must be within {lower.isoformat()} and {upper.isoformat()}')
    step=info['step_seconds']
    if int((start_utc-lower).total_seconds())%step or int((end_utc-lower).total_seconds())%step:
        raise ValueError(f'Refresh interval must align to the {step}-second grid')
    part=root/'outputs/catalog-trajectory-source-refresh-2026-10-08-10/part-00000.parquet'
    con=duckdb.connect()
    try:
        rows=con.execute("""select norad_id,time_utc,element_epoch,element_age_hours,orbit_regime,sgp4_error,
            x_teme_km,y_teme_km,z_teme_km,vx_teme_km_s,vy_teme_km_s,vz_teme_km_s
            from read_parquet(?) where norad_id=? and cast(time_utc as timestamptz)>=? and
            cast(time_utc as timestamptz)<? order by time_utc""",
            [str(part),norad_id,start_utc,end_utc]).fetchall()
    finally:
        con.close()
    expected=int((end_utc-start_utc).total_seconds())//step
    if len(rows)!=expected:
        raise KeyError(f'No complete refreshed trajectory for NORAD {norad_id}; found {len(rows)} of {expected} samples')
    names=['norad_id','time_utc','element_epoch','element_age_hours','orbit_regime','sgp4_error',
           'x_teme_km','y_teme_km','z_teme_km','vx_teme_km_s','vy_teme_km_s','vz_teme_km_s']
    stream=io.StringIO(newline='')
    writer=csv.writer(stream)
    writer.writerow(names)
    writer.writerows(rows)
    return stream.getvalue(),info


def ztf_opportunity_payload(root=ROOT):
    """Read the persisted ZTF image-to-orbit review and check its shape."""
    path=Path(root)/'outputs/ztf-palomer-opportunity-poc/audit.json'
    if not path.is_file():
        raise FileNotFoundError('ZTF Palomar opportunity audit is not available')
    payload=json.loads(path.read_text())
    candidates=payload.get('candidates')
    if not isinstance(candidates,list) or len(candidates)!=5:
        raise ValueError('ZTF Palomar opportunity audit must contain five candidate tracks')
    if len({row.get('expid') for row in candidates})!=4:
        raise ValueError('ZTF Palomar opportunity audit must cover four sampled exposures')
    if any(not row.get('image_sha256') or not row.get('image_url') for row in candidates):
        raise ValueError('ZTF candidate image provenance is incomplete')
    return payload


def ztf_fullnight_payload(root=ROOT):
    """Load the full-night ZTF crossing audit and verify its source linkage."""
    root=Path(root)
    path=root/'outputs/ztf-palomer-fullnight-2024-07-10/midpoint_crossing_audit.json'
    if not path.is_file():
        raise FileNotFoundError('ZTF full-night crossing audit is not available')
    payload=json.loads(path.read_text())
    relative=Path(payload.get('source_metadata_file',''))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('ZTF full-night metadata path must be workspace-relative')
    metadata=root/relative
    if not metadata.is_file():
        raise FileNotFoundError('ZTF full-night metadata snapshot is not available')
    if hashlib.sha256(metadata.read_bytes()).hexdigest()!=payload.get('metadata_sha256'):
        raise ValueError('ZTF full-night metadata checksum does not match crossing audit')
    with metadata.open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    exposure_ids={row.get('expid') for row in rows}
    candidates=payload.get('candidates')
    summary=payload.get('exposure_summary')
    totals=payload.get('totals',{})
    if not isinstance(candidates,list) or not isinstance(summary,list):
        raise ValueError('ZTF full-night crossing rows are missing')
    if (len(rows)!=payload.get('metadata_rows')
            or len(exposure_ids)!=payload.get('exposures')
            or len(summary)!=len(exposure_ids)
            or len(candidates)!=totals.get('candidate_footprint_tracks')
            or sum(bool(item.get('sunlit_midpoint')) for item in candidates)!=totals.get('sunlit_candidate_footprint_tracks')
            or sum(int(item.get('footprint_tracks',-1)) for item in summary)!=len(candidates)
            or sum(int(item.get('footprint_tracks',0))>0 for item in summary)!=totals.get('exposures_with_midpoint_tracks')):
        raise ValueError('ZTF full-night crossing counts do not reconcile with source metadata')
    if payload.get('catalog_ids_considered',0)<=0:
        raise ValueError('ZTF full-night catalog coverage is missing')
    return payload


def ztf_exposure_path_payload(root=ROOT):
    """Validate the dense, full-exposure propagation of midpoint candidates."""
    root=Path(root)
    folder=root/'outputs/ztf-palomer-fullnight-2024-07-10'
    midpoint_path=folder/'midpoint_crossing_audit.json'
    path=folder/'exposure_path_audit.json'
    if not path.is_file() or not midpoint_path.is_file():
        raise FileNotFoundError('ZTF full-night exposure-path audit is not available')
    midpoint=json.loads(midpoint_path.read_text())
    payload=json.loads(path.read_text())
    if payload.get('midpoint_audit_sha256')!=hashlib.sha256(midpoint_path.read_bytes()).hexdigest():
        raise ValueError('ZTF exposure-path audit does not match its midpoint candidate source')
    if payload.get('metadata_sha256')!=midpoint.get('metadata_sha256'):
        raise ValueError('ZTF exposure-path metadata checksum differs from midpoint audit')
    midpoint_keys={(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id']))
                   for row in midpoint.get('candidates',[])}
    candidates=payload.get('candidates')
    totals=payload.get('totals',{})
    if not isinstance(candidates,list):
        raise ValueError('ZTF exposure-path candidate rows are missing')
    path_keys={(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id']))
               for row in candidates}
    if (payload.get('status')!='completed_full_exposure_paths_for_midpoint_candidates'
            or path_keys!=midpoint_keys
            or len(path_keys)!=totals.get('midpoint_candidates_replayed')
            or totals.get('candidates_with_path_inside')!=len(path_keys)
            or totals.get('candidates_with_observable_path_inside')!=len(path_keys)
            or totals.get('candidates_with_sunlit_observable_path_inside')
                !=sum(bool(row.get('any_path_sunlit_observable_inside')) for row in candidates)
            or totals.get('exposures_with_any_sunlit_observable_path_inside')
                !=len({row['expid'] for row in candidates if row.get('any_path_sunlit_observable_inside')})
            or totals.get('maximum_midpoint_direction_error_arcsec',float('inf'))>=0.1):
        raise ValueError('ZTF exposure-path candidates or totals do not reconcile')
    return payload


def ztf_edge_crossing_payload(root=ROOT):
    """Validate full-exposure edge crossings outside midpoint candidate set."""
    root=Path(root)
    folder=root/'outputs/ztf-palomer-fullnight-2024-07-10'
    midpoint_path=folder/'midpoint_crossing_audit.json'
    path=folder/'edge_crossing_audit.json'
    if not path.is_file() or not midpoint_path.is_file():
        raise FileNotFoundError('ZTF full-night edge-crossing audit is not available')
    midpoint=json.loads(midpoint_path.read_text())
    payload=json.loads(path.read_text())
    if payload.get('midpoint_audit_sha256')!=hashlib.sha256(midpoint_path.read_bytes()).hexdigest():
        raise ValueError('ZTF edge-crossing audit does not match midpoint audit')
    if payload.get('metadata_sha256')!=midpoint.get('metadata_sha256'):
        raise ValueError('ZTF edge-crossing metadata checksum differs from midpoint audit')
    midpoint_keys={(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id']))
                   for row in midpoint.get('candidates',[])}
    candidates=payload.get('candidates')
    totals=payload.get('totals',{})
    if not isinstance(candidates,list):
        raise ValueError('ZTF edge-crossing candidate rows are missing')
    keys={(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id'])) for row in candidates}
    hits=[row for row in candidates if row.get('crosses_quadrant_during_exposure')]
    observable=[row for row in candidates if row.get('observable_crossing_above_10deg')]
    sunlit=[row for row in candidates if row.get('sunlit_observable_crossing')]
    if (payload.get('status')!='completed_screened_edge_crossing_replay'
            or payload.get('scope_complete') is not True
            or len(keys)!=len(candidates)
            or keys & midpoint_keys
            or len(candidates)!=totals.get('screened_candidates')
            or len(hits)!=totals.get('exact_path_edge_crossings')
            or len(observable)!=totals.get('observable_edge_crossings_above_10deg')
            or len(sunlit)!=totals.get('sunlit_observable_edge_crossings')
            or len({row['expid'] for row in hits})!=totals.get('exposures_with_edge_crossing')
            or len({row['expid'] for row in sunlit})!=totals.get('exposures_with_sunlit_observable_edge_crossing')):
        raise ValueError('ZTF edge-crossing rows and totals do not reconcile')
    return payload


def ztf_image_sample_payload(root=ROOT):
    """Validate checksums, source ledgers, and candidate counts for the image sample."""
    root=Path(root)
    folder=root/'outputs/ztf-palomer-fullnight-2024-07-10'
    path=folder/'image_sample_audit.json'
    if not path.is_file():
        raise FileNotFoundError('ZTF full-night image sample audit is not available')
    payload=json.loads(path.read_text())
    sources={name:folder/f'{name}.json' for name in
             ('midpoint_crossing_audit','exposure_path_audit','edge_crossing_audit')}
    for name,source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f'ZTF image sample source audit is missing: {name}')
    expected_hashes={
        'midpoint_audit_sha256':hashlib.sha256(sources['midpoint_crossing_audit'].read_bytes()).hexdigest(),
        'exposure_path_audit_sha256':hashlib.sha256(sources['exposure_path_audit'].read_bytes()).hexdigest(),
        'edge_crossing_audit_sha256':hashlib.sha256(sources['edge_crossing_audit'].read_bytes()).hexdigest(),
    }
    if payload.get('metadata_sha256')!=json.loads(sources['midpoint_crossing_audit'].read_text()).get('metadata_sha256'):
        raise ValueError('ZTF image sample metadata checksum differs from its source')
    if any(payload.get(key)!=value for key,value in expected_hashes.items()):
        raise ValueError('ZTF image sample does not match its source opportunity ledgers')
    midpoint=json.loads(sources['midpoint_crossing_audit'].read_text())
    paths=json.loads(sources['exposure_path_audit'].read_text())
    edges=json.loads(sources['edge_crossing_audit'].read_text())
    path_by_key={(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id'])):row
                 for row in paths.get('candidates',[])}
    eligible={(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id']))
              for row in midpoint.get('candidates',[])
              if path_by_key.get((row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id'])),{}).get('any_path_sunlit_observable_inside')}
    eligible.update((row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id']))
                    for row in edges.get('candidates',[]) if row.get('sunlit_observable_crossing'))
    images=payload.get('image_results')
    if not isinstance(images,list) or payload.get('status')!='completed_profile_audit':
        raise ValueError('ZTF image sample is incomplete')
    count=0
    keys=set()
    for image in images:
        image_path=Path(image.get('image_path',''))
        if image_path.is_absolute() or '..' in image_path.parts:
            raise ValueError('ZTF image sample path must be workspace-relative')
        image_path=root/image_path
        if (not image_path.is_file() or image_path.stat().st_size!=image.get('image_bytes')
                or hashlib.sha256(image_path.read_bytes()).hexdigest()!=image.get('image_sha256')):
            raise ValueError(f'ZTF image sample checksum or size mismatch: {image.get("image_path")}')
        results=image.get('candidate_results')
        if not isinstance(results,list) or len(results)!=image.get('candidate_count'):
            raise ValueError('ZTF image sample candidate count does not reconcile')
        for row in results:
            key=(str(row['expid']),int(row['ccdid']),int(row['qid']),int(row['norad_id']))
            if key in keys:
                raise ValueError('ZTF image sample contains duplicate candidate opportunity keys')
            if key not in eligible:
                raise ValueError('ZTF image sample candidate is absent from the predicted opportunity ledgers')
            keys.add(key);count+=1
    if count!=payload.get('opportunity_count') or len(images)!=payload.get('images_completed'):
        raise ValueError('ZTF image sample totals do not reconcile')
    return payload


def ztf_injected_streak_payload(root=ROOT):
    """Validate leave-one-exposure-out synthetic streak sensitivity results."""
    root=Path(root)
    folder=root/'outputs/ztf-palomer-fullnight-2024-07-10'
    sample_path=folder/'image_sample_audit.json'
    path=folder/'injected_streak_detection_benchmark.json'
    if not path.is_file() or not sample_path.is_file():
        raise FileNotFoundError('ZTF injected-streak benchmark is not available')
    sample=json.loads(sample_path.read_text())
    payload=json.loads(path.read_text())
    if payload.get('image_sample_sha256')!=hashlib.sha256(sample_path.read_bytes()).hexdigest():
        raise ValueError('ZTF injected-streak benchmark does not match its image sample')
    heldout=payload.get('heldout_image_results')
    sample_ids={str(row['expid']) for row in sample.get('image_results',[])}
    heldout_ids={str(row['expid']) for row in heldout or []}
    if (payload.get('status')!='completed_image_level_injection_benchmark'
            or len(heldout or [])!=sample.get('images_completed')
            or heldout_ids!=sample_ids):
        raise ValueError('ZTF injected-streak heldout image inventory is incomplete')
    total_trials=0
    for image in heldout:
        train={str(value) for value in image.get('training_exposure_ids',[])}
        if str(image.get('expid')) in train or train|{str(image.get('expid'))}!=sample_ids:
            raise ValueError('ZTF injected-streak benchmark contains exposure leakage')
        if image.get('image_sha256')!=next((row['image_sha256'] for row in sample['image_results']
                                                if str(row['expid'])==str(image['expid'])),None):
            raise ValueError('ZTF injected-streak benchmark image checksum differs from sample')
        for candidate in image.get('candidate_results',[]):
            total_trials+=len(candidate.get('injection_trials',[]))
    if total_trials==0:
        raise ValueError('ZTF injected-streak benchmark has no positive-control trials')
    offsets=[row['maglimit_offset'] for row in payload.get('summary_by_magnitude',[])]
    if not offsets or len(offsets)!=len(set(offsets)):
        raise ValueError('ZTF injected-streak magnitude response summary is missing')
    return payload


def ztf_real_image_association_payload(root=ROOT):
    """Validate descriptive real-frame path-versus-parallel-lane measurements."""
    root=Path(root)
    folder=root/'outputs/ztf-palomer-fullnight-2024-07-10'
    sample_path=folder/'image_sample_audit.json'
    path=folder/'real_image_path_association_audit.json'
    if not path.is_file() or not sample_path.is_file():
        raise FileNotFoundError('ZTF real-image path association audit is not available')
    payload=json.loads(path.read_text())
    sample=json.loads(sample_path.read_text())
    if (payload.get('status')!='completed_descriptive_real_image_path_association_audit'
            or payload.get('image_sample_sha256')!=hashlib.sha256(sample_path.read_bytes()).hexdigest()
            or len(payload.get('opportunity_results',[]))!=sample.get('opportunity_count')
            or payload.get('selection_and_measurement',{}).get('profiled_opportunities')+
               payload.get('selection_and_measurement',{}).get('profile_unavailable')!=sample.get('opportunity_count')):
        raise ValueError('ZTF real-image path association results do not match the source sample')
    return payload


def serve(output,port):
    output=output.resolve();web=ROOT/'web'
    if output.name=='all-orbits-study':dropout_name='all-orbits-dropout-study'
    elif output.name in {'all-orbits-all-catalog-targets','all-orbits-paper-exact'}:dropout_name='all-orbits-all-catalog-targets-dropout'
    else:dropout_name='dropout-study'
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed=urlsplit(self.path);path=parsed.path
            if path=='/api/current-active-snapshot':
                try:
                    body=json.dumps(current_active_snapshot_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Current active payload snapshot is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Current active payload snapshot failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/current-active-snapshot.csv':
                try:
                    body=current_active_snapshot_csv().encode()
                except FileNotFoundError:
                    self.send_error(404,'Current active payload snapshot is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Current active payload snapshot failed validation');return
                self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Content-Disposition','attachment; filename="current-active-payload-states.csv"');self.send_header('ETag',f'"{current_active_snapshot_payload()["parquet_sha256"]}"');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/catalog-trajectory':
                try:
                    body=json.dumps(catalog_trajectory_progress()).encode()
                except (FileNotFoundError,json.JSONDecodeError):
                    self.send_error(503,'Catalog trajectory export manifest is unavailable or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/random-search':
                try:
                    body=json.dumps(random_search_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Random-search reference is not available');return
                except (ValueError,json.JSONDecodeError):
                    self.send_error(503,'Random-search reference is incomplete or unaudited');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/awp-nbody':
                try:
                    body=json.dumps(awp_nbody_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Solar/lunar AWP comparison is not available');return
                except (ValueError,json.JSONDecodeError):
                    self.send_error(503,'Solar/lunar AWP comparison is incomplete');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/object-coverage':
                try:
                    norad_id=int(parse_qs(parsed.query).get('norad',[''])[0])
                    body=json.dumps(object_coverage_payload(norad_id)).encode()
                except (ValueError,TypeError):
                    self.send_error(400,'NORAD ID must be an integer');return
                except FileNotFoundError:
                    self.send_error(404,'State-vector coverage index is not available');return
                except KeyError:
                    self.send_error(404,'NORAD ID is not in the indexed history');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/trajectory.csv':
                query=parse_qs(parsed.query)
                try:
                    norad_id=int(query.get('norad',[''])[0])
                    start=query.get('start',[''])[0]
                    end=query.get('end',[''])[0]
                    step=int(query.get('step_seconds',['60'])[0])
                    age=float(query.get('max_age_hours',['72'])[0])
                    body=trajectory_csv_payload(norad_id,start,end,step,age).encode()
                except (ValueError,TypeError) as exc:
                    self.send_error(400,str(exc));return
                except FileNotFoundError as exc:
                    self.send_error(404,str(exc));return
                except KeyError as exc:
                    self.send_error(404,str(exc));return
                self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Content-Disposition',f'attachment; filename="norad-{norad_id}-trajectory.csv"');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/catalog-trajectory-refresh':
                try:
                    body=json.dumps(catalog_trajectory_refresh_info()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Latest-source trajectory refresh is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Latest-source trajectory refresh failed audit validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/catalog-trajectory-refresh.csv':
                query=parse_qs(parsed.query)
                try:
                    norad_id=int(query.get('norad',[''])[0])
                    start=query.get('start',[''])[0]
                    end=query.get('end',[''])[0]
                    body,info=catalog_trajectory_refresh_csv_payload(norad_id,start,end)
                    body=body.encode()
                except (ValueError,TypeError) as exc:
                    self.send_error(400,str(exc));return
                except FileNotFoundError as exc:
                    self.send_error(404,str(exc));return
                except KeyError as exc:
                    self.send_error(404,str(exc));return
                self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Content-Disposition',f'attachment; filename="norad-{norad_id}-trajectory-latest-source.csv"');self.send_header('X-GoDSAT-Source-Revision',info['source_revision']);self.send_header('X-GoDSAT-Audit-Status',info['status']);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/catalog-trajectory.csv':
                query=parse_qs(parsed.query)
                try:
                    start=query.get('start',[''])[0]
                    end=query.get('end',[''])[0]
                    raw_id=query.get('norad',[''])[0]
                    body=catalog_ephemeris_csv_payload(start,end,
                        norad_id=raw_id or None).encode()
                except (ValueError,TypeError) as exc:
                    self.send_error(400,str(exc));return
                except FileNotFoundError as exc:
                    self.send_error(503,'The audited catalog ephemeris is not available');return
                except KeyError as exc:
                    self.send_error(404,str(exc));return
                filename='all-catalog' if not raw_id else f'norad-{int(raw_id)}'
                self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Content-Disposition',f'attachment; filename="{filename}-ephemeris.csv"');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/state-vector-index':
                try:
                    body=json.dumps(state_vector_index_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'State-vector coverage index is not available');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            paths={'/':(web/'index.html','text/html'),'/api/summary':(output/'summary.json','application/json'),
                '/api/config':(output/'config.json','application/json'),
                '/api/coverage':(ROOT/'data/coverage.json','application/json'),
                '/api/regime-coverage':(ROOT/'data/all_catalog_orbit_regime_coverage.json','application/json'),
                '/api/robustness':(ROOT/'outputs/multi-date-robustness/manifest.json','application/json'),
                '/api/ground-sensors':(ROOT/'data/ground_sensor/ilrs_lageos1_npt/sensor_summary.json','application/json'),
                '/api/durham-ground-gap-audit':(ROOT/'data/ground_sensor/durham_widefield_ssa/dataset_audit.json','application/json'),
                '/api/range-validation':(ROOT/'data/ground_sensor/ilrs_lageos1_npt/range_validation_summary.json','application/json'),
                '/api/dense-sgp4-cpf-validation':(ROOT/'outputs/dense-sgp4-cpf-validation-2022-2026/independent_audit.json','application/json'),
                '/api/awp-ilrs-cpf':(ROOT/'outputs/awp-ilrs-cpf-iers-earth-constants-2022-2026/summary.json','application/json'),
                '/api/ilrs-return-quality':(ROOT/'data/ground_sensor/ilrs_lageos1_npt/return_quality_analysis.json','application/json')}
            if path=='/api/ztf-palomer-opportunities':
                try:
                    body=json.dumps(ztf_opportunity_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF Palomar opportunity audit is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF Palomar opportunity audit failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/ztf-palomer-fullnight':
                try:
                    body=json.dumps(ztf_fullnight_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF full-night crossing audit is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF full-night crossing audit failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/ztf-palomer-fullnight-paths':
                try:
                    body=json.dumps(ztf_exposure_path_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF full-night exposure-path audit is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF full-night exposure-path audit failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/ztf-palomer-fullnight-edges':
                try:
                    body=json.dumps(ztf_edge_crossing_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF full-night edge-crossing audit is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF full-night edge-crossing audit failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/ztf-palomer-fullnight-images':
                try:
                    body=json.dumps(ztf_image_sample_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF full-night image sample is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF full-night image sample failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/ztf-palomer-injection-benchmark':
                try:
                    body=json.dumps(ztf_injected_streak_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF injected-streak benchmark is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF injected-streak benchmark failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/ztf-palomer-real-image-associations':
                try:
                    body=json.dumps(ztf_real_image_association_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'ZTF real-image association audit is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'ZTF real-image association audit failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path.startswith('/ztf-fullnight-profile/'):
                name=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'track_\d+_\d+_c\d+_q\d+\.png',name):
                    self.send_error(404);return
                paths[path]=(ROOT/'outputs/ztf-palomer-fullnight-2024-07-10/image_profiles'/name,'image/png')
            ztf_audit_path=ROOT/'outputs/ztf-palomer-opportunity-poc/audit.json'
            if ztf_audit_path.is_file():
                try:
                    ztf_audit=json.loads(ztf_audit_path.read_text())
                    for candidate in ztf_audit.get('candidates',[]):
                        name=f"track_{int(candidate['norad_id'])}_{candidate['expid']}.png"
                        paths[f'/ztf-opportunity-images/{name}']=(ROOT/'outputs/ztf-palomer-opportunity-poc'/name,'image/png')
                except (ValueError,KeyError,TypeError):
                    pass
            if path=='/api/on-orbit-dropout':
                try:
                    body=json.dumps(on_orbit_dropout_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'On-orbit dropout replay is not available');return
                except (ValueError,json.JSONDecodeError):
                    self.send_error(503,'On-orbit dropout replay is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/full-catalog-tasking-seed-sensitivity':
                try:
                    body=json.dumps(full_catalog_seed_sensitivity_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Full-catalog seed-sensitivity results are not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Full-catalog seed-sensitivity audit is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/full-catalog-tasking-daily-progress':
                try:
                    body=json.dumps(full_catalog_daily_tasking_progress_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Daily full-catalog tasking progress is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Daily full-catalog tasking progress failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/full-catalog-tasking-weekly':
                try:
                    body=json.dumps(full_catalog_weekly_tasking_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Weekly full-catalog tasking results are not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Weekly full-catalog tasking audit is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/full-catalog-tasking-empirical-block-weekly':
                try:
                    body=json.dumps(full_catalog_empirical_block_tasking_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Empirical-block weekly tasking results are not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Empirical-block weekly tasking audit is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/cassiope-attitude-telemetry':
                try:
                    body=json.dumps(cassiope_attitude_telemetry_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'CASSIOPE attitude telemetry audit is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'CASSIOPE attitude telemetry audit is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/on-orbit-attitude':
                try:
                    body=json.dumps(on_orbit_attitude_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'On-orbit attitude metadata is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'On-orbit attitude metadata failed validation');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/on-orbit-attitude.csv':
                try:
                    attitude=on_orbit_attitude_payload()
                    folder=ROOT/'data/onboard_sensor/dust_star_tracker/dropout_study'
                    body=(folder/'spacecraft_attitude_ephemeris.csv').read_bytes()
                except FileNotFoundError:
                    self.send_error(404,'On-orbit attitude metadata is not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'On-orbit attitude metadata failed validation');return
                self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Content-Disposition','attachment; filename="dust-cassiope-attitude-ephemeris.csv"');self.send_header('ETag',f'"{attitude["csv_sha256"]}"');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/detection-sensitivity':
                try:
                    body=json.dumps(detection_sensitivity_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Detection-probability sensitivity results are not available');return
                except (ValueError,json.JSONDecodeError,KeyError,TypeError):
                    self.send_error(503,'Detection-probability sensitivity audit is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/dropout':
                study=parse_qs(parsed.query).get('study',['annual'])[0].lower()
                if study=='quarterly':
                    dropout_output=quarterly_dropout_output()
                elif study=='monthly':
                    dropout_output=monthly_dropout_output()
                    summary_path=dropout_output/'dropout_summary.json'
                    body=json.dumps(monthly_dropout_progress()).encode()
                    if not summary_path.is_file():
                        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
                elif study=='annual':
                    dropout_output=ROOT/'outputs'/dropout_name
                else:
                    self.send_error(400,'Unknown dropout study');return
                paths[path]=(dropout_output/'dropout_summary.json','application/json')
            if path=='/api/awp':
                regime=parse_qs(parsed.query).get('regime',['leo'])[0].lower()
                if regime not in {'leo','meo','geo','heo'}: self.send_error(400,'Unknown orbit regime');return
                awp=ROOT/'outputs'/('awp_check.json' if regime=='leo' else f'awp_check_{regime}.json')
                paths[path]=(awp,'application/json')
            if path=='/api/awp-historical':
                try:
                    body=json.dumps(awp_historical_payload()).encode()
                except FileNotFoundError:
                    self.send_error(404,'Historical AWP comparison is not available');return
                except (ValueError,json.JSONDecodeError):
                    self.send_error(503,'Historical AWP comparison is incomplete or invalid');return
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            if path=='/api/replay':
                regime=parse_qs(parsed.query).get('regime',['leo'])[0].lower()
                if regime not in {'leo','meo','geo','heo'}: self.send_error(400,'Unknown orbit regime');return
                candidate=output/'replays'/f'{regime}.json'
                paths[path]=(candidate if candidate.is_file() else output/'replay.json','application/json')
            for name in ['main_effects','half_normal','residual_diagnostics','response_contours','validation']:
                paths['/plots/'+name+'.png']=(output/'plots'/(name+'.png'),'image/png')
            if path not in paths:self.send_error(404);return
            file,mime=paths[path]
            if not file.is_file():self.send_error(404,'Run output not available yet');return
            body=file.read_bytes();self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    print(f'GoDSAT dashboard: http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
