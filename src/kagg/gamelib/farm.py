"""Farm geometry and land-expansion pricing.

tile_distance mirrors the movement model implied by FARMER_MOVES
(kaggriculture.py:88 - one of NORTH/SOUTH/EAST/WEST per turn, so distance
is Manhattan, not Euclidean or Chebyshev). land_price mirrors _do_buy_land
(kaggriculture.py:712).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import LAND_ORDER, LAND_PRICES


def tile_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Manhattan distance between two (x, y) board coordinates - the
    number of turns a farmer/hand needs to move from `a` to `b`, one
    orthogonal step per turn (FARMER_MOVES has no diagonal)."""
    ax, ay = a
    bx, by = b
    return abs(ax - bx) + abs(ay - by)


def shed_access_tiles(board_size: int) -> list[tuple[int, int]]:
    """The four inner-corner tiles around the shed (one per quadrant's
    corner touching the board's exact center), in NWSE order - mirrors
    kaggriculture.py's `_shed_access_tiles`. PICKUP/PLACE (see
    kaggriculture.py's `_is_shed_adjacent`) and the shed-drop branch of
    PLACE all require standing on exactly one of these tiles."""
    half = board_size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]


def land_price(n_unlocked_extra: int) -> int | None:
    """Cost of the next quadrant beyond NW, given how many extra quadrants
    (NE/SW/SE) are already unlocked. `None` once all three are bought -
    mirrors _do_buy_land's `n_unlocked_extra >= len(LAND_ORDER)` guard,
    which no-ops rather than erroring past that point.
    """
    if n_unlocked_extra >= len(LAND_ORDER):
        return None
    return LAND_PRICES[n_unlocked_extra]
