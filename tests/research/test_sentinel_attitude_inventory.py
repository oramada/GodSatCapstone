import json

import pytest

import scripts.data.inventory_sentinel_attitude as inventory_module


def product(name, product_id):
    return {
        'Id': product_id,
        'Name': name,
        'ContentDate': {'Start': '2026-01-01T00:00:00Z'},
        'ContentLength': 123,
    }


def test_inventory_resumes_platform_queries_after_failure(tmp_path, monkeypatch):
    output = tmp_path / 'catalog_inventory.json'
    calls = []

    def fail_on_second_platform(start, end, platforms):
        platform = platforms[0]
        calls.append(platform)
        if platform == 'S1B':
            raise RuntimeError('temporary catalogue outage')
        return [product('S1A_OPER_AUX_PROQUA_POD__20260101', 'first')]

    monkeypatch.setattr(inventory_module, 'list_products', fail_on_second_platform)
    with pytest.raises(RuntimeError, match='temporary catalogue outage'):
        inventory_module.write_inventory(
            output, '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z', ['S1A', 'S1B']
        )

    checkpoint = json.loads(output.read_text())
    assert checkpoint['completed_platforms'] == ['S1A']
    assert checkpoint['product_count'] == 1

    def complete_second_platform(start, end, platforms):
        calls.append(platforms[0])
        return [product('S1B_OPER_AUX_PROQUA_POD__20260102', 'second')]

    monkeypatch.setattr(inventory_module, 'list_products', complete_second_platform)
    result = inventory_module.write_inventory(
        output, '2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z', ['S1A', 'S1B']
    )

    assert calls == ['S1A', 'S1B', 'S1B']
    assert result['status'] == 'completed'
    assert result['product_count'] == 2
    assert result['counts_by_platform'] == {'S1A': 1, 'S1B': 1}


def test_inventory_upgrades_legacy_flat_product_list(tmp_path, monkeypatch):
    output = tmp_path / 'catalog_inventory.json'
    start = '2026-01-01T00:00:00Z'
    end = '2026-02-01T00:00:00Z'
    output.write_text(json.dumps({
        'requested_start_utc': start,
        'requested_end_exclusive_utc': end,
        'platforms': ['S1A', 'S1B'],
        'catalogued_utc': '2026-02-01T00:00:00+00:00',
        'products': [{
            'id': 'first',
            'name': 'S1A_OPER_AUX_PROQUA_POD__20260101',
            'content_date': {'Start': '2026-01-01T00:00:00Z'},
            'content_length': 123,
        }],
    }))
    monkeypatch.setattr(
        inventory_module, 'list_products',
        lambda *_: pytest.fail('a completed legacy inventory should not be refetched'),
    )

    result = inventory_module.write_inventory(output, start, end, ['S1A', 'S1B'])

    assert result['status'] == 'completed'
    assert result['product_count'] == 1
    assert result['products_by_platform']['S1B'] == []
    assert result['catalogued_utc'] == '2026-02-01T00:00:00+00:00'
