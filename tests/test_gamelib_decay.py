"""Property test for kagg.gamelib.decay.decay_step() - see SPEC-gamelib.md.

Drives the real _decay_plants against a synthetic tile (only the fields it
actually reads: kind, max_lifespan_step, yield_units) and checks whether
yield_units drops by exactly 1 at a given step, compared to decay_step()'s
boolean.
"""

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.decay import decay_step

_BOARD_SIZE = 10
_STARTING_YIELD = 10  # comfortably above 0, so weed-conversion never
# triggers within this test's step range and each check is isolated.


def _real_decay_fires(max_lifespan_step: int, step: int) -> bool:
    farm = real._new_farm(_BOARD_SIZE, starting_money=3000)
    fx, fy = farm["farmer"]
    farm["tiles"][fy][fx] = {
        "kind": "PLANT",
        "max_lifespan_step": max_lifespan_step,
        "yield_units": _STARTING_YIELD,
    }
    real._decay_plants(farm, step)
    return farm["tiles"][fy][fx]["yield_units"] < _STARTING_YIELD


def test_decay_step_never_fires_for_ongoing_crops_negative_mls():
    for step in [0, 1, 100, 10_000]:
        assert decay_step(max_lifespan_step=-1, step=step) is False
        assert _real_decay_fires(-1, step) is False


def test_decay_step_matches_real_decay_plants():
    for max_lifespan_step in [0, 1, 50, 96, 240]:
        for offset in range(-3, 12):
            step = max_lifespan_step + offset
            if step < 0:
                continue
            expected = _real_decay_fires(max_lifespan_step, step)
            actual = decay_step(max_lifespan_step, step)
            assert actual == expected, (max_lifespan_step, step)
