"""Cache and audit the official IERS finals2000A Earth-orientation series."""
import datetime as dt
import hashlib
import json
import pathlib
import urllib.request

from astropy.utils.iers import IERS_A

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/ground_sensor/ilrs_lageos1_npt/ancillary'
URL = 'https://maia.usno.navy.mil/ser7/finals2000A.all'
OUT = DATA / 'finals2000A.all'
MANIFEST = DATA / 'eop_manifest.json'


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(URL, headers={'User-Agent': 'GoDSAT-research/1.0'})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    tmp = OUT.with_suffix('.all.tmp')
    tmp.write_bytes(raw)
    table = IERS_A.open(str(tmp))
    if len(table) < 1000:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f'Unexpectedly short Earth-orientation archive: {len(table)} rows')
    tmp.replace(OUT)
    sha = hashlib.sha256(raw).hexdigest()
    first_date = (dt.datetime(1858, 11, 17) +
                  dt.timedelta(days=float(table['MJD'][0].to_value('d')))).date()
    last_date = (dt.datetime(1858, 11, 17) +
                 dt.timedelta(days=float(table['MJD'][-1].to_value('d')))).date()
    manifest = {'status': 'completed', 'source': 'USNO/IERS Bulletin A finals2000A series',
        'url': URL, 'path': str(OUT.relative_to(ROOT)), 'downloaded_utc':
            dt.datetime.fromtimestamp(OUT.stat().st_mtime, dt.timezone.utc).isoformat(),
        'bytes': len(raw), 'sha256': sha, 'rows': len(table),
        'first_mjd': float(table['MJD'][0].to_value('d')),
        'last_mjd': float(table['MJD'][-1].to_value('d')),
        'first_date': first_date.isoformat(), 'last_date': last_date.isoformat(),
        'intended_use': 'TEME-to-ITRS transformations; interpolate UT1-UTC and polar motion from IERS EOP.',
        'limitations': ['Recent Bulletin A values may be rapid estimates or predictions; each row retains its IERS flags.',
            'Not a substitute for an analysis-grade EOP series when assessing millimeter-level geodesy.']}
    MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
