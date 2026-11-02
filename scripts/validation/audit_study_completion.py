"""Inventory current GoDSAT study evidence without treating partial runs as completion."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF_NAME = 'docs/papers/methodology.pdf'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_artifact(root, name, relative, expected_status, fields=None):
    path = root/relative
    row = {'requirement': name, 'path': relative, 'state': 'missing',
           'expected_status': expected_status, 'field_checks': {}}
    if not path.is_file():
        return row
    row['sha256'] = sha256(path)
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError) as error:
        row.update(state='invalid', error=str(error)); return row
    row['observed_status'] = value.get('status')
    row['field_checks'] = {key: {'expected': expected, 'observed': value.get(key),
                                  'matches': value.get(key) == expected}
                           for key, expected in (fields or {}).items()}
    row['state'] = ('recorded_audit_passed' if value.get('status') == expected_status
                    and all(item['matches'] for item in row['field_checks'].values()) else 'incomplete')
    return row


def inventory(root=ROOT, pdf=None):
    root = Path(root).resolve(); pdf = Path(pdf or root/PDF_NAME)
    evidence = []
    def add(name, path, status, **fields):
        evidence.append(inspect_artifact(root, name, path, status, fields))
    add('Supplied-PDF complete screening contrasts and retrospective compute-budget comparison',
        'outputs/governing-design-followthrough-20261025/summary.json',
        'completed_source_bound_screening_and_compute_prefix_analysis')
    add('Authorized physical-response paper-sized LEO experiment execution',
        'outputs/governing-design-physical-leo-20261025/campaign_integrity_audit.json',
        'completed', screening_treatments=16, ccd_treatments=15, bayesian_treatments=31,
        validation_retrains=15, heldout_policy_seed_rows=25, checkpoint_count=77)
    add('Every new checkpoint selection response and held-out physical action replay',
        'outputs/governing-design-physical-leo-20261025/independent_physical_audit.json',
        'passed_all_checkpoint_selection_and_heldout_physical_replays',
        checkpoint_selection_responses_replayed=77, heldout_response_rows_replayed=25,
        independent_action_traces_reconstructed=25)
    add('All new training signatures/loss histories and three full trajectory repeats',
        'outputs/governing-design-physical-leo-20261025/training_replay_audit.json',
        'passed_all_treatment_signatures_and_sampled_training_replay',
        treatment_signatures_verified=77, complete_finite_training_histories=77,
        full_training_replays=[{'name':name,'episodes':40,'all_checkpoint_tensors_exact':True,
                               'entire_training_history_exact':True}
                              for name in ['screen_00','screen_01','rsm_00']])
    add('Original LEO pure-error center replication',
        'outputs/leo-center-replication-20261025/independent_validation.json', 'completed',
        additional_replicates_validated=12, center_observations=13)
    add('New physical-response LEO pure-error center replication',
        'outputs/governing-design-physical-leo-center-20261025/independent_validation.json', 'completed',
        additional_replicates_validated=12, center_observations=13)
    add('Every new assumed-parameter/loss sensitivity estimate with independent physical sample replay',
        'outputs/physical-sensor-sensitivity-20261025/independent_audit.json',
        'passed_source_response_and_parameter_sensitivity_reproduction', response_rows_checked=2295,
        source_scenarios_checked=17, paired_effect_vectors_checked=72, temporal_intervals_checked=216,
        sampled_policy_and_independent_physical_action_replays=81)
    add('Full native-epoch history including final-date supplement',
        'data/historical_state_vectors_combined/manifest.json', 'validated_nonoverlapping_native_epoch_union',
        records=79405779, objects=40206)
    add('Every pinned four-hour catalog part audited',
        'outputs/catalog-trajectory-all-4hour-20261024/validation.json', 'validated_complete',
        parts_validated=1462, rows=352687032, objects=40206)
    add('Final-date fresh-source uniform-cadence overlay',
        'outputs/catalog-final-date-refresh-20261024/independent_audit.json', 'passed_source_and_baseline_reconciliation')
    add('Combined refreshed grid with exact catalogue membership checked over every row',
        'outputs/catalog-trajectory-combined-20261024/manifest.json', 'validated_complete_refreshed_grid_union',
        rows=352687032, objects=40206, cohort_membership_checked_over_every_row=True)
    for label, folder in [('LEO reference', 'paper-reference-cpu-20261024'),
                          ('Four-regime current-active hosts', 'all-orbits-active-hosts-cpu-20261024')]:
        add(label+' experimental design execution', f'outputs/{folder}/campaign_integrity_audit.json',
            'completed', screening_treatments=16, ccd_treatments=15, bayesian_treatments=31,
            validation_retrains=15, heldout_policy_seed_rows=25, checkpoint_count=77)
    add('Independent center replication and RSM diagnostic reproduction',
        'outputs/all-orbits-center-replication-20261024/independent_validation.json', 'completed',
        additional_replicates_validated=12, center_observations=13, response_surfaces_reproduced=True)
    add('Twenty extra post-training dates and held-out comparison statistics',
        'outputs/post-training-monthly-robustness-20261024/independent_integrity_audit.json', 'completed_valid',
        saved_comparison_summary_matches=True)
    add('All daily paired catalog tasking cells',
        'outputs/full-catalog-tasking-daily-20261024/independent_audit.json', 'passed_structural_and_statistical',
        dates_checked=1462, paired_date_regime_cells_checked=5848, response_rows_checked=11696)
    add('Full quarterly dropout grid and stratified checkpoint-policy replays',
        'outputs/dropout-five-policy-quarterly-20261024/numerical_replay_audit.json',
        'completed_numerically_validated_and_sample_replayed', full_study_complete=True,
        rows_checked=81600, completed_cells=68, summary_statistics_reproduced=True)
    add('Every reported quarterly dropout confidence and temporal block interval',
        'outputs/dropout-five-policy-quarterly-20261024/uncertainty_independent_audit.json',
        'passed_all_reported_temporal_uncertainty_statistics', response_rows=81600,
        independent_dates=17, condition_metric_estimates_checked=288,
        paired_effect_estimates_checked=192, moving_block_intervals_checked=576)
    add('Daily tasking temporal-dependence sensitivity',
        'outputs/full-catalog-tasking-daily-20261024/temporal_uncertainty.json',
        'completed_temporal_block_bootstrap', dates=1462, responses=11696)
    add('Daily tasking means, annual means and all temporal intervals independently reproduced',
        'outputs/full-catalog-tasking-daily-20261024/independent_temporal_audit.json',
        'passed_all_daily_temporal_statistics', dates=1462, response_rows=11696,
        effect_vectors_checked=12, annual_means_checked=60, block_intervals_checked=48)
    add('Geometry-conditioned single-observation effects and alternate-injection sample replay',
        'outputs/geometry-single-loss-quarterly-20261024/independent_audit.json',
        'passed_source_statistics_and_sampled_counterfactual_replay',
        cells_checked=68, probes_checked=2253,
        all_reported_date_cluster_statistics_recomputed=True,
        alternate_loss_injection_baselines_replayed=12,
        alternate_loss_injection_probes_replayed=85)
    add('Complete empirical-versus-Markov paired effects and temporal uncertainty reproduction',
        'outputs/measured-paired-process-comparison-20261024/independent_statistics_audit.json',
        'passed_all_reported_measured_comparison_statistics', dates_checked=208,
        paired_baseline_cells_checked=832, effect_vectors_and_means_checked=36,
        moving_block_intervals_checked=108, attempt_loss_groups_checked=8)
    add('Monthly common-frame force-model policy/dropout sensitivity',
        'outputs/awp-sun-moon-teme-policy-monthly-20261024/independent_audit.json', 'completed_valid',
        policy_rows=1920, dropout_rows=19200, failures=[])
    for label, folder in [('J2', 'j2'), ('J2 plus solar/lunar gravity', 'sun-moon')]:
        add(label+' comparison with operational ILRS orbit products',
            f'outputs/awp-ilrs-cpf-{folder}-20261024/independent_audit.json',
            'passed_structural_and_statistical', targets_checked=4, response_rows_checked=1860)
    add('Four-target observed ILRS source hashes, joins, range arithmetic and clustered contrasts',
        'outputs/ilrs-cross-target-sensor-quality-20261024/independent_audit.json',
        'passed_source_and_numerical_reproduction')
    add('DUST capture-gap custody counterfactual source/statistical reproduction',
        'outputs/dust-dropout-20261024/capture_cadence_custody_audit.json',
        'passed_independent_source_and_statistical_reproduction')
    for mode in ['raw-wcs', 'star-corrected']:
        add(f'DUST {mode} directional consistency and metadata exclusions',
            f'outputs/dust-tle-track-validation-20261024/{mode}/independent_audit.json', 'passed',
            source_track_inventory=160, completed_track_outputs=156, failed_track_count=4,
            held_out_frame_count=2930)
    add('Durham processed optical detections and conditional catalogue gaps',
        'data/ground_sensor/durham_widefield_ssa/dataset_audit.json', 'completed_conditional_on_sky_detection_gap_audit')
    add('All attitude products replayed and publisher absence reconciled',
        'data/attitude/cassiope_epop/independent_audit.json', 'passed_structural_and_statistical',
        source_cdf_days_replayed=1398, publisher_absence_probes_verified=64, failures=[])
    add('Measured outage masks and transition/bootstrap statistics',
        'data/attitude/cassiope_epop/dropout_masks_independent_audit.json', 'passed_independent_source_replay',
        profile_transition_and_bootstrap_statistics_verified=True)
    for process in ['empirical-block', 'fitted-markov']:
        add(f'Measured-profile {process} weekly tasking',
            f'outputs/measured-{process}-weekly-20261024/independent_audit.json',
            'passed_structural_and_statistical', dates_checked=208,
            paired_date_regime_cells_checked=832, response_rows_checked=1664)
    pdf_evidence = {'path': str(pdf), 'state': 'missing'}
    if pdf.is_file():
        pdf_evidence.update(state='present_requires_protocol_review', sha256=sha256(pdf), bytes=pdf.stat().st_size)
    protocol = inspect_artifact(root, 'Requirement-by-requirement source-PDF compliance',
        'outputs/study-execution/source-protocol-audit.json', 'requirement_by_requirement_verified')
    if protocol['state'] == 'recorded_audit_passed':
        value = json.loads((root/protocol['path']).read_text())
        if (not pdf.is_file() or value.get('source_pdf_sha256') != pdf_evidence.get('sha256')
                or not value.get('requirements') or value.get('remaining_requirements') != []
                or any(row.get('state') not in {'executed_and_verified','completed_with_user_authorized_assumptions'}
                       for row in value.get('requirements',[]))
                or any(not (root/path).is_file() or sha256(root/path)!=expected
                       for path,expected in value.get('source_hashes',{}).items())):
            protocol['state'] = 'unverified_protocol_binding'
        else:
            pdf_evidence['state']='source_bound_protocol_reviewed'
            pdf_evidence['compliance_scope']=value.get('compliance_scope')
    evidence.insert(0, protocol)
    drift = []
    index = root/'outputs/study-execution/evidence-index.json'
    if index.exists():
        for key, item in json.loads(index.read_text()).get('artifacts', {}).items():
            path = root/item['path']
            if not path.is_file() or sha256(path) != item['sha256']:
                drift.append({'name': key, 'path': item['path']})
    return {'status': 'completion_inventory_requires_scientific_review',
        'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'source_pdf': pdf_evidence,
        'requirements': evidence, 'stale_or_missing_index_entries': drift,
        'all_required_recorded_audits_passed': pdf.is_file() and not drift
            and all(row['state'] == 'recorded_audit_passed' for row in evidence),
        'scope': 'This inventory checks actual artifact bytes, recorded audit status and declared design dimensions. It does not replace source/numerical replay audits or a scientific review of model assumptions, protocol fidelity and the final conclusions. A negative experimental result does not make a correctly executed experiment incomplete.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--pdf', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); value = inventory(args.root, args.pdf)
    path = args.output or args.root/'outputs/study-execution/completion-inventory.json'
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2)+'\n')
    lines = ['# Current study completion inventory', '', value['scope'], '',
             f"Authoritative design PDF: **{value['source_pdf']['state']}**.", '',
             '| Requirement | Current evidence |', '|---|---|']
    lines += [f"| {row['requirement']} | [{row['state']}]({(args.root/row['path']).resolve()}) |" for row in value['requirements']]
    if value['stale_or_missing_index_entries']:
        lines += ['', 'Evidence-index entries requiring refresh: '+', '.join(row['name'] for row in value['stale_or_missing_index_entries'])]
    path.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'all_required_recorded_audits_passed': value['all_required_recorded_audits_passed'],
                      'source_pdf': value['source_pdf']['state'],
                      'recorded_audits_passed': sum(row['state']=='recorded_audit_passed' for row in value['requirements']),
                      'required_audits': len(value['requirements']),
                      'stale_index_entries': len(value['stale_or_missing_index_entries'])}))


if __name__ == '__main__':
    main()
