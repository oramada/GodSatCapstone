"""Environmental effects on straight ground-to-space radio paths.

These are explicit first-order propagation estimates, not detections or orbit
forces. Full-column TEC is never silently applied to a satellite inside that
column. Missing fields produce unavailable effects, not zero corrections.
"""
import math
import bisect
import numpy as np
from .environment import finite, utc, ionospheric_group_delay_m

C_M_S=299792458.
EARTH_RADIUS_KM=6371.


def validate_config(value):
    if not isinstance(value,dict) or value.get('schema')!='godsat.ground-links.v1':
        raise ValueError('Expected godsat.ground-links.v1')
    frequency=value.get('frequency_hz')
    if not finite(frequency) or not 1e8<=frequency<=1e11:
        raise ValueError('Ground-link frequency must be 100 MHz–100 GHz')
    stations=value.get('stations')
    if not isinstance(stations,list) or not 1<=len(stations)<=32:
        raise ValueError('Ground links require 1–32 stations')
    ids=set()
    for station in stations:
        if not isinstance(station,dict):raise ValueError('Invalid ground station')
        if not isinstance(station.get('id'),str) or not station['id'] or station['id'] in ids:
            raise ValueError('Ground station IDs must be unique strings')
        ids.add(station['id'])
        if not isinstance(station.get('name'),str) or not station['name']:
            raise ValueError('Ground stations require names')
        if not isinstance(station.get('reference'),str) or not station['reference']:
            raise ValueError('Ground stations require coordinate provenance')
        for field,lo,hi in [('latitude_deg',-90,90),('longitude_deg',-180,180),('altitude_km',-1,10)]:
            if not finite(station.get(field)) or not lo<=station[field]<=hi:
                raise ValueError(f'Invalid station {field}')
        if 'orthometric_height_km' in station and (not finite(station['orthometric_height_km']) or not -1<=station['orthometric_height_km']<=10):
            raise ValueError('Invalid station orthometric height')
    for key,default,lo,hi in [('minimum_elevation_deg',15,5,90),('shell_height_km',450,200,800),
            ('max_tec_distance_km',400,0,1000),('max_weather_distance_km',50,0,100),
            ('max_weather_height_difference_km',.1,0,.25)]:
        v=value.get(key,default)
        if not finite(v) or not lo<=v<=hi: raise ValueError(f'Invalid {key}')
    for key in ['tec_source_id','weather_source_id']:
        if key in value and not isinstance(value[key],str):raise ValueError(f'Invalid {key}')
    if value.get('tec_interpolation','nearest') not in {'nearest','bilinear'}:raise ValueError('Unsupported TEC interpolation')
    return value


def basis(latitude,longitude):
    lat,lon=np.deg2rad([latitude,longitude]);sl,cl=math.sin(lon),math.cos(lon);sp,cp=math.sin(lat),math.cos(lat)
    return np.array([[-sl,cl,0],[-sp*cl,-sp*sl,cp],[cp*cl,cp*sl,sp]])


def great_circle_km(lat,lon,other_lat,other_lon):
    a,b=np.deg2rad([lat,other_lat]);d=np.deg2rad(other_lon-lon)
    cosine=math.sin(a)*math.sin(b)+math.cos(a)*math.cos(b)*math.cos(d)
    return EARTH_RADIUS_KM*math.acos(max(-1.,min(1.,cosine)))


