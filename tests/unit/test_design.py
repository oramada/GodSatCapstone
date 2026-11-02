import numpy as np

from godsat.design import ccd, defining_words, fit_surface, screening


def test_pdf_screening_generators_produce_resolution_iv_fraction():
    design, _ = screening(seed=2026)

    assert design.shape == (16, 7)
    assert set(np.unique(design)) == {-1.0, 1.0}
    np.testing.assert_array_equal(design[:, 4], design[:, 0] * design[:, 1] * design[:, 2])
    np.testing.assert_array_equal(design[:, 5], design[:, 0] * design[:, 1] * design[:, 3])
    np.testing.assert_array_equal(design[:, 6], design[:, 0] * design[:, 2] * design[:, 3])

    # Multiplying the three generators E=ABC, F=ABD, G=ACD gives the
    # seven non-identity words below. Every word has length at least four.
    assert defining_words() == [
        "I", "ABCE", "ABDF", "ACDG", "AEFG", "BCFG", "BDEG", "CDEF"
    ]
    assert min(map(len, defining_words()[1:])) == 4


def test_replicated_center_points_estimate_pure_error_for_lack_of_fit():
    design = ccd(center_replicates=5, seed=17)
    x = design[:, :3]
    values = (1.0 + 2.0 * x[:, 0] - x[:, 1] + 0.5 * x[:, 2]
              + 0.3 * x[:, 0] ** 2 + 0.4 * x[:, 1] ** 2
              + 0.2 * x[:, 2] ** 2 + 0.1 * x[:, 0] * x[:, 1])
    centers = np.flatnonzero(np.all(x == 0.0, axis=1))
    values[centers] += np.array([-0.2, -0.1, 0.0, 0.1, 0.2])

    fitted = fit_surface(x, values)

    assert fitted["rank"] == 10
    assert fitted["lack_of_fit"]["pure_error_df"] == 4
    assert fitted["lack_of_fit"]["lack_of_fit_df"] == 5
    assert np.isfinite(fitted["lack_of_fit"]["p_value"])
