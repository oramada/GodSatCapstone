import numpy as np
import pytest

from scripts.compare_catalog_dropout_cohorts import (
    mean_ci,
    moving_block_ci,
    summarize_episode_mechanism,
)


def test_mean_ci_uses_date_level_observations():
    mean, interval = mean_ci(np.asarray([1.0, 2.0, 3.0]))
    assert mean == 2.0
    assert interval[0] < mean < interval[1]


def test_moving_block_interval_is_reproducible_and_bounded():
    values = np.linspace(-1.0, 1.0, 24)
    first = moving_block_ci(values, block_length=4, replicates=1000, seed=17)
    second = moving_block_ci(values, block_length=4, replicates=1000, seed=17)
    assert first == second
    assert -1.0 <= first[0] <= first[1] <= 1.0


def test_episode_mechanism_separates_action_and_opportunity_denominators():
    index = {}
    for date, targets, actions, misses, opportunities in [
        ("d1", 10, 4, 1, 100),
        ("d2", 20, 4, 1, 300),
    ]:
        for rate in (0.0, 0.2):
            index[(date, "leo", rate)] = {
                "catalog_objects_in_episode": targets,
                "sensor_actions": actions,
                "dropout_trials": actions,
                "dropout_misses": 0 if rate == 0 else misses,
                "target_observable_step_count": opportunities,
            }
    result = summarize_episode_mechanism(index, ["d1", "d2"], "leo")
    assert result["mean_geometrically_observable_object_steps"] == 200
    assert result["mean_assigned_observations_20pct_burst"] == 4
    assert result["pooled_realized_dropout_percent_of_assigned_observations"] == 25
    assert result["assigned_observations_as_percent_of_geometric_opportunities"] == 2


def test_episode_mechanism_rejects_unpaired_target_count():
    index = {
        ("d1", "leo", 0.0): {"catalog_objects_in_episode": 1},
        ("d1", "leo", 0.2): {"catalog_objects_in_episode": 2},
    }
    with pytest.raises(ValueError, match="target count"):
        summarize_episode_mechanism(index, ["d1"], "leo")


@pytest.mark.parametrize("values", [np.asarray([1.0]), np.asarray([1.0, np.nan])])
def test_mean_ci_rejects_invalid_date_effects(values):
    with pytest.raises(ValueError):
        mean_ci(values)
