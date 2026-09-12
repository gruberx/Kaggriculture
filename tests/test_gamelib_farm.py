"""Unit tests for tile_distance() and land_price() - see SPEC-gamelib.md.

Both are simple enough not to need a randomized property-test oracle per
SPEC-gamelib.md's own "Testing (unit, no oracle needed)" section, but
land_price() additionally gets a real cross-check against _do_buy_land
since that costs nothing extra and catches an off-by-one for free.
"""

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.farm import land_price, shed_access_tiles, shed_distance, tile_distance


def test_tile_distance_is_zero_on_identity():
    assert tile_distance((4, 4), (4, 4)) == 0


def test_tile_distance_is_symmetric():
    assert tile_distance((1, 2), (7, 9)) == tile_distance((7, 9), (1, 2))


def test_tile_distance_opposite_corners_of_a_10x10_board():
    assert tile_distance((0, 0), (9, 9)) == 18


def test_tile_distance_matches_manhattan_formula():
    assert tile_distance((2, 3), (5, 8)) == abs(5 - 2) + abs(8 - 3)


def test_land_price_matches_real_do_buy_land_charges():
    board_size = 10
    farm = real._new_farm(board_size, starting_money=10_000)
    charged = []
    for n_unlocked_extra in range(4):  # 3 real purchases, then one no-op
        price = land_price(n_unlocked_extra)
        money_before = farm["money"]
        real._do_buy_land(farm, board_size)
        charged.append(money_before - farm["money"])
        assert charged[-1] == (price or 0)


def test_land_price_returns_none_once_all_quadrants_bought():
    assert land_price(3) is None
    assert land_price(4) is None


def test_land_price_matches_documented_prices():
    assert land_price(0) == 1000
    assert land_price(1) == 2000
    assert land_price(2) == 4000


def test_shed_access_tiles_matches_the_real_interpreter():
    # Found needed while implementing T6.4: PICKUP/PLACE/FEED all key off
    # standing on one of these exact tiles (_is_shed_adjacent), so this
    # must match kaggriculture.py's own _shed_access_tiles precisely, not
    # just "somewhere near the shed."
    assert shed_access_tiles(10) == real._shed_access_tiles(10)


def test_shed_access_tiles_are_the_board_center():
    assert set(shed_access_tiles(10)) == {(4, 4), (5, 4), (4, 5), (5, 5)}


def test_shed_distance_is_zero_on_a_shed_access_tile():
    for tile in shed_access_tiles(10):
        assert shed_distance(tile, 10) == 0


def test_shed_distance_is_the_min_over_all_four_access_tiles():
    # (0, 4) is distance 4 from (4,4) but distance 5 from (5,4)/(4,5)/(5,5)
    # - must pick the nearest one, not e.g. always (4,4).
    assert shed_distance((0, 4), 10) == 4


def test_shed_distance_of_the_farthest_nw_corner():
    assert shed_distance((0, 0), 10) == 8


def test_shed_distance_matches_tile_distance_to_the_nearest_access_tile():
    pos = (2, 7)
    board_size = 10
    expected = min(tile_distance(pos, s) for s in shed_access_tiles(board_size))
    assert shed_distance(pos, board_size) == expected
