"""Explicit, offline NRLMSIS inputs and neutral-density evaluation."""
import csv
import datetime as dt
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
from .environment import utc


class SpaceWeather:
    """Named CelesTrak CSV columns; no index-based parsing or implicit filling."""
    def __init__(self,path):
        path=Path(path)
        raw=path.read_bytes()
        if len(raw)>16*1024*1024:raise ValueError('Space-weather input exceeds 16 MiB')
        with path.open(newline='') as stream:
            records=list(csv.DictReader(stream))
        self.rows={r['DATE']:r for r in records}
        if len(self.rows)!=len(records):raise ValueError('Duplicate dates in space-weather input')
        self.metadata={'name':path.name,'sha256':hashlib.sha256(raw).hexdigest(),
            'reference':'https://celestrak.org/SpaceData/SpaceWx-format.php',
            'semantics':'Previous-day observed-distance F10.7; current centered 81-day average; explicit seven-element Ap history.',
            'limits':'Centered averages and current/future rows may include estimates or predictions; flux qualifiers are retained. The CSV does not supply a separate provenance flag for each Ap bin.'}
        sidecar=path.with_suffix('.source.json')
        if sidecar.is_file():
            provenance=json.loads(sidecar.read_text())
            if provenance.get('sha256')!=self.metadata['sha256']:raise ValueError('Space-weather provenance does not match file hash')
            self.metadata['download']=provenance
        self.used={}

    def number(self,date,column):
        row=self.rows.get(date.isoformat())
        if row is None:raise ValueError(f'Missing space-weather day {date}')
        try:value=float(row[column])
        except (KeyError,ValueError,TypeError) as exc:raise ValueError(f'Missing space-weather {date} {column}') from exc
        if not np.isfinite(value) or value<0:raise ValueError(f'Invalid space-weather {date} {column}')
        return value

    def at(self,when):
        when=utc(when.isoformat() if hasattr(when,'isoformat') else when)
        day=when.date();hour=when.hour//3*3;key=f'{day}T{hour:02d}:00:00Z'
        if key in self.used:return self.used[key]
        previous=day-dt.timedelta(days=1)
        f107=self.number(previous,'F10.7_OBS');f107a=self.number(day,'F10.7_OBS_CENTER81')
        if not 0<f107<=400 or not 0<f107a<=400:raise ValueError('F10.7 outside the supported model-driver range (0,400] sfu')
        anchor=dt.datetime.combine(day,dt.time(hour),dt.timezone.utc)
        def ap(offset):
            instant=anchor-dt.timedelta(hours=offset)
            return self.number(instant.date(),f'AP{instant.hour//3+1}')
        aps=[self.number(day,'AP_AVG'),ap(0),ap(3),ap(6),ap(9),
             float(np.mean([ap(h) for h in range(12,34,3)])),float(np.mean([ap(h) for h in range(36,58,3)]))]
        value={'time_bin_utc':key,'f107_sfu':f107,'f107a_sfu':f107a,'aps':aps,
               'previous_flux_qualifier':self.rows[previous.isoformat()].get('F10.7_DATA_TYPE'),
               'current_flux_qualifier':self.rows[day.isoformat()].get('F10.7_DATA_TYPE')}
        self.used[key]=value;return value

    def provenance(self):
        return {**self.metadata,'used_bins':list(self.used.values())}


class MsisAtmosphere:
    def __init__(self,drivers,ap_mode='history'):
        if ap_mode not in {'history','daily'}:raise ValueError('Ap mode must be history or daily')
        self.drivers=drivers;self.ap_mode=ap_mode

    def geodetic(self,when,longitude,latitude,altitude_km):
        import pymsis
        when=utc(when.isoformat() if hasattr(when,'isoformat') else when)
        longitude,latitude,altitude=np.broadcast_arrays(longitude,latitude,altitude_km)
        if not np.isfinite(altitude).all() or np.any((altitude<0)|(altitude>1000)):
            raise ValueError('NRLMSIS adapter requires 0–1,000 km geodetic altitude')
        n=altitude.size;values=self.drivers.at(when)
        stamp=np.datetime64(when.astimezone(dt.timezone.utc).replace(tzinfo=None),'us')
        # Equal-length arrays select fly-through mode; never broadcast an N^4 grid.
        result=pymsis.calculate(np.full(n,stamp),longitude.ravel(),latitude.ravel(),altitude.ravel(),
            f107s=np.full(n,values['f107_sfu']),f107as=np.full(n,values['f107a_sfu']),
            aps=np.tile(values['aps'],(n,1)),version='2.1',geomagnetic_activity=-1 if self.ap_mode=='history' else 1)
        density=np.asarray(result[:,pymsis.Variable.MASS_DENSITY],dtype=float).reshape(altitude.shape)
        if not np.isfinite(density).all() or np.any(density<0):raise ValueError('NRLMSIS returned unavailable density')
        return density

    def density(self,when,position_itrs_km):
        import astropy.units as u
        from astropy.coordinates import EarthLocation
        location=EarthLocation.from_geocentric(*np.asarray(position_itrs_km).T*u.km)
        return self.geodetic(when,location.lon.deg,location.lat.deg,location.height.to_value(u.km))

    def provenance(self):
        import pymsis
        folder=Path(pymsis.__file__).parent
        return {'model':'NRLMSIS 2.1','implementation':'pymsis','version':importlib.metadata.version('pymsis'),
            'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'ap_mode':self.ap_mode,'parameter_sha256':hashlib.sha256((folder/'msis21.parm').read_bytes()).hexdigest(),
            'drivers':self.drivers.provenance(),
            'limits':'Empirical neutral atmosphere, not measured density. No implicit drivers or downloads. Model errors are not solver error estimates.'}
