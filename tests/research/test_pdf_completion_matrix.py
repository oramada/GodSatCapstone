import pytest

from scripts.validation.audit_pdf_completion_matrix import reconcile
from scripts.validation.audit_study_completion import PDF_NAME


def test_missing_pdf_does_not_fabricate_page_count_or_content(tmp_path):
    result=reconcile(tmp_path)
    assert result['status']=='source_document_unavailable'
    assert result['source_pdf']['pages'] is None
    assert result['pdf_page_count'] is None
    assert result['pdf_contains_drop_out_term'] is None
    assert result['protocol_requirements_verified'] is False
    assert result['all_required_recorded_audits_passed'] is False
    assert result['requirements'][0]['state']=='missing'
    assert not any('pdf_section' in row for row in result['requirements'])


def test_actual_page_count_does_not_establish_protocol_compliance(tmp_path):
    pypdf=pytest.importorskip('pypdf')
    writer=pypdf.PdfWriter()
    writer.add_blank_page(width=72,height=72)
    writer.add_blank_page(width=72,height=72)
    (tmp_path/PDF_NAME).parent.mkdir(parents=True)
    with (tmp_path/PDF_NAME).open('wb') as stream:writer.write(stream)
    result=reconcile(tmp_path)
    assert result['status']=='source_protocol_unverified'
    assert result['source_pdf']['pages']==2
    assert result['pdf_contains_drop_out_term'] is None
    assert result['pdf_extractable_text_present'] is False
    assert result['protocol_requirements_verified'] is False
    assert result['all_required_recorded_audits_passed'] is False
