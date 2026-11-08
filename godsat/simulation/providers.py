"""Reproducible adapters for external environmental products.

No external data is fetched during playback. Raw downloads are kept alongside
normalized files, with hashes and source semantics, for offline reproduction.
"""
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import urllib.parse
import urllib.request

from .environment import SCHEMA, utc, finite, validate_environment


def download(url, destination, limit=16*1024*1024):
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('Source must use HTTPS')
    request = urllib.request.Request(url, headers={'User-Agent': 'GoDSAT-research/0.2'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if urllib.parse.urlsplit(response.url).scheme != 'https':
            raise ValueError('Source must remain HTTPS')
        raw = response.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Source exceeds bounded download size')
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Path(destination).write_bytes(raw)
    return raw, {'url': url, 'retrieved_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def write_bundle(bundle, output):
    validate_environment(bundle)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, allow_nan=False, indent=2)+'\n')


def validate_hold(seconds):
    if not finite(seconds) or not 0 <= seconds <= 86400:
        raise ValueError('Explicit sample hold must be between 0 and 86,400 seconds')


def weather_bundle(value, source, hold_seconds=0):
    """Normalize Open-Meteo current *model* values, not weather observations."""
    validate_hold(hold_seconds)
    current = value['current']
    units = value['current_units']
    expected = {'temperature_2m': '°C', 'surface_pressure': 'hPa', 'cloud_cover': '%'}
    if any(units.get(k) != unit for k, unit in expected.items()) or value.get('utc_offset_seconds') != 0:
        raise ValueError('Weather input must use documented Celsius, hPa, percent and UTC units')
    when = utc(current['time']+'Z' if len(current['time']) in (16,19) else current['time'])
    sample = {'source_id': 'open-meteo', 'time_utc': when.isoformat(),
              'valid_until_utc': (when+dt.timedelta(seconds=hold_seconds)).isoformat(),
              'latitude_deg': value['latitude'], 'longitude_deg': value['longitude'],
              'altitude_km': value['elevation']/1000}
    surface = {}
    if current.get('surface_pressure') is not None:
        surface['pressure_pa'] = current['surface_pressure']*100
    if current.get('cloud_cover') is not None:
        surface['cloud_fraction'] = current['cloud_cover']/100
    samples = [{**sample,'values':surface}] if surface else []
    if current.get('temperature_2m') is not None:
        samples.append({**sample,'altitude_km':sample['altitude_km']+.002,
                        'values':{'temperature_k':current['temperature_2m']+273.15}})
    return validate_environment({'schema':SCHEMA,'sources':[{
        'id':'open-meteo','name':'Open-Meteo current weather model output','kind':'modeled',
        'vertical_datum':'mean_sea_level',
        'reference':'https://open-meteo.com/en/docs','input':source,
        'temporal_policy':f'Explicit zero-order hold of instantaneous model sample for {hold_seconds:g} seconds; not independently established validity',
        'limits':'Grid-cell model values; no station observations. Total cloud fraction is a column quantity located at the surface, not a cloud height.'}], 'samples':samples})


def fetch_weather(latitude, longitude, output, hold_seconds=0, time_utc=None):
    if not finite(latitude) or not finite(longitude) or not -90<=latitude<=90 or not -180<=longitude<=180:
        raise ValueError('Invalid weather coordinates')
    parameters={'latitude':latitude,'longitude':longitude,'timezone':'UTC'}
    if time_utc is None:parameters['current']='temperature_2m,surface_pressure,cloud_cover'
    else:
        requested=utc(time_utc)
        parameters.update(hourly='temperature_2m,surface_pressure,cloud_cover',start_date=requested.date().isoformat(),end_date=requested.date().isoformat())
    query=urllib.parse.urlencode(parameters)
    raw, source=download('https://api.open-meteo.com/v1/forecast?'+query,Path(output).with_suffix('.raw.json'))
    value=json.loads(raw)
    if time_utc is not None:
        times=[utc(t+'Z') for t in value['hourly']['time']]
        eligible=[i for i,t in enumerate(times) if t<=requested]
        if not eligible:raise ValueError('No hourly weather value at or before requested time')
        i=eligible[-1]
        if (requested-times[i]).total_seconds()>=3600:raise ValueError('Hourly weather coverage gap')
        value['current_units']=value['hourly_units']
        value['current']={k:v[i] for k,v in value['hourly'].items()}
    bundle=weather_bundle(value,source,hold_seconds)
    if time_utc is not None:
        bundle['sources'][0]['name']='Open-Meteo hourly weather model output'
        bundle['sources'][0]['requested_time_utc']=requested.isoformat()
    write_bundle(bundle,output)
    return bundle


def glotec_bundle(value, source, hold_seconds=0):
    """Normalize NOAA assimilative TEC columns and F2 peak electron density."""
    validate_hold(hold_seconds)
    variables=value.get('metadata',{}).get('variables',{})
    if value.get('type')!='FeatureCollection' or variables.get('tec',{}).get('units')!='TECU' or variables.get('hmF2',{}).get('units')!='km' or variables.get('NmF2',{}).get('units')!='el/m^3':
        raise ValueError('Unsupported GloTEC geometry or units')
    when=utc(value['time_tag']); until=(when+dt.timedelta(seconds=hold_seconds)).isoformat()
    samples=[]; missing=0; quality_counts={}
    for feature in value['features']:
        if feature.get('geometry',{}).get('type')!='Point': raise ValueError('GloTEC requires point grid geometry')
        lon,lat=feature['geometry']['coordinates']; p=feature['properties']; quality=p.get('quality_flag')
        quality_counts[str(quality)]=quality_counts.get(str(quality),0)+1
        common={'source_id':'glotec','time_utc':when.isoformat(),'valid_until_utc':until,
                'latitude_deg':lat,'longitude_deg':lon,'quality_flag':quality}
        tec=p.get('tec')
        if finite(tec) and tec>=0:
            samples.append({**common,'altitude_km':0,'support':'vertical column','values':{'vertical_tec_tecu':tec}})
        else: missing+=1
        density,height=p.get('NmF2'),p.get('hmF2')
        if finite(density) and density>=0 and finite(height) and 0<=height<=2000:
            samples.append({**common,'altitude_km':height,'support':'F2 peak','values':{'electron_density_m3':density}})
        else: missing+=1
    return validate_environment({'schema':SCHEMA,'sources':[{'id':'glotec','name':'NOAA GloTEC assimilative ionosphere',
        'kind':'modeled','reference':'https://www.spaceweather.gov/products/glotec','input':source,
        'product_time_utc':when.isoformat(),'quality_flag_counts':quality_counts,'missing_values':missing,'column_top_km':8500,
        'grid_spacing_deg':{'latitude':2.5,'longitude':5.0},
        'temporal_policy':f'Explicit sample hold of {hold_seconds:g} seconds; no temporal interpolation',
        'limits':'Assimilative model estimates, not direct point observations. TEC is a column plotted at ground coordinates; NmF2 is located at the modeled hmF2 altitude. Quality flag 0 can be background-dominated.'}], 'samples':samples})


def fetch_glotec(output, hold_seconds=0):
    output=Path(output)
    raw,index_source=download('https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt.json',output.with_suffix('.index.raw.json'))
    index=json.loads(raw)
    if not isinstance(index,list) or not index: raise ValueError('GloTEC index is empty')
    latest=max(index,key=lambda row:utc(row['time_tag']))
    path=latest['url']
    if not path.startswith('/products/glotec/geojson_2d_urt/') or '..' in path or '?' in path or '#' in path:
        raise ValueError('Unexpected GloTEC product path')
    raw,source=download('https://services.swpc.noaa.gov'+path,output.with_suffix('.raw.geojson'))
    source['index']=index_source
    value=json.loads(raw)
    if utc(value['time_tag'])!=utc(latest['time_tag']): raise ValueError('GloTEC index/product time mismatch')
    bundle=glotec_bundle(value,source,hold_seconds)
    write_bundle(bundle,output)
    return bundle


def igrf_bundle(points, time_utc, hold_seconds=0):
    """IGRF-14 internal main field at WGS84 geodetic locations, output ENU nT."""
    import numpy as np
    import ppigrf
    import ppigrf.ppigrf as implementation
    validate_hold(hold_seconds)
    when=utc(time_utc)
    if not dt.datetime(1900,1,1,tzinfo=dt.timezone.utc) <= when < dt.datetime(2030,1,1,tzinfo=dt.timezone.utc):
        raise ValueError('IGRF-14 adapter supports 1900 <= epoch < 2030; refuses extrapolation')
    if not isinstance(points,list) or not 0<len(points)<=20000:
        raise ValueError('IGRF requires 1–20,000 geodetic points')
    for p in points:
        for key,lower,upper in [('latitude_deg',-90,90),('longitude_deg',-180,180),('altitude_km',0,2000)]:
            if not finite(p.get(key)) or not lower<=p[key]<=upper:
                raise ValueError(f'Invalid IGRF {key}; adapter altitude is restricted to 0–2,000 km')
    coefficient=Path(implementation.__file__).with_name('IGRF14.shc')
    # Select coefficients explicitly, even if a future library changes its default.
    east,north,up=ppigrf.igrf(np.array([p['longitude_deg'] for p in points]),
        np.array([p['latitude_deg'] for p in points]),np.array([p['altitude_km'] for p in points]),
        when.replace(tzinfo=None),coeff_fn=str(coefficient))
    samples=[]
    for j,p in enumerate(points):
        samples.append({**p,'source_id':'igrf14','time_utc':when.isoformat(),
            'valid_until_utc':(when+dt.timedelta(seconds=hold_seconds)).isoformat(),
            'values':{'magnetic_east_nt':float(east[0,j]),'magnetic_north_nt':float(north[0,j]),'magnetic_up_nt':float(up[0,j])}})
    return validate_environment({'schema':SCHEMA,'sources':[{'id':'igrf14','name':'IGRF-14 internal main magnetic field',
        'kind':'modeled','reference':'https://www.ncei.noaa.gov/products/international-geomagnetic-reference-field',
        'implementation':'ppigrf','version':importlib.metadata.version('ppigrf'),
        'coefficients_sha256':hashlib.sha256(coefficient.read_bytes()).hexdigest(),
        'coordinate_system':'WGS84 geodetic input; local east/north/up components in nT',
        'temporal_policy':f'Explicit sample hold of {hold_seconds:g} seconds',
        'limits':'Internal main field only; excludes external storm fields, small-scale crustal anomalies and ionospheric currents. Restricted to 0–2,000 km in this adapter.'}], 'samples':samples})


def ionex_bundle(path, hold_seconds=0):
    """Read IONEX 1.x 2-D TEC maps; no interpolation and no missing-value fill."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation
    validate_hold(hold_seconds)
    path=Path(path)
    if path.stat().st_size>32*1024*1024:
        raise ValueError('IONEX input exceeds 32 MiB')
    raw=path.read_bytes(); lines=raw.decode('ascii').splitlines()
    exponent=-1; base_radius=6371.; dimension=None; samples=[]; missing=0
    in_header=True; in_tec=False; epoch=None; i=0; version=None
    while i<len(lines):
        line=lines[i]; i+=1; label=line[60:].strip(); value=line[:60]
        if label=='IONEX VERSION / TYPE': version=float(value[:8])
        elif label=='MAP DIMENSION': dimension=int(value)
        elif label=='BASE RADIUS': base_radius=float(value)
        elif label=='EXPONENT': exponent=int(value)
        elif label=='END OF HEADER':
            if version is None or not 1<=version<2 or dimension!=2:
                raise ValueError('Only explicitly declared IONEX 1.x two-dimensional TEC maps are supported')
            if not 6000<=base_radius<=6500 or not -6<=exponent<=6:
                raise ValueError('Invalid IONEX base radius or exponent')
            in_header=False
        elif not in_header and label=='START OF TEC MAP': in_tec=True; epoch=None
        elif label=='END OF TEC MAP': in_tec=False
        elif in_tec and label=='EPOCH OF CURRENT MAP':
            parts=list(map(int,value.split()))
            epoch=dt.datetime(*parts,tzinfo=dt.timezone.utc)
        elif in_tec and label=='LAT/LON1/LON2/DLON/H':
            if epoch is None: raise ValueError('IONEX row precedes map epoch')
            lat,lo,hi,step,height=map(float,value.split())
            if step==0 or (hi-lo)/step<0 or not -90<=lat<=90 or not 0<=height<=2000:
                raise ValueError('Invalid IONEX grid coordinates')
            count=round((hi-lo)/step)+1
            if count<1 or count>10000 or abs((count-1)*step-(hi-lo))>1e-6:
                raise ValueError('Invalid IONEX longitude span')
            values=[]
            while len(values)<count and i<len(lines):
                values.extend(int(lines[i][c:c+5]) for c in range(0,len(lines[i]),5) if lines[i][c:c+5].strip())
                i+=1
            if len(values)!=count: raise ValueError('IONEX row has incorrect value count')
            for j,raw_value in enumerate(values):
                if raw_value==9999: missing+=1; continue
                if raw_value<0: raise ValueError('Negative TEC unsupported')
                longitude=(lo+j*step+180)%360-180
                # IONEX latitude is geocentric on a sphere; renderer takes WGS84 geodetic.
                r=(base_radius+height)*1000; phi=math.radians(lat); lam=math.radians(longitude)
                location=EarthLocation.from_geocentric(r*math.cos(phi)*math.cos(lam)*u.m,r*math.cos(phi)*math.sin(lam)*u.m,r*math.sin(phi)*u.m)
                samples.append({'source_id':'ionex','time_utc':epoch.isoformat(),
                    'valid_until_utc':(epoch+dt.timedelta(seconds=hold_seconds)).isoformat(),
                    'latitude_deg':float(location.lat.deg),'longitude_deg':float(location.lon.deg),
                    'altitude_km':float(location.height.to_value(u.km)),
                    'values':{'vertical_tec_tecu':raw_value*10.**exponent}})
                if len(samples)>100000: raise ValueError('IONEX exceeds normalized sample budget; subset the input')
    if in_header or in_tec or not samples: raise ValueError('Incomplete IONEX or no usable TEC samples')
    return validate_environment({'schema':SCHEMA,'sources':[{'id':'ionex','name':path.name+' TEC maps','kind':'modeled',
        'reference':'https://files.igs.org/pub/data/format/ionex1.pdf','input_sha256':hashlib.sha256(raw).hexdigest(),
        'format':'IONEX 1.x 2D TEC','missing_samples':missing,
        'temporal_policy':f'Explicit sample hold of {hold_seconds:g} seconds; no interpolation',
        'coordinate_conversion':'Geocentric latitude and base radius + map height converted to WGS84 geodetic location',
        'limits':'Estimated TEC maps, not direct point measurements. RMS and height correction maps are not ingested.'}], 'samples':samples})
