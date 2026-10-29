from midiremap.core.notemap import instrument_group, keyword_group, normalize_name
from midiremap.templates import load_map_template


def test_colon_form_has_priority():
    assert instrument_group("Kick: Hit") == "Kick"
    assert instrument_group("  Hi-Hat :  Open Tip 1 ") == "Hi-Hat"
    assert instrument_group("Snare: Rim: Shot") == "Snare"  # по первому «:»
    assert instrument_group("Floortom 1: Hit") == "Floortom 1"  # префикс, а не ключевое слово «Toms»
    assert instrument_group("Ride: Crash Edge") == "Ride"
    assert instrument_group(": nothing") is None  # пустой префикс — по ключевым словам (не узнали)


def test_keyword_fallback_and_order():
    assert instrument_group("Kick (hit)") == "Kick"  # скобки Guitar Pro 8 — не префикс
    assert instrument_group("Acoustic Bass Drum") == "Kick"  # bass drum — раньше барабанов
    assert instrument_group("Ride Bell") == "Ride"  # не перкуссия
    assert instrument_group("Chinese Cymbal") == "China"  # раньше Cymbal
    assert instrument_group("Crash Cymbal 2") == "Crash"
    assert instrument_group("Reverse Cymbal (hit)") == "Cymbal"
    assert instrument_group("Hi Bongo") == "Percussion"  # «Hi» — не Hi-Hat
    assert instrument_group("Closed Hi Hat") == instrument_group("HiHat open") == "Hi-Hat"
    assert instrument_group("Side Stick") == instrument_group("Rimshot") == instrument_group("Snare rim") == "Snare"
    assert instrument_group("Bottom") is None  # «tom» — только словом
    assert instrument_group("Trim") is None  # «rim» — только словом
    assert instrument_group("Metronome (bell)") is None and instrument_group("") is None
    assert keyword_group("RACK TOM 2") == "Toms"


GM = {
    "Kick": [35, 36], "Snare": [37, 38, 40], "Hi-Hat": [42, 44, 46], "Toms": [41, 43, 45, 47, 48, 50],
    "Crash": [49, 57], "Ride": [51, 53, 59], "China": [52], "Splash": [55],
    "Percussion": [39, 54, 56, 58, *range(60, 82)],
}
GP8 = {
    "Kick": [35, 36], "Snare": [31, 37, 38, 40, 91], "Hi-Hat": [42, 44, 46, 92],
    "Toms": [41, 43, 45, 47, 48, 50], "Crash": [49, 57, 97, 98], "Ride": [29, 51, 53, 59, 93, 94, 126, 127],
    "China": [52, 96], "Splash": [55, 95], "Cymbal": [30, 115, 116], "Other": [33, 34],
    "Percussion": [39, 54, 56, 58, *range(60, 88), 99, 100, 101, 102, 103, *range(104, 115), 117, 118, 119, 120,
                   122, 123, 124, 125],
}


def grouping(template):
    m = load_map_template(template)
    out: dict[str, list[int]] = {}
    for n, name in sorted(m.names.items()):
        out.setdefault(instrument_group(name) or "Other", []).append(n)
    return out


def test_all_general_midi_names():
    assert grouping("General MIDI") == {k: sorted(v) for k, v in GM.items()}


def test_all_guitar_pro_8_names():
    assert grouping("Guitar Pro 8") == {k: sorted(v) for k, v in GP8.items()}


def test_prefixed_templates_unchanged():
    sd3, ezd3 = (load_map_template(t) for t in ("Superior Drummer 3", "EZdrummer 3"))
    for m in (sd3, ezd3):
        assert all(instrument_group(v) == v.partition(":")[0].strip() for v in m.names.values())
    assert instrument_group(sd3.names[36]) == "Kick" and instrument_group(ezd3.names[38]) == "Snare"
    # регистр в именах групп сравнивается через normalize_name
    assert normalize_name(instrument_group("hi-hat: Closed")) == normalize_name(instrument_group(sd3.names[42]))


def test_grancassa_is_orchestral_percussion_not_kit_kick():
    m = load_map_template("Guitar Pro 8")
    assert m.names[114] == "Grancassa (hit)" and instrument_group(m.names[114]) == "Percussion"
    assert [instrument_group(m.names[n]) for n in (35, 36)] == ["Kick", "Kick"]  # «Kick (hit)» — бочка


def test_group_rank_order_for_display():
    from midiremap.core.notemap import GROUP_ORDER, group_rank
    assert GROUP_ORDER == ("Kick", "Snare", "Hi-Hat", "Toms", "Ride", "Crash", "Cymbal", "China", "Splash",
                           "Percussion", "Other")
    ranks = [group_rank(g) for g in ("Kick", "Snare", "Hi-Hat", "Racktom 1", "Floortom 2", "Ride", "Crash 2",
                                     "Cymbal 3", "China", "Splash", "Percussion", "Other")]
    assert ranks == sorted(ranks) and ranks[3] == ranks[4] == GROUP_ORDER.index("Toms")
    assert group_rank("Tambourine") == GROUP_ORDER.index("Percussion")  # по ключевым словам подписи
    assert group_rank("Cymbal 1") == GROUP_ORDER.index("Cymbal")         # SD3: тарелки «Cymbal N» — после Crash
    assert group_rank(None) == group_rank("Metronome") == group_rank("Other") == len(GROUP_ORDER) - 1
