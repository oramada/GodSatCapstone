import datetime as dt
import json
import math
from pathlib import Path
import pytest
from godsat.simulation.links import FieldSamples,radio_path,validate_config,evaluate_links
from godsat.studio.scene import base,load_scene

NOW=dt.datetime(2026,11,8,18,55,tzinfo=dt.timezone.utc)
STATION={'id':'test','name':'Test station','latitude_deg':0,'longitude_deg':0,'altitude_km':0,'orthometric_height_km':0,'reference':'Hypothetical test fixture'}
CONFIG={'schema':'godsat.ground-links.v1','frequency_hz':1575.42e6,'stations':[STATION]}


def fields():
    common={'time_utc':NOW.isoformat(),'valid_until_utc':(NOW+dt.timedelta(seconds=60)).isoformat(),
        'latitude_deg':0,'longitude_deg':0,'altitude_km':0}
    return FieldSamples({'sources':[{'id':'tec','column_top_km':8500},{'id':'weather','vertical_datum':'ellipsoidal'}],
        'samples':[{**common,'source_id':'tec','values':{'vertical_tec_tecu':10}},
                   {**common,'source_id':'weather','values':{'pressure_pa':101325,'cloud_fraction':.4}}]})


def test_zenith_geometry_and_analytic_environmental_effects():
    result=radio_path([26578.137,0,0],STATION,NOW,CONFIG,fields(),lambda *args:([0,0,30000],{'model':'test field'}))
    assert result['elevation_deg']==pytest.approx(90)
    assert result['range_km']==pytest.approx(20200)
    assert result['vacuum_time_ms']==pytest.approx(20200e6/299792458.)
    assert result['ionosphere_group_delay_m']==pytest.approx(1.623724475,abs=1e-9)
    assert result['dry_slant_delay_m']==pytest.approx(.0022768*1013.25/.99734)
    assert result['uplink_faraday_deg']==pytest.approx(math.degrees(2.36e4*1e17*3e-5/1575.42e6**2))
    higher=radio_path([26578.137,0,0],STATION,NOW,{**CONFIG,'frequency_hz':3150.84e6},fields(),lambda *a:([0,0,30000],{}))
    assert higher['ionosphere_group_delay_m']==pytest.approx(result['ionosphere_group_delay_m']/4)
    assert higher['uplink_faraday_deg']==pytest.approx(result['uplink_faraday_deg']/4)
    assert higher['dry_slant_delay_m']==result['dry_slant_delay_m']


def test_missing_stale_and_low_satellite_data_are_not_zero_corrections():
    low=radio_path([7078.137,0,0],STATION,NOW,CONFIG,fields())
    assert low['ionosphere_group_delay_m'] is None
    assert 'inside the column' in low['unavailable']['ionosphere']
    stale=radio_path([26578.137,0,0],STATION,NOW+dt.timedelta(seconds=61),CONFIG,fields())
    assert stale['dry_slant_delay_m'] is None and stale['ionosphere_group_delay_m'] is None
    assert stale['vacuum_time_ms'] is not None
    hidden=radio_path([-26578.137,0,0],STATION,NOW,CONFIG,fields())
    assert hidden['elevation_deg']==pytest.approx(-90)
    assert hidden['dry_slant_delay_m'] is None


def test_config_and_scene_roundtrip(tmp_path,monkeypatch):
    from godsat.simulation import links
    monkeypatch.setattr(links,'igrf_field',lambda *a:([0,0,30000],{}))
    validate_config(CONFIG)
    scene=base('link fixture','ITRS',[NOW.isoformat()],[{'id':'sat','name':'Test satellite','kind':'satellite','positions_km':[[26578.137,0,0]]}],{'kind':'illustrative','description':'test'},ground_links=CONFIG)
    path=tmp_path/'scene.json';path.write_text(json.dumps(scene))
    restored=load_scene(path);assert restored['ground_links']==CONFIG
    result=evaluate_links(restored,'sat','test')
    assert result['rows'][0]['ionosphere_group_delay_m'] is None
    assert result['rows'][0]['vacuum_time_ms']>0
    assert restored['observations'] is None
    with pytest.raises(ValueError):validate_config({**CONFIG,'frequency_hz':1})


def test_bilinear_tec_wraps_dateline_but_does_not_fill_holes():
    samples=[]
    for lat in [-5.,5.]:
        for lon in [175.,-175.]:
            samples.append({'source_id':'tec','time_utc':NOW.isoformat(),'valid_until_utc':NOW.isoformat(),
                'latitude_deg':lat,'longitude_deg':lon,'altitude_km':0,
                'values':{'vertical_tec_tecu':10+lat+(0 if lon==175 else 10)}})
    bundle={'sources':[{'id':'tec','grid_spacing_deg':{'latitude':10,'longitude':10}}],'samples':samples}
    result=FieldSamples(bundle).bilinear_tec(NOW,0,180,1000,'tec')
    assert result['sample']['values']['vertical_tec_tecu']==pytest.approx(15)
    assert sum(c['weight'] for c in result['corners'])==pytest.approx(1)
    assert FieldSamples(bundle).bilinear_tec(NOW,0,0,1000,'tec') is None
    bundle['samples']=samples[:-1]
    assert FieldSamples(bundle).bilinear_tec(NOW,0,180,1000,'tec') is None


def test_pressure_requires_a_known_vertical_datum_and_station_orthometric_height():
    without_height={k:v for k,v in STATION.items() if k!='orthometric_height_km'}
    result=radio_path([26578.137,0,0],without_height,NOW,CONFIG,fields())
    assert result['dry_slant_delay_m'] is None
    assert result['ionosphere_group_delay_m'] is not None


def test_ground_link_http_endpoint_matches_scene_and_rejects_unknown_station(tmp_path,monkeypatch):
    import io
    from godsat.studio.service import StudioService
    from godsat.simulation import links
    monkeypatch.setattr(links,'igrf_field',lambda *a:([0,0,30000],{}))
    value=base('fixture','ITRS',[NOW.isoformat()],[{'id':'sat','name':'sat','kind':'satellite','positions_km':[[26578.137,0,0]]}],{'kind':'illustrative','description':'test'},ground_links=CONFIG)
    path=tmp_path/'scene.json';path.write_text(json.dumps(value))
    service=StudioService(Path(__file__).parents[2],tmp_path)
    identity=next(a['id'] for a in service.catalog.scan()['artifacts'] if a['name']=='scene.json')
    class Handler:
        def __init__(self,url):self.path=url;self.wfile=io.BytesIO();self.headers={'Host':'127.0.0.1:8765'}
        def send_response(self,status):self.status=status
        def send_header(self,*args):pass
        def end_headers(self):pass
    request=Handler(f'/api/studio/links?id={identity}&object=sat&station=test')
    assert service.handle(request) and request.status==200
    result=json.loads(request.wfile.getvalue());assert len(result['scene_sha256'])==64
    assert result['rows'][0]['range_km']==pytest.approx(20200)
    request=Handler(f'/api/studio/links?id={identity}&object=sat&station=missing')
    assert service.handle(request) and request.status==400
