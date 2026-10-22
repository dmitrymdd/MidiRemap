"""Раскладка вида профиля «кабелями» (этап 8b2): чистый Python, без Qt — покрывается pytest.

Три колонки, две раскладки:
- ПУЛ (PoolLayout, своя прокрутка): блоки состояний Unassigned / Keep / Delete, внутри — группы instrument_group
  исходной карты;
- СЦЕНА (SceneLayout, общая прокрутка колонок 2 и 3, начинается сверху): подключённые исходные ноты (правило map)
  напротив своей цели и целевая карта — по строке на артикуляцию (имена сравниваются через normalize_name), под
  заголовками групп instrument_group. map на неосновную ноту артикуляции — кабель к той же строке. Высота строки
  цели = max(1, число строк напротив неё): связка 10-в-1 — одна высокая строка цели и десять строк напротив.

Координаты — в строках (y, height) каждой раскладки отдельно; пиксели считает виджет (cable_view.py).

Порядок ЗАМОРОЖЕН между явными пересортировками (OrderSnapshot):
- подключили (или переподключили к другой цели) — строка сразу уходит из пула и встаёт напротив цели;
- убрали кабель (правило стало keep/delete/пусто) — строка остаётся в сцене на своём месте, без кабеля
  (SourceRow.stale, виджет её приглушает); после пересортировки возвращается в пул;
- сменилось состояние без подключения (напр. удалили в таблице) — строка остаётся в своём блоке пула
  (вид — по текущему правилу).
Полная пересортировка — fresh_order() (или build_layout(..., snapshot=None)).

Алиасы источника (одно имя на нескольких нотах, normalize_name) в одном месте (блок пула или строка цели) —
ОДНА строка с несколькими нотами (SourceRow.notes) и одним кабелем; правила при этом по-прежнему по нотам.
Строку можно раскрыть (ключ «<место>|<имя>» в expanded): заголовок алиасов + строка на каждую ноту.
Ноты с разными правилами показываются раскрытыми всегда (SourceRow.mixed).

Сворачивание пула: ключи — BLOCKS и «<блок>/<группа>». Группы цели — два режима: «только подключённые»
(по умолчанию; видны артикуляции, напротив которых есть строки, группа без них — один заголовок) и «все»
(ключ «target/<группа>» в show_all). Заголовок показывает число нот (пул) или артикуляций (цель).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.notemap import NoteMap, articulations, instrument_group, normalize_name, primary_note
from ..core.profile import RemapProfile, Rule

UNASSIGNED, KEEP, DELETE, MAPPED = "unassigned", "keep", "delete", "map"
MIXED = "mixed"  # заголовок раскрытых алиасов, у нот которых разные правила
BLOCKS = (UNASSIGNED, KEEP, DELETE)
BLOCK_LABELS = {UNASSIGNED: "Unassigned", KEEP: "Keep", DELETE: "Delete"}
DEFAULT_COLLAPSED = frozenset({KEEP, DELETE})

TARGET_PREFIX = "target/"
# служебные ключи групп (не совпадут с normalize_name настоящего инструмента)
OTHER, MISSING = "\0other", "\0missing"


@dataclass(frozen=True)
class OrderSnapshot:
    """Замороженный порядок строк слева. blocks: блок -> ноты в порядке показа (уже по группам);
    slots: ключ цели (slot_key) -> ноты напротив неё. Каждая нота — ровно в одном месте."""
    blocks: dict[str, tuple[int, ...]] = field(default_factory=dict)
    slots: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def place_of(self, note: int) -> tuple[str, str] | None:
        """("block", блок) / ("slot", ключ цели) / None."""
        for b, notes in self.blocks.items():
            if note in notes:
                return "block", b
        for k, notes in self.slots.items():
            if note in notes:
                return "slot", k
        return None


@dataclass(frozen=True)
class Header:
    """Заголовок блока или группы (сворачивается по key)."""
    key: str
    label: str
    count: int        # нот в блоке/группе слева; артикуляций в группе справа
    collapsed: bool   # пул — свёрнут; цель — часть артикуляций скрыта (режим «только подключённые»)
    level: int        # 0 — блок состояния или группа цели, 1 — группа внутри блока
    y: int
    notes: tuple[int, ...] = ()  # пул: ноты блока или группы (правый клик по группе)
    shown: int | None = None     # цель: артикуляций, напротив которых есть строки


@dataclass(frozen=True)
class SourceRow:
    """Строка слева: одна нота или несколько нот-алиасов (одно имя, одно место, одинаковые правила)."""
    notes: tuple[int, ...]
    name: str | None   # None — ноты нет в исходной карте
    state: str         # UNASSIGNED / KEEP / DELETE / MAPPED — по текущему правилу; MIXED — правила разные
    connected: bool    # есть кабель (map в цель, напротив которой стоит строка); у заголовка — хоть у одной ноты
    block: str | None  # блок пула; None — строка в сцене напротив цели
    y: int
    alias: str | None = None  # ключ раскрытия «<место>|<имя>»: у строки из нескольких нот и у заголовка алиасов
    expanded: bool = False    # заголовок раскрытых алиасов: под ним — строки по нотам (child), кабеля у него нет
    mixed: bool = False       # у нот разные правила — свернуть нельзя
    child: bool = False       # строка ноты под заголовком алиасов

    @property
    def note(self) -> int:
        return self.notes[0]

    @property
    def stale(self) -> bool:
        """Строка в сцене, у которой убрали кабель: стоит на месте до пересортировки."""
        return self.block is None and not self.connected


@dataclass(frozen=True)
class TargetRow:
    """Артикуляция целевой карты (или номер вне целевой карты: label пуст, notes = (номер,))."""
    slot: str
    label: str
    notes: tuple[int, ...]
    write_to: int | None  # основная нота (primary_note); None — нот несколько и Write to не выбран
    in_map: bool
    y: int
    height: int


@dataclass(frozen=True)
class Cable:
    """Кабель строки слева (у строки алиасов — один на все её ноты)."""
    notes: tuple[int, ...]
    dst: int
    src_y: int
    target: TargetRow

    @property
    def src(self) -> int:
        return self.notes[0]


@dataclass
class PoolLayout:
    """Колонка 1 — пул (своя прокрутка)."""
    headers: list[Header]
    rows: list[SourceRow]
    height: int


@dataclass
class SceneLayout:
    """Колонки 2 и 3 — подключённые ноты и цель (общая прокрутка, с y = 0)."""
    source_rows: list[SourceRow]
    target_headers: list[Header]
    target_rows: list[TargetRow]
    cables: list[Cable]
    height: int


@dataclass
class CableLayout:
    pool: PoolLayout
    scene: SceneLayout
    order: OrderSnapshot   # порядок, по которому построено (передать в следующий build_layout)

    def source_row(self, note: int) -> SourceRow | None:
        """Строка с нотой в пуле или в сцене (у раскрытых алиасов — строка самой ноты, а не заголовок).
        None — нота в свёрнутом блоке/группе."""
        rows = [r for r in self.pool.rows + self.scene.source_rows if note in r.notes]
        return next((r for r in rows if not r.expanded), rows[0] if rows else None)

    def target_row(self, slot: str) -> TargetRow | None:
        return next((r for r in self.scene.target_rows if r.slot == slot), None)

    def header(self, key: str) -> Header | None:
        return next((h for h in self.pool.headers + self.scene.target_headers if h.key == key), None)


# --- ключи и состояния ---

def slot_key(target_map: NoteMap | None, dst: int) -> str:
    """Строка цели для ноты dst: артикуляция целевой карты или отдельный номер вне карты."""
    if target_map is not None and dst in target_map.names:
        return "a:" + normalize_name(target_map.names[dst])
    return f"n:{dst}"


def note_state(rule: Rule | None) -> str:
    if rule is None:
        return UNASSIGNED
    return {"keep": KEEP, "delete": DELETE, "map": MAPPED}[rule.action]


def all_notes(p: RemapProfile) -> list[int]:
    """Строки слева: ноты исходной карты и ноты с правилами (без исходной карты — только правила)."""
    src = set(p.source_map.names) if p.source_map is not None else set()
    return sorted(src | set(p.rules))


def _slot_valid(key: str, target_map: NoteMap | None, arts: dict[str, list[int]]) -> bool:
    if key.startswith("a:"):
        return key[2:] in arts
    n = int(key[2:])
    return target_map is None or n not in target_map.names


def _source_group(names: dict[int, str], n: int) -> tuple[str, str]:
    if n not in names:
        return MISSING, "Not in the source map"
    g = instrument_group(names[n])
    return (normalize_name(g), g) if g else (OTHER, "Other")


def _grouped(notes: Iterable[int], names: dict[int, str]) -> list[int]:
    """Ноты по группам: группы — по первой (меньшей) ноте, «Other» и «Not in the source map» — в конце."""
    notes = sorted(notes)
    first: dict[str, int] = {}
    for n in notes:
        first.setdefault(_source_group(names, n)[0], n)

    def key(n: int) -> tuple:
        g = _source_group(names, n)[0]
        return g == MISSING, g == OTHER, first[g], n
    return sorted(notes, key=key)


# --- порядок ---

def fresh_order(p: RemapProfile) -> OrderSnapshot:
    """Полная пересортировка: блоки — по группам и номерам, напротив цели — по номерам."""
    names = p.source_map.names if p.source_map is not None else {}
    blocks: dict[str, list[int]] = {b: [] for b in BLOCKS}
    slots: dict[str, list[int]] = {}
    for n in all_notes(p):
        rule = p.rules.get(n)
        if rule is not None and rule.action == "map":
            slots.setdefault(slot_key(p.target_map, rule.dst), []).append(n)
        else:
            blocks[note_state(rule)].append(n)
    return OrderSnapshot({b: tuple(_grouped(v, names)) for b, v in blocks.items()},
                         {k: tuple(v) for k, v in slots.items()})


def update_order(p: RemapProfile, prev: OrderSnapshot | None) -> OrderSnapshot:
    """Замороженный порядок после правок (без пересортировки). prev = None — fresh_order().

    Строка с правилом map не напротив своей цели — переезжает в конец строк этой цели; остальные строки
    остаются на местах. Ноты, которых больше нет, выбрасываются; новые (и стоявшие у исчезнувшей цели) —
    в конец своего блока или своей цели."""
    if prev is None:
        return fresh_order(p)
    tgt = p.target_map
    arts = articulations(tgt) if tgt is not None else {}
    notes = set(all_notes(p))
    seen: set[int] = set()

    def keep_known(seq: Iterable[int]) -> list[int]:
        out = []
        for n in seq:
            if n in notes and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    blocks = {b: keep_known(prev.blocks.get(b, ())) for b in BLOCKS}
    slots = {k: keep_known(v) for k, v in prev.slots.items() if _slot_valid(k, tgt, arts)}
    for n in sorted(notes):
        rule = p.rules.get(n)
        if rule is not None and rule.action == "map":
            key = slot_key(tgt, rule.dst)
            if n in slots.get(key, ()):
                continue
            if n in seen:
                for seq in (*blocks.values(), *slots.values()):
                    if n in seq:
                        seq.remove(n)
                        break
            slots.setdefault(key, []).append(n)
        elif n not in seen:
            blocks[note_state(rule)].append(n)
    return OrderSnapshot({b: tuple(v) for b, v in blocks.items()},
                         {k: tuple(v) for k, v in slots.items() if v})


# --- раскладка ---

def _target_groups(p: RemapProfile, order: OrderSnapshot) -> list[tuple[str | None, str, list[TargetRow]]]:
    """Группы цели (ключ, подпись, строки без координат). Ключ None — плоский список без заголовка."""
    tgt = p.target_map
    rows: list[tuple[str | None, str, TargetRow]] = []
    grouped = tgt is not None and any(instrument_group(v) for v in tgt.names.values())
    if tgt is not None:
        for key, notes in sorted(articulations(tgt).items(), key=lambda kv: kv[1][0]):
            label = tgt.names[notes[0]]
            g = instrument_group(label) if grouped else None
            gkey, glabel = ((normalize_name(g), g) if g else (OTHER, "Other")) if grouped else (None, "")
            rows.append((gkey, glabel, TargetRow("a:" + key, label, tuple(notes), primary_note(tgt, label),
                                                 True, 0, 1)))
    # номера вне целевой карты: из правил и из замороженного порядка
    extra = {int(k[2:]) for k in order.slots if k.startswith("n:")}
    extra |= {r.dst for r in p.rules.values() if r.action == "map" and (tgt is None or r.dst not in tgt.names)}
    for n in sorted(extra):
        gkey, glabel = (MISSING, "Not in the target map") if grouped else (None, "")
        rows.append((gkey, glabel, TargetRow(f"n:{n}", "", (n,), n, False, 0, 1)))
    groups: dict[str | None, tuple[str, list[TargetRow]]] = {}
    for gkey, glabel, row in rows:
        groups.setdefault(gkey, (glabel, []))[1].append(row)
    keys = sorted(groups, key=lambda k: (k == MISSING, k == OTHER))  # устойчиво: иначе — по первой ноте
    return [(k, groups[k][0], groups[k][1]) for k in keys]


def build_layout(p: RemapProfile | None, collapsed: Iterable[str] = DEFAULT_COLLAPSED,
                 snapshot: OrderSnapshot | None = None, show_all: Iterable[str] = (),
                 expanded: Iterable[str] = ()) -> CableLayout:
    """Раскладки пула и сцены. snapshot — порядок прошлой раскладки (layout.order) или None (пересортировать).
    collapsed — свёрнутые блоки и группы пула; show_all — группы цели в режиме «все»; expanded — раскрытые
    алиасы («<место>|<имя>»). Новый порядок — в результате (CableLayout.order)."""
    if p is None:
        return CableLayout(PoolLayout([], [], 0), SceneLayout([], [], [], [], 0), OrderSnapshot())
    order = update_order(p, snapshot)
    expanded = set(expanded)
    return CableLayout(_pool_layout(p, order, set(collapsed), expanded),
                       _scene_layout(p, order, set(show_all), expanded), order)


def _source_row(p: RemapProfile, notes: list[int], y: int, block: str | None, slot: str | None,
                **extra) -> SourceRow:
    rules = [p.rules.get(n) for n in notes]
    connected = any(r is not None and r.action == "map" and slot == slot_key(p.target_map, r.dst) for r in rules)
    state = note_state(rules[0]) if len(set(rules)) == 1 else MIXED
    names = p.source_map.names if p.source_map is not None else {}
    return SourceRow(tuple(notes), names.get(notes[0]), state, connected, block, y, **extra)


def _unit_rows(p: RemapProfile, notes: Iterable[int], y: int, block: str | None, slot: str | None,
               expanded: set[str]) -> list[SourceRow]:
    """Строки одного места (блок или цель): алиасы — одной строкой (на месте первой ноты), раскрытые или
    с разными правилами — заголовок и строки по нотам."""
    names = p.source_map.names if p.source_map is not None else {}
    by_name: dict[str, list[int]] = {}
    for n in notes:
        by_name.setdefault(normalize_name(names[n]) if n in names else f"\0{n}", []).append(n)
    place = block if block is not None else slot
    out: list[SourceRow] = []
    for name, members in by_name.items():
        if len(members) == 1:
            out.append(_source_row(p, members, y + len(out), block, slot))
            continue
        key = f"{place}|{name}"
        mixed = len({p.rules.get(n) for n in members}) > 1
        if not mixed and key not in expanded:
            out.append(_source_row(p, members, y + len(out), block, slot, alias=key))
            continue
        out.append(_source_row(p, members, y + len(out), block, slot, alias=key, expanded=True, mixed=mixed))
        for n in members:
            out.append(_source_row(p, [n], y + len(out), block, slot, child=True))
    return out


def _pool_layout(p: RemapProfile, order: OrderSnapshot, collapsed: set[str], expanded: set[str]) -> PoolLayout:
    names = p.source_map.names if p.source_map is not None else {}
    grouped = any(instrument_group(v) for v in names.values())
    heads: list[Header] = []
    rows: list[SourceRow] = []
    y = 0
    for b in BLOCKS:
        notes = order.blocks.get(b, ())
        if not notes:
            continue
        heads.append(Header(b, BLOCK_LABELS[b], len(notes), b in collapsed, 0, y, tuple(notes)))
        y += 1
        if b in collapsed:
            continue
        groups: dict[str, tuple[str, list[int]]] = {}
        for n in notes:
            gkey, glabel = _source_group(names, n) if grouped else ("", "")
            groups.setdefault(gkey, (glabel, []))[1].append(n)
        for gkey, (glabel, members) in groups.items():
            if grouped:
                key = f"{b}/{gkey}"
                heads.append(Header(key, glabel, len(members), key in collapsed, 1, y, tuple(members)))
                y += 1
                if key in collapsed:
                    continue
            units = _unit_rows(p, members, y, b, None, expanded)
            rows.extend(units)
            y += len(units)
    return PoolLayout(heads, rows, y)


def _scene_layout(p: RemapProfile, order: OrderSnapshot, show_all: set[str], expanded: set[str]) -> SceneLayout:
    s_rows: list[SourceRow] = []
    t_heads: list[Header] = []
    t_rows: list[TargetRow] = []
    cables: list[Cable] = []
    y = 0
    for gkey, glabel, rows in _target_groups(p, order):
        visible = rows
        if gkey is not None:
            key = TARGET_PREFIX + gkey
            occupied = [r for r in rows if order.slots.get(r.slot)]  # и строки без кабеля до пересортировки
            if key not in show_all:
                visible = occupied
            t_heads.append(Header(key, glabel, len(rows), len(visible) < len(rows), 0, y, shown=len(occupied)))
            y += 1
        for r in visible:
            units = _unit_rows(p, order.slots.get(r.slot, ()), y, None, r.slot, expanded)
            placed = TargetRow(r.slot, r.label, r.notes, r.write_to, r.in_map, y, max(1, len(units)))
            t_rows.append(placed)
            for row in units:
                s_rows.append(row)
                if row.connected and not row.expanded:
                    cables.append(Cable(row.notes, p.rules[row.note].dst, row.y, placed))
            y += placed.height
    return SceneLayout(s_rows, t_heads, t_rows, cables, y)
