import csv
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
from scripts.validation.audit_dropout_results import audit


def fixture(output):
    output.mkdir()
    design={'dates':['d1','d2'],'regimes':['leo','geo'],
        'modes':['independent','burst'],'rates':[0.0,0.05],
        'replicates':2,'model_seeds':[101,211]}
    (output/'dropout_design.json').write_text(json.dumps(
        {'design_signature':'sig','design':design}))
    return design


def write_rows(path,rows):
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=[
            'date','regime','mode','replicate','model_seed','dropout_probability'])
        writer.writeheader();writer.writerows(rows)


def expected_rows(design,selected_cells=None):
    cells=selected_cells or [(d,r) for d in design['dates'] for r in design['regimes']]
    return [{'date':d,'regime':r,'mode':mode,'replicate':replicate,
        'model_seed':seed,'dropout_probability':rate}
        for d,r in cells for mode in design['modes']
        for replicate in range(design['replicates'])
        for seed in design['model_seeds'] for rate in design['rates']]


def test_dropout_audit_validates_complete_design_and_checkpoint(tmp_path):
    design=fixture(tmp_path/'out')
    rows=expected_rows(design)
    write_rows(tmp_path/'out/dropout_responses.csv',rows)
    (tmp_path/'out/dropout_summary.json').write_text(json.dumps(
        {'status':'completed','design_signature':'sig'}))

    report=audit(tmp_path/'out')

    assert report['status']=='completed_valid'
    assert report['rows_read']==64
    assert report['completed_cells']==4
    assert report['missing_rows']==0


def test_dropout_audit_distinguishes_resumable_partial_checkpoint(tmp_path):
    design=fixture(tmp_path/'out')
    rows=expected_rows(design,[('d1','leo')])
    write_rows(tmp_path/'out/dropout_responses.csv',rows)

    report=audit(tmp_path/'out')

    assert report['status']=='partial_checkpoint'
    assert report['completed_cells']==1
    assert report['missing_rows']==48
    assert report['summary_present'] is False


def test_dropout_audit_rejects_duplicate_or_unplanned_completed_rows(tmp_path):
    design=fixture(tmp_path/'out')
    rows=expected_rows(design)
    rows.extend([rows[0],{**rows[0],'date':'unexpected'}])
    write_rows(tmp_path/'out/dropout_responses.csv',rows)
    (tmp_path/'out/dropout_summary.json').write_text(json.dumps(
        {'status':'completed','design_signature':'sig'}))

    report=audit(tmp_path/'out')

    assert report['status']=='completed_invalid'
    assert report['duplicate_rows']==1
    assert report['unexpected_rows']==1