class FieldSamples:
    def __init__(self,bundle):
        self.sources={s['id']:s for s in bundle.get('sources',[])}
        self.rows={}
        for row in bundle.get('samples',[]):
            for field in row['values']:
                self.rows.setdefault(field,[]).append((utc(row['time_utc']),utc(row['valid_until_utc']),row))
        self.tec_grids={}
        for start,end,row in self.rows.get('vertical_tec_tecu',[]):
            key=(row['source_id'],start,end)
            self.tec_grids.setdefault(key,{})[(row['latitude_deg'],(row['longitude_deg']+180)%360-180)]=row

    def bilinear_tec(self,when,lat,lon,max_distance,source_id):
        lon=(lon+180)%360-180
        groups=sorted(self.tec_grids.items(),key=lambda item:item[0][1],reverse=True)
        for (sid,start,end),grid in groups:
            if (source_id is not None and sid!=source_id) or not start<=when<=end:continue
            spacing=self.sources[sid].get('grid_spacing_deg',{})
            if not all(finite(spacing.get(k)) and spacing[k]>0 for k in ['latitude','longitude']):continue
            latitudes=sorted({p[0] for p in grid});longitudes=sorted({p[1] for p in grid})
            if not latitudes[0]<=lat<=latitudes[-1]:continue
            yi=bisect.bisect_left(latitudes,lat)
            low=latitudes[yi] if yi<len(latitudes) and latitudes[yi]==lat else latitudes[yi-1]
            high=latitudes[yi]
            xi=bisect.bisect_left(longitudes,lon)
            if xi<len(longitudes) and longitudes[xi]==lon:left=right=lon
            else:
                left=longitudes[xi-1] if xi>0 else longitudes[-1]-360
                right=longitudes[xi] if xi<len(longitudes) else longitudes[0]+360
            if high!=low and not math.isclose(high-low,spacing['latitude'],abs_tol=1e-6):continue
            if right!=left and not math.isclose(right-left,spacing['longitude'],abs_tol=1e-6):continue
            yw=0 if high==low else (lat-low)/(high-low)
            xw=0 if right==left else (lon-left)/(right-left)
            corners=[];valid=True
            for latitude,wy in [(low,1-yw),(high,yw)]:
                for longitude,wx in [(left,1-xw),(right,xw)]:
                    weight=wy*wx
                    if weight==0:continue
                    longitude=(longitude+180)%360-180;row=grid.get((latitude,longitude))
                    distance=great_circle_km(lat,lon,latitude,longitude)
                    if row is None or distance>max_distance:valid=False;break
                    corners.append({'latitude_deg':latitude,'longitude_deg':longitude,'weight':weight,
                        'vertical_tecu':row['values']['vertical_tec_tecu'],'distance_km':distance,'quality_flag':row.get('quality_flag')})
                if not valid:break
            if not valid or not corners:continue
            value=sum(c['weight']*c['vertical_tecu'] for c in corners)
            return {'sample':{'source_id':sid,'time_utc':start.isoformat(),'values':{'vertical_tec_tecu':value}},
                'source':self.sources[sid],'distance_km':max(c['distance_km'] for c in corners),
                'method':'bilinear within one epoch; no hole filling','corners':corners}
        return None

    def nearest(self,field,when,lat,lon,max_distance,source_id=None,height=None,max_height=None):
        candidates=[]
        for start,end,row in self.rows.get(field,[]):
            if start>when or end<when or field not in row['values']:continue
            if source_id is not None and row['source_id']!=source_id:continue
            if height is not None and abs(row['altitude_km']-height)>max_height:continue
            distance=great_circle_km(lat,lon,row['latitude_deg'],row['longitude_deg'])
            if distance<=max_distance:candidates.append((distance,-start.timestamp(),row))
        if not candidates:return None
        _,_,row=min(candidates,key=lambda r:(r[0],r[1],r[2]['source_id']))
        return {'sample':row,'distance_km':great_circle_km(lat,lon,row['latitude_deg'],row['longitude_deg']),
                'source':self.sources[row['source_id']]}


def dry_zenith_delay_m(pressure_pa,latitude_deg,height_km):
    """Saastamoinen/Davis hydrostatic term, IERS conventions, pressure in Pa."""
    if not finite(pressure_pa) or pressure_pa<=0:raise ValueError('Pressure must be positive')
    return .0022768*(pressure_pa/100)/(1-.00266*math.cos(2*math.radians(latitude_deg))-.00028*height_km)


def faraday_rotation_rad(slant_tec_tecu,parallel_field_t,frequency_hz):
    """First-order thin-shell Faraday integral, uplink propagation direction."""
    if not all(finite(x) for x in [slant_tec_tecu,parallel_field_t,frequency_hz]) or slant_tec_tecu<0 or frequency_hz<=0:
        raise ValueError('Invalid Faraday inputs')
    return 2.36e4*(slant_tec_tecu*1e16)*parallel_field_t/frequency_hz**2


