import copy

from midiremap.core.notemap import NoteMap, articulations, normalize_name
from midiremap.core.profile import RemapProfile, Rule
from midiremap.core.suggest import Suggestion, apply_suggestions, suggest_rules
from midiremap.templates import load_map_template


def maps(target_primary=()):
    src = NoteMap('src', {36: 'Kick', 38: 'snare  center', 42: 'Hat Closed', 51: 'Ride', 49: 'Crash',
                          60: 'Kick', 70: '  '})
    # Ride на трёх нотах, Hat Closed — на двух (с разным регистром), Kick/Snare — по одной
    tgt = NoteMap('tgt', {35: 'Kick', 38: 'Snare Center', 42: 'Hat Closed', 43: 'hat closed',
                          51: 'Ride', 59: 'Ride', 126: 'Ride'}, primary=set(target_primary))
    return src, tgt


def by_src(suggestions):
    return {s.src: s for s in suggestions}


def test_kinds_without_primary():
    src, tgt = maps()
    result = suggest_rules(src, tgt)
    assert [s.src for s in result] == sorted(src.names)
    s = by_src(result)
    assert s[36] == Suggestion(36, 35, 'exact', 'Kick')
    assert s[60] == Suggestion(60, 35, 'exact', 'Kick')  # одно имя на нескольких исходных нотах — многие-в-одну
    assert s[38] == Suggestion(38, 38, 'probable', 'Snare Center')
    assert s[51] == Suggestion(51, None, 'ambiguous', 'Ride')
    assert s[42] == Suggestion(42, None, 'ambiguous', 'Hat Closed')
    assert s[49] == Suggestion(49, None, 'none', None)
    assert s[70] == Suggestion(70, None, 'none', None)  # пустое имя не сопоставляется


def test_primary_resolves_ambiguity():
    src, tgt = maps(target_primary=[59, 43])
    s = by_src(suggest_rules(src, tgt))
    assert s[51] == Suggestion(51, 59, 'exact', 'Ride')
    # основная нота «hat closed» пишется иначе, чем исходное имя → только вероятное совпадение
    assert s[42] == Suggestion(42, 43, 'probable', 'hat closed')


def test_two_primaries_stay_ambiguous():
    src, tgt = maps(target_primary=[51, 59])
    assert by_src(suggest_rules(src, tgt))[51] == Suggestion(51, None, 'ambiguous', 'Ride')


def test_no_fuzzy_matching():
    src = NoteMap('src', {36: 'Kick 1', 38: 'Snare', 40: 'Snr', 49: 'Crash'})
    tgt = NoteMap('tgt', {36: 'Kick', 38: 'Snare Rimshot', 49: 'Crash 1', 50: 'Crsh'})
    assert all(s.kind == 'none' and s.dst is None for s in suggest_rules(src, tgt))


def test_empty_maps():
    assert suggest_rules(NoteMap('a'), NoteMap('b', {36: 'Kick'})) == []
    assert suggest_rules(NoteMap('a', {36: 'Kick'}), NoteMap('b')) == [Suggestion(36, None, 'none', None)]


# --- apply_suggestions ---

def test_apply_adds_only_missing_rules_and_keeps_input():
    src, tgt = maps(target_primary=[59])
    profile = RemapProfile('p', src, tgt, {36: Rule.delete(), 38: Rule.keep(), 60: Rule.map_to(100)})
    before = copy.deepcopy(profile)
    out = apply_suggestions(profile, suggest_rules(src, tgt))
    assert profile == before  # вход не изменён
    assert out is not profile and out.rules is not profile.rules
    assert out.rules == {36: Rule.delete(), 38: Rule.keep(), 60: Rule.map_to(100), 51: Rule.map_to(59)}
    assert out.source_map == src and out.target_map == tgt and out.name == 'p'


def test_apply_kinds_filter():
    src, tgt = maps()
    profile = RemapProfile('p', src, tgt)
    suggestions = suggest_rules(src, tgt)
    assert apply_suggestions(profile, suggestions, kinds=('exact',)).rules == {
        36: Rule.map_to(35), 60: Rule.map_to(35)}
    assert apply_suggestions(profile, suggestions).rules == {
        36: Rule.map_to(35), 60: Rule.map_to(35), 38: Rule.map_to(38)}


