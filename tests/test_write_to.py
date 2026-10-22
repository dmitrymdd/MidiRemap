"""with_write_to(): выбор Write to в копии целевой карты профиля и перенаправление правил map."""
import pytest

from midiremap.core.notemap import NoteMap, validate_map
from midiremap.core.profile import RemapProfile, Rule, with_write_to

SRC = NoteMap("src", {36: "Kick", 38: "Snare", 40: "Rim", 51: "Ride", 53: "Bell"})
TGT = NoteMap("tgt", {36: "Kick", 38: "Snare", 39: "snare ", 40: "Snare", 51: "Ride"}, primary={38})


def test_sets_primary_and_repoints_all_rules_of_the_articulation():
    p = RemapProfile("p", SRC, TGT, {38: Rule.map_to(38), 40: Rule.map_to(39), 36: Rule.map_to(36),
                                     51: Rule.keep(), 53: Rule.delete()})
    out = with_write_to(p, 40)
    assert out.target_map.primary == {40}
    assert out.rules == {38: Rule.map_to(40), 40: Rule.map_to(40), 36: Rule.map_to(36),
                         51: Rule.keep(), 53: Rule.delete()}
    assert validate_map(out.target_map) == []
    # входной профиль не меняется
    assert p.target_map.primary == {38} and p.rules[38] == Rule.map_to(38)


def test_keeps_other_primaries_and_meta_status():
    tgt = NoteMap("tgt", {**TGT.names, 50: "Ride", 52: "Ride"}, primary={38, 50})
    out = with_write_to(RemapProfile("p", None, tgt), 52)
    assert out.target_map.primary == {38, 52}
    assert out.target_map.meta == tgt.meta


def test_single_note_articulation_needs_no_flag():
    out = with_write_to(RemapProfile("p", SRC, TGT, {36: Rule.map_to(36)}), 36)
    assert out.target_map.primary == {38} and out.rules == {36: Rule.map_to(36)}


def test_note_outside_target_map():
    with pytest.raises(ValueError):
        with_write_to(RemapProfile("p", SRC, TGT), 99)
    with pytest.raises(ValueError):
        with_write_to(RemapProfile("p", SRC, None), 36)
