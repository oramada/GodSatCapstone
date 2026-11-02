import json

import pytest

from scripts.experiments.parallel_catalog_cells import publish_exact_cell


def test_parallel_publication_rejects_existing_different_scientific_result(tmp_path):
    path=tmp_path/'cell.json'
    payload={'rows':[{'custody':.2}], 'configuration_signature':'a'}
    assert publish_exact_cell(path,payload) == 'published'
    assert publish_exact_cell(path,payload) == 'existing_exact'
    with pytest.raises(ValueError,match='differs'):
        publish_exact_cell(path,{**payload,'rows':[{'custody':.3}]})
    assert json.loads(path.read_text()) == payload
    assert list(tmp_path.glob('*.tmp')) == []
