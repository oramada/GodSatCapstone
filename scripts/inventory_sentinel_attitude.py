"""Cache the public CDSE catalogue inventory for Sentinel AUX_PROQUA attitude products."""
import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.sentinel_attitude import PLATFORM_NORAD, list_products


def write_inventory(output, start, end, platforms):
    output = pathlib.Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps({
        'start': start, 'end': end, 'platforms': platforms,
    }, sort_keys=True).encode()).hexdigest()
    if output.exists():
        inventory = json.loads(output.read_text())
        if not inventory.get('request_signature'):
            # Upgrade the first inventory format, which stored one flat product list.
            if (inventory.get('requested_start_utc') != start
                    or inventory.get('requested_end_exclusive_utc') != end
                    or sorted(inventory.get('platforms', [])) != platforms):
                raise ValueError(f'{output} contains an inventory for a different request')
            grouped = {platform: [] for platform in platforms}
            for product in inventory.pop('products', []):
                grouped.setdefault(product['name'][:3], []).append(product)
            inventory['products_by_platform'] = grouped
            inventory['request_signature'] = signature
            inventory['status'] = 'completed'
        elif inventory.get('request_signature') != signature:
            raise ValueError(f'{output} contains an inventory for a different request')
    else:
        inventory = {
            'source': 'Copernicus Data Space Ecosystem OData product catalogue',
            'request_signature': signature,
            'requested_start_utc': start,
            'requested_end_exclusive_utc': end,
            'platforms': platforms,
            'status': 'running',
            'products_by_platform': {},
            'limitations': [
                'Catalogue discovery is public; product download requires authenticated CDSE access.',
                'AUX_PROQUA coverage is for the listed Sentinel missions only, not all cataloged spacecraft.',
                'Only currently online catalogue products are included.',
            ],
        }

    completed = inventory['products_by_platform']
    for platform in platforms:
        if platform in completed:
            continue
        products = list_products(start, end, [platform])
        completed[platform] = [
            {
                'id': product.get('Id'),
                'name': product.get('Name'),
                'content_date': product.get('ContentDate'),
                'content_length': product.get('ContentLength'),
            }
            for product in products
        ]
        inventory.update({
            'status': 'running',
            'catalogued_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'completed_platforms': sorted(completed),
            'product_count': sum(map(len, completed.values())),
        })
        temp = output.with_suffix(output.suffix + '.tmp')
        temp.write_text(json.dumps(inventory, indent=2) + '\n')
        temp.replace(output)
        print(f'{platform}: {len(products):,} online products', flush=True)

    products = [product for rows in completed.values() for product in rows]
    by_platform = collections.Counter(product['name'][:3] for product in products)
    by_platform_year = collections.Counter(
        (product['name'][:3], str(product.get('content_date', {}).get('Start', ''))[:4])
        for product in products
    )
    inventory.update({
        'status': 'completed',
        'catalogued_utc': inventory.get('catalogued_utc', dt.datetime.now(dt.timezone.utc).isoformat()),
        'completed_platforms': sorted(completed),
        'product_count': len(products),
        'counts_by_platform': dict(sorted(by_platform.items())),
        'counts_by_platform_year': {
            f'{platform}:{year}': count
            for (platform, year), count in sorted(by_platform_year.items())
        },
    })
    temp = output.with_suffix(output.suffix + '.tmp')
    temp.write_text(json.dumps(inventory, indent=2) + '\n')
    temp.replace(output)
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2022-10-09T00:00:00Z')
    parser.add_argument('--end', default='2026-10-10T00:00:00Z', help='exclusive UTC end')
    parser.add_argument('--platforms', nargs='+', choices=sorted(PLATFORM_NORAD),
                        default=sorted(PLATFORM_NORAD))
    parser.add_argument('--output', default=str(ROOT / 'data/attitude/sentinel_quaternions/catalog_inventory.json'))
    args = parser.parse_args()
    result = write_inventory(args.output, args.start, args.end, sorted(set(args.platforms)))
    print(json.dumps({
        'status': result['status'],
        'catalogued_utc': result['catalogued_utc'],
        'product_count': result['product_count'],
        'counts_by_platform': result['counts_by_platform'],
        'output': str(pathlib.Path(args.output).expanduser().resolve()),
    }, indent=2))


if __name__ == '__main__':
    main()
