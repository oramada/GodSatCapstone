import numpy as np
import pytest
import torch

from scripts.experiments.run_geometry_loss_probes import episode, geometry_group
from scripts.validation.audit_geometry_loss_probes import alternate_episode


class FirstTarget:
    def distribution(self,obs,mask):
        logits=torch.zeros(mask.shape)
        logits[:,0]=10
        return torch.distributions.Categorical(logits=logits.masked_fill(~mask,-1e9))


def test_single_successful_observation_is_removed_with_paired_continuation():
    scenario={'states':np.asarray([[[7000.,0,0,0,7.5,0],[7100.,10,0,0,7.4,0]]]*4),
              'times':np.arange(4),'ids':np.asarray([100,200]),'agents':1,
              'ages':np.zeros((4,2))}
    config={'step_seconds':60,'custody_seconds':30,'slew_rate_deg_s':2,
            'field_of_regard_deg':180,'max_range_km':6000,'detection_probability':1.,
            'range_detection_penalty':0.,'stale_detection_penalty':0.,
            'max_element_age_hours':72,'slew_penalty':.03,'false_penalty':.2,'collision_penalty':.1}
    hp={'claim_resolution':8}
    baseline=episode(FirstTarget(),scenario,config,hp,123)
    assert len(baseline['events']) == 3
    forced=baseline['events'][1]
    counter=episode(FirstTarget(),scenario,config,hp,123,forced,baseline)
    assert baseline['detected'] == [[0],[0],[0]]
    assert counter['detected'] == [[0],[],[0]]
    assert baseline['metrics']['custody_continuity'] == 1
    assert counter['metrics']['custody_continuity'] == pytest.approx(2/3)
    assert baseline['actions'] == counter['actions']
    alternate=alternate_episode(FirstTarget(),scenario,config,hp,123,
        {'baseline_actions':baseline['actions'],'baseline_detected':baseline['detected']},forced)
    for metric in ('custody_continuity','observable_custody','slew_energy_proxy','objective'):
        assert alternate[metric] == counter['metrics'][metric]
    assert alternate['dropout_misses'] == 1


def test_geometry_bins_keep_boundary_observations_in_upper_group():
    assert geometry_group(1999.9,39.9) == (0,0)
    assert geometry_group(2000.,40.) == (1,1)
    assert geometry_group(4000.,80.) == (2,2)
    with pytest.raises(ValueError):geometry_group(float('nan'),0.)