def radio_path(position_itrs_km,station,when,config,fields,magnetic_model=None):
    import astropy.units as u
    from astropy.coordinates import EarthLocation
    result={'elevation_deg':None,'range_km':None,'vacuum_time_ms':None,'dry_slant_delay_m':None,
            'ionosphere_group_delay_m':None,'uplink_faraday_deg':None,'cloud_fraction':None,'inputs':{},'unavailable':{}}
    if position_itrs_km is None:
        result['unavailable']['geometry']='No valid satellite state';return result
    place=EarthLocation.from_geodetic(station['longitude_deg']*u.deg,station['latitude_deg']*u.deg,station['altitude_km']*u.km)
    origin=np.array([x.to_value(u.km) for x in place.geocentric]);p=np.asarray(position_itrs_km,dtype=float)
    delta=p-origin;distance=float(np.linalg.norm(delta))
    if not math.isfinite(distance) or distance<=0:
        result['unavailable']['geometry']='Invalid satellite-station distance';return result
    direction=delta/distance;enu=basis(station['latitude_deg'],station['longitude_deg'])
    elevation=math.degrees(math.asin(float(np.clip(direction@enu[2],-1,1))))
    result.update(elevation_deg=elevation,range_km=distance,vacuum_time_ms=distance*1e6/C_M_S)
    if elevation<config.get('minimum_elevation_deg',15):
        result['unavailable']['geometry']='Below the configured elevation mask';return result
    weather=fields.nearest('pressure_pa',when,station['latitude_deg'],station['longitude_deg'],
        config.get('max_weather_distance_km',50),config.get('weather_source_id'))
    orthometric=station.get('orthometric_height_km')
    datum=weather['source'].get('vertical_datum') if weather else None
    expected_height=orthometric if datum=='mean_sea_level' else station['altitude_km']
    usable_height=weather is not None and orthometric is not None and datum in {'mean_sea_level','ellipsoidal'} and abs(weather['sample']['altitude_km']-expected_height)<=config.get('max_weather_height_difference_km',.1)
    if weather and usable_height and weather['sample']['values']['pressure_pa']>0:
        row=weather['sample'];pressure=row['values']['pressure_pa']
        result['dry_slant_delay_m']=dry_zenith_delay_m(pressure,station['latitude_deg'],orthometric)/math.sin(math.radians(elevation))
        result['inputs']['pressure']={'source_id':row['source_id'],'sample_time':row['time_utc'],
            'distance_km':weather['distance_km'],'height_difference_km':row['altitude_km']-expected_height,'pressure_pa':pressure,'vertical_datum':datum}
    else:result['unavailable']['dry_atmosphere']='No valid nearby pressure sample with a compatible vertical datum and station orthometric height'
    cloud=fields.nearest('cloud_fraction',when,station['latitude_deg'],station['longitude_deg'],
        config.get('max_weather_distance_km',50),config.get('weather_source_id'))
    if cloud:result['cloud_fraction']=cloud['sample']['values']['cloud_fraction']
    # A single shell is a declared approximation, not a reconstruction of a vertical profile.
    shell_radius=EARTH_RADIUS_KM+config.get('shell_height_km',450)
    od=float(origin@direction);discriminant=od*od+shell_radius**2-float(origin@origin)
    if discriminant<=0:
        result['unavailable']['ionosphere']='Path does not reach the ionosphere shell';return result
    along=-od+math.sqrt(discriminant)
    if along>distance:
        result['unavailable']['ionosphere']='Satellite is below the ionosphere shell';return result
    pierce=origin+along*direction
    location=EarthLocation.from_geocentric(*(pierce*u.km))
    lat,lon,height=float(location.lat.deg),float(location.lon.deg),float(location.height.to_value(u.km))
    if config.get('tec_interpolation','nearest')=='bilinear':
        tec=fields.bilinear_tec(when,lat,lon,config.get('max_tec_distance_km',400),config.get('tec_source_id'))
    else:tec=fields.nearest('vertical_tec_tecu',when,lat,lon,config.get('max_tec_distance_km',400),config.get('tec_source_id'))
    if not tec:
        result['unavailable']['ionosphere']='No valid nearby TEC sample at the pierce point';return result
    top=tec['source'].get('column_top_km')
    satellite_height=float(EarthLocation.from_geocentric(*(p*u.km)).height.to_value(u.km))
    if not finite(top) or satellite_height<top:
        result['unavailable']['ionosphere']='TEC column top unknown or satellite lies inside the column; a vertical profile is required';return result
    mapping=1/float(direction@(pierce/shell_radius));vertical=tec['sample']['values']['vertical_tec_tecu'];slant=vertical*mapping
    result['ionosphere_group_delay_m']=ionospheric_group_delay_m(slant,config['frequency_hz'])
    result['inputs']['tec']={'source_id':tec['sample']['source_id'],'sample_time':tec['sample']['time_utc'],
        'distance_km':tec['distance_km'],'pierce_latitude_deg':lat,'pierce_longitude_deg':lon,
        'vertical_tecu':vertical,'slant_tecu':slant,'mapping':mapping,'column_top_km':top,
        'interpolation':tec.get('method','nearest valid sample'),'corners':tec.get('corners')}
    if magnetic_model is None:
        result['unavailable']['faraday']='Magnetic field model unavailable';return result
    try:
        field,provenance=magnetic_model(lat,lon,height,when)
        parallel=float((np.asarray(field)@basis(lat,lon))@direction)*1e-9
        result['uplink_faraday_deg']=math.degrees(faraday_rotation_rad(slant,parallel,config['frequency_hz']))
        result['inputs']['magnetic']={**provenance,'parallel_t':parallel}
    except (ImportError,ValueError) as exc:result['unavailable']['faraday']=str(exc)
    return result


