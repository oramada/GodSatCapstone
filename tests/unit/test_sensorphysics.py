import numpy as np
import pytest

from godsat.environment import TaskingEnv
from godsat.sensorphysics import PhysicalTaskingEnv, environment_class, slew_profile
from scripts.validation.audit_physical_campaign import reconstruct_trace


def inputs(detection=0, clutter=1):
    states=np.zeros((4,2,6));states[:,:,0]=[7000,8000]
    scenario={'states':states,'ages':np.zeros((4,2)),'ids':np.array([1,2]),
              'times':np.arange(4),'agents':1}
    config={'step_seconds':60,'max_range_km':6000,'slew_rate_deg_s':2,
            'field_of_regard_deg':180,'custody_seconds':180,'detection_probability':detection,
            'range_detection_penalty':0,'stale_detection_penalty':0,'max_element_age_hours':72,
            'slew_penalty':.03,'false_penalty':.2,'collision_penalty':.1,
            'gimbal_inertia_kg_m2':2,'gimbal_max_torque_nm':.02,'gimbal_efficiency':.65,
            'gimbal_drive_power_watts':.05,
            'false_association_probability_per_missed_look':clutter,
            'sensor_response_model':'assumed_gimbal_and_clutter_v1'}
    return scenario,config


@pytest.mark.parametrize('angle',[.01,.3,1.5])
def test_slew_work_matches_integrated_positive_motor_power_and_endpoint(angle):
    inertia,torque,speed,efficiency=2.,.02,.035,.65
    duration,energy,peak=slew_profile(angle,inertia,torque,speed,efficiency)
    acceleration=torque/inertia
    acceleration_time=peak/acceleration
    cruise=duration-2*acceleration_time
    assert peak*acceleration_time+peak*cruise == pytest.approx(angle)
    time=np.linspace(0,acceleration_time,1001)
    electrical_power=torque*acceleration*time/efficiency
    assert np.trapezoid(electrical_power,time) == pytest.approx(energy)
    assert peak<=speed
    assert cruise>=-1e-12


def test_clutter_updates_reported_age_but_never_true_custody():
    s,c=inputs();env=PhysicalTaskingEnv(s,c,seed=123)
    for _ in range(env.steps):env.step([0])
    result=env.metrics()
    assert result['custody_continuity']==0
    assert result['false_track_rate']==1
    assert result['false_observation_rate']==1
    assert result['false_observations']==3
    assert np.isfinite(env.last_seen).all()
    assert np.isneginf(env.truth_last_seen).all()
    old=env.trace.copy();env.reset()
    for _ in range(env.steps):env.step([0])
    assert env.trace==old


def test_nominal_true_reports_and_complete_dropout_do_not_create_false_tracks():
    s,c=inputs(detection=1,clutter=1)
    env=PhysicalTaskingEnv(s,c)
    env.step([0]);assert env.metrics()['false_track_rate']==0
    assert env.metrics()['custody_continuity']==1
    s,c=inputs(detection=0,clutter=1)
    env=PhysicalTaskingEnv(s,c,dropout_probability=.5)
    env.dropout_uniforms[:]=0
    env.step([0]);assert env.metrics()['reported_observations']==0


def test_acceleration_bound_masks_slew_that_speed_only_model_accepts():
    s,c=inputs();angle=np.deg2rad(118)
    s['states'][:,1,:3]=s['states'][:,0,:3]+1000*np.array([np.cos(angle),np.sin(angle),0])
    assert TaskingEnv(s,c).geometry()[-1][0,0]
    assert not PhysicalTaskingEnv(s,c).geometry()[-1][0,0]
    assert environment_class({}) is TaskingEnv
    with pytest.raises(ValueError):environment_class({'sensor_response_model':'typo'})


def test_independent_action_audit_reconstructs_false_tracks_and_torque_work():
    s,c=inputs();s['states'][:,1,:3]=[7800,500,0]
    env=PhysicalTaskingEnv(s,c,seed=741)
    for _ in range(env.steps):env.step([0])
    expected=reconstruct_trace(s,c,741,env.trace)
    assert expected['slew_energy_joules']>0
    for name,value in expected.items():assert value==pytest.approx(env.metrics()[name])
    env.trace[0]['slew_energy_joules_mean']+=1
    with pytest.raises(ValueError,match='torque-work'):reconstruct_trace(s,c,741,env.trace)


@pytest.mark.parametrize('mode',['independent','burst'])
def test_independent_trace_audit_preserves_loss_stream_and_clutter_suppression(mode):
    s,c=inputs(detection=.5,clutter=1)
    env=PhysicalTaskingEnv(s,c,seed=78,dropout_probability=.5,dropout_mode=mode)
    for _ in range(env.steps):env.step([0])
    result=reconstruct_trace(s,c,78,env.trace,probability=.5,mode=mode)
    for name,value in result.items():assert value==pytest.approx(env.metrics()[name])
