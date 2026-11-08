import copy
import datetime as dt
import json
from pathlib import Path
import numpy as np
import pytest
from godsat.simulation.numerical import MU,RADIUS,J2,gravity,drag_acceleration,third_body_acceleration,integrate_experiment,frame_table,validate_experiment
from godsat.simulation.atmosphere import MsisAtmosphere,SpaceWeather


def experiment():
    radius=RADIUS+400
    return {'schema':'godsat.numerical.v1','frame':'GCRS','epoch':'2026-11-08T18:55:00Z',
        'duration_seconds':600,'integration_step_seconds':10,'output_step_seconds':60,
        'forces':{'j2':False,'drag':False,'third_bodies':False},
        'source':{'kind':'illustrative','reference':'Synthetic circular orbit'},
        'objects':[{'id':'1','name':'Synthetic','position_gcrs_km':[radius,0,0],
                    'velocity_gcrs_km_s':[0,float(np.sqrt(MU/radius)),0]}]}


def test_two_body_circular_solution_and_step_convergence():
    config=experiment();radius=RADIUS+400;rate=np.sqrt(MU/radius**3)
    errors=[]
    for step in [20,10]:
        config['integration_step_seconds']=step
        scene,states=integrate_experiment(config)
        times=np.arange(0,601,60);expected=np.array([radius*np.cos(rate*times),radius*np.sin(rate*times),np.zeros(len(times))]).T
        errors.append(np.max(np.linalg.norm(states[:,0,:3]-expected,axis=1)))
        energy=.5*np.sum(states[:,0,3:]**2,axis=1)-MU/np.linalg.norm(states[:,0,:3],axis=1)
        assert np.ptp(energy)<1e-8
        assert scene['observations'] is None and scene['source']['kind']=='illustrative'
    assert errors[1]*1000<.01
    assert errors[0]>errors[1]*10


def test_j2_force_matches_closed_form_axes_and_drag_dissipates_relative_energy():
    r=7000.;points=np.array([[r,0,0],[0,0,r]])
    perturbation=gravity(points,True)-gravity(points,False)
    assert perturbation[0,0]==pytest.approx(-1.5*J2*MU*RADIUS**2/r**4)
    assert perturbation[1,2]==pytest.approx(3*J2*MU*RADIUS**2/r**4)
    velocity=np.array([[7.,0,0],[1.,2.,3.]])
    acceleration=drag_acceleration(velocity,np.array([1e-12,2e-12]),np.array([.02,.01]))
    assert np.all(np.sum(acceleration*velocity,axis=1)<0)
    np.testing.assert_allclose(drag_acceleration(velocity,np.array([2e-12,4e-12]),np.array([.02,.01])),2*acceleration)
    with pytest.raises(ValueError):drag_acceleration(velocity,np.array([-1.,1.]),np.ones(2))


def test_frame_rotation_and_derivative_include_corotation():
    now=dt.datetime(2026,11,8,tzinfo=dt.timezone.utc)
    rotations,rates,_,_=frame_table([now])
    np.testing.assert_allclose(rotations[0]@rotations[0].T,np.eye(3),atol=1e-14)
    angular=rates[0]@rotations[0].T
    np.testing.assert_allclose(angular+angular.T,np.zeros((3,3)),atol=1e-10)
    assert np.linalg.norm(angular)==pytest.approx(np.sqrt(2)*7.292115e-5,rel=1e-5)


def test_force_inputs_are_explicit_and_unsupported_time_grids_fail():
    config=experiment();config['forces']['drag']=True
    with pytest.raises(ValueError,match='mass'):validate_experiment(config)
    config=experiment();config['integration_step_seconds']=7
    with pytest.raises(ValueError,match='integer'):validate_experiment(config)


def test_msis_density_matches_published_reference_vectors():
    fixture=json.loads((Path(__file__).parents[1]/'fixtures/msis21-density-reference.json').read_text())
    for row in fixture['rows']:
        class Drivers:
            def at(self,when):return {'f107_sfu':row['f107'],'f107a_sfu':row['f107a'],'aps':[row['ap']]*7}
        density=MsisAtmosphere(Drivers(),ap_mode='daily').geodetic(row['time'],row['lon'],row['lat'],row['alt'])
        assert float(density)==pytest.approx(row['density_kg_m3'],rel=.002)


def test_space_weather_history_indices_previous_day_flux_and_missing_data(tmp_path):
    import csv
    rows=[]
    for day in range(1,5):
        row={'DATE':f'2026-01-0{day}','F10.7_OBS':100+day-1,'F10.7_OBS_CENTER81':200+day-1,'F10.7_DATA_TYPE':'PRD' if day==4 else 'OBS','AP_AVG':(day-1)*8+3.5}
        row.update({f'AP{i}':(day-1)*8+i-1 for i in range(1,9)});rows.append(row)
    path=tmp_path/'weather.csv'
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    source=SpaceWeather(path);value=source.at('2026-01-04T06:30:00Z')
    assert value['f107_sfu']==102 and value['f107a_sfu']==203
    assert value['aps']==[27.5,26,25,24,23,18.5,10.5]
    assert value['current_flux_qualifier']=='PRD'
    with pytest.raises(ValueError,match='Missing'):source.at('2026-01-01T00:00:00Z')


def test_third_body_removes_acceleration_of_the_earth_and_has_tidal_signs():
    body=np.array([384400.,0,0]);mu=4902.800066
    np.testing.assert_allclose(third_body_acceleration(np.zeros((1,3)),body,mu),0,atol=1e-20)
    points=np.array([[100.,0,0],[0,100.,0]])
    acceleration=third_body_acceleration(points,body,mu)
    assert acceleration[0,0]>0 and acceleration[1,1]<0
    assert acceleration[0,0]==pytest.approx(2*mu*100/384400.**3,rel=.001)


def test_j2_nodal_precession_matches_first_order_secular_prediction():
    config=experiment();config['duration_seconds']=86400;config['output_step_seconds']=600
    config['integration_step_seconds']=20;config['forces']['j2']=True
    radius=RADIUS+400;inc=np.deg2rad(53);speed=np.sqrt(MU/radius)
    rotation,_,_,_=frame_table([dt.datetime(2026,11,8,18,55,tzinfo=dt.timezone.utc)])
    config['objects'][0]['position_gcrs_km']=(np.array([radius,0,0])@rotation[0]).tolist()
    config['objects'][0]['velocity_gcrs_km_s']=(np.array([0,speed*np.cos(inc),speed*np.sin(inc)])@rotation[0]).tolist()
    _,states=integrate_experiment(config)
    r=states[:,0,:3]@rotation[0].T;v=states[:,0,3:]@rotation[0].T
    normal=np.cross(r,v);node=np.cross(np.array([0,0,1]),normal)
    raan=np.unwrap(np.arctan2(node[:,1],node[:,0]))
    measured=np.polyfit(np.arange(len(raan))*600,raan,1)[0]
    expected=-1.5*J2*np.sqrt(MU/radius**3)*(RADIUS/radius)**2*np.cos(inc)
    assert measured==pytest.approx(expected,rel=.02)