def igrf_field(latitude,longitude,height,when):
    from .providers import igrf_bundle
    bundle=igrf_bundle([{'latitude_deg':latitude,'longitude_deg':longitude,'altitude_km':height}],when.isoformat())
    v=bundle['samples'][0]['values'];source=bundle['sources'][0]
    return [v['magnetic_east_nt'],v['magnetic_north_nt'],v['magnetic_up_nt']],{
        'model':'IGRF-14','version':source['version'],'coefficients_sha256':source['coefficients_sha256']}


def evaluate_links(scene,object_id,station_id):
    config=validate_config(scene.get('ground_links'))
    if scene['frame']!='ITRS':raise ValueError('Ground-link diagnostics currently require an ITRS scene')
    station=next((s for s in config['stations'] if s['id']==station_id),None)
    obj=next((o for o in scene['objects'] if o['id']==object_id),None)
    if station is None or obj is None:raise ValueError('Unknown ground station or satellite')
    fields=FieldSamples(scene.get('environment',{}))
    rows=[radio_path(p,station,utc(t),config,fields,igrf_field) for p,t in zip(obj['positions_km'],scene['times'])]
    return {'schema':'godsat.link-diagnostics.v1','station':station,'object_id':object_id,
        'scene_sha256':scene['source'].get('sha256'),
        'frequency_hz':config['frequency_hz'],'times':scene['times'],'rows':rows,
        'limits':['Straight geometric ray; no refraction, diffraction, multipath or receiver model.',
            'Instantaneous geometry; no signal light-time iteration, Sagnac, relativity or clock corrections.',
            'Dry delay uses Saastamoinen zenith hydrostatic delay and secant elevation mapping; wet delay is not estimated.',
            'TEC is mapped through one spherical shell; targets inside the source column are unsupported.',
            'Faraday rotation assumes the main magnetic field at that shell represents the TEC-weighted field; external storm fields are omitted.',
            'Cloud fraction is contextual area coverage, not optical path opacity or a detection probability.',
            'Radio frequency is a scenario parameter, not verified satellite hardware or an operational link assignment.',
            'Results are sampled at saved epochs. No inference of observations or custody, and no changes to SGP4 orbits.']}


def main():
    import argparse
    import hashlib
    import json
    from pathlib import Path
    from godsat.studio.scene import load_scene
    parser=argparse.ArgumentParser(description='Evaluate a configured snapshot radio path over a saved scene')
    parser.add_argument('--scene',type=Path,required=True)
    parser.add_argument('--object',required=True)
    parser.add_argument('--station',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.scene.resolve()==args.output.resolve():parser.error('Output must differ from the input scene')
    scene=load_scene(args.scene)
    scene['source']['sha256']=hashlib.sha256(args.scene.read_bytes()).hexdigest()
    result=evaluate_links(scene,args.object,args.station)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,allow_nan=False,indent=2)+'\n')
    print(f'{args.output}: {len(result["rows"])} snapshot estimates')


if __name__=='__main__':main()
