"""Unit tests for tile_distance() and land_price() - see SPEC-gamelib.md.

Both are simple enough not to need a randomized property-test oracle per
SPEC-gamelib.md's own "Testing (unit, no oracle needed)" section, but
land_price() additionally gets a real cross-check against _do_buy_land
since that costs nothing extra and catches an off-by-one for free.
"""

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.farm import land_price, tile_distance


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
