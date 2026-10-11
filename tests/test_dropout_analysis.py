import pytest

from scripts.analyze_dropout import moving_block_interval, paired_differences


def row(model_seed, replicate, value):
    return {'model_seed': model_seed, 'replicate': replicate, 'custody_continuity': value}


def test_paired_differences_match_within_each_model_checkpoint():
    baseline = [row(101, 0, 0.1), row(503, 0, 0.9)]
    treatment = [row(101, 0, 0.0), row(503, 0, 0.4)]

    assert paired_differences(treatment, baseline, 'custody_continuity') == pytest.approx([-0.1, -0.5])


def test_paired_differences_reject_missing_checkpoint_pairs():
    with pytest.raises(ValueError, match='matching model-seed/replicate pairs'):
        paired_differences([row(101, 0, 0.1)], [row(503, 0, 0.2)], 'custody_continuity')


def test_paired_differences_reject_duplicate_checkpoint_pairs():
    with pytest.raises(ValueError, match='duplicate model-seed/replicate pair'):
        paired_differences(
            [row(101, 0, 0.1), row(101, 0, 0.2)],
            [row(101, 0, 0.3)],
            'custody_continuity',
        )


def test_moving_block_interval_is_reproducible_and_keeps_constant_series_exact():
    first = moving_block_interval([0.25] * 48, block_length=6, samples=500, seed=42)
    second = moving_block_interval([0.25] * 48, block_length=6, samples=500, seed=42)

    assert first == second == (0.25, 0.25)


def test_moving_block_interval_rejects_block_longer_than_series():
    with pytest.raises(ValueError, match='positive and in range'):
        moving_block_interval([1.0, 2.0], block_length=3)
