"""Map the actual supplied manuscript requirements to executed study evidence."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
from pypdf import PdfReader

from godsat.orbits import ROOT


def audit(root=ROOT):
    root=Path(root).resolve();sources={};requirements=[]
    def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def read(relative):
        path=root/relative
        if not path.exists():return None
        sources[relative]=digest(path)
        return json.loads(path.read_text())
    def verify_design(folder):
        path=root/folder/'screening_design.csv'
        with path.open() as f:rows=list(csv.DictReader(f))
        sources[str(path.relative_to(root))]=digest(path)
        x=np.asarray([[float(r[k]) for k in 'ABCDEFG'] for r in rows])
        if x.shape!=(16,7) or not np.array_equal(x.T@x,np.eye(7)*16):raise ValueError('Screen dimensions or orthogonality differ')
        if not (np.array_equal(x[:,4],x[:,0]*x[:,1]*x[:,2]) and
                np.array_equal(x[:,5],x[:,0]*x[:,1]*x[:,3]) and
                np.array_equal(x[:,6],x[:,0]*x[:,2]*x[:,3])):raise ValueError('Screen generators differ from equation 3')
        factors=['learning_rate','discount','actor_width','critic_depth','entropy','claim_resolution','target_tau']
        low=np.array([1e-5,.90,64,2,.01,32,.001]);high=np.array([1e-3,.99,256,4,.10,128,.05])
        for row,point in zip(rows,x):
            expected=(low+high)/2+point*(high-low)/2
            for i,factor in enumerate(factors):
                value=int(round(expected[i])) if factor in ['actor_width','critic_depth','claim_resolution'] else expected[i]
                if not np.isclose(float(row[factor]),value,rtol=1e-14,atol=1e-15):raise ValueError('Source factor levels/coding differ')
        config=read(folder+'/config.json')
        if [int(r['standard_order']) for r in rows]!=np.random.default_rng(config['design_seed']).permutation(16).tolist():raise ValueError('Randomized source design order differs')
        path=root/folder/'rsm_design.csv'
        with path.open() as f:rows=list(csv.DictReader(f))
        sources[str(path.relative_to(root))]=digest(path)
        local=np.array([[float(r[k]) for k in ['x1','x2','x3']] for r in rows])
        nonzero=np.count_nonzero(local,axis=1)
        if len(rows)!=15 or sum(nonzero==3)!=8 or sum(nonzero==1)!=6 or sum(nonzero==0)!=1:raise ValueError('CCD source design differs')
        q=np.column_stack([np.ones(len(local)),local,local**2,local[:,0]*local[:,1],local[:,0]*local[:,2],local[:,1]*local[:,2]])
        if np.linalg.matrix_rank(q)!=10:raise ValueError('Source quadratic model is unidentifiable')
    meta=read('outputs/study-execution/source-inventory/governing-design-pdf.json')
    if not meta:raise ValueError('Actual governing source inventory required')
    pdf=Path(meta['path']);reader=PdfReader(pdf)
    if digest(pdf)!=meta['sha256']:raise ValueError('Governing PDF changed')
    text='\n'.join(p.extract_text() or '' for p in reader.pages)
    if len(reader.pages)!=6 or any(s not in text for s in ['3. METHODOLOGY','3.1','3.2','3.3','3.4','3.5','Placeholder for numerical tables']):
        raise ValueError('Source changed or required sections are not extractable')
    sources[str(pdf.relative_to(root))]=digest(pdf)
    def add(identifier,section,pages,text,state,evidence,explanation):
        requirements.append(dict(id=identifier,pdf_section=section,pages=pages,requirement=text,
                                 state=state,evidence=evidence,assessment=explanation))
    old='outputs/paper-reference-cpu-20261024'
    original=read(old+'/campaign_integrity_audit.json')
    supplement=read('outputs/governing-design-followthrough-20261025/summary.json')
    leo_center=read('outputs/leo-center-replication-20261025/independent_validation.json')
    new='outputs/governing-design-physical-leo-20261025'
    physical=read(new+'/independent_physical_audit.json')
    training=read(new+'/training_replay_audit.json')
    if training:
        if (training['status']!='passed_all_treatment_signatures_and_sampled_training_replay'
                or training['treatment_signatures_verified']!=77 or len(training['full_training_replays'])!=3):
            raise ValueError('Training replay audit incomplete')
        for relative,expected in training['source_hashes'].items():
            if digest(root/relative)!=expected:raise ValueError('Training replay source changed')
    summary=read(new+'/summary.json')
    center=read('outputs/governing-design-physical-leo-center-20261025/independent_validation.json')
    sensitivity=read('outputs/physical-sensor-sensitivity-20261025/independent_audit.json')
    if sensitivity:
        sensitivity_summary=read('outputs/physical-sensor-sensitivity-20261025/summary.json')
        if (sensitivity['summary_sha256']!=digest(root/'outputs/physical-sensor-sensitivity-20261025/summary.json') or
                sensitivity['response_rows_checked']!=2295 or sensitivity['temporal_intervals_checked']!=216 or
                sensitivity['sampled_policy_and_independent_physical_action_replays']!=81):
            raise ValueError('Sensitivity audit incomplete or stale')
        if digest(root/'outputs/physical-sensor-sensitivity-20261025/responses.csv')!=sensitivity_summary['responses_sha256']:
            raise ValueError('Sensitivity response bytes changed')
        for relative,expected in sensitivity_summary['source_hashes'].items():
            if digest(root/relative)!=expected:raise ValueError('Sensitivity audit source changed')
    complete=bool(physical and physical['status']=='passed_all_checkpoint_selection_and_heldout_physical_replays')
    if original:verify_design(old)
    if complete:
        verify_design(new)
        if physical['summary_sha256']!=digest(root/new/'summary.json'):raise ValueError('Physical audit is stale')
        for relative,expected in physical['source_hashes'].items():
            if digest(root/relative)!=expected:raise ValueError('Physical audit source changed')
    if supplement:
        for relative,expected in supplement['source_hashes'].items():
            if digest(root/relative)!=expected:raise ValueError('Screening/budget supplement source changed')
    pending='pending_execution_or_audit';done='executed_and_verified'
    state=done if complete else pending
    add('P01','3.1 / Table 1',[3],'Seven factors and exact low/high values; linear coded map with discrete network/grid factors.',done if original else pending,[old+'/screening_design.csv',new+'/screening_design.csv'],'The source-level ranges match the implementation. New assumed-sensor campaign retains the factor region; integer factors are rounded before execution.')
    add('P02','3.2 / equations 3–4',[3],'Sixteen resolution-IV screening treatments from E=ABC, F=ABD, G=ACD.',done if original else pending,[old+'/campaign_integrity_audit.json','outputs/governing-design-followthrough-20261025/summary.json'],'Use the stated generators. Printed equation 4 is inconsistent with their group; corrected relation is I=ABCE=ABDF=ACDG=AEFG=BCFG=BDEG=CDEF. Literal use of both is impossible.')
    add('P03','3.2, 3.5',[3,4],'Seeded randomized standard-order design, deterministic treatment seeds, run provenance.',done if complete and training else pending,[new+'/screening_design.csv',new+'/runs',new+'/training_replay_audit.json'],'Single CPU host with seeded randomized order, strict Torch determinism, node/software/seed metadata and scenario/code hashes. All 77 signatures/loss histories checked; three full training trajectories and checkpoint tensors repeated exactly. No distributed or GPU speedup claim.')
    add('P04','3.2, 4',[3,4],'Main-effect contrasts, full two-factor alias chains, half-normal and interaction analysis.',done if supplement else pending,['outputs/governing-design-followthrough-20261025/report.md'],'Supplement enumerates all 15 orthogonal contrasts, including the three-factor residual omitted by the legacy report. The future analysis kernel retains all eight residual chains. Confounded interactions are never individually interpreted.')
    add('P05','3.2',[3],'Estimate screening noise by inactive higher-order pooling and rank three clean main effects.',done if supplement else pending,['outputs/governing-design-followthrough-20261025/summary.json',new+'/screening_analysis.json'],'Only one independent contrast has minimum alias order three; high-order-only variance has one df. Lenth flags and the all-contrast half-normal plot expose the assumption. Main factors are selected from measured objective effects; the placeholder eta/gamma/width ranking is not imposed.')
    add('P06','3.3 / equations 5–6',[4],'Fifteen-run face-centered CCD: eight cube points, six axial points, one center.',state,[new+'/rsm_design.csv',new+'/campaign_integrity_audit.json'],'The exact 15-treatment design is preserved. Additional center replication is a separately budgeted diagnostic.')
    add('P07','3.3, 4',[4],'Full quadratic OLS, coefficients, canonical classification and constrained ridge search.',state,[new+'/response_surfaces.json',new+'/anova_all_responses.json',new+'/coefficient_uncertainty_all_responses.json'],'Fit all recorded responses, retain saddle/out-of-region classifications and bounded ridge points. A numerical recommendation is exploratory unless adequacy and held-out results support it.')
    add('P08','3.3, 4',[4],'Residual normal-probability / fitted-residual plots and pure-error lack-of-fit testing before accepting an optimum.',done if center and center['status']=='completed' else pending,[new+'/plots/residual_diagnostics.png','outputs/governing-design-physical-leo-center-20261025/independent_validation.json','outputs/leo-center-replication-20261025/independent_validation.json'],'The single-center 15-run source design has no pure-error df. Twelve extra independent center retrains remedy that design limitation; this is an explicit addition. Rejecting a fitted optimum or failing to show improvement is a valid study result.')
    add('P09','3.4',[4],'Retrain recommendation with five independent seeds; compare with baseline and BO.',state,[new+'/validation.csv',new+'/independent_physical_audit.json'],'All three learned configurations retrain independently at the same five seeds. Held-out test windows are excluded from selection. Greedy and random controls are additional references.')
    add('P10','3.4, 3.5',[4],'Bayesian reference with 31 treatments and matched computational budget.',done if supplement else pending,['outputs/governing-design-followthrough-20261025/report.md',new+'/responses.csv'],'31 runs match treatment/episode count, not time because network sizes vary. Retrospective prefixes within DOE measured wall/CPU budgets retain the same validated BO recommendation in both original campaigns. Overhead and machine-load differences are disclosed; no equal-GPU claim is made.')
    add('P11','3.2, 3.4, 4',[3,4],'Custody continuity and slew-energy responses for every configuration.',state,[new+'/responses.csv',new+'/validation.csv','docs/physical-sensor-assumptions.md'],'New responses use separately maintained true custody and dimensioned idealized actuator energy in joules. User authorized documented sensor assumptions; these are not calibrated spacecraft energy measurements.')
    add('P12','3.2, 3.4, 4',[3,4],'False-track response for every configuration.',state,[new+'/responses.csv',new+'/validation.csv','docs/physical-sensor-assumptions.md'],'Missed detections remain separately labeled. Active false declared-track slots divided by all active declared-track slots measure simulated false tracks; separate false-observation counts are retained. Independent action reconstruction checks that clutter never earns true custody.')
    add('P13','3.2, 3.5',[3,4],'Wall time, GPU-hours, node/software/seed and per-treatment energy estimate.',state,[new+'/runs',new+'/campaign_integrity_audit.json'],'CPU wall/process time and zero GPU activity are recorded. A 50 W assumed host scenario supplies explicitly labeled energy estimates; calibrated energy remains unavailable. User authorized documented assumptions; host and gimbal energy are distinct.')
    add('P14','3.4, 4',[4],'Cost-performance ratios, matrices, raw responses, fitted coefficients and seeds released.',state,[new+'/responses.csv',new+'/validation.csv',new+'/summary.json',new+'/models'],'Local reviewable artifacts retain raw records and checkpoints. Summary includes cost-performance ratios with their accounting boundaries. Public repository publication was not requested.')
    add('P15','Abstract, 1, 4, 5',[1,2,4,5],'Test claimed 11–14% custody improvement, 9% energy reduction and search savings.',state,[new+'/summary.json','reports/current-study-20261024.md'],'Source Results section explicitly contains placeholders. Claims are hypotheses, not completion conditions. Preserve negative results. 128/31 is about 4.13, so an order-of-magnitude reduction is not established by this comparison.')
    add('P16','2.1, 3.4',[2,4],'GoDSAT actor–critic model and original baseline comparison.','completed_with_user_authorized_assumptions',['docs/source-fidelity.md','docs/physical-sensor-assumptions.md','configs/archive/governing-design-physical-leo.json'],'The available upstream controller is Q-table/gradient-based, unlike the manuscript actor–critic description. Shared neural actor and centralized/target critic plus a documented reference configuration implement the authorized simulation adaptation. Exact published-baseline reproduction and native-MATLAB parity are not claimed.')
    add('U01','User extension',[],'Realistic orbit geometry and complete available satellite history.',done,['data/historical_state_vectors_combined/manifest.json','outputs/catalog-trajectory-combined-20261024/manifest.json','outputs/ilrs-force-comparison-20261024/summary.json'],'All pinned history and final-date supplement processed. Explicit propagation/staleness gaps remain. Numerical force models compared in common frames with operational CPF; reconstructed histories are not measured truth.')
    add('U02','User extension',[],'Measure dropout effectiveness, geometry effects and measured-data sensitivity.',done,['outputs/dropout-five-policy-quarterly-20261024/uncertainty_independent_audit.json','outputs/measured-paired-process-comparison-20261024/independent_statistics_audit.json','outputs/geometry-single-loss-quarterly-20261024/independent_audit.json'],'Full registered quarterly/daily/source-availability studies are audited. They retain their original sensor assumptions and separate target/controller denominators. No dropout requirement or loss-process term appears in the supplied PDF text; these are requested extensions.')
    add('U03','User-authorized assumptions',[],'Validate the additional mechanical/clutter model and disclose parameter sensitivity.',done if sensitivity and sensitivity['status']=='passed_source_response_and_parameter_sensitivity_reproduction' else pending,['tests/unit/test_sensorphysics.py',new+'/independent_physical_audit.json','outputs/physical-sensor-sensitivity-20261025/independent_audit.json'],'Unit tests independently integrate torque work, exercise false tracks and complete loss, and check truth/report separation. The nominal campaign and frozen-policy parameter/loss sensitivity require separate numerical audits.')
    remaining=[r['id'] for r in requirements if r['state']==pending]
    result={'status':'source_protocol_review_with_remaining_work' if remaining else 'requirement_by_requirement_verified',
            'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'source_pdf_sha256':meta['sha256'],
            'source_pdf_pages':len(reader.pages),'source_hashes':sources,'requirements':requirements,
            'remaining_requirements':remaining,
            'compliance_scope':'Executed simulation adaptation under explicit user-authorized assumptions. Does not certify exact published-baseline reproduction, calibrated sensor performance or the manuscript placeholder gains.',
            'source_errata':['Printed defining relation differs from generator group.','A 15-point CCD with one center has no replicated pure error.','31 versus 128 treatments does not show an order-of-magnitude reduction.','Matched treatment count does not itself equal matched computation time.'],
            'user_authorization':'Use documented simulation assumptions (2026-10-25).'}
    target=root/'outputs/study-execution/source-protocol-audit.json';target.write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Governing PDF requirement audit','',f"Source: six pages, SHA-256 `{meta['sha256']}`.", '',result['compliance_scope'],'',
           '| ID | Source | Requirement | Assessment |','|---|---|---|---|']
    for r in requirements:lines.append(f"| {r['id']} | {r['pdf_section']}; pages {r['pages']} | {r['requirement']} | {r['state']}: {r['assessment']} |")
    lines+=['','Remaining execution/audit items: '+(', '.join(remaining) or 'none')+'.','',
            'Source errata:','']+['- '+s for s in result['source_errata']]
    (root/'docs/governing-pdf-audit.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    result=audit();print(json.dumps({'status':result['status'],'remaining':result['remaining_requirements']}))
