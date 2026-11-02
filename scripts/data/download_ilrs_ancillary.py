"""Fetch official ILRS station-frame, eccentricity, and data-handling files."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import hashlib
import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/ground_sensor/ilrs_lageos1_npt/ancillary'
SOURCES = {
    'SLRF2020_POS_VEL_2026-02-05.snx': 'https://ilrs.gsfc.nasa.gov/docs/2026/SLRF2020_POS%2BVEL_2026.02.05.snx',
    'ILRS_station_eccentricities_UNE_2026-05-27.snx': 'https://ilrs.gsfc.nasa.gov/docs/2026/slrecc.260527.ILRS.une.snx',
    'ILRS_Data_Handling_File_2026-05-27.snx': 'https://ilrs.gsfc.nasa.gov/docs/2026/ILRS_Data_Handling_File_20260527.snx',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    files = []
    for name, url in SOURCES.items():
        path = DATA / name
        if path.is_file():
            body = path.read_bytes()
            status = 'cached'
        else:
            request = urllib.request.Request(url, headers={'User-Agent': 'GoDSAT-research/1.0'})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                if response.status != 200:
                    raise RuntimeError(f'{url}: HTTP {response.status}')
            if not body.startswith(b'%=SNX'):
                raise ValueError(f'{url} did not return a SINEX file')
            temp = path.with_suffix(path.suffix + '.tmp')
            temp.write_bytes(body)
            temp.replace(path)
            status = 'downloaded'
        if not body.startswith(b'%=SNX'):
            raise ValueError(f'Invalid cached SINEX file: {path}')
        files.append({'path': str(path.relative_to(ROOT)), 'url': url,
                      'bytes': len(body), 'sha256': sha256(body), 'status': status})
    manifest = {
        'status': 'completed',
        'source': 'International Laser Ranging Service (ILRS), SLRF2020 frame and ancillary files',
        'files': files,
        'not_downloaded': [{
            'description': 'Satellite and station dependent LAGEOS center-of-mass model archive',
            'url': 'https://datos-geodesia.ign.es/SLR/centre_of_mass_models/models/com6.260112.tar.gz',
            'reason': 'The host did not complete a TCP connection from this environment; fetch separately before precision range calibration.'}],
        'limitations': ['The station coordinate and eccentricity files are reference metadata; applying them does not itself transform TEME to ITRS.',
            'Use the ILRS Data Handling File and applicable LAGEOS center-of-mass correction model for precision residuals.']}
    (DATA / 'ancillary_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
