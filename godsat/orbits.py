"""Historical SGP4 replay and AWP numerical propagation adapters."""
import datetime as dt
import importlib
import hashlib
import math
import os
import pathlib
import sys
import numpy as np
import duckdb
from sgp4.api import Satrec, SatrecArray, WGS72, jday

ROOT = pathlib.Path(__file__).resolve().parents[1]
EARTH_RADIUS = 6378.135
EARTH_MU = 398600.4418
# IERS Conventions (2010), Table 1.1. The vendored AWP table rounds Earth's
# mass and consequently derives an inconsistent GM (398589.196 km^3/s^2).
# TLEs are initialized with WGS-72 SGP4, but the numerical force model should
# use physical Earth constants rather than that rounded teaching-example data.
AWP_EARTH_CONSTANTS = {
    'mu': 398600.4418,
    'radius': 6378.1366,
    'J2': 1.0826359e-3,
}

def utc(value):
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Date must include UTC offset or Z')
    return value.astimezone(dt.timezone.utc)

def julian(value):
    return jday(value.year, value.month, value.day, value.hour, value.minute,
                value.second + value.microsecond / 1e6)

def teme_to_gcrs(state, when):
    """Transform a six-element TEME state to geocentric celestial axes.

    AWP's Earth-centered integrator assumes an inertial J2000-like orientation.
    SGP4 returns TEME, whose axes can differ materially over a geocentric radius;
    explicitly rotate position and velocity before comparing the propagators.
    Astropy's frame transform also handles the velocity differential.
    """
    import astropy.units as units
    from astropy.coordinates import CartesianDifferential, CartesianRepresentation, GCRS, TEME
    from astropy.time import Time

    instant = utc(when)
    epoch = Time(instant)
    values = np.asarray(state, dtype=float)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise ValueError('TEME state must contain six finite position/velocity values')
    representation = CartesianRepresentation(
        values[:3] * units.km,
        differentials=CartesianDifferential(values[3:] * units.km / units.s),
    )
    transformed = TEME(representation, obstime=epoch).transform_to(GCRS(obstime=epoch))
    position = transformed.cartesian.xyz.to_value(units.km)
    velocity = transformed.velocity.d_xyz.to_value(units.km / units.s)
    return np.concatenate((position, velocity))

def frame_transform_provenance():
    """Return software and Earth-orientation provenance for TEME/GCRS transforms."""
    import astropy
    from astropy.utils import iers

    table = iers.earth_orientation_table.get()
    data_path = pathlib.Path(table.meta.get('data_path', ''))
    digest = None
    if data_path.is_file():
        hasher = hashlib.sha256()
        with data_path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
        digest = hasher.hexdigest()
    return {
        'library': 'Astropy',
        'library_version': astropy.__version__,
        'source_frame': 'TEME',
        'target_frame': 'GCRS',
        'earth_orientation_table': type(table).__name__,
        'earth_orientation_data_url': table.meta.get('data_url'),
        'earth_orientation_predictive_mjd': table.meta.get('predictive_mjd'),
        'earth_orientation_data_sha256': digest,
    }

def satellite(row):
    jd, fr = julian(utc(row['epoch']))
    s = Satrec()
    s.sgp4init(WGS72, 'i', int(row['norad_id']), jd + fr - 2433281.5,
              float(row['bstar']), float(row['mean_motion_dot']) * 2 * math.pi / 1440**2,
              0., float(row['eccentricity']), math.radians(row['arg_perigee']),
              math.radians(row['inclination']), math.radians(row['mean_anomaly']),
              row['mean_motion'] * 2 * math.pi / 1440, math.radians(row['raan']))
    return s

def orbit_regime(row):
    """Classify an element set by mean orbit, with HEO taking precedence.

    Boundaries are pragmatic scenario bins, not official catalog categories.
    """
    e=float(row['eccentricity']); n=float(row['mean_motion'])*2*math.pi/86400
    if n<=0 or not math.isfinite(n): return 'unknown'
    a=(EARTH_MU/n**2)**(1/3); altitude=a-EARTH_RADIUS
    apogee=a*(1+e)-EARTH_RADIUS
    if e>=.25 and apogee>2000: return 'heo'
    if 33786<=altitude<=37786 and e<.25: return 'geo'
    if 2000<=altitude<33786: return 'meo'
    if altitude<2000 and apogee<2000: return 'leo'
    return 'other'

