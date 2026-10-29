import pytest

from midiremap.core.notemap import NoteMap
from midiremap.core.profile import RemapProfile, Rule
from midiremap.storage import Storage, default_root, id_taken, sanitize_id


@pytest.fixture
def st(tmp_path):
    return Storage(tmp_path / 'data')


def test_default_root_is_app_folder():
    assert default_root().name in ('MidiRemap', '.midiremap')


def test_empty_storage_lists_nothing(st):
    assert st.list_maps() == ([], []) and st.list_profiles() == ([], [])


def test_profile_save_load_list_delete(st):
    p = RemapProfile('GM → SD3', rules={36: Rule.map_to(36), 60: Rule.delete()})
    pid = st.save_profile(p)
    assert pid == 'GM → SD3'
    assert (st.profiles_dir / 'GM → SD3.json').is_file()
    assert st.load_profile(pid) == p
    entries, issues = st.list_profiles()
    assert [(e.id, e.name) for e in entries] == [('GM → SD3', 'GM → SD3')] and issues == []
    st.delete_profile(pid)
    assert st.list_profiles() == ([], [])
    with pytest.raises(FileNotFoundError):
        st.delete_profile(pid)


def test_map_save_load_list_delete(st):
    m = NoteMap('Моя карта', {36: 'Бочка', 38: 'Малый', 51: 'Ride', 59: 'Ride'}, order=[38, 36], primary={51})
    mid = st.save_map(m)
    assert (st.maps_dir / 'Моя карта.json').is_file()
    loaded, issues = st.load_map(mid)
    assert issues == [] and loaded == m
    entries, _ = st.list_maps()
    assert [(e.id, e.name, e.legacy) for e in entries] == [('Моя карта', 'Моя карта', False)]
    st.delete_map(mid)
    assert st.list_maps() == ([], [])
    with pytest.raises(FileNotFoundError):
        st.delete_map(mid)
    with pytest.raises(FileNotFoundError):
        st.load_map(mid)


def test_display_name_of_json_map_comes_from_data(st):
    st.save_map(NoteMap('Shown name', {36: 'Kick'}), map_id='file-id')
    entries, _ = st.list_maps()
    assert [(e.id, e.name) for e in entries] == [('file-id', 'Shown name')]


LEGACY_TXT = '# MIDI note/CC name map\r\n38 Snare\r\n36 Kick\r\n'


def test_legacy_txt_map_listed_and_loaded(st):
    st.maps_dir.mkdir(parents=True)
    (st.maps_dir / 'Old.txt').write_bytes(LEGACY_TXT.encode('utf-8'))
    st.save_map(NoteMap('New', {36: 'Kick'}))
    entries, issues = st.list_maps()
    assert issues == []
    assert [(e.id, e.name, e.legacy) for e in entries] == [('New', 'New', False), ('Old', 'Old', True)]
    m, issues = st.load_map('Old')
    assert m.names == {36: 'Kick', 38: 'Snare'} and issues == []


def test_saving_over_legacy_map_writes_json(st):
    st.maps_dir.mkdir(parents=True)
    (st.maps_dir / 'Old.txt').write_bytes(LEGACY_TXT.encode('utf-8'))
    m, _ = st.load_map('Old')
    with pytest.raises(FileExistsError):
        st.save_map(m)
    assert st.save_map(m, overwrite=True) == 'Old'
    assert sorted(p.name for p in st.maps_dir.iterdir()) == ['Old.json']
    entries, _ = st.list_maps()
    assert [(e.id, e.legacy) for e in entries] == [('Old', False)]
    assert st.load_map('Old')[0] == m


def test_json_map_shadows_legacy_txt_with_same_id(st):
    st.save_map(NoteMap('Same', {36: 'From JSON'}))
    (st.maps_dir / 'Same.txt').write_bytes(LEGACY_TXT.encode('utf-8'))
    entries, _ = st.list_maps()
    assert [(e.id, e.legacy) for e in entries] == [('Same', False)]
    assert st.load_map('Same')[0].names == {36: 'From JSON'}
    st.delete_map('Same')
    assert list(st.maps_dir.iterdir()) == []


def test_explicit_id_and_display_name_inside_data(st):
    pid = st.save_profile(RemapProfile('Отображаемое имя'), profile_id='file-id')
    entries, _ = st.list_profiles()
    assert [(e.id, e.name) for e in entries] == [('file-id', 'Отображаемое имя')]
    assert st.load_profile(pid).name == 'Отображаемое имя'


def test_no_overwrite_without_flag(st):
    st.save_profile(RemapProfile('p', rules={36: Rule.keep()}))
    with pytest.raises(FileExistsError):
        st.save_profile(RemapProfile('p'))
    assert st.load_profile('p').rules == {36: Rule.keep()}
    st.save_profile(RemapProfile('p'), overwrite=True)
    assert st.load_profile('p').rules == {}
    st.save_map(NoteMap('m', {36: 'A'}))
    with pytest.raises(FileExistsError):
        st.save_map(NoteMap('m', {36: 'B'}))
    assert not [f for f in st.profiles_dir.iterdir() if f.suffix == '.tmp']


