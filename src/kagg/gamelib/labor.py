"""Farm-hand hiring cost - mirrors kaggriculture.py's _fib()/_hire_cost().

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import FARM_HAND_COST_MULT


def _fib(n: int) -> int:
    """Indexed so _fib(0)=1, _fib(1)=1, _fib(2)=2, _fib(3)=3, _fib(4)=5..."""
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hire_cost(n_already_today: int, mult: int = FARM_HAND_COST_MULT) -> int:
    """Cost of the (n_already_today + 1)-th hire today.

    Mirrors kaggriculture.py's _hire_cost(). Resets to fib(0)=1 at the
    start of each day - the caller must pass the current day's
    `hires_today` from farm state, not a running total across days
    (SPEC-gamelib.md "Key subtleties").
    """
    return mult * _fib(n_already_today)
