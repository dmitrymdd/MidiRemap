"""Раскладка вида профиля «кабелями» (этап 8b2): чистый Python, без Qt — покрывается pytest.

Слева — исходные ноты: сверху блоки состояний Unassigned / Keep / Delete (внутри — группы instrument_group
исходной карты), ниже — подключённые ноты (правило map) напротив своей цели. Справа — целевая карта: по строке
на артикуляцию (имена сравниваются через normalize_name), под заголовками групп instrument_group. map на
неосновную ноту артикуляции — кабель к той же строке артикуляции. Высота строки цели = max(1, число исходных
строк напротив неё): связка 10-в-1 — одна высокая строка цели и десять строк напротив.

Координаты — в строках (y, height); пиксели считает виджет (cable_view.py).

Порядок ЗАМОРОЖЕН между явными пересортировками (OrderSnapshot):
- строка, у которой убрали кабель (правило стало keep/delete/пусто), остаётся на месте без кабеля;
- строка, которую подключили или переподключили к другой цели, сразу встаёт напротив цели;
- строка, сменившая состояние без подключения, остаётся в своём блоке (вид строки — по текущему правилу).
Полная пересортировка — fresh_order() (или build_layout(..., snapshot=None)).

Сворачивание: ключи — BLOCKS, «<блок>/<группа>», «target/<группа>». Свёрнутый заголовок показывает число;
у свёрнутой группы цели кабели сходятся на её заголовке, а высота заголовка вмещает все строки напротив.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.notemap import NoteMap, articulations, instrument_group, normalize_name, primary_note
from ..core.profile import RemapProfile, Rule

UNASSIGNED, KEEP, DELETE, MAPPED = "unassigned", "keep", "delete", "map"
BLOCKS = (UNASSIGNED, KEEP, DELETE)
BLOCK_LABELS = {UNASSIGNED: "Unassigned", KEEP: "Keep", DELETE: "Delete"}
DEFAULT_COLLAPSED = frozenset({KEEP, DELETE})

TARGET_PREFIX = "target/"
# служебные ключи групп (не совпадут с normalize_name настоящего инструмента)
OTHER, MISSING = "\0other", "\0missing"

GAP = 1  # пустая строка между блоками состояний и подключёнными нотами


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
    collapsed: bool
    level: int        # 0 — блок состояния или группа цели, 1 — группа внутри блока
    y: int
    height: int = 1


@dataclass(frozen=True)
class SourceRow:
    note: int
    name: str | None   # None — ноты нет в исходной карте
    state: str         # UNASSIGNED / KEEP / DELETE / MAPPED — по текущему правилу
    connected: bool    # есть кабель (map в цель, напротив которой стоит строка)
    block: str | None  # блок состояния; None — строка напротив цели
    y: int


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
    src: int
    dst: int
    src_y: int
    target: TargetRow | Header  # Header — свёрнутая группа цели


@dataclass
class CableLayout:
    source_headers: list[Header]
    source_rows: list[SourceRow]
    target_headers: list[Header]
    target_rows: list[TargetRow]
    cables: list[Cable]
    height: int
    connected_top: int     # y первой строки области «напротив цели»
    order: OrderSnapshot   # порядок, по которому построено (передать в следующий build_layout)

    def source_row(self, note: int) -> SourceRow | None:
        return next((r for r in self.source_rows if r.note == note), None)

    def target_row(self, slot: str) -> TargetRow | None:
        return next((r for r in self.target_rows if r.slot == slot), None)

    def header(self, key: str) -> Header | None:
        return next((h for h in self.source_headers + self.target_headers if h.key == key), None)


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
                 snapshot: OrderSnapshot | None = None) -> CableLayout:
    """Раскладка обеих колонок и кабелей. snapshot — порядок прошлой раскладки (layout.order) или None
    (пересортировать). Новый порядок — в результате (CableLayout.order)."""
    if p is None:
        return CableLayout([], [], [], [], [], 0, 0, OrderSnapshot())
    collapsed = set(collapsed)
    order = update_order(p, snapshot)
    names = p.source_map.names if p.source_map is not None else {}
    src_grouped = any(instrument_group(v) for v in names.values())
    tgt = p.target_map

    def source_row(n: int, y: int, block: str | None, slot: str | None) -> SourceRow:
        rule = p.rules.get(n)
        connected = rule is not None and rule.action == "map" and slot == slot_key(tgt, rule.dst)
        return SourceRow(n, names.get(n), note_state(rule), connected, block, y)

    s_heads: list[Header] = []
    s_rows: list[SourceRow] = []
    y = 0
    for b in BLOCKS:
        notes = order.blocks.get(b, ())
        if not notes:
            continue
        s_heads.append(Header(b, BLOCK_LABELS[b], len(notes), b in collapsed, 0, y))
        y += 1
        if b in collapsed:
            continue
        groups: dict[str, tuple[str, list[int]]] = {}
        for n in notes:
            gkey, glabel = _source_group(names, n) if src_grouped else ("", "")
            groups.setdefault(gkey, (glabel, []))[1].append(n)
        for gkey, (glabel, members) in groups.items():
            if src_grouped:
                key = f"{b}/{gkey}"
                s_heads.append(Header(key, glabel, len(members), key in collapsed, 1, y))
                y += 1
                if key in collapsed:
                    continue
            for n in members:
                s_rows.append(source_row(n, y, b, None))
                y += 1
    if y and order.slots:
        y += GAP
    connected_top = y

    t_heads: list[Header] = []
    t_rows: list[TargetRow] = []
    cables: list[Cable] = []
    for gkey, glabel, rows in _target_groups(p, order):
        if gkey is not None:
            key = TARGET_PREFIX + gkey
            if key in collapsed:
                members = [(n, r.slot) for r in rows for n in order.slots.get(r.slot, ())]
                head = Header(key, glabel, len(rows), True, 0, y, max(1, len(members)))
                t_heads.append(head)
                for i, (n, slot) in enumerate(members):
                    row = source_row(n, y + i, None, slot)
                    s_rows.append(row)
                    if row.connected:
                        cables.append(Cable(n, p.rules[n].dst, row.y, head))
                y += head.height
                continue
            t_heads.append(Header(key, glabel, len(rows), False, 0, y))
            y += 1
        for r in rows:
            members = order.slots.get(r.slot, ())
            placed = TargetRow(r.slot, r.label, r.notes, r.write_to, r.in_map, y, max(1, len(members)))
            t_rows.append(placed)
            for i, n in enumerate(members):
                row = source_row(n, y + i, None, r.slot)
                s_rows.append(row)
                if row.connected:
                    cables.append(Cable(n, p.rules[n].dst, row.y, placed))
            y += placed.height
    return CableLayout(s_heads, s_rows, t_heads, t_rows, cables, y, connected_top, order)
