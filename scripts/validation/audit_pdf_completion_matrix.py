#!/usr/bin/env python3
"""Compatibility entry point for source-bound current study completion evidence.

Legacy hard-coded paper sections and old execution paths cannot establish PDF
compliance. Requirements now come from the current evidence inventory, with
source-PDF metadata extracted from actual bytes when available.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import io
import json
from pathlib import Path
import re

from godsat.orbits import ROOT
from scripts.validation.audit_study_completion import PDF_NAME,inventory


def reconcile(root:Path=ROOT)->dict:
    root=Path(root).resolve()
    result=inventory(root)
    pdf=root/PDF_NAME
    document={**result['source_pdf'],'pages':None}
    page_count=contains_dropout=extractable_text_present=None
    extraction_error=None
    if pdf.is_file():
        try:
            from pypdf import PdfReader
            data=pdf.read_bytes()
            if hashlib.sha256(data).hexdigest()!=document['sha256']:
                raise ValueError('Source PDF changed during the inventory read')
            reader=PdfReader(io.BytesIO(data))
            page_count=len(reader.pages)
            text='\n'.join(page.extract_text() or '' for page in reader.pages)
            extractable_text_present=bool(text.strip())
            contains_dropout=(bool(re.search(r'drop[\s-]*out',text,re.I))
                              if extractable_text_present else None)
            document['pages']=page_count
        except Exception as error:
            extraction_error=f'{type(error).__name__}: {error}'
    protocol=result['requirements'][0]
    protocol_verified=(protocol['state']=='recorded_audit_passed'
                       and page_count is not None and extraction_error is None)
    if not pdf.is_file():status='source_document_unavailable'
    elif extraction_error:status='source_document_unreadable'
    elif not protocol_verified:status='source_protocol_unverified'
    else:status='reconciled_recorded_evidence_requires_scientific_review'
    daily_folder=root/'outputs/full-catalog-tasking-daily-20261024'
    def optional(name):
        path=daily_folder/name
        return json.loads(path.read_text()) if path.exists() else None
    progress=optional('progress.json');prefix=optional('completed_prefix_audit.json')
    campaign_progress=None
    if progress:
        campaign_progress={
            'status':progress.get('status'),
            'expected_groups':progress.get('expected_date_regime_groups'),
            'runner_completed_groups':progress.get('completed_date_regime_groups'),
            'runner_completed_dates':progress.get('complete_date_count'),
            'independently_audited_groups':prefix.get('paired_date_regime_cells_checked',0) if prefix else 0,
            'independently_audited_response_rows':prefix.get('response_rows_checked',0) if prefix else 0,
            'audit_status':prefix.get('status','not_run') if prefix else 'not_run'}
    return {
        'status':status,'generated_utc':result['generated_utc'],'source_pdf':document,
        'pdf_page_count':page_count,'pdf_contains_drop_out_term':contains_dropout,
        'pdf_extractable_text_present':extractable_text_present,
        'pdf_text_search_scope':'Digitally extracted text only; no OCR or inference of research-question scope.',
        'pdf_extraction_error':extraction_error,'protocol_requirements_verified':protocol_verified,
        'all_required_recorded_audits_passed':bool(result['all_required_recorded_audits_passed'] and protocol_verified),
        'daily_campaign_progress':campaign_progress,'requirements':result['requirements'],
        'stale_or_missing_index_entries':result['stale_or_missing_index_entries'],
        'interpretation':'Current configured-study and user-extension evidence. These rows are not attributed to numbered PDF sections without a source-bound protocol audit. Missing PDF metadata remains unknown; recorded audit status does not replace scientific review.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=reconcile(args.root)
    target=args.output or args.root/'outputs/study-execution/legacy_completion_matrix.json'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'requirements':len(result['requirements']),
                      'protocol_requirements_verified':result['protocol_requirements_verified'],'output':str(target)},indent=2))