def test_ambiguous_and_none_never_produce_rules():
    src, tgt = maps()
    profile = RemapProfile('p', src, tgt)
    out = apply_suggestions(profile, suggest_rules(src, tgt), kinds=('exact', 'probable', 'ambiguous', 'none'))
    assert set(out.rules) == {36, 38, 60}


# --- встроенные шаблоны ---

def test_templates_gp8_to_sd3_no_false_suggestions():
    gp8, sd3 = load_map_template('Guitar Pro 8'), load_map_template('Superior Drummer 3')
    result = suggest_rules(gp8, sd3)
    assert [s.src for s in result] == sorted(gp8.names)
    # в данных шаблонов у GP8 и SD3 нет общих имён (даже после нормализации) → только 'none'
    sd3_names = set(articulations(sd3))
    assert not {normalize_name(n) for n in gp8.names.values()} & sd3_names
    assert all(s.kind == 'none' and s.dst is None for s in result)


def test_templates_ezd3_to_sd3_consistent_with_data():
    ezd, sd3 = load_map_template('EZdrummer 3'), load_map_template('Superior Drummer 3')
    groups = articulations(sd3)
    result = suggest_rules(ezd, sd3)
    assert [s.src for s in result] == sorted(ezd.names)
    for s in result:
        notes = groups.get(normalize_name(ezd.names[s.src]), [])
        if s.kind in ('exact', 'probable'):
            assert notes == [s.dst]  # в шаблонах primary нет → только артикуляции на одной ноте
            assert s.target_name == sd3.names[s.dst]
            assert (sd3.names[s.dst] == ezd.names[s.src]) == (s.kind == 'exact')
        elif s.kind == 'ambiguous':
            assert len(notes) > 1 and s.dst is None and normalize_name(s.target_name) == normalize_name(
                ezd.names[s.src])
        else:
            assert not notes and s.dst is None and s.target_name is None
    kinds = {s.kind for s in result}
    assert {'exact', 'ambiguous', 'none'} <= kinds  # в этой паре есть все три случая
    profile = apply_suggestions(RemapProfile('EZD3 → SD3', ezd, sd3), result)
    assert profile.rules == {s.src: Rule.map_to(s.dst) for s in result if s.kind in ('exact', 'probable')}


# --- подсказки в редакторе профиля: логика назначения (assign_plan) ---

def test_plan_and_apply_suggested_follow_assignment_logic():
    from midiremap.core.suggest import apply_suggested, plan_suggestions, suggestion_targets
    src, tgt = maps()
    src.names.update({44: 'Hat Closed', 59: 'Ride', 126: 'Ride', 80: 'Ride'})
    p = RemapProfile('p', src, tgt, {51: Rule.delete()})
    st = suggestion_targets(src, tgt)
    assert st == {36: 'kick', 60: 'kick', 38: 'snare center', 42: 'hat closed', 44: 'hat closed',
                  51: 'ride', 59: 'ride', 126: 'ride', 80: 'ride'}  # 49 без совпадения, 70 — пустое имя
    # Kick — одна нота цели; Hat Closed: 42 совпала по номеру и молча стала Write to для 44;
    # Ride: совпали две (59, 126) — для 80 нужен вопрос о Write to; у 51 уже есть правило
    assert plan_suggestions(p, st) == {36: 35, 60: 35, 38: 38, 42: 42, 44: 42, 59: 59, 126: 126, 80: None}
    new, done = apply_suggested(p, st)
    assert done == [36, 38, 42, 44, 59, 60, 126]
    assert new.rules[44] == Rule.map_to(42) and 42 in new.target_map.primary
    assert new.rules[59] == Rule.map_to(59) and new.rules[126] == Rule.map_to(126)
    assert 80 not in new.rules and new.rules[51] == Rule.delete()
    assert not new.target_map.primary & {51, 59, 126}  # Write to Ride не выбирали
    assert p.rules == {51: Rule.delete()} and not p.target_map.primary  # вход не меняется
    # артикуляции, которой нет в цели, и ноты с правилом пропускаются
    assert plan_suggestions(p, {36: 'nope', 51: 'ride'}) == {}