@pytest.mark.parametrize('name, expected', [
    ('a/b\\c:d*e?f"g<h>i|j', 'a_b_c_d_e_f_g_h_i_j'),
    ('  trailing dots... ', 'trailing dots'),
    ('CON', '_CON'),
    ('nul.txt', '_nul.txt'),
    ('Com1', '_Com1'),
    ('COM10', 'COM10'),
    ('Console', 'Console'),
    ('', 'untitled'),
    ('...', 'untitled'),
    ('tab\there', 'tab_here'),
    ('x' * 300, 'x' * 100),
])
def test_sanitize_id(name, expected):
    assert sanitize_id(name) == expected


def test_save_uses_sanitized_name(st):
    pid = st.save_profile(RemapProfile('GM/SD3: v2?'))
    assert pid == 'GM_SD3_ v2_'
    assert st.load_profile(pid).name == 'GM/SD3: v2?'


@pytest.mark.parametrize('bad', ['../evil', 'a/b', 'CON', 'x.', ''])
def test_unsafe_ids_rejected(st, bad):
    with pytest.raises(ValueError):
        st.load_profile(bad)
    with pytest.raises(ValueError):
        st.save_profile(RemapProfile('p'), profile_id=bad)


def test_corrupt_profile_skipped_in_listing(st):
    st.save_profile(RemapProfile('good'))
    (st.profiles_dir / 'broken.json').write_text('{not json', encoding='utf-8')
    (st.profiles_dir / 'future.json').write_text('{"format": 99, "name": "x"}', encoding='utf-8')
    (st.profiles_dir / 'binary.json').write_bytes(b'\xff\xfe\x00garbage')
    (st.profiles_dir / 'notes.txt').write_text('ignored', encoding='utf-8')
    entries, issues = st.list_profiles()
    assert [e.id for e in entries] == ['good']
    assert sorted(i.path.name for i in issues) == ['binary.json', 'broken.json', 'future.json']


def test_garbage_map_does_not_crash_listing(st):
    st.save_map(NoteMap('good', {36: 'Kick'}))
    (st.maps_dir / 'garbage.txt').write_bytes(b'\xff\xfe\x00\x81 garbage')  # парсер снисходителен: карта с ошибками
    (st.maps_dir / 'folder.txt').mkdir()  # не файл — пропускается молча
    (st.maps_dir / 'broken.json').write_text('{not json', encoding='utf-8')
    (st.maps_dir / 'profile.json').write_text('{"format": 1, "name": "p", "rules": []}', encoding='utf-8')
    entries, issues = st.list_maps()
    assert [e.id for e in entries] == ['garbage', 'good']
    assert sorted(i.path.name for i in issues) == ['broken.json', 'profile.json']


def test_id_taken_ignores_case_and_the_renamed_entry():
    ids = ['Kit', 'GM → SD3']
    assert id_taken('kit', ids) and id_taken('  KIT ', ids)
    assert id_taken('GM → SD3', ids) and not id_taken('GM -> SD3', ids)
    assert not id_taken('Kit', ids, exclude_id='kit')  # переименование самой записи
    assert id_taken('a/b', ['a_b'])  # сравнивается ID (имя файла), а не имя


def test_rename_profile_moves_file(st):
    pid = st.save_profile(RemapProfile('Old', rules={36: Rule.keep()}))
    new = RemapProfile('New', rules={36: Rule.keep()})
    assert st.rename_profile(pid, new) == 'New'
    assert [e.id for e in st.list_profiles()[0]] == ['New'] and st.load_profile('New') == new


def test_rename_profile_case_only_keeps_file_and_id(st):
    pid = st.save_profile(RemapProfile('kit'))
    assert st.rename_profile(pid, RemapProfile('Kit')) == 'kit'
    assert [(e.id, e.name) for e in st.list_profiles()[0]] == [('kit', 'Kit')]


def test_rename_onto_existing_fails_and_keeps_old(st):
    st.save_profile(RemapProfile('A'))
    st.save_profile(RemapProfile('B'))
    with pytest.raises(FileExistsError):
        st.rename_profile('A', RemapProfile('B'))
    assert [(e.id, e.name) for e in st.list_profiles()[0]] == [('A', 'A'), ('B', 'B')]


def test_rename_map_moves_file_and_legacy_txt(st):
    st.maps_dir.mkdir(parents=True)
    (st.maps_dir / 'Old.txt').write_text('# MIDI note/CC name map\n36 Kick\n', encoding='utf-8')
    m, _ = st.load_map('Old')
    m.name = 'New'
    assert st.rename_map('Old', m) == 'New'
    assert [e.id for e in st.list_maps()[0]] == ['New'] and not (st.maps_dir / 'Old.txt').exists()
    m.name = 'NEW'
    assert st.rename_map('New', m) == 'New' and st.load_map('New')[0].name == 'NEW'
