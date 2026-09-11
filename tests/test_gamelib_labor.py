"""Property test for kagg.gamelib.labor.hire_cost() - see SPEC-gamelib.md.

Imports the real kaggriculture.py as the oracle - allowed only from tests
(gamelib itself never imports kaggle_environments, see SPEC-gamelib.md
"Boundaries specific to this module").
"""

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.labor import hire_cost


def test_hire_cost_matches_real_hire_cost_for_first_twenty_hires():
    for n_already_today in range(20):
        assert hire_cost(n_already_today) == real._hire_cost(n_already_today)


def test_hire_cost_honors_a_custom_multiplier():
    for n_already_today in range(20):
        assert hire_cost(n_already_today, mult=3) == real._hire_cost(n_already_today, mult=3)
