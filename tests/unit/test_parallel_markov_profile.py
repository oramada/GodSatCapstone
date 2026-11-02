from copy import deepcopy
import hashlib
import json

import pytest

from scripts.experiments.parallel_markov_cells import reconcile_profile


def test_parallel_cells_reject_a_different_profile_or_intervention_design():
    profile={'one_minute_attitude_solution_dropout_rate':.25,'simulator_markov_persistence_parameter':.8}
    binding={'outage_rates':[0.,.25],'dropout_profile_sha256':'source',
             'dropout_burst_persistence':.8,'reference_step_seconds':60}
    design={'outage_rates':[0.,.25],'dropout_design_sha256':hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest(),
            'config':{'dropout_burst_persistence':.8,'dropout_burst_reference_step_seconds':60}}
    reconcile_profile(design,profile,'source')
    with pytest.raises(ValueError,match='profile'):reconcile_profile(design,profile,'different source')
    other=deepcopy(design);other['config']['dropout_burst_persistence']=.9
    with pytest.raises(ValueError,match='profile'):reconcile_profile(other,profile,'source')
