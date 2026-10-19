import importlib.util
from pathlib import Path

import pytest

from midiremap.core.notenames import load_notenames
from midiremap.templates import list_map_templates, load_map_template

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / 'src' / 'midiremap' / 'templates' / 'maps'


def _builder():
    spec = importlib.util.spec_from_file_location('build_map_templates', ROOT / 'tools' / 'build_map_templates.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_template_files_match_generator():
    """Файлы шаблонов = результат tools/build_map_templates.py (из samples/maps и метаданных скрипта)."""
    expected = _builder().build()
    actual = {p.name: p.read_bytes().decode('utf-8') for p in TEMPLATES_DIR.glob('*.json')}
    assert actual == expected


def test_templates_match_samples():
    builder = _builder()
    for name, (sample, _) in builder.TEMPLATES.items():
        src, _ = load_notenames(ROOT / 'samples' / 'maps' / sample)
        t = load_map_template(name)
        assert (t.names, t.order, t.extra_lines) == (src.names, src.order, src.extra_lines)
        assert t.primary == set()  # флагов primary в шаблонах нет: нет исходных данных


def test_template_metadata():
    t = {i: m for i, m in list_map_templates()}
    assert list(t) == ['EZdrummer 3', 'General MIDI', 'Guitar Pro 8', 'Superior Drummer 3']
    assert t['Superior Drummer 3'].meta.status == 'verified'
    assert t['EZdrummer 3'].meta.status == 'verified'
    assert 'not of the EZdrummer 3 plugin' in t['EZdrummer 3'].meta.notes
    assert t['General MIDI'].meta.status == 'unverified'
    assert t['Guitar Pro 8'].meta.status == 'unverified'
    assert len(t['Superior Drummer 3'].names) == len(t['EZdrummer 3'].names) == 122


@pytest.mark.parametrize('bad', ['nope', '../maps/General MIDI', 'a/b'])
def test_unknown_template(bad):
    with pytest.raises(KeyError):
        load_map_template(bad)
