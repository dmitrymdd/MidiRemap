from midiremap.core.notemap import instrument_group, normalize_name
from midiremap.templates import load_map_template


def test_colon_form():
    assert instrument_group("Kick: Hit") == "Kick"
    assert instrument_group("  Hi-Hat :  Open Tip 1 ") == "Hi-Hat"
    assert instrument_group("Snare: Rim: Shot") == "Snare"  # по первому «:»
    assert instrument_group(": nothing") is None


def test_parens_form():
    assert instrument_group("Kick (hit)") == "Kick"
    assert instrument_group("Ride (middle)  ") == "Ride"
    assert instrument_group("(hit)") is None
    assert instrument_group("Snare (side) stick") is None  # скобка не в конце


def test_plain_names():
    assert instrument_group("Acoustic Bass Drum") is None
    assert instrument_group("") is None


def test_templates():
    for tid in ("Superior Drummer 3", "EZdrummer 3", "Guitar Pro 8"):
        m = load_map_template(tid)
        assert all(instrument_group(name) for name in m.names.values()), tid
    gm = load_map_template("General MIDI")
    assert not any(instrument_group(name) for name in gm.names.values())


def test_concrete_template_names():
    sd3, ezd3, gp8 = (load_map_template(t) for t in ("Superior Drummer 3", "EZdrummer 3", "Guitar Pro 8"))
    assert sd3.names[36].startswith("Kick:") and instrument_group(sd3.names[36]) == "Kick"
    assert instrument_group(ezd3.names[38]) == "Snare"
    assert instrument_group(gp8.names[51]) == "Ride"
    assert instrument_group(gp8.names[42]) == "Hi-Hat"
    # регистр в именах групп сравнивается через normalize_name
    assert normalize_name(instrument_group("hi-hat: Closed")) == normalize_name(instrument_group(sd3.names[42]))
