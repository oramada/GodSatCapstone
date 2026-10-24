import numpy as np

from scripts.audit_dust_gap_image_visibility import (
    auc, benjamini_hochberg, local_contrast, session_bootstrap_mean_ci,
)


def test_local_contrast_detects_inserted_point_and_clips_at_image_edge():
    background = np.full((32, 32), 20, dtype=np.uint8)
    background[16, 16] = 220
    centered = local_contrast(background, 16, 16, search_radius=0)
    edge = local_contrast(background, 1, 1, search_radius=0)
    assert centered > 10
    assert edge is not None


def test_auc_handles_ties_as_half_credit():
    assert auc([2, 3], [1, 2]) == 0.875


def test_benjamini_hochberg_adjustment_preserves_input_order_and_monotonicity():
    adjusted = benjamini_hochberg([0.04, 0.01, 0.03])
    assert np.allclose(adjusted, [0.04, 0.03, 0.04])


def test_session_bootstrap_is_reproducible_and_returns_bounded_interval():
    values = [0.2, 0.4, 0.6, 0.8]
    left = session_bootstrap_mean_ci(values, seed=12, replicates=1000)
    right = session_bootstrap_mean_ci(values, seed=12, replicates=1000)
    assert left == right
    assert 0 <= left[0] <= np.mean(values) <= left[1] <= 1
