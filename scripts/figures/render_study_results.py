"""Build the current scientific synthesis from completed, audited study outputs."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import datetime as dt
import json
from pathlib import Path

from godsat.orbits import ROOT
from scripts.experiments.run_dropout_campaign import sha256


def render(output):
    output=Path(output).resolve();sources={}
    def read(relative,status=None):
        path=ROOT/relative;value=json.loads(path.read_text())
        if status is not None and value.get('status')!=status:
            raise ValueError(f'Required completed source is unavailable: {relative}')
        sources[relative]=sha256(path);return value
    def link(relative,label):
        import os
        return f'[{label}]({Path(os.path.relpath(ROOT/relative,output.parent)).as_posix()})'
    def interval(mean,half,scale=1,digits=4):
        return f'{mean*scale:+.{digits}f} [{(mean-half)*scale:+.{digits}f}, {(mean+half)*scale:+.{digits}f}]'
    def completed(relative,status):
        path=ROOT/relative
        return path.exists() and json.loads(path.read_text()).get('status')==status
    campaign=read('outputs/all-orbits-active-hosts-cpu-20261024/summary.json','completed')
    read('outputs/all-orbits-active-hosts-cpu-20261024/campaign_integrity_audit.json','completed')
    robust=read('outputs/post-training-monthly-robustness-20261024/manifest.json','completed')
    read('outputs/post-training-monthly-robustness-20261024/independent_integrity_audit.json','completed_valid')
    surfaces=read('outputs/all-orbits-center-replication-20261024/response_surfaces_augmented.json')
    read('outputs/all-orbits-center-replication-20261024/independent_validation.json','completed')
    native=read('data/historical_state_vectors_combined/manifest.json','validated_nonoverlapping_native_epoch_union')
    grid=read('outputs/catalog-trajectory-combined-20261024/manifest.json','validated_complete_refreshed_grid_union')
    if not grid['cohort_membership_checked_over_every_row']:
        raise ValueError('Full catalogue membership check required')
    forces=read('outputs/ilrs-force-comparison-20261024/summary.json','rendered_from_audited_matched_reference_samples')
    for receipt in forces['source_receipts']:
        path=Path(receipt['path'])
        if sha256(path)!=receipt['sha256']:raise ValueError('Matched force-comparison source changed')
        sources[str(path.relative_to(ROOT))]=receipt['sha256']
    measured=read('outputs/measured-paired-process-comparison-20261024/summary.json','completed_paired_process_comparison')
    measured_audit=read('outputs/measured-paired-process-comparison-20261024/independent_statistics_audit.json','passed_all_reported_measured_comparison_statistics')
    if measured_audit['summary_sha256']!=sources['outputs/measured-paired-process-comparison-20261024/summary.json']:
        raise ValueError('Measured comparison audit is stale')
    for label,folder in [('empirical','outputs/measured-empirical-block-weekly-20261024'),
                         ('markov','outputs/measured-fitted-markov-weekly-20261024')]:
        for name,digest in measured['source_artifacts'][label].items():
            relative=f'{folder}/{name}'
            if sha256(ROOT/relative)!=digest:raise ValueError('Measured tasking source changed')
            sources[relative]=digest
        replay=read(f'{folder}/sampled_action_replay.json','passed_sampled_source_and_action_replay')
        if (replay['response_rows_replayed']!=24 or not replay['all_returned_fields_exact']
                or replay['summary_sha256']!=sources[f'{folder}/summary.json']):
            raise ValueError('Sampled action replay does not match measured source')
    profile=read('data/attitude/cassiope_epop/dropout_profile_1minute.json','completed')
    attitude_audit=read('data/attitude/cassiope_epop/independent_audit.json','passed_structural_and_statistical')
    if (not attitude_audit['source_cdf_replay_requested']
            or attitude_audit['source_cdf_days_replayed']!=attitude_audit['downloaded_days']
            or not attitude_audit['publisher_absence_verification_requested']
            or attitude_audit['publisher_absence_probes_verified']!=len(attitude_audit['not_published_days'])):
        raise ValueError('Complete attitude source replay and absence checks required')
    if profile['source_audit_sha256']!=sources['data/attitude/cassiope_epop/independent_audit.json']:
        raise ValueError('Availability profile is not tied to the source audit')
    windows=read('outputs/attitude-hour-window-model-20261024/summary.json','completed_exact_source_window_and_markov_comparison')
    geometry=read('outputs/geometry-single-loss-quarterly-20261024/summary.json','completed')
    geometry_audit=read('outputs/geometry-single-loss-quarterly-20261024/independent_audit.json','passed_source_statistics_and_sampled_counterfactual_replay')
    if geometry_audit['summary_sha256']!=sources['outputs/geometry-single-loss-quarterly-20261024/summary.json']:
        raise ValueError('Geometry audit is stale')
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    protocol_path='outputs/study-execution/source-protocol-audit.json'
    protocol=read(protocol_path) if (ROOT/protocol_path).exists() else None
    if protocol:
        metadata=read('outputs/study-execution/source-inventory/governing-design-pdf.json')
        pdf=Path(metadata['path'])
        if sha256(pdf)!=metadata['sha256'] or protocol['source_pdf_sha256']!=metadata['sha256']:
            raise ValueError('Governing protocol source binding changed')
        sources[str(pdf.relative_to(ROOT))]=metadata['sha256']
    protocol_note=(f"The six-page governing PDF has been supplied, read and hashed. Its requirement audit currently records {len(protocol['remaining_requirements'])} remaining execution/audit items. The user authorized documented sensor and baseline assumptions; exact published-baseline reproduction is not claimed."
                   if protocol else 'Protocol compliance remains unverified: the governing factorial/RSM design PDF has not been audited.')
    lines=['# GoDSAT study: current scientific results','',
        f'Generated {now}. {protocol_note} This is an executed simulation study with observational reference checks.','',
        'The configured optimization does not establish an all-target custody improvement. Additional held-out dates show lower observable-target custody for the DOE recommendation. Observed availability and injected losses affect the simulated tasking responses, but neither provides a measured fleet failure-effectiveness estimate. Only results with the required completed component audits are included below.','',
        '## Implemented system and estimands','',
        'The learned-policy experiments use six present-day active-payload sensor hosts and 18 orbital targets per scene, with separate LEO, MEO, GEO and HEO host groups. Scenes select dense observable target clusters; they are not random samples of all catalogue targets. Each episode lasts one hour at 60-second steps. Historical SGP4 states determine geometry; detection probabilities, field of regard, slew constraints, custody persistence and observation failures are modeled. Current active status is backcast through time and does not establish historical operations.','',
        'The shared categorical neural actor and centralized critic differ from the available original framework’s Q-table/gradient controller and global ClaimMap state machine. A separate greedy urgency/slew scheduler scales to all fresh, usable catalogue targets. These controllers and target denominators are separate estimands. '+link('docs/source-fidelity.md','Source fidelity comparison')+'.','',
        'Custody continuity concerns target-time slots within the modeled custody interval. Observable custody uses observable slots; its denominator differs from all-target custody. Slew responses are normalized angle proxies, not joules or propellant. Failed-observation proxies do not identify false physical tracks. CPU execution and zero GPU use do not establish a GPU speedup.','',
        '## Orbital coverage and physical reference checks','',
        f'The reconstructed native-epoch union contains {native["records"]:,} records for {native["objects"]:,} objects over 2022-10-09 through 2026-10-09. It includes an independently replayed final-date supplement and retains five flagged propagation failures. The readable four-hour union contains {grid["rows"]:,} planned rows, {grid["samples_per_object"]:,} samples per object and exact audited cohort membership.','',
        '| Four-hour row status | Rows | Fraction of planned grid |','|---|---:|---:|']
    for key,count in grid['status_counts'].items():lines.append(f'| {key.replace("_"," ")} | {count:,} | {count/grid["rows"]:.3%} |')
    lines.extend(['','Missing or stale rows remain unavailable. The complete grid is not a complete measured trajectory. Sampled tasking episodes also do not imply continuous four-year operations. '+link('outputs/catalog-trajectory-combined-20261024/manifest.json','Readable grid and provenance')+'.','',
        'Matched operational ILRS CPF reference samples compare historical SGP4 with numerical two-body/J2 and J2 plus solar/lunar gravity. The numerical propagators start from archived SGP4 epoch states, with explicit TEME/GCRS handling. Both simplified numerical models agree less closely with CPF on this sample; adding force terms has not demonstrated improved orbit accuracy. CPF itself is an operational product rather than independent truth.','',
        '| Target | Matched epochs | SGP4 median separation (km) | J2 (km) | J2 + Sun/Moon (km) |','|---|---:|---:|---:|---:|'])
    for row in forces['targets']:
        lines.append(f'| {row["target"]} | {row["samples"]} | {row["sgp4_median_separation_km"]:.4f} | {row["awp_j2_median_separation_km"]:.4f} | {row["awp_j2_sun_moon_median_separation_km"]:.4f} |')
    refresh='outputs/final-date-tasking-source-refresh-20261024'
    if completed(refresh+'/independent_audit.json','passed_source_controls_statistics_and_sampled_tasking_replay'):
        refresh_summary=read(refresh+'/summary.json','completed_descriptive_source_refresh_sensitivity')
        refresh_audit=read(refresh+'/independent_audit.json','passed_source_controls_statistics_and_sampled_tasking_replay')
        if refresh_audit['summary_sha256']!=sha256(ROOT/refresh/'summary.json'):
            raise ValueError('Source-refresh tasking audit is stale')
        interactions=refresh_summary['outage_interactions']
        largest=max(abs(r['change_in_20pct_minus_zero_effect']['custody_continuity']*100) for r in interactions)
        observable=max(abs(r['change_in_20pct_minus_zero_effect']['observable_custody']*100) for r in interactions)
        lines.extend(['',f'The tasking campaign remains bound to its frozen annual-source snapshot. A separate final-date refresh check completed {refresh_audit["response_rows_checked"]} conditions over the two final midnight hours, with full episode cohorts, shared IDs and shared validity masks. All {refresh_audit["canonical_baseline_rows_checked"]} original full-cohort responses matched exactly; independently rebuilt controls and {refresh_audit["sampled_tasking_responses_replayed"]} sampled replays passed. The largest change in the 20%-minus-zero effect was {largest:.8f} percentage points for all-target custody and {observable:.8f} points for observable custody. These two-window checks do not establish population robustness or orbit accuracy. '+link(refresh+'/report.md','Source-refresh sensitivity')+'.'])
    lines.extend(['','The separate monthly common-frame tasking comparison passed its audit. It addresses response sensitivity within one-hour scenes, not long-horizon orbit truth or equivalence. '+link('outputs/awp-sun-moon-teme-policy-monthly-20261024/report.md','Monthly policy and force sensitivity')+'.','',
        '## Optimization and additional-date evaluation','',
        f'The four-regime campaign completed {campaign["screening_runs"]} screening treatments, {campaign["rsm_runs"]} CCD treatments, {campaign["bayesian_runs"]} BO treatments and {campaign["validation_retrains"]} validation retrains. The selected factors were {", ".join(campaign["selected_factors"])}. Screening plus CCD and the BO search each use 31 treatment runs. Twelve extra center retrains are separate model-adequacy diagnostics, not part of that original matched treatment budget.','',
        'The primary paired intervals use five trained seeds after regime aggregation. The additional-date intervals first average paired seeds and regimes within each of 20 dates, then cluster by date. These intervals answer different questions and are not interchangeable.','',
        '| Response | Primary DOE − baseline, 95% interval | Additional 20 dates, DOE − baseline, date-clustered 95% interval |','|---|---:|---:|'])
    for metric,label,scale in [('custody_continuity','All-target custody (pp)',100),('slew_energy_proxy','Normalized slew proxy',1),('objective','Reward/objective units',1)]:
        a=campaign['paired_comparisons'][metric];b=robust['date_clustered_comparisons']['doe_recommended'][metric]
        digits=6 if metric=='slew_energy_proxy' else 4
        lines.append(f'| {label} | {interval(a["paired_mean_change"],a["paired_ci95_half_width"],scale,digits)} | {interval(b["paired_change_vs_baseline"],b["date_clustered_ci95_half_width"],scale,digits)} |')
    obs=robust['date_clustered_comparisons']['doe_recommended']['observable_custody']
    lines.extend(['',f'On the additional dates, observable-target custody changes by {interval(obs["paired_change_vs_baseline"],obs["date_clustered_ci95_half_width"],100)} percentage points. The primary slew reduction does not persist on those dates. These results do not justify a general improvement claim.','',
        f'The center-replicated custody surface has lack-of-fit p={surfaces["custody_continuity"]["lack_of_fit"]["p_value"]:.5f}; the objective surface has p={surfaces["objective"]["lack_of_fit"]["p_value"]:.5f}. Nonrejection for the objective does not prove adequacy. The fitted stationary-point classification is {surfaces["objective"]["classification"]}; it is not a demonstrated optimum.','',
        '## Measured availability and paired loss-process sensitivity','',
        f'The audited CASSIOPE attitude product supplies {attitude_audit["downloaded_days"]:,} published daily products in a {attitude_audit["requested_days"]:,}-day request; {len(attitude_audit["not_published_days"])} publisher-confirmed unpublished days remain unknown. The unavailable one-minute solution fraction is {profile["one_minute_attitude_solution_dropout_rate"]:.3%} on published days. Definitive attitude solutions interpolate sensor information; these flags are not a log of every instantaneous sensor failure or prospective onboard availability. Unknown-day bounds and serial-dependence sensitivity are reported separately. '+link('outputs/attitude-availability-20261024/report.md','Availability analysis')+'.','',
        f'Across {windows["overlapping_source_window_count"]:,} overlapping within-day hour windows, the completely unavailable-hour fraction is {windows["empirical_all_unavailable_probability"]:.3%}; the fitted stationary Markov reference gives {windows["markov_all_unavailable_probability"]:.8%}. Those windows overlap and are not independent samples. This descriptive mismatch does not by itself quantify tasking consequences.','',
        'Both tasking processes now cover the same 208 weekly dates, four regimes and paired zero/source-rate conditions: 1,664 responses each. All 832 baseline cells match, and all 108 reported moving-block intervals were independently reproduced. Each process also passed 24 sampled deterministic action replays. The following changes concern observable-target custody, in percentage points.','',
        '| Hosts | Empirical loss − zero | Markov loss − zero | Markov − empirical | 13-week-block interval for process contrast |','|---|---:|---:|---:|---:|'])
    for regime in ('leo','meo','geo','heo'):
        a=measured['empirical_effects'][regime]['observable_custody'];b=measured['markov_effects'][regime]['observable_custody'];c=measured['markov_minus_empirical_effects'][regime]['observable_custody'];lo,hi=c['circular_moving_block_ci95']['13']
        lines.append(f'| {regime.upper()} | {a["mean"]*100:+.4f} | {b["mean"]*100:+.4f} | {c["mean"]*100:+.4f} | [{lo*100:+.4f}, {hi*100:+.4f}] |')
    lines.extend(['','These are pointwise, fixed-profile conditional intervals. Realized loss counts, timing and later adaptive actions all differ between processes; the contrast does not isolate burst structure at equal realized loss frequency. One spacecraft’s retrospectively fitted availability applied independently to hypothetical hosts does not establish fleet reliability. '+link('outputs/measured-paired-process-comparison-20261024/report.md','Complete paired-process analysis')+'.','',
        f'Geometry sensitivity uses {geometry["baseline_episodes"]} baseline episodes and {geometry["counterfactual_probes"]:,} paired single-successful-observation suppressions across 68 quarterly cells. All grouped statistics passed audit, and an alternate loss branch reproduced 85 sampled counterfactuals. These 18-target learned-policy probes condition on a successful baseline observation and occupied range/slew bin. Differences between bins also reflect date, target and checkpoint composition. They are separate from all-catalogue loss-rate effects. '+link('outputs/geometry-single-loss-quarterly-20261024/report.md','Geometry results and figure')+'.','',
        '## Observational cross-checks and remaining limits','',
        '| Source | Valid use | Inference not established |','|---|---|---|',
        '| DUST onboard star-tracker imagery | Capture/annotation gaps and angular candidate consistency | Hardware dropout rates, NORAD identity accuracy or held-out stellar calibration truth |',
        '| ILRS acquired normal points and CPF | Range arithmetic, acquired-return quality associations and operational orbit-product consistency | Unsuccessful acquisition probability, independent CPF orbit truth or causal return-quality effects |',
        '| Durham optical detections | Catalogue/astrometric checks and gaps conditional on bracketed detections | Unconditional acquisition or hardware-failure rates |',
        '| CASSIOPE definitive attitudes | Published-product validity masks and hypothetical availability sensitivity | Historical fleet availability or prospective sensor-failure prediction |','',
        link('outputs/study-execution/evidence-index.json','Source and audit index')+' identifies the individual reports and receipts. Synthetic probabilities remain assumptions even when orbital geometry and availability sequences originate in real data.','',
        ])
    integrated=set()
    daily='outputs/full-catalog-tasking-daily-20261024'
    if (completed(daily+'/independent_audit.json','passed_structural_and_statistical')
            and completed(daily+'/temporal_uncertainty.json','completed_temporal_block_bootstrap')
            and completed(daily+'/independent_temporal_audit.json','passed_all_daily_temporal_statistics')):
        daily_audit=read(daily+'/independent_audit.json','passed_structural_and_statistical')
        daily_summary=read(daily+'/summary.json','completed')
        temporal=read(daily+'/temporal_uncertainty.json','completed_temporal_block_bootstrap')
        temporal_audit=read(daily+'/independent_temporal_audit.json','passed_all_daily_temporal_statistics')
        if (temporal_audit['source_temporal_sha256']!=sha256(ROOT/daily/'temporal_uncertainty.json')
                or temporal_audit['block_intervals_checked']!=48
                or temporal_audit['source_responses_sha256']!=sha256(ROOT/daily/'responses.csv')):
            raise ValueError('Independent daily temporal audit is stale or incomplete')
        for name,digest in temporal['source_sha256'].items():
            if sha256(ROOT/daily/name)!=digest:raise ValueError('Daily temporal analysis source changed')
            sources[daily+'/'+name]=digest
        if (daily_audit['dates_checked']!=1462 or daily_audit['response_rows_checked']!=11696
                or daily_summary['completed_date_regime_groups']!=5848
                or temporal['dates']!=1462 or temporal['responses']!=11696):
            raise ValueError('Final daily tasking dimensions do not match the registered study')
        lines.extend(['','## Daily all-catalogue paired loss study','',
            'All 1,462 daily UTC epochs and four host regimes completed, giving 5,848 paired cells and 11,696 response rows. Each date samples one hour, so this covers approximately 4.17% of the calendar hours rather than continuous four-year tasking. Targets are fresh valid catalogue objects at each epoch; population size and observability change with time.','',
            'The intervention is injected 20% persistent burst loss versus a paired zero-loss reference. The following intervals use circular blocks of 30 consecutive daily paired effects, conditional on these modeled episodes. They are serial-dependence sensitivity estimates, not calibrated fleet reliability bounds.','',
            '| Hosts | All-target custody change (pp) | 30-day block interval (pp) | Observable custody change (pp) | 30-day block interval (pp) |',
            '|---|---:|---:|---:|---:|'])
        for regime in ('leo','meo','geo','heo'):
            a=temporal['effects'][regime]['custody_continuity'];b=temporal['effects'][regime]['observable_custody']
            alo,ahi=a['moving_block_ci95']['30'];blo,bhi=b['moving_block_ci95']['30']
            lines.append(f'| {regime.upper()} | {a["mean"]*100:+.4f} | [{alo*100:+.4f}, {ahi*100:+.4f}] | {b["mean"]*100:+.4f} | [{blo*100:+.4f}, {bhi*100:+.4f}] |')
        lines.extend(['','All-target and observable-target denominators remain distinct. Other block lengths and annual sensitivity are retained in '+link(daily+'/temporal_uncertainty.json','the temporal analysis')+'. This greedy catalogue reference is separate from the 18-target learned-policy studies.'])
        if completed(daily+'/sampled_action_replay.json','passed_sampled_source_and_action_replay'):
            replay=read(daily+'/sampled_action_replay.json','passed_sampled_source_and_action_replay')
            if replay['summary_sha256']!=sha256(ROOT/daily/'summary.json') or replay['response_rows_replayed']!=24:
                raise ValueError('Daily sampled action replay is stale or incomplete')
            lines.append('All 48 temporal intervals and 60 annual means were independently reproduced. Twenty-four complete response records from first/middle/last dates also matched fresh deterministic action replays; this does not constitute a replay of every unsampled action.')
        integrated.update(['Daily all-catalogue final source/response audit','Daily temporal-dependence analysis',
                           'Daily temporal statistics reproduction'])
    quarterly='outputs/dropout-five-policy-quarterly-20261024'
    if (completed(quarterly+'/numerical_replay_audit.json','completed_numerically_validated_and_sample_replayed')
            and completed(quarterly+'/uncertainty_independent_audit.json','passed_all_reported_temporal_uncertainty_statistics')):
        numerical=read(quarterly+'/numerical_replay_audit.json','completed_numerically_validated_and_sample_replayed')
        uncertainty=read(quarterly+'/uncertainty_independent_audit.json','passed_all_reported_temporal_uncertainty_statistics')
        quarterly_summary=read(quarterly+'/dropout_summary.json','completed')
        if (not numerical['full_study_complete'] or numerical['rows_checked']!=81600
                or numerical['completed_cells']!=68 or uncertainty['response_rows']!=81600
                or uncertainty['independent_dates']!=17
                or uncertainty['moving_block_intervals_checked']!=576
                or not numerical['summary_statistics_reproduced']
                or not numerical['snapshot_still_current']
                or numerical['response_snapshot_sha256']!=sha256(ROOT/quarterly/'dropout_responses.csv')
                or uncertainty['source_responses_sha256']!=sha256(ROOT/quarterly/'dropout_responses.csv')
                or uncertainty['source_summary_sha256']!=sha256(ROOT/quarterly/'dropout_summary.json')):
            raise ValueError('Final quarterly source/uncertainty audit does not match the registered study')
        sources[quarterly+'/dropout_responses.csv']=uncertainty['source_responses_sha256']
        lines.extend(['','## Quarterly frozen-policy loss-rate study','',
            'The full grid contains 81,600 responses: 17 sampled dates, four host regimes, five frozen checkpoints, 20 paired simulation replicates, two loss processes and six requested rates. Model-training seed and simulation replicate are paired across rates; responses are averaged within sampled date before date-level uncertainty is estimated.','',
            'The table selects the 20% burst-loss contrast against zero. Six-date moving blocks are blocks of consecutive sampled dates, not six calendar days. Other rates, both processes and 3-/6-/12-date block sensitivities remain in the component report. Intervals are pointwise and conditional on the simulated scenes; they do not turn 81,600 rows into independent observational samples.','',
            '| Hosts | Mean custody change (pp) | 6-sampled-date block interval (pp) |',
            '|---|---:|---:|'])
        for regime in ('leo','meo','geo','heo'):
            effect=quarterly_summary['paired_vs_zero_dropout'][f'{regime}:burst:custody_continuity']['0.2']
            ci=effect['moving_block_bootstrap_ci95_by_date_block']['6']
            lines.append(f'| {regime.upper()} | {effect["date_clustered_mean_change"]*100:+.4f} | [{ci["lower"]*100:+.4f}, {ci["upper"]*100:+.4f}] |')
        lines.extend(['','Complete rate/mode responses and uncertainty sensitivity: '+link(quarterly+'/dropout_report.md','quarterly component report')+'. These are injected losses under synthetic detection assumptions, without dropout-specific policy retraining.'])
        integrated.update(['Quarterly five-checkpoint dropout final audit','Quarterly temporal uncertainty reproduction'])
    physical_receipt_path='reports/governing-design-study-20261025.provenance.json'
    if (ROOT/physical_receipt_path).exists():
        physical_receipt=read(physical_receipt_path,'rendered_from_audited_governing_design_followthrough')
        physical_report='reports/governing-design-study-20261025.md'
        if sha256(ROOT/physical_report)!=physical_receipt['report_sha256']:
            raise ValueError('Physical-response synthesis changed')
        sources[physical_report]=physical_receipt['report_sha256']
        for relative,digest in physical_receipt['source_hashes'].items():
            if sha256(ROOT/relative)!=digest:raise ValueError('Physical-response synthesis input changed')
            sources[relative]=digest
        physical_summary=read('outputs/governing-design-physical-leo-20261025/summary.json','completed')
        c=physical_summary['paired_comparisons']['custody_continuity'];e=physical_summary['paired_comparisons']['slew_energy_joules']
        lines.extend(['','## Supplied-PDF physical-response followthrough','',
            'The new LEO campaign follows the supplied design under user-authorized baseline and sensor assumptions. It completed another 16 screening, 15 CCD and 31 BO treatments plus five-seed validation. Unlike the earlier proxy studies, it reports torque/speed-limited actuator energy in joules and explicit simulated false-track slots. All 77 checkpoint selection responses and 25 held-out responses passed replay and independent action reconstruction.','',
            f'DOE − baseline custody is {interval(c["paired_mean_change"],c["paired_ci95_half_width"],100)} percentage points; modeled mean slew energy changes by {interval(e["paired_mean_change"],e["paired_ci95_half_width"],1,6)} J per host-step. These results do not establish the manuscript placeholder gains.','',
            'Separate center replication and 2,295 quarterly parameter/loss sensitivity responses complete the assumed-model validation. They do not calibrate hardware or change the original campaigns retrospectively. '+link(physical_report,'Full supplied-design report, figures and sensitivity results')+'.'])
    validation_path=ROOT/'outputs/study-execution/validation-review.json'
    if validation_path.exists():
        validation=read('outputs/study-execution/validation-review.json')
        junit=ROOT/validation['junit_path']
        if sha256(junit)!=validation['junit_sha256']:raise ValueError('Validation receipt is stale')
        sources[validation['junit_path']]=validation['junit_sha256']
        core,research=validation['counts']['core'],validation['counts']['research']
        lines.extend(['','## Software validation scope','',
            f'The current combined run records {core["passed"]} core tests passed, {core["skipped"]} core tests skipped, {research["passed"]} research tests passed and {research["failed"]} research tests failed. All three research failures are missing-artifact errors for older source-refresh, MOST 2004/2005 and Sentinel inventory outputs. The broader suite is not green. '+link('outputs/study-execution/validation-review.json','Exact counts and missing artifacts')+'.','',
            'The legacy PDF audit now reads metadata from hashed source bytes and leaves unavailable or unextractable content unknown. Its missing-file and actual-page-count regressions do not establish the governing PDF’s compliance.'])
    lines.extend(['','## Final component evidence and protocol review','',
        '| Requirement | Current evidence |','|---|---|'])
    unresolved=(list(protocol['remaining_requirements']) if protocol else ['Governing protocol audit'])
    for label,relative,expected in [
        ('Daily all-catalogue final source/response audit','outputs/full-catalog-tasking-daily-20261024/independent_audit.json','passed_structural_and_statistical'),
        ('Daily temporal-dependence analysis','outputs/full-catalog-tasking-daily-20261024/temporal_uncertainty.json','completed_temporal_block_bootstrap'),
        ('Daily temporal statistics reproduction','outputs/full-catalog-tasking-daily-20261024/independent_temporal_audit.json','passed_all_daily_temporal_statistics'),
        ('Quarterly five-checkpoint dropout final audit','outputs/dropout-five-policy-quarterly-20261024/numerical_replay_audit.json','completed_numerically_validated_and_sample_replayed'),
        ('Quarterly temporal uncertainty reproduction','outputs/dropout-five-policy-quarterly-20261024/uncertainty_independent_audit.json','passed_all_reported_temporal_uncertainty_statistics')]:
        path=ROOT/relative
        if path.exists() and json.loads(path.read_text()).get('status')==expected:
            sources[relative]=sha256(path)
            state=('passed; results integrated above' if label in integrated
                   else 'passed; waiting for companion final audit before integration')
        else:state='pending; partial effects excluded';unresolved.append(label)
        lines.append(f'| {label} | {state} |')
    lines.append('| Source protocol compliance | '+(protocol['status'] if protocol else 'Pending source audit')+' |')
    if protocol:
        lines.extend(['',link('docs/governing-pdf-audit.md','Governing PDF requirement audit')+'; '+link('docs/physical-sensor-assumptions.md','Authorized sensor assumptions')+'.'])
    if unresolved:
        lines.extend(['','The original objective remains unfulfilled while the source audit records pending items. Original configured campaigns are complete; the new physical-response campaign and its required audits are separate evidence.'])
    else:
        lines.extend(['','The governing protocol has been executed as an explicitly documented simulation adaptation under user-authorized baseline and sensor assumptions. Exact published-controller replication, calibrated hardware performance and positive placeholder improvement claims are not established.'])
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text('\n'.join(lines)+'\n')
    receipt={'status':('current_scientific_synthesis_incomplete_protocol_verification' if unresolved else 'current_scientific_synthesis_protocol_executed_with_authorized_assumptions'),'generated_utc':now,
        'report_sha256':sha256(output),'generator_sha256':sha256(Path(__file__)),
        'sources':sources,'unresolved_requirements':unresolved,
        'scope':'Synthesis of completed audited component evidence. It is not a full-goal completion certificate or an independent replay of the underlying studies.'}
    output.with_suffix('.provenance.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'reports/current-study-20261024.md')
    args=parser.parse_args();receipt=render(args.output);print(json.dumps({'status':receipt['status'],'unresolved':receipt['unresolved_requirements']}))