class History:
    def __init__(self, root=ROOT, cohort='current_payload', window=None,
                 max_age_hours=72):
        self.root = pathlib.Path(root)
        if cohort not in {'current_payload', 'current_active_payload', 'iridium_next', 'all'}:
            raise ValueError('cohort must be current_payload, current_active_payload, iridium_next, or all')
        self.cohort = cohort
        if cohort == 'current_payload':
            self.paths = [self.root / 'data/current_payload_orbit_history.parquet']
        elif cohort == 'current_active_payload':
            self.paths = [self.root / 'data/current_active_payload_orbit_history.parquet']
        elif cohort == 'iridium_next':
            self.paths = [self.root / 'data/iridium_next_orbit_history.parquet']
        else:
            raw = self.root / 'data/raw'
            available = sorted(raw.glob('tle_*.parquet'))
            if window is not None:
                lower, upper = map(utc, window)
                if lower > upper:
                    raise ValueError('history window start must not follow its end')
                if max_age_hours < 0:
                    raise ValueError('max_age_hours must be nonnegative')
                lower -= dt.timedelta(hours=max_age_hours)
                available = [path for path in available
                    if lower.year <= int(path.stem.rsplit('_', 1)[1]) <= upper.year]
            self.paths = available
        if cohort in {'current_payload', 'current_active_payload', 'iridium_next'} and not self.paths[0].exists():
            script = {'current_payload': 'data/export_current.py', 'current_active_payload': 'data/export_current_active_payload_history.py',
                      'iridium_next': 'data/prepare_iridium_next_cohort.py'}[cohort]
            raise FileNotFoundError(f'Run scripts/{script} first')
        if cohort == 'all' and not self.paths:
            raise FileNotFoundError('Historical TLE/OMM archives are missing')
        self.db = duckdb.connect()
        self.db.execute("SET TimeZone='UTC'")
        self.db.execute("SET threads=2")
        self.db.execute("SET memory_limit='1GB'")
        # Keep paths explicit and ordered. A bounded history window avoids
        # opening every annual archive for short trajectory requests.
        parquet_paths = [str(path) for path in self.paths]
        source = (self.db.read_parquet(parquet_paths[0]) if len(parquet_paths) == 1
                  else self.db.read_parquet(parquet_paths))
        source.create_view('history')

    def records(self, start, end, max_age=72, ids=None):
        start, end = utc(start), utc(end)
        query = 'SELECT * FROM history WHERE epoch BETWEEN ? AND ?'
        args = [start-dt.timedelta(hours=max_age), end]
        if ids is not None:
            query += ' AND norad_id IN (SELECT unnest(?))'
            args.append(list(map(int, ids)))
        # Some public archives repeat an object/epoch with slightly different
        # float32 elements. Stable tie-breaks keep replay deterministic.
        result = self.db.execute(query+' ORDER BY norad_id, epoch, inclination, raan, '
            'eccentricity, arg_perigee, mean_anomaly, mean_motion, mean_motion_dot, bstar', args)
        cols = [c[0] for c in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]

    def snapshot(self, date, max_age=72):
        date=utc(date)
        result=self.db.execute('''SELECT * FROM history WHERE epoch BETWEEN ? AND ?
            QUALIFY row_number() OVER (PARTITION BY norad_id ORDER BY epoch DESC,
                inclination DESC, raan DESC, eccentricity DESC, arg_perigee DESC,
                mean_anomaly DESC, mean_motion DESC, mean_motion_dot DESC, bstar DESC)=1
            ORDER BY norad_id''', [date-dt.timedelta(hours=max_age),date])
        cols=[c[0] for c in result.description]
        return [dict(zip(cols,r)) for r in result.fetchall()]

    def replay(self, ids, times, max_age=72, grouped_records=None):
        times=[utc(t) for t in times]
        if grouped_records is None:
            rows=self.records(times[0],times[-1],max_age,ids)
            grouped={int(i):[] for i in ids}
            for r in rows: grouped[r['norad_id']].append(r)
        else:
            grouped=grouped_records
        states=np.full((len(times),len(ids),6),np.nan)
        ages=np.full((len(times),len(ids)),np.inf)
        errors=np.full((len(times),len(ids)),-1,dtype=np.int16)
        source_epochs=np.full((len(times),len(ids)),'',dtype='U40')
        pointers=np.full(len(ids),-1,dtype=np.int64)
        active_satellites=[None]*len(ids)
        time_julians=[julian(t) for t in times]
        for ti,t in enumerate(times):
            active_indices=[]
            active_satrecs=[]
            for k,oid in enumerate(ids):
                records=grouped[int(oid)]
                j=int(pointers[k])
                while j+1<len(records) and records[j+1]['epoch']<=t:
                    j+=1
                    active_satellites[k]=satellite(records[j])
                pointers[k]=j
                if j<0: continue
                age=(t-records[j]['epoch']).total_seconds()/3600
                ages[ti,k]=age; source_epochs[ti,k]=records[j]['epoch'].isoformat()
                if age>max_age: continue
                active_indices.append(k)
                active_satrecs.append(active_satellites[k])
            if not active_indices:
                continue
            jd,fr=time_julians[ti]
            errors_batch,positions,velocities=SatrecArray(active_satrecs).sgp4(
                np.asarray([jd],dtype=np.float64),np.asarray([fr],dtype=np.float64))
            active_indices=np.asarray(active_indices,dtype=np.int64)
            errors_batch=errors_batch[:,0]
            errors[ti,active_indices]=errors_batch
            vectors=np.concatenate((positions[:,0,:],velocities[:,0,:]),axis=1)
            successful=(errors_batch==0)&np.isfinite(vectors).all(axis=1)
            states[ti,active_indices[successful]]=vectors[successful]
        return states,ages,errors,source_epochs

