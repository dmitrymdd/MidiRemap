"""Раскладка вида профиля «кабелями»: чистый Python, без Qt — покрывается pytest.

Три колонки, две раскладки:
- ПУЛ (PoolLayout, своя прокрутка): неподключённые ноты исходной карты по группам instrument_group. Зачёркнутые
  (delete) — в своей группе, как остальные; ноты с явным keep (старые профили) — с маркером «=» (SourceRow.state);
- СЦЕНА (SceneLayout, общая прокрутка колонок 2 и 3, начинается сверху): подключённые исходные ноты (правило map)
  напротив своей цели и целевая карта — по строке на артикуляцию (имена сравниваются через normalize_name), под
  заголовками групп instrument_group. map на неосновную ноту артикуляции — кабель к той же строке. Высота строки
  цели = max(1, число строк напротив неё): связка 10-в-1 — одна высокая строка цели и десять строк напротив.
  Строка цели показывает номера, на которые реально идут правила (TargetRow.lines): каждый номер — на уровне
  первой строки напротив, чей кабель идёт на него, и кабель приходит на свой номер (53 — 53 читается сразу).
  Неиспользуемые ноты артикуляции — за «+N» (TargetRow.hidden).

Координаты — в строках (y, height) каждой раскладки отдельно; пиксели считает виджет (cable_view.py).

Раскладка строится заново после КАЖДОЙ правки (placement(), порядок не замораживается): подключили — строка
сразу напротив цели; убрали кабель или зачеркнули — сразу в своей группе пула. Пул — по группам и номерам
(зачёркнутые — тоже), напротив каждой цели сначала строки с основным кабелем (primary_pairs), затем остальные по
номеру — номер основного кабеля на строке цели верхний. Чтобы вид не прыгал, прокрутку держит виджет.

Алиасы источника (одно имя на нескольких нотах, normalize_name) в одном месте (пул или строка цели) —
ОДНА строка с несколькими нотами (SourceRow.notes) и одним кабелем; правила при этом по-прежнему по нотам.
Строку можно раскрыть (ключ «<место>|<имя>» в expanded): заголовок алиасов + строка на каждую ноту.
Ноты с разными правилами показываются раскрытыми всегда (SourceRow.mixed).

Подсказки (suggested: нота без правила -> артикуляция цели, совпало имя): строка встаёт напротив своей
цели, как подключённая, с пунктирным кабелем (Cable.suggested) на номер, куда она легла бы (core
plan_suggestions; нужен выбор Write to — кабель на первую строку цели). Применили — кабель становится сплошным
на том же месте; подсказки скрыли — строки возвращаются в пул.

Строка алиасов показывает один номер (SourceRow.shown): ноту, которая идёт на свой же номер (n -> n,
SourceRow.same), иначе — наименьшую; остальные — за «+N». Номера акцентом не выделяются: основную связь
показывает толщина кабеля.

Сворачивание пула: ключи групп «unassigned/<группа>» (POOL_PREFIX). Группы цели — два режима: «только подключённые»
(по умолчанию; видны артикуляции, напротив которых есть строки, группа без них — один заголовок) и «все»
(ключ «target/<группа>» в show_all). Начальное состояние групп цели — initial_show_all(): пока кабелей нет
совсем — все раскрыты; виджет применяет его ОДИН раз, к группам, которых ещё не видел, дальше режим
меняет только пользователь (первый кабель ничего не сворачивает). Заголовок показывает число нот (пул) или
артикуляций (цель).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from ..core.notemap import (
    NoteMap, articulations, display_group, group_sort_key, instrument_group, normalize_name, primary_note,
)
from ..core.profile import RemapProfile, Rule, primary_pairs
from ..core.suggest import plan_suggestions

UNASSIGNED, KEEP, DELETE, MAPPED = "unassigned", "keep", "delete", "map"
MIXED = "mixed"  # заголовок раскрытых алиасов, у нот которых разные правила
POOL_PREFIX, TARGET_PREFIX = UNASSIGNED + "/", "target/"  # ключи групп пула и цели
# служебные ключи групп (не совпадут с normalize_name настоящего инструмента)
MISSING = "\0missing"


@dataclass(frozen=True)
class Placement:
    """Где стоят строки слева. pool: ноты пула в порядке показа (уже по группам);
    slots: ключ цели (slot_key) -> ноты напротив неё. Каждая нота — ровно в одном месте."""
    pool: tuple[int, ...] = ()
    slots: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def place_of(self, note: int) -> tuple[str, str] | None:
        """("pool", "") / ("slot", ключ цели) / None."""
        if note in self.pool:
            return "pool", ""
        for k, notes in self.slots.items():
            if note in notes:
                return "slot", k
        return None


@dataclass(frozen=True)
class Header:
    """Заголовок группы пула или цели (сворачивается по key)."""
    key: str
    label: str
    count: int        # нот в группе пула; артикуляций в группе цели
    collapsed: bool   # пул — свёрнута; цель — часть артикуляций скрыта (режим «только подключённые»)
    y: int
    notes: tuple[int, ...] = ()  # пул: ноты группы; цель: ноты артикуляций группы (drop на группу)
    shown: int | None = None     # цель: артикуляций, напротив которых есть строки


@dataclass(frozen=True)
class SourceRow:
    """Строка слева: одна нота или несколько нот-алиасов (одно имя, одно место, одинаковые правила)."""
    notes: tuple[int, ...]
    name: str | None   # None — ноты нет в исходной карте
    state: str         # UNASSIGNED / KEEP / DELETE / MAPPED — по текущему правилу; MIXED — правила разные
    connected: bool    # есть кабель (map в цель, напротив которой стоит строка); у заголовка — хоть у одной ноты
    block: str | None  # UNASSIGNED — строка пула; None — строка в сцене напротив цели
    y: int
    alias: str | None = None  # ключ раскрытия «<место>|<имя>»: у строки из нескольких нот и у заголовка алиасов
    expanded: bool = False    # заголовок раскрытых алиасов: под ним — строки по нотам (child), кабеля у него нет
    mixed: bool = False       # у нот разные правила — свернуть нельзя
    child: bool = False       # строка ноты под заголовком алиасов
    suggested: bool = False   # подсказка: правила нет, строка напротив предложенной цели (пунктирный кабель)
    number: int | None = None  # показываемый номер (см. shown); None — первая нота
    same: bool = False         # number идёт на свой же номер (n -> n); для выбора shown, НЕ для подсветки

    @property
    def note(self) -> int:
        return self.notes[0]

    @property
    def shown(self) -> int:
        """Номер для показа: у алиасов — нота n -> n или наименьшая."""
        return self.number if self.number is not None else self.notes[0]


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
    lines: tuple[tuple[int, int], ...] = ()  # (смещение строки внутри блока, номер): номера, на которые идут кабели

    @property
    def numbers(self) -> tuple[tuple[int, int], ...]:
        """Номера для показа: использованные; если кабелей нет — Write to (или первая нота) на первой строке."""
        if self.lines:
            return self.lines
        return ((0, self.write_to if self.write_to is not None else self.notes[0]),)

    @property
    def hidden(self) -> int:
        """Нот артикуляции, не показанных номерами (бейдж «+N»)."""
        return len(self.notes) - len(self.numbers)


@dataclass(frozen=True)
class Cable:
    """Кабель строки слева (у строки алиасов — один на все её ноты)."""
    notes: tuple[int, ...]
    dst: int | None  # None — подсказка, которой нужен выбор Write to
    src_y: int
    target: TargetRow
    dst_y: int = 0  # строка номера dst в блоке цели (абсолютная)
    suggested: bool = False  # пунктир: подсказка, правила ещё нет
    primary: bool = False    # основной кабель ноты цели (один на ноту, см. _mark_primary) — толще прочих

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
    placement: Placement   # где стоят строки (по нему построено)

    def source_row(self, note: int) -> SourceRow | None:
        """Строка с нотой в пуле или в сцене (у раскрытых алиасов — строка самой ноты, а не заголовок).
        None — нота в свёрнутой группе."""
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


def _source_group(names: dict[int, str], n: int) -> tuple[str, str]:
    if n not in names:
        return MISSING, "Not in the source map"
    return display_group(names[n])


def _grouped(notes: Iterable[int], names: dict[int, str]) -> list[int]:
    """Ноты по группам: группы — в общем порядке GROUP_ORDER (group_rank подписи), одинаковый ранг — по первой
    (меньшей) ноте; «Other» — после всех, «Not in the source map» — в самом конце."""
    notes = sorted(notes)
    first: dict[str, tuple] = {}
    for n in notes:
        key, label = _source_group(names, n)
        first.setdefault(key, group_sort_key(label, n, last=key == MISSING))

    def key(n: int) -> tuple:
        return first[_source_group(names, n)[0]], n
    return sorted(notes, key=key)


# --- порядок ---

def _wanted_slot(p: RemapProfile, n: int, suggested: Mapping[int, str]) -> str | None:
    """Цель, напротив которой должна стоять нота: по правилу map или по подсказке (нота без правила)."""
    rule = p.rules.get(n)
    if rule is not None and rule.action == "map":
        return slot_key(p.target_map, rule.dst)
    if rule is None and n in suggested:
        return "a:" + suggested[n]
    return None


def _bundle_order(primary: set[int], notes: Iterable[int]) -> tuple[int, ...]:
    """Ноты напротив одной цели: сначала с основным кабелем (primary — их ноты), затем остальные — по номеру."""
    return tuple(sorted(notes, key=lambda n: (n not in primary, n)))


def placement(p: RemapProfile, suggested: Mapping[int, str] = {}) -> Placement:
    """Пул — по группам и номерам, напротив цели — строки с основным кабелем, затем остальные по номерам.
    suggested — подсказки (нота -> артикуляция цели), только для нот без правила."""
    names = p.source_map.names if p.source_map is not None else {}
    pool: list[int] = []
    slots: dict[str, list[int]] = {}
    for n in all_notes(p):
        key = _wanted_slot(p, n, suggested)
        if key is not None:
            slots.setdefault(key, []).append(n)
        else:
            pool.append(n)
    primary = {a for a, _ in primary_pairs(p)} if slots else set()  # один раз, а не на каждую связку
    return Placement(tuple(_grouped(pool, names)), {k: _bundle_order(primary, v) for k, v in slots.items()})


# --- раскладка ---

def _target_groups(p: RemapProfile) -> list[tuple[str | None, str, list[TargetRow]]]:
    """Группы цели (ключ, подпись, строки без координат). Ключ None — плоский список без заголовка."""
    tgt = p.target_map
    rows: list[tuple[str | None, str, TargetRow]] = []
    grouped = tgt is not None and any(instrument_group(v) for v in tgt.names.values())
    if tgt is not None:
        for key, notes in sorted(articulations(tgt).items(), key=lambda kv: kv[1][0]):
            label = tgt.names[notes[0]]
            gkey, glabel = display_group(label) if grouped else (None, "")
            rows.append((gkey, glabel, TargetRow("a:" + key, label, tuple(notes), primary_note(tgt, label),
                                                 True, 0, 1)))
    # номера вне целевой карты — из правил
    extra = {r.dst for r in p.rules.values() if r.action == "map" and (tgt is None or r.dst not in tgt.names)}
    for n in sorted(extra):
        gkey, glabel = (MISSING, "Not in the target map") if grouped else (None, "")
        rows.append((gkey, glabel, TargetRow(f"n:{n}", "", (n,), n, False, 0, 1)))
    groups: dict[str | None, tuple[str, list[TargetRow]]] = {}
    for gkey, glabel, row in rows:
        groups.setdefault(gkey, (glabel, []))[1].append(row)
    # общий порядок групп (GROUP_ORDER, как в пуле); одинаковый ранг — по первой ноте группы
    keys = sorted(groups, key=lambda k: group_sort_key(groups[k][0], groups[k][1][0].notes[0], last=k == MISSING))
    return [(k, groups[k][0], groups[k][1]) for k in keys]


def target_group_keys(p: RemapProfile | None) -> list[str]:
    """Ключи групп цели («target/<группа>») в порядке показа; плоская цель (без групп) — пусто."""
    if p is None:
        return []
    return [TARGET_PREFIX + k for k, _, _ in _target_groups(p) if k is not None]


def initial_show_all(p: RemapProfile | None) -> set[str]:
    """Начальный режим групп цели: ни одного кабеля (правила map; новый профиль) — все группы «все», иначе —
    «только подключённые». Подсказки не в счёт: их строки встают напротив своих целей и в раскрытых группах.
    Только для групп, которых вид ещё не показывал (см. CableEditor)."""
    if p is None or any(r.action == "map" for r in p.rules.values()):
        return set()
    return set(target_group_keys(p))


def build_layout(p: RemapProfile | None, collapsed: Iterable[str] = (), *, show_all: Iterable[str] = (),
                 expanded: Iterable[str] = (), suggested: Mapping[int, str] = {}) -> CableLayout:
    """Раскладки пула и сцены — заново по текущим правилам. collapsed — свёрнутые группы пула; show_all — группы
    цели в режиме «все»; expanded — раскрытые алиасы («<место>|<имя>»); suggested — подсказки (нота ->
    артикуляция цели; ноты с правилом и артикуляции, которых нет в цели, не считаются)."""
    if p is None:
        return CableLayout(PoolLayout([], [], 0), SceneLayout([], [], [], [], 0), Placement())
    planned = plan_suggestions(p, suggested) if suggested else {}
    suggested = {n: a for n, a in suggested.items() if n in planned}
    order = placement(p, suggested)
    expanded = set(expanded)
    ctx = _Ctx(p, suggested, planned)
    return CableLayout(_pool_layout(ctx, order, set(collapsed), expanded),
                       _scene_layout(ctx, order, set(show_all), expanded), order)


@dataclass(frozen=True)
class _Ctx:
    """Профиль и подсказки для построения строк."""
    p: RemapProfile
    suggested: Mapping[int, str]       # нота без правила -> артикуляция цели
    planned: Mapping[int, int | None]  # нота -> куда легла бы подсказка (None — нужен выбор Write to)

    def dst(self, n: int) -> int | None:
        """Куда идёт нота: по правилу map или по подсказке."""
        r = self.p.rules.get(n)
        if r is not None:
            return r.dst if r.action == "map" else None
        return self.planned.get(n)

    def suggested_at(self, n: int, slot: str | None) -> bool:
        return slot is not None and n in self.suggested and "a:" + self.suggested[n] == slot


def _source_row(ctx: _Ctx, notes: list[int], y: int, block: str | None, slot: str | None,
                **extra) -> SourceRow:
    p = ctx.p
    rules = [p.rules.get(n) for n in notes]
    connected = any(r is not None and r.action == "map" and slot == slot_key(p.target_map, r.dst) for r in rules)
    suggested = not connected and all(ctx.suggested_at(n, slot) for n in notes)
    state = note_state(rules[0]) if len(set(rules)) == 1 else MIXED
    names = p.source_map.names if p.source_map is not None else {}
    cabled = (connected or suggested) and not extra.get("expanded")  # у заголовка раскрытых same нет
    same = sorted(n for n in notes if cabled and ctx.dst(n) == n)
    return SourceRow(tuple(notes), names.get(notes[0]), state, connected, block, y, suggested=suggested,
                     number=same[0] if same else min(notes), same=bool(same), **extra)


def _unit_rows(ctx: _Ctx, notes: Iterable[int], y: int, block: str | None, slot: str | None,
               expanded: set[str]) -> list[SourceRow]:
    """Строки одного места (пул или цель): алиасы — одной строкой (на месте первой ноты), раскрытые или
    с разными правилами — заголовок и строки по нотам."""
    p = ctx.p
    names = p.source_map.names if p.source_map is not None else {}
    by_name: dict[str, list[int]] = {}
    for n in notes:
        by_name.setdefault(normalize_name(names[n]) if n in names else f"\0{n}", []).append(n)
    place = block if block is not None else slot
    out: list[SourceRow] = []
    for name, members in by_name.items():
        if len(members) == 1:
            out.append(_source_row(ctx, members, y + len(out), block, slot))
            continue
        key = f"{place}|{name}"
        # разные правила (или подсказки на разные номера) — раскрыто всегда
        mixed = len({(p.rules.get(n), ctx.suggested_at(n, slot) and ctx.planned.get(n)) for n in members}) > 1
        # строка алиасов (и заголовок раскрытых) — на месте первой ноты места, её ноты — по возрастанию;
        # строки нот под заголовком — в порядке места (в связке — основной кабель первым)
        if not mixed and key not in expanded:
            out.append(_source_row(ctx, sorted(members), y + len(out), block, slot, alias=key))
            continue
        out.append(_source_row(ctx, sorted(members), y + len(out), block, slot, alias=key, expanded=True,
                               mixed=mixed))
        for n in members:
            out.append(_source_row(ctx, [n], y + len(out), block, slot, child=True))
    return out


def _pool_layout(ctx: _Ctx, order: Placement, collapsed: set[str], expanded: set[str]) -> PoolLayout:
    """Пул — по группам исходной карты (без групп — плоский список); группы — в порядке order.pool."""
    p = ctx.p
    names = p.source_map.names if p.source_map is not None else {}
    if not any(instrument_group(v) for v in names.values()):
        rows = _unit_rows(ctx, order.pool, 0, UNASSIGNED, None, expanded)
        return PoolLayout([], rows, len(rows))
    groups: dict[str, tuple[str, list[int]]] = {}
    for n in order.pool:
        gkey, glabel = _source_group(names, n)
        groups.setdefault(gkey, (glabel, []))[1].append(n)
    heads: list[Header] = []
    rows: list[SourceRow] = []
    y = 0
    for gkey, (glabel, members) in groups.items():
        key = POOL_PREFIX + gkey
        heads.append(Header(key, glabel, len(members), key in collapsed, y, tuple(members)))
        y += 1
        if key in collapsed:
            continue
        units = _unit_rows(ctx, members, y, UNASSIGNED, None, expanded)
        rows.extend(units)
        y += len(units)
    return PoolLayout(heads, rows, y)


def _mark_primary(cables: list[Cable], pairs: set[tuple[int, int]]) -> list[Cable]:
    """Основной кабель — тот, чья пара (исходная нота, нота цели) есть в primary_pairs() профиля: обратное
    правило ноты цели ведёт назад на эту исходную ноту. Пока обратные правила выводятся из прямых — ровно
    один на ноту цели: n -> n, иначе наименьшая из идущих на неё. Строка алиасов (свёрнутая, «+N») основная, если
    среди её нот есть основная. Подсказки (пунктир) основными не бывают."""
    return [replace(c, primary=True) if not c.suggested and any((n, c.dst) in pairs for n in c.notes) else c
            for c in cables]


def _scene_layout(ctx: _Ctx, order: Placement, show_all: set[str], expanded: set[str]) -> SceneLayout:
    p = ctx.p
    s_rows: list[SourceRow] = []
    t_heads: list[Header] = []
    t_rows: list[TargetRow] = []
    cables: list[Cable] = []
    pairs = primary_pairs(p)
    y = 0
    for gkey, glabel, rows in _target_groups(p):
        visible = rows
        if gkey is not None:
            key = TARGET_PREFIX + gkey
            occupied = [r for r in rows if order.slots.get(r.slot)]
            if key not in show_all:
                visible = occupied
            notes = tuple(sorted(n for r in rows if r.in_map for n in r.notes))
            t_heads.append(Header(key, glabel, len(rows), len(visible) < len(rows), y, notes,
                                  shown=len(occupied)))
            y += 1
        for r in visible:
            units = _unit_rows(ctx, order.slots.get(r.slot, ()), y, None, r.slot, expanded)
            cabled = [row for row in units if (row.connected or row.suggested) and not row.expanded]
            first: dict[int, int] = {}  # номер -> смещение первой строки, чей кабель идёт на него
            for row in cabled:
                dst = ctx.dst(row.shown)
                if dst is not None:
                    first.setdefault(dst, row.y - y)
            lines = tuple(sorted((off, dst) for dst, off in first.items()))
            placed = TargetRow(r.slot, r.label, r.notes, r.write_to, r.in_map, y, max(1, len(units)), lines)
            t_rows.append(placed)
            s_rows.extend(units)
            slot_cables = []
            for row in cabled:
                dst = ctx.dst(row.shown)
                slot_cables.append(Cable(row.notes, dst, row.y, placed, y + first.get(dst, 0), row.suggested))
            cables.extend(_mark_primary(slot_cables, pairs))
            y += placed.height
    return SceneLayout(s_rows, t_heads, t_rows, cables, y)
