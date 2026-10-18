import pytest

from midiremap.core.notemap import NoteMap
from midiremap.core.profile import RemapProfile, Rule
from midiremap.storage import Storage, default_root, sanitize_id


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
    m = NoteMap('Моя карта', {36: 'Бочка', 38: 'Малый'}, order=[38, 36])
    mid = st.save_map(m)
    loaded, issues = st.load_map(mid)
    assert issues == [] and loaded == m
    entries, _ = st.list_maps()
    assert [(e.id, e.name) for e in entries] == [('Моя карта', 'Моя карта')]
    st.delete_map(mid)
    assert st.list_maps() == ([], [])


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
    entries, issues = st.list_maps()
    assert [e.id for e in entries] == ['garbage', 'good'] and issues == []
