"""Physics checks use independent potential/area calculations, not snapshots."""
import copy
import json
from pathlib import Path
import numpy as np
import pytest
from godsat.simulation.forces import (zonal_gravity, illumination_fraction, solar_radiation_acceleration,
    schwarzschild_acceleration, AU_KM, SUN_RADIUS_KM, SOLAR_PRESSURE_N_M2, C_KM_S)
from godsat.simulation.numerical import gravity, MU, RADIUS, J2, validate_experiment, integrate_experiment

ROOT=Path(__file__).parents[2]


def test_zonals_match_independent_potential_gradient_and_j2():
    rng=np.random.default_rng(18)
    xyz=rng.normal(size=(20,3));xyz=xyz/np.linalg.norm(xyz,axis=1)[:,None]*7200
    xyz=np.vstack([xyz,[[0,0,7200],[0,0,-7200],[7200,0,0]]])
    np.testing.assert_allclose(zonal_gravity(xyz,MU,RADIUS,{'2':J2}),gravity(xyz,True),atol=2e-18)
    coefficients={str(i):(-1)**i*1e-4/i for i in range(2,9)}
    def potential(r):
        d=np.linalg.norm(r,axis=1);c=np.zeros(9)
        correction=0
        for n,j in coefficients.items():
            c[:]=0;c[int(n)]=1
            correction+=j*(RADIUS/d)**int(n)*np.polynomial.legendre.legval(r[:,2]/d,c)
        return MU/d*(1-correction)
    gradient=[];h=.02
    for axis in np.eye(3)*h:
        gradient.append((-potential(xyz+2*axis)+8*potential(xyz+axis)-8*potential(xyz-axis)+potential(xyz-2*axis))/(12*h))
    np.testing.assert_allclose(zonal_gravity(xyz,MU,RADIUS,coefficients),np.array(gradient).T,atol=2e-12)


def test_srp_direction_distance_scaling_and_umbra():
    p=np.array([[7000.,0,0],[7000,0,0]])
    sun=np.array([AU_KM+7000,0,0])
    a,light=solar_radiation_acceleration(p,sun,np.array([.01,.02]),RADIUS)
    np.testing.assert_allclose(light,1)
    np.testing.assert_allclose(a[:,0],-SOLAR_PRESSURE_N_M2/1000*np.array([.01,.02]),rtol=1e-14)
    np.testing.assert_allclose(a[:,1:],0)
    far,_=solar_radiation_acceleration(p,np.array([2*AU_KM+7000,0,0]),np.array([.01,.02]),RADIUS)
    np.testing.assert_allclose(far,a/4,rtol=1e-14)
    shadow,light=solar_radiation_acceleration(-p,np.array([AU_KM,0,0]),np.ones(2),RADIUS)
    np.testing.assert_allclose(shadow,0);np.testing.assert_allclose(light,0)


def test_penumbra_matches_independent_disc_area_quadrature():
    from numpy.polynomial.legendre import leggauss
    x,w=leggauss(1024)
    for y in [RADIUS-100,RADIUS,RADIUS+100]:
        p=np.array([-42000.,y,0]);sun=np.array([AU_KM,0,0]);v=sun-p
        a=np.arcsin(SUN_RADIUS_KM/np.linalg.norm(v));b=np.arcsin(RADIUS/np.linalg.norm(p))
        d=np.arccos(np.dot(v,-p)/(np.linalg.norm(v)*np.linalg.norm(p)))
        lo=max(-a,d-b);hi=min(a,d+b)
        xx=(x+1)*(hi-lo)/2+lo
        height=np.minimum(np.sqrt(np.maximum(0,a*a-xx*xx)),np.sqrt(np.maximum(0,b*b-(xx-d)**2)))
        expected=1-np.sum(w*height)*(hi-lo)/(np.pi*a*a)
        value=illumination_fraction(p[None,:],sun,RADIUS)[0]
        assert 0<value<1
        assert value==pytest.approx(expected,abs=1e-5)
    # Far behind Earth: annular eclipse and a fraction strictly between 0 and 1.
    assert 0<illumination_fraction(np.array([[-2e6,0,0]]),np.array([AU_KM,0,0]),RADIUS)[0]<1


def test_schwarzschild_circular_limit_and_rotation_covariance():
    r=7000.;p=np.array([[r,0,0]]);v=np.array([[0,np.sqrt(MU/r),0]])
    expected=3*MU*MU/(C_KM_S*C_KM_S*r**3)
    np.testing.assert_allclose(schwarzschild_acceleration(p,v,MU),[[expected,0,0]],rtol=1e-14)
    q,_=np.linalg.qr(np.random.default_rng(42).normal(size=(3,3)))
    p=np.array([[7000.,400.,100.]]);v=np.array([[1.,7.,2.]])
    np.testing.assert_allclose(schwarzschild_acceleration(p@q,v@q,MU),schwarzschild_acceleration(p,v,MU)@q,atol=1e-23)


def extended():
    return json.loads((ROOT/'configs/numerical-extended.json').read_text())


def test_explicit_model_properties_and_no_j2_double_count():
    c=extended();validate_experiment(c)
    for change in ['j2','reference','normalization','mass_kg','radiation_area_m2','radiation_coefficient']:
        bad=copy.deepcopy(c)
        if change=='j2':bad['forces']['j2']=True
        elif change in ['reference','normalization']:bad['gravity_model'].pop(change)
        else:bad['objects'][0].pop(change)
        with pytest.raises(ValueError):validate_experiment(bad)
    bad=extended();bad['gravity_model']['coefficients']['9']=1e-6
    with pytest.raises(ValueError):validate_experiment(bad)


def test_extended_integration_converges_and_records_each_force():
    c=extended();c['duration_seconds']=600;c['output_step_seconds']=60
    states=[]
    for h in [10,5,2.5]:
        c['integration_step_seconds']=h;scene,state=integrate_experiment(c);states.append(state)
    errors=[np.max(np.linalg.norm(state[:,:,:3]-states[-1][:,:,:3],axis=2)) for state in states[:-1]]
    assert errors[0]>errors[1]*8
    assert errors[1]<1e-4
    assert scene['source']['solar_radiation']['sampled_illumination_range']==[0.,0.]  # This short initial arc is in Earth's shadow.
    assert scene['source']['relativity']['c_km_s']==C_KM_S
    assert scene['source']['gravity_model']==c['gravity_model']
    assert scene['source']['spacecraft_parameters'][0]['radiation_area_m2']==1.2
    assert len(scene['source']['additional_forces_source_sha256'])==64


def test_srp_only_does_not_enable_third_body_gravity():
    c=extended();c['duration_seconds']=60;c['output_step_seconds']=30
    c['forces']={'solar_radiation_pressure':True}
    c['objects'][0]['position_gcrs_km']=[-x for x in c['objects'][0]['position_gcrs_km']]
    scene,state=integrate_experiment(c)
    assert not scene['source']['force_model'].get('third_bodies',False)
    assert scene['source']['solar_radiation'] is not None
    assert scene['source']['gravity_model'] is None
    assert np.isfinite(state).all()
    assert scene['source']['solar_radiation']['sampled_illumination_range']==[1.,1.]
    c['forces']={}
    _,baseline=integrate_experiment(c)
    assert np.linalg.norm(state[-1,0,:3]-baseline[-1,0,:3])>1e-9