def awp_propagate(state, seconds, times, j2=True, drag=False,
                  area_mass_m2_kg=0.01, drag_coefficient=2.2,
                  third_bodies=False, epoch=None):
    """Call AWP's actual Spacecraft force model with SciPy.

    States are supplied in GCRS/J2000-like inertial axes. Optional solar/lunar
    third-body terms use AWP's SPICE force routine and vendored DE432s kernel.
    This short-window model does not replace historical SGP4 replay.
    """
    from scipy.integrate import solve_ivp
    tools=ROOT/'vendor/AWP/src/python_tools'
    if not tools.exists(): raise FileNotFoundError('AWP checkout is missing')
    if str(tools) not in sys.path: sys.path.insert(0,str(tools))
    cls=importlib.import_module('Spacecraft').Spacecraft
    pd=importlib.import_module('planetary_data')
    # Deliberately avoid the constructor, which loads time/SPICE kernels and
    # chooses its own output grid. All force computations are upstream methods.
    obj=cls.__new__(cls); obj.cb={**pd.earth, **AWP_EARTH_CONSTANTS};obj.et0=0.
    obj.orbit_perts_funcs=[obj.calc_J2] if j2 else []
    spice=None;spice_kernel_paths=[]
    if third_bodies:
        if epoch is None:
            raise ValueError('epoch is required when solar/lunar third-body gravity is enabled')
        spice=importlib.import_module('spiceypy')
        # Large SPICE kernels are often stored outside the synchronized
        # workspace (for example, on iCloud-managed checkouts). Allow an
        # explicit kernel directory while keeping the vendored AWP default.
        spice_data=pathlib.Path(os.environ.get(
            'GODSAT_SPICE_DATA_DIR', ROOT/'vendor/AWP/data/spice'))
        for kernel in (spice_data/'lsk/naif0012.tls',spice_data/'spk/de432s.bsp'):
            spice.furnsh(str(kernel));spice_kernel_paths.append(str(kernel))
        obj.et0=spice.str2et(utc(epoch).strftime('%Y-%m-%dT%H:%M:%S.%f'))
        # AWP's Moon table has a copied Earth mass/GM. Override the GM with the
        # standard lunar value rather than passing its erroneous table entry.
        sun={**pd.sun,'mu':1.3271244004193938e11}
        moon={**pd.moon,'mu':4.902800066e3}
        obj.config={'frame':'J2000','orbit_perts':{'n_bodies':[sun,moon]}}
        obj.orbit_perts_funcs.append(obj.calc_n_bodies)
    if drag:
        if area_mass_m2_kg<=0 or drag_coefficient<=0:
            raise ValueError('area_mass_m2_kg and drag_coefficient must be positive')
        # Log-linear approximation to a standard quiet-atmosphere density table.
        # It is suitable for model sensitivity, not operational orbit prediction.
        altitudes=np.array([100,150,200,250,300,350,400,450,500,600,700,800,900,1000],float)
        densities=np.array([5.604e-7,2.070e-9,2.789e-10,7.248e-11,2.418e-11,
            9.518e-12,3.725e-12,1.585e-12,6.967e-13,1.454e-13,3.614e-14,
            1.170e-14,5.245e-15,3.019e-15])
        omega_earth=7.2921150e-5
        def calc_drag(et,state):
            r=np.asarray(state[:3],float);radius=np.linalg.norm(r);altitude=radius-obj.cb['radius']
            if altitude<100 or altitude>1000:return np.zeros(3)
            rho=float(np.exp(np.interp(altitude,altitudes,np.log(densities))))
            v_relative=np.asarray(state[3:6],float)*1000.-np.cross([0.,0.,omega_earth],r*1000.)
            speed=np.linalg.norm(v_relative)
            return -0.5*drag_coefficient*area_mass_m2_kg*rho*speed*v_relative/1000.
        obj.orbit_perts_funcs.append(calc_drag)
    y=np.r_[np.asarray(state,float),0.]
    try:
        solution=solve_ivp(obj.diffy_q,(0.,float(seconds)),y,t_eval=np.asarray(times),
                           method='DOP853',rtol=1e-10,atol=1e-10)
    finally:
        for kernel in reversed(spice_kernel_paths):
            spice.unload(kernel)
    if not solution.success: raise RuntimeError(solution.message)
    return solution.y[:6].T
