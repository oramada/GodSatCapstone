import datetime as dt
import json
from pathlib import Path
import numpy as np
import pytest
from godsat.simulation.providers import weather_bundle, glotec_bundle, ionex_bundle, igrf_bundle


def test_weather_units_missing_values_and_source_classification():
    value={'latitude':35.,'longitude':-120.,'elevation':100.,'utc_offset_seconds':0,
        'current_units':{'temperature_2m':'°C','surface_pressure':'hPa','cloud_cover':'%'},
        'current':{'time':'2026-11-08T19:15','temperature_2m':20.,'surface_pressure':990.,'cloud_cover':None}}
    result=weather_bundle(value,{'sha256':'fixture'},900)
    assert result['sources'][0]['kind']=='modeled'
    assert result['samples'][0]['values']=={'pressure_pa':99000.}
    assert result['samples'][1]['values']=={'temperature_k':293.15}
    assert result['samples'][1]['altitude_km']==pytest.approx(.102)
    assert result['samples'][0]['valid_until_utc']=='2026-11-08T19:30:00+00:00'
    value['current_units']['temperature_2m']='°F'
    with pytest.raises(ValueError,match='units'):weather_bundle(value,{})


def test_glotec_keeps_column_and_peak_distinct_with_quality_flags():
    value={'type':'FeatureCollection','time_tag':'2026-11-08T18:55:00Z',
        'metadata':{'variables':{'tec':{'units':'TECU'},'hmF2':{'units':'km'},'NmF2':{'units':'el/m^3'}}},
        'features':[{'geometry':{'type':'Point','coordinates':[10.,20.]},
                     'properties':{'tec':12.,'hmF2':300.,'NmF2':1e11,'quality_flag':0}}]}
    result=glotec_bundle(value,{})
    assert result['sources'][0]['kind']=='modeled'
    assert [s['altitude_km'] for s in result['samples']]==[0,300]
    assert result['samples'][0]['quality_flag']==0
    assert result['samples'][1]['values']=={'electron_density_m3':1e11}
    value['features'][0]['properties']['tec']=None
    assert len(glotec_bundle(value,{})['samples'])==1


def test_ionex_fixed_width_exponent_missing_and_geocentric_coordinates(tmp_path):
    def record(value,label):return f'{value:<60}{label}\n'
    raw=''.join([record('     1.0','IONEX VERSION / TYPE'),record('     2','MAP DIMENSION'),
        record('  6371.0','BASE RADIUS'),record('    -1','EXPONENT'),record('','END OF HEADER'),
        record('     1','START OF TEC MAP'),record(' 2026 11 8 0 0 0','EPOCH OF CURRENT MAP'),
        record(' 0.0 -5.0 5.0 5.0 450.0','LAT/LON1/LON2/DLON/H'),
        ''.join(f'{v:5d}' for v in [100,9999,200])+'\n',record('     1','END OF TEC MAP')])
    path=tmp_path/'map.inx';path.write_text(raw)
    result=ionex_bundle(path,600)
    assert len(result['samples'])==2
    assert result['sources'][0]['missing_samples']==1
    assert result['samples'][0]['values']['vertical_tec_tecu']==10.
    assert result['samples'][0]['altitude_km']==pytest.approx(442.863,abs=1e-6)
    assert result['samples'][1]['longitude_deg']==pytest.approx(5.)
    path.write_text(raw.replace('     2','     3',1))
    with pytest.raises(ValueError,match='two-dimensional'):ionex_bundle(path)


def test_igrf_matches_official_fortran_reference_and_rejects_extrapolation():
    reference=json.loads((Path(__file__).parents[2]/'docs/benchmarks/igrf14-reference.json').read_text())
    for year in sorted({r['year'] for r in reference['reference']}):
        rows=[r for r in reference['reference'] if r['year']==year]
        points=[{k:r[k] for k in ['latitude_deg','longitude_deg','altitude_km']} for r in rows]
        bundle=igrf_bundle(points,f'{year}-01-01T00:00:00Z')
        actual=[[s['values'][k] for k in ['magnetic_east_nt','magnetic_north_nt','magnetic_up_nt']] for s in bundle['samples']]
        np.testing.assert_allclose(actual,[r['reference_enu_nt'] for r in rows],atol=.1,rtol=0)
    with pytest.raises(ValueError,match='extrapolation'):
        igrf_bundle(points,'2031-01-01T00:00:00Z')


def test_hourly_weather_selection_never_uses_a_future_sample(tmp_path,monkeypatch):
    from godsat.simulation import providers
    value={'latitude':0.,'longitude':0.,'elevation':0.,'utc_offset_seconds':0,
        'hourly_units':{'temperature_2m':'°C','surface_pressure':'hPa','cloud_cover':'%'},
        'hourly':{'time':['2026-11-08T18:00','2026-11-08T19:00'],
                  'temperature_2m':[20.,21.],'surface_pressure':[1000.,1010.],'cloud_cover':[20.,30.]}}
    monkeypatch.setattr(providers,'download',lambda *a:(json.dumps(value).encode(),{'sha256':'fixture'}))
    result=providers.fetch_weather(0,0,tmp_path/'weather.json',3600,'2026-11-08T18:55:00Z')
    assert result['samples'][0]['time_utc']=='2026-11-08T18:00:00+00:00'
    assert result['samples'][0]['values']['pressure_pa']==100000
    assert result['sources'][0]['vertical_datum']=='mean_sea_level'
    with pytest.raises(ValueError,match='No hourly weather'):
        providers.fetch_weather(0,0,tmp_path/'earlier.json',0,'2026-11-08T17:00:00Z')
