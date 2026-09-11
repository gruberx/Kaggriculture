"""Shed capacity accounting - mirrors kaggriculture.py's
_drop_inventories_to_shed().

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations


def shed_room(shed: dict, capacity: int) -> int:
    """Units of room left in the shed before it hits `capacity`.

    Mirrors the room computation inside _drop_inventories_to_shed
    (kaggriculture.py:843): `current = sum(shed.values())`,
    `room = max(0, capacity - current)`. Never negative, even if the shed
    is already over capacity (possible when several drops each clamp
    individually against capacity within the same end-of-day tick, per
    kaggriculture.py's own inventory-drop loop) - a caller must never read
    a negative result as "please remove items".
    """
    current = sum(shed.values())
    return max(0, capacity - current)
