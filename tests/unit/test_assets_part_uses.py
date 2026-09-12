"""A wear part measured in uses: field validation and the derived predicates."""

import hk_assets as assets
import pytest


def _part(**extra):
    return assets._normalize_part({"id": "p1", "name": "DWR", "type": "wear", **extra})


def _counted(target=25, **extra):
    return _part(replace_interval=target, replace_unit="uses", **extra)


# ── replace_unit ──────────────────────────────────────────────────────────────
def test_uses_is_a_valid_replace_unit():
    assert _counted()["replace_unit"] == "uses"


def test_the_time_units_still_work():
    assert _part(replace_interval=12, replace_unit="months")["replace_unit"] == "months"


def test_an_unknown_replace_unit_is_refused():
    with pytest.raises(assets.AssetValidationError, match="invalid replace_unit"):
        _part(replace_interval=12, replace_unit="hikes")


def test_uses_is_not_a_valid_task_unit():
    """PART_REPLACE_UNITS and UNITS differ by exactly this value.

    Widening UNITS instead would make ``recurrence_type: "floating", unit: "uses"`` a
    valid task that no branch of ``compute_next_due`` can compute.
    """
    from hk_const import PART_REPLACE_UNITS, UNITS

    assert "uses" in PART_REPLACE_UNITS
    assert "uses" not in UNITS


# ── the target ceiling ────────────────────────────────────────────────────────
def test_a_uses_target_is_capped():
    """``recurrence._record_entry`` trims every completion list to 500, blindly.

    A larger target loses the entries its own count is derived from and reads low
    forever, with nothing on any surface to say why.
    """
    with pytest.raises(assets.AssetValidationError, match="counted in uses"):
        _counted(target=251)


def test_the_ceiling_itself_is_accepted():
    assert _counted(target=250)["replace_interval"] == 250


def test_a_time_measured_interval_is_not_capped_at_the_use_ceiling():
    assert _part(replace_interval=500, replace_unit="months")["replace_interval"] == 500


def test_two_targets_worth_of_retention_fits_inside_the_global_cap():
    from hk_const import MAX_COMPLETION_HISTORY

    assert assets.use_retention_cap(_counted(target=250)) == MAX_COMPLETION_HISTORY


# ── the time backstop ─────────────────────────────────────────────────────────
def test_a_backstop_is_stored_beside_a_count():
    part = _counted(replace_also_every={"interval": 12, "unit": "months"})
    assert part["replace_also_every"] == {"interval": 12, "unit": "months"}


def test_a_backstop_defaults_its_interval_to_one():
    part = _counted(replace_also_every={"unit": "months"})
    assert part["replace_also_every"] == {"interval": 1, "unit": "months"}


def test_a_backstop_unit_must_be_a_time_unit():
    with pytest.raises(assets.AssetValidationError, match=r"also_every\.unit"):
        _counted(replace_also_every={"interval": 2, "unit": "uses"})


def test_a_backstop_interval_must_be_positive():
    with pytest.raises(assets.AssetValidationError, match="must be >= 1"):
        _counted(replace_also_every={"interval": 0, "unit": "months"})


def test_a_backstop_beside_a_time_measured_part_is_cleared_not_refused():
    """Switching the unit back to months must not fail the save with an error about a
    control the form just hid."""
    part = _part(
        replace_interval=12,
        replace_unit="months",
        replace_also_every={"interval": 6, "unit": "months"},
    )
    assert part["replace_also_every"] is None


def test_no_backstop_is_none():
    assert _counted()["replace_also_every"] is None


# ── the action ────────────────────────────────────────────────────────────────
def test_the_default_action_is_replace():
    assert _part()["action"] == "replace"


@pytest.mark.parametrize(
    "action", ["replace", "clean", "service", "renew", "sharpen", "rotate", "inspect"]
)
def test_every_shipped_action_is_accepted(action):
    assert _part(action=action)["action"] == action


def test_an_unknown_action_is_refused():
    with pytest.raises(assets.AssetValidationError, match="invalid part action"):
        _part(action="polish")


# ── the use noun and name ─────────────────────────────────────────────────────
def test_a_use_noun_is_kept():
    assert _counted(use_noun="wear")["use_noun"] == "wear"


def test_a_use_noun_is_stripped():
    assert _counted(use_noun="  hike  ")["use_noun"] == "hike"


def test_a_long_use_noun_is_refused():
    with pytest.raises(assets.AssetValidationError, match="use_noun"):
        _counted(use_noun="x" * 17)


def test_an_absent_use_noun_is_empty_not_english():
    """The fallback word is localized, and the panel is the surface with the
    viewer's language."""
    assert _counted()["use_noun"] == ""
    assert assets.part_use_noun(_counted()) == ""


