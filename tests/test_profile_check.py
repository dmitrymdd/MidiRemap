from midiremap.core.notemap import NoteMap
from midiremap.core.profile import (
    DST_NOT_IN_TARGET, KEEP_DIFFERENT, KEEP_NOT_IN_TARGET, NO_RULE, SRC_NOT_IN_SOURCE, ProfileIssue, RemapProfile,
    Rule, keep_issue, validate_profile,
)
from midiremap.core.suggest import apply_suggestions, suggest_rules
from midiremap.templates import load_map_template

SRC = NoteMap('src', {36: 'Kick', 38: 'Snare', 42: 'Hat Closed', 51: 'Ride'})
TGT = NoteMap('tgt', {36: 'kick ', 38: 'Rimshot', 51: 'Ride', 126: 'Ride'})


def codes(issues):
    return [(i.code, i.note) for i in issues]


def test_no_maps_no_map_issues():
    p = RemapProfile('p', rules={1: Rule.keep(), 36: Rule.map_to(127), 60: Rule.delete()})
    assert validate_profile(p) == []


def test_clean_profile():
    p = RemapProfile('p', SRC, TGT, {36: Rule.keep(), 38: Rule.delete(), 42: Rule.map_to(51), 51: Rule.keep()})
    assert validate_profile(p) == []


def test_src_not_in_source_map():
    p = RemapProfile('p', SRC, None, {36: Rule.delete(), 37: Rule.delete(), 40: Rule.map_to(36)})
    assert codes(validate_profile(p)) == [(SRC_NOT_IN_SOURCE, 37), (NO_RULE, 38), (SRC_NOT_IN_SOURCE, 40),
                                          (NO_RULE, 42), (NO_RULE, 51)]


def test_dst_not_in_target_map():
    p = RemapProfile('p', None, TGT, {36: Rule.map_to(35), 38: Rule.map_to(38)})
    issues = validate_profile(p)
    assert issues == [ProfileIssue(DST_NOT_IN_TARGET, 36, 'note 36 is mapped to 35, which is not in the target map')]


def test_map_to_non_primary_note_is_valid():
    tgt = NoteMap('tgt', TGT.names, primary={51})
    p = RemapProfile('p', SRC, tgt, {36: Rule.delete(), 38: Rule.delete(), 42: Rule.map_to(126),
                                     51: Rule.map_to(126)})
    assert validate_profile(p) == []


def test_keep_missing_in_target():
    p = RemapProfile('p', None, TGT, {42: Rule.keep()})
    assert codes(validate_profile(p)) == [(KEEP_NOT_IN_TARGET, 42)]


def test_keep_different_articulation():
    p = RemapProfile('p', SRC, TGT, {36: Rule.keep(), 38: Rule.keep(), 42: Rule.delete(), 51: Rule.keep()})
    issues = validate_profile(p)
    assert codes(issues) == [(KEEP_DIFFERENT, 38)]  # 36: «Kick» и «kick » — одна артикуляция
    assert '"Snare"' in issues[0].message and '"Rimshot"' in issues[0].message


def test_keep_without_source_map_only_checks_presence():
    p = RemapProfile('p', None, TGT, {38: Rule.keep()})
    assert validate_profile(p) == []


def test_keep_of_note_outside_source_map():
    # 126 нет в исходной карте → только SRC_NOT_IN_SOURCE, сравнивать артикуляции не с чем
    p = RemapProfile('p', SRC, TGT, {126: Rule.keep()})
    assert (SRC_NOT_IN_SOURCE, 126) in codes(validate_profile(p))
    assert not [i for i in validate_profile(p) if i.code == KEEP_DIFFERENT]


def test_no_rule_one_issue_per_note():
    p = RemapProfile('p', SRC, TGT, {36: Rule.delete()})
    issues = validate_profile(p)
    assert codes(issues) == [(NO_RULE, 38), (NO_RULE, 42), (NO_RULE, 51)]
    assert issues[0].message == 'note 38 "Snare" has no rule (kept by default)'


def test_several_issues_sorted_by_note():
    p = RemapProfile('p', SRC, TGT, {100: Rule.map_to(101), 42: Rule.keep()})
    assert codes(validate_profile(p)) == [(NO_RULE, 36), (NO_RULE, 38), (KEEP_NOT_IN_TARGET, 42), (NO_RULE, 51),
                                          (SRC_NOT_IN_SOURCE, 100), (DST_NOT_IN_TARGET, 100)]


def test_keep_issue_helper():
    assert keep_issue(SRC, None, 42) is None
    assert keep_issue(SRC, TGT, 36) is None
    assert keep_issue(SRC, TGT, 42).code == KEEP_NOT_IN_TARGET
    assert keep_issue(SRC, TGT, 38).code == KEEP_DIFFERENT
    assert keep_issue(None, TGT, 38) is None


def test_validate_does_not_change_profile():
    p = RemapProfile('p', SRC, TGT, {42: Rule.keep()})
    before = p.to_json()
    validate_profile(p)
    assert p.to_json() == before


def test_templates_ezd3_to_sd3_after_suggestions():
    ezd, sd3 = load_map_template('EZdrummer 3'), load_map_template('Superior Drummer 3')
    suggestions = suggest_rules(ezd, sd3)
    p = apply_suggestions(RemapProfile('EZD3 → SD3', ezd, sd3), suggestions)
    issues = validate_profile(p)
    # правила из подсказок ведут на существующие ноты; без правила — ровно ноты без точной/вероятной подсказки
    assert all(i.code == NO_RULE for i in issues)
    assert [i.note for i in issues] == [s.src for s in suggestions if s.kind in ('ambiguous', 'none')]