def test_a_use_task_name_override_is_kept():
    assert _counted(use_task_name="Wear rain jacket")["use_task_name"] == (
        "Wear rain jacket"
    )


# ── the carried count ─────────────────────────────────────────────────────────
def test_a_carried_count_is_kept():
    assert _counted(carried_uses=24)["carried_uses"] == 24


def test_an_absent_carried_count_is_zero():
    assert _counted()["carried_uses"] == 0
    assert assets.part_carried_uses(_counted()) == 0


def test_a_carried_count_of_text_is_refused():
    with pytest.raises(assets.AssetValidationError, match="carried_uses"):
        _counted(carried_uses="two dozen")


@pytest.mark.parametrize("stated", [-1, -1.5, -0.5, -0.999])
def test_a_negative_carried_count_is_refused(stated):
    """A fraction below zero is refused too, which needed ``floor`` over ``int``.

    ``int`` truncates toward zero, so -0.5 arrived at the guard as 0 and was accepted
    while -1 was refused. One wrong file, answered 2 ways, and the half that passed
    said nothing at all.
    """
    with pytest.raises(assets.AssetValidationError, match="carried_uses must be >= 0"):
        _counted(carried_uses=stated)


def test_a_carried_count_above_the_history_cap_is_refused():
    """``recurrence._record_entry`` trims every completion log to 500 on every write.

    A carry above that is a figure Home Keeper could never have produced, so the file
    that states one is wrong rather than merely large.
    """
    with pytest.raises(
        assets.AssetValidationError, match="carried_uses must be <= 500"
    ):
        _counted(carried_uses=501)


def test_the_history_cap_itself_is_accepted():
    """The ceiling is MAX_COMPLETION_HISTORY, not the 250 use target: a household can
    let a count run past its target."""
    assert _counted(carried_uses=500)["carried_uses"] == 500


def test_a_boolean_carried_count_is_refused():
    """``True`` is an ``int`` in Python, so only the boolean guard refuses it."""
    with pytest.raises(assets.AssetValidationError, match="carried_uses"):
        _counted(carried_uses=True)


@pytest.mark.parametrize(
    ("stated", "kept"),
    [
        (0, 0),  # a stated zero, which is not the same input as an absent key
        ("24", 24),  # the text a YAML file holds, matching _PART_SCHEMA's Coerce(int)
        (24.5, 24),  # a fraction of a use is not a use
        (24.999, 24),
    ],
)
def test_a_carried_count_takes_the_shapes_a_hand_written_file_holds(stated, kept):
    """Coerced, and truncated toward zero, like every other whole-number part field.

    Worth stating rather than leaving to ``int()``: a file written by hand or by an
    assistant is the case this field exists for, and `"24"` is what YAML gives for a
    quoted number. Truncation is the same rule ``replace_also_every.interval`` uses,
    so a count never lands between 2 uses.
    """
    assert _counted(carried_uses=stated)["carried_uses"] == kept


# ── the predicates ────────────────────────────────────────────────────────────
def test_part_counts_uses():
    assert assets.part_counts_uses(_counted()) is True


def test_a_time_measured_wear_part_does_not_count_uses():
    assert (
        assets.part_counts_uses(_part(replace_interval=12, replace_unit="months"))
        is False
    )


def test_a_wear_part_with_no_target_does_not_count_uses():
    assert assets.part_counts_uses(_part()) is False


def test_a_consumable_with_a_uses_unit_does_not_count_uses():
    """Every condition has to hold, so a stray unit on a consumable is inert."""
    part = assets._normalize_part(
        {
            "id": "p1",
            "name": "Filter",
            "type": "consumable",
            "replace_interval": 25,
            "replace_unit": "uses",
        }
    )
    assert assets.part_counts_uses(part) is False


def test_part_use_target():
    assert assets.part_use_target(_counted(target=40)) == 40


def test_part_action_falls_back_for_a_stored_junk_value():
    assert assets.part_action({"action": "polish"}) == "replace"


def test_part_replace_backstop_is_none_for_a_time_measured_part():
    part = _part(replace_interval=12, replace_unit="months")
    assert assets.part_replace_backstop(part) is None


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (1, 50),  # the floor
        (10, 50),  # 2 x 10 is still under the floor
        (25, 50),  # 2 x 25 lands exactly on it
        (100, 200),  # 2 x target
        (250, 500),  # the ceiling, which is the global completion cap
    ],
)
def test_retention_cap_scales_with_the_target(target, expected):
    assert assets.use_retention_cap(_counted(target=target)) == expected
