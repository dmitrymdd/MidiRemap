"""Профиль ремапа: исходная карта + целевая карта + явные правила (без Qt и без UI)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .legacy_map import NOTE_MAP
from .notemap import (
    NoteMap, articulations, check_note, map_body_from_dict, map_body_to_dict, normalize_name, primary_note,
)

FORMAT_VERSION = 2               # пишется всегда
READ_VERSIONS = (1, 2)           # читаются; у формата 1 нет reverse_rules (выводятся из прямых)

FORWARD, REVERSE = "forward", "reverse"  # направление конвертации
DIRECTIONS = (FORWARD, REVERSE)

Action = Literal["map", "delete", "keep"]
ACTIONS: tuple[str, ...] = ("map", "delete", "keep")


class ProfileFormatError(ValueError):
    """Профиль не читается: не JSON, неизвестная версия формата, битые поля."""


@dataclass(frozen=True)
class Rule:
    """Что сделать с исходной нотой: map — на ноту dst, delete — удалить, keep — оставить на том же номере."""
    action: Action
    dst: int | None = None

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}, expected one of {ACTIONS}")
        if self.action == "map":
            check_note(self.dst, "dst")
        elif self.dst is not None:
            raise ValueError(f"dst is only allowed for the 'map' action, not for {self.action!r}")

    @classmethod
    def map_to(cls, dst: int) -> Rule:
        return cls("map", dst)

    @classmethod
    def delete(cls) -> Rule:
        return cls("delete")

    @classmethod
    def keep(cls) -> Rule:
        return cls("keep")


@dataclass
class RemapProfile:
    """Профиль ремапа. Одно правило на исходную ноту (ключ rules — исходная нота).

    Карты — ВСТРОЕННЫЕ КОПИИ (профиль самодостаточен): при создании они копируются,
    поэтому последующая правка карты в менеджере карт профиль не меняет.
    Обе карты необязательны.

    Двунаправленность: reverse_rules — правила обратного направления, нота ЦЕЛЕВОЙ карты -> нота
    исходной (та же форма Rule). None — не заданы, действуют выведенные из прямых (derive_reverse());
    рабочий набор — effective_reverse(). Прямой кабель a -> b основной, если обратное правило b — b -> a
    (primary_pairs()); отдельного хранения «основного» нет.
    """
    name: str
    source_map: NoteMap | None = None
    target_map: NoteMap | None = None
    rules: dict[int, Rule] = field(default_factory=dict)
    reverse_rules: dict[int, Rule] | None = None

    def __post_init__(self) -> None:
        self.source_map = copy.deepcopy(self.source_map)
        self.target_map = copy.deepcopy(self.target_map)
        self.rules = dict(self.rules)
        if self.reverse_rules is not None:
            self.reverse_rules = dict(self.reverse_rules)
        self.validate()

    def validate(self) -> None:
        for what, rules in (("src", self.rules), ("reverse src", self.reverse_rules or {})):
            for src, rule in rules.items():
                check_note(src, what)
                if not isinstance(rule, Rule):
                    raise TypeError(f"rule for note {src} must be a Rule, got {type(rule).__name__}")

    def effective_reverse(self) -> dict[int, Rule]:
        """Правила обратного направления: заданные или (reverse_rules = None) выведенные из прямых."""
        if self.reverse_rules is not None:
            return dict(self.reverse_rules)
        return derive_reverse(self)

    def reversed(self) -> RemapProfile:
        """Профиль обратного направления: карты поменяны местами, rules — effective_reverse(),
        reverse_rules — прямые правила. Через него обратная сторона переиспользует convert/validate/suggest/assign.

        Инволюция по СОДЕРЖАНИЮ: p.reversed().reversed() даёт те же карты и правила, но при
        reverse_rules = None выведенные правила становятся заданными явно. Поэтому сравнивать — через to_dict()
        (там пишутся действующие правила), а не через ==."""
        return RemapProfile(self.name, self.target_map, self.source_map, self.effective_reverse(), dict(self.rules))

    def oriented(self, direction: str) -> RemapProfile:
        """FORWARD — сам профиль, REVERSE — reversed()."""
        if direction == FORWARD:
            return self
        if direction == REVERSE:
            return self.reversed()
        raise ValueError(f"unknown direction {direction!r}, expected one of {DIRECTIONS}")

    def to_dict(self) -> dict[str, Any]:
        """JSON-объект формата 2; reverse_rules пишутся всегда (действующие — заданные или выведенные)."""
        self.validate()
        return {
            "format": FORMAT_VERSION,
            "name": self.name,
            "source_map": _map_to_dict(self.source_map),
            "target_map": _map_to_dict(self.target_map),
            "rules": _rules_to_list(self.rules),
            "reverse_rules": _rules_to_list(self.effective_reverse()),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: Any) -> RemapProfile:
        if not isinstance(data, dict):
            raise ProfileFormatError("a profile must be a JSON object")
        if "format" not in data:
            raise ProfileFormatError("no 'format' field: this is not a MidiRemap profile")
        version = data["format"]
        if isinstance(version, bool) or version not in READ_VERSIONS:
            supported = ", ".join(map(str, READ_VERSIONS))
            raise ProfileFormatError(f"unsupported profile format version: {version!r} (supported: {supported})")
        try:
            name = data["name"]
            if not isinstance(name, str):
                raise ValueError("'name' must be a string")
            rules = _rules_from_list(data.get("rules", []), "rules")
            raw_reverse = data.get("reverse_rules") if version >= 2 else None
            reverse = None if raw_reverse is None else _rules_from_list(raw_reverse, "reverse_rules")
            p = cls(
                name=name,
                source_map=_map_from_dict(data.get("source_map"), "source_map"),
                target_map=_map_from_dict(data.get("target_map"), "target_map"),
                rules=rules,
            )
            # совпадают с выведенными — храним как None: поведение то же (sync_reverse ведёт их одинаково),
            # а прочитанный и только что созданный профиль равны и через ==
            p.reverse_rules = reverse
            p.reverse_rules = normalized_reverse(p)
            return p
        except KeyError as e:
            raise ProfileFormatError(f"required field {e.args[0]!r} is missing") from e
        except (ValueError, TypeError) as e:
            raise ProfileFormatError(f"invalid profile: {e}") from e

    @classmethod
    def from_json(cls, text: str) -> RemapProfile:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProfileFormatError(f"profile file is not valid JSON: {e}") from e
        return cls.from_dict(data)


def _rules_to_list(rules: dict[int, Rule]) -> list[dict[str, Any]]:
    out = []
    for src in sorted(rules):
        rule = rules[src]
        item: dict[str, Any] = {"src": src, "action": rule.action}
        if rule.action == "map":
            item["dst"] = rule.dst
        out.append(item)
    return out


def _rules_from_list(raw: Any, what: str) -> dict[int, Rule]:
    if not isinstance(raw, list):
        raise ValueError(f"'{what}' must be a list")
    rules: dict[int, Rule] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"a rule must be an object: {item!r}")
        src = item["src"]
        check_note(src, f"{what}.src")
        if src in rules:
            raise ValueError(f"'{what}': two rules for note {src}")
        rules[src] = Rule(item["action"], item.get("dst"))
    return rules


def _map_to_dict(m: NoteMap | None) -> dict[str, Any] | None:
    return None if m is None else map_body_to_dict(m)


def _map_from_dict(data: Any, what: str) -> NoteMap | None:
    return None if data is None else map_body_from_dict(data, what)


# --- обратное направление ---

def derive_reverse(p: RemapProfile) -> dict[int, Rule]:
    """Обратные правила, выведенные из прямых (по возрастанию ноты цели).

    - Нота цели b, на которую идут прямые map: b -> b, если среди них есть сама b (n -> n), иначе b -> наименьшая
      из них (это и есть основной кабель b).
    - Прочие ноты той же артикуляции цели (алиасы, normalize_name), на которые кабели не идут: то же, что у
      Write to артикуляции, если у него есть правило, иначе — что у наименьшей её ноты с правилом.
    - Остальные ноты цели правила не получают. keep кабелем не считается и обратного правила не порождает
      (при обратной конвертации такая нота и так остаётся на месте — keep по умолчанию)."""
    incoming = _incoming(p)
    out = {b: Rule.map_to(b if b in srcs else min(srcs)) for b, srcs in incoming.items()}
    tgt = p.target_map
    if tgt is not None:
        for notes in articulations(tgt).values():
            donor = _donor(tgt, notes, incoming)
            if len(notes) < 2 or donor is None:
                continue
            for n in notes:
                if n not in incoming:
                    out[n] = out[donor]
    return dict(sorted(out.items()))


def _incoming(p: RemapProfile) -> dict[int, list[int]]:
    """Нота цели -> исходные ноты, чьи прямые map идут на неё."""
    incoming: dict[int, list[int]] = {}
    for src, rule in p.rules.items():
        if rule.action == "map":
            incoming.setdefault(rule.dst, []).append(src)
    return incoming


def _donor(tgt: NoteMap, notes: list[int], incoming: dict[int, list[int]]) -> int | None:
    """Нота артикуляции цели, чьё обратное правило копируют её алиасы без входящих кабелей: Write to, если на
    него идут кабели, иначе наименьшая нота с кабелями. None — кабелей на артикуляцию нет."""
    donors = [n for n in notes if n in incoming]
    if not donors:
        return None
    wt = primary_note(tgt, tgt.names[notes[0]])
    return wt if wt in incoming else donors[0]


def normalized_reverse(p: RemapProfile) -> dict[int, Rule] | None:
    """reverse_rules профиля, а если они равны выведенным из прямых — None (поведение то же: sync_reverse ведёт
    их одинаково; так хранятся прочитанные из JSON и правленые в редакторе)."""
    if p.reverse_rules is None or p.reverse_rules == derive_reverse(p):
        return None
    return dict(sorted(p.reverse_rules.items()))


def primary_pairs(p: RemapProfile) -> set[tuple[int, int]]:
    """Основные кабели (a, b): прямое правило a -> b, и обратное правило b — b -> a.
    На каждую ноту цели — не больше одного."""
    rev = p.effective_reverse()
    return {(a, r.dst) for a, r in p.rules.items()
            if r.action == "map" and rev.get(r.dst) == Rule.map_to(a)}


def sync_reverse(before: RemapProfile, after: RemapProfile) -> dict[int, Rule] | None:
    """reverse_rules для after после правки прямых правил или Write to цели (before -> after).

    Заданное обратное правило, равное выведенному из before, следует за прямыми: заменяется выведенным из
    after (или убирается). Отличающееся от выведенного (задано вручную) — не трогается.
    reverse_rules = None (выводятся) — остаётся None."""
    if after.reverse_rules is None:
        return None
    old, new = derive_reverse(before), derive_reverse(after)
    out = dict(after.reverse_rules)
    for b in set(old) | set(new):
        if old.get(b) != new.get(b) and out.get(b) == old.get(b):
            if b in new:
                out[b] = new[b]
            else:
                out.pop(b, None)
    return dict(sorted(out.items()))


def with_primary_cable(p: RemapProfile, a: int, b: int) -> RemapProfile:
    """Новый профиль: прямой кабель a -> b — основной (двойной клик в направлении →): обратное правило b -> a.

    Алиасы той же артикуляции цели без своих кабелей, чьё обратное правило скопировано с b (b — их донор по
    derive_reverse, правило совпадает с прежним правилом b), переходят на a вместе с b — иначе одна нота
    «Ride: Bell» вела бы на a, а остальные — на прежнюю ноту. Прямые правила не меняются.
    Кабель уже основной — профиль не меняется (копия). Нет прямого правила a -> b — ValueError."""
    if p.rules.get(a) != Rule.map_to(b):
        raise ValueError(f"note {a} is not mapped to {b}")
    out = copy.deepcopy(p)
    rev = p.effective_reverse()
    old, new = rev.get(b), Rule.map_to(a)
    if old == new:
        return out
    rev[b] = new
    tgt = p.target_map
    if tgt is not None and b in tgt.names and old is not None:
        notes = articulations(tgt)[normalize_name(tgt.names[b])]
        incoming = _incoming(p)
        if _donor(tgt, notes, incoming) == b:
            for n in notes:
                if n not in incoming and rev.get(n) == old:
                    rev[n] = new
    out.reverse_rules = dict(sorted(rev.items()))
    out.reverse_rules = normalized_reverse(out)
    return out


def with_forward_primary(p: RemapProfile, a: int, b: int) -> RemapProfile:
    """Новый профиль: обратный кабель b -> a — основной (двойной клик в направлении ←): прямое правило a -> b
    (на какую ноту a пишется при прямой конвертации) вместо прежнего a -> b'. Обратные правила, выведенные для
    b', следуют за прямыми (sync_reverse). Постусловие: (a, b) в primary_pairs() — если синхронизация сдвинула
    правило b, b -> a ставится явно. Нет обратного правила b -> a — ValueError."""
    if p.effective_reverse().get(b) != Rule.map_to(a):
        raise ValueError(f"target note {b} is not mapped back to {a}")
    out = copy.deepcopy(p)
    out.rules[a] = Rule.map_to(b)
    out.reverse_rules = sync_reverse(p, out)
    pin_primary(out, a, b)
    out.reverse_rules = normalized_reverse(out)
    return out


def pin_primary(p: RemapProfile, a: int, b: int) -> None:
    """Если (a, b) не основной кабель — обратное правило b -> a явно (профиль меняется на месте)."""
    if (a, b) not in primary_pairs(p):
        rev = p.effective_reverse()
        rev[b] = Rule.map_to(a)
        p.reverse_rules = dict(sorted(rev.items()))


def keep_existing_primary(before: RemapProfile, after: RemapProfile, numbers: list[int]) -> list[int]:
    """После подключения n -> n на номера numbers (двойной клик по Unassigned в →): где на номер уже шли кабели
    (в before), новый кабель — НЕОСНОВНОЙ, прежний основной остаётся. derive_reverse предпочёл бы n -> n — поэтому
    обратные правила номера и алиасов его артикуляции без кабелей возвращаются к прежним и задаются явно
    (after меняется на месте; в after.reverse_rules уже должна быть синхронизация прямых). Возвращает занятые номера."""
    inc = _incoming(before)
    occupied = [n for n in numbers if n in inc]
    if not occupied:
        return []
    old, rev = before.effective_reverse(), after.effective_reverse()
    tgt, inc_after = after.target_map, _incoming(after)
    for n in occupied:
        notes = articulations(tgt)[normalize_name(tgt.names[n])] if tgt is not None and n in tgt.names else [n]
        for m in notes:
            if m != n and m in inc_after:
                continue  # у алиаса свои кабели — его правило выводится из них
            if m in old:
                rev[m] = old[m]
            else:
                rev.pop(m, None)
    after.reverse_rules = dict(sorted(rev.items()))
    return occupied


def missing_rules(p: RemapProfile, direction: str = FORWARD) -> list[int]:
    """Полнота направления: ноты карты исходной стороны (для REVERSE — целевой карты) без правила.
    Без этой карты — пусто. Это статус, а не ошибка."""
    q = p.oriented(direction)
    if q.source_map is None:
        return []
    return sorted(n for n in q.source_map.names if n not in q.rules)


# --- проверка профиля по картам ---

# Коды ProfileIssue. NO_RULE — не ошибка, а вопрос пользователю (по умолчанию нота остаётся на месте);
# остальные — предупреждения.
SRC_NOT_IN_SOURCE = "src_not_in_source_map"      # map/keep для ноты, которой нет в исходной карте (delete — норма)
DST_NOT_IN_TARGET = "dst_not_in_target_map"      # map на ноту, которой нет в целевой карте
KEEP_NOT_IN_TARGET = "keep_not_in_target_map"    # keep, а этого номера нет в целевой карте
KEEP_DIFFERENT = "keep_different_articulation"   # keep, а на этом номере в целевой карте другая артикуляция
NO_RULE = "no_rule"                              # нота исходной карты без правила


@dataclass
class ProfileIssue:
    code: str
    note: int  # исходная нота, к которой относится замечание
    message: str


# названия карт исходной и целевой стороны направления в текстах замечаний: в REVERSE исходная сторона —
# целевая карта профиля
_SIDES = {FORWARD: ("source map", "target map"), REVERSE: ("target map", "source map")}


def keep_issue(source_map: NoteMap | None, target_map: NoteMap | None, note: int,
               direction: str = FORWARD) -> ProfileIssue | None:
    """Что не так, если оставить ноту на том же номере (явный keep или keep по умолчанию).

    None — замечаний нет или проверить не по чему (нет целевой карты; для «другой артикуляции» нужны обе).
    source_map / target_map — карты исходной и целевой стороны направления; direction — только для текста
    (в REVERSE это целевая и исходная карты профиля, так они и названы)."""
    src_label, tgt_label = _SIDES[direction]
    if target_map is None:
        return None
    if note not in target_map.names:
        return ProfileIssue(KEEP_NOT_IN_TARGET, note, f"note {note} is kept, but the {tgt_label} has no note {note}")
    if source_map is not None and note in source_map.names:
        src_name, dst_name = source_map.names[note], target_map.names[note]
        if normalize_name(src_name) != normalize_name(dst_name):
            return ProfileIssue(KEEP_DIFFERENT, note,
                                f'note {note} is kept, but it is "{src_name}" in the {src_label} '
                                f'and "{dst_name}" in the {tgt_label}')
    return None


def validate_profile(p: RemapProfile, direction: str = FORWARD) -> list[ProfileIssue]:
    """Замечания к правилам профиля в направлении direction относительно его карт, по возрастанию ноты
    исходной стороны (в REVERSE — ноты целевой карты и обратные правила; тексты называют карты профиля).

    Каждая проверка — только если нужная карта есть; профиль без карт замечаний не получает.
    delete для ноты вне исходной карты — не замечание (удалить лишнее — норма).
    map на неосновную ноту артикуляции с несколькими нотами — допустимо, не проверяется.
    """
    q = p.oriented(direction)
    src_label, tgt_label = _SIDES[direction]
    src_map, tgt_map = q.source_map, q.target_map
    issues: list[ProfileIssue] = []
    for src in sorted(q.rules):
        rule = q.rules[src]
        if src_map is not None and src not in src_map.names and rule.action != "delete":
            issues.append(ProfileIssue(SRC_NOT_IN_SOURCE, src, f"rule for note {src}, which is not in the {src_label}"))
        if rule.action == "map" and tgt_map is not None and rule.dst not in tgt_map.names:
            issues.append(ProfileIssue(DST_NOT_IN_TARGET, src,
                                       f"note {src} is mapped to {rule.dst}, which is not in the {tgt_label}"))
        elif rule.action == "keep":
            issue = keep_issue(src_map, tgt_map, src, direction)
            if issue is not None:
                issues.append(issue)
    if src_map is not None:
        issues.extend(ProfileIssue(NO_RULE, n, f'note {n} "{src_map.names[n]}" has no rule (kept by default)')
                      for n in sorted(src_map.names) if n not in q.rules)
    issues.sort(key=lambda i: i.note)  # сортировка устойчива: порядок проверок внутри ноты сохраняется
    return issues


def with_explicit_keeps(p: RemapProfile) -> RemapProfile:
    """Новый профиль: каждой ноте исходной карты без правила — явный keep (входной профиль не меняется).

    При сохранении профиля так фиксируется решение «оставить на месте», и конвертация спрашивает
    только о нотах, которых нет в исходной карте. Без исходной карты — просто копия."""
    out = copy.deepcopy(p)
    if out.source_map is not None:
        for n in out.source_map.names:
            out.rules.setdefault(n, Rule.keep())
    out.validate()
    return out


def _set_primary(tgt: NoteMap, notes: list[int], note: int) -> None:
    """primary = note среди нот артикуляции (на месте); у артикуляции на одной ноте флаг не нужен."""
    if len(notes) > 1:
        tgt.primary.difference_update(notes)
        tgt.primary.add(note)


def with_write_to(p: RemapProfile, note: int) -> RemapProfile:
    """Новый профиль: note — Write to своей артикуляции (входной профиль не меняется).

    На note переводятся ТОЛЬКО правила map, которые шли на прежний Write to и не совпадают по номеру
    (правило n → n остаётся: нота уже на своём номере). Правила на другие ноты артикуляции не трогаются;
    если Write to не было — перенаправлять нечего.
    primary ставится во ВСТРОЕННУЮ копию целевой карты профиля (карта в хранилище не меняется) и снимается
    с прочих нот артикуляции; у артикуляции на одной ноте флаг не нужен — не ставится."""
    tgt = p.target_map
    if tgt is None or note not in tgt.names:
        raise ValueError(f"note {note} is not in the target map")
    out = copy.deepcopy(p)
    name = tgt.names[note]
    old = primary_note(tgt, name)
    _set_primary(out.target_map, articulations(tgt)[normalize_name(name)], note)
    if old is not None and old != note:
        for src, rule in out.rules.items():
            if rule.action == "map" and rule.dst == old and src != old:
                out.rules[src] = Rule.map_to(note)
    return out


# --- назначение нот на цель ---

@dataclass(frozen=True)
class AssignPlan:
    """Что будет при назначении исходных нот на артикуляцию цели (assign_plan)."""
    name: str                   # имя артикуляции в целевой карте
    targets: tuple[int, ...]    # её ноты
    same: tuple[int, ...]       # исходные ноты, чей номер — среди её нот: n → n
    others: tuple[int, ...]     # остальные: на Write to
    write_to: int | None        # текущий Write to или выбранный молча (одна совпавшая нота); None — см. ask
    preselect: int | None       # для вопроса о Write to: первая совпавшая нота (или None)

    @property
    def ask(self) -> bool:
        """Нужно спросить Write to: есть ноты не на своих номерах, а Write to не выбран."""
        return bool(self.others) and self.write_to is None


def assign_plan(p: RemapProfile, notes: list[int], articulation: str) -> AssignPlan:
    """План назначения нот на артикуляцию целевой карты (по имени, сравнение через normalize_name).

    Нота, чей номер есть среди нот артикуляции, остаётся на нём (n → n) — без вопросов. Остальные — на
    Write to артикуляции. Write to нет: одна совпавшая нота в этом же назначении — она и станет Write to
    (молча); несколько совпавших или ни одной — спросить (один раз на назначение, предвыбор — первая
    совпавшая)."""
    tgt = p.target_map
    if tgt is None:
        raise ValueError("the profile has no target map")
    targets = articulations(tgt).get(normalize_name(articulation))
    if not targets:
        raise ValueError(f"no articulation {articulation!r} in the target map")
    name = tgt.names[targets[0]]
    notes = sorted(set(notes))
    same = tuple(n for n in notes if n in targets)
    others = tuple(n for n in notes if n not in targets)
    write_to = primary_note(tgt, name)
    if write_to is None and others and len(same) == 1:
        write_to = same[0]
    return AssignPlan(name, tuple(targets), same, others, write_to, same[0] if same else None)


def assign_to_articulation(p: RemapProfile, notes: list[int], articulation: str,
                           write_to: int | None = None) -> RemapProfile:
    """Новый профиль: ноты назначены на артикуляцию по assign_plan() (входной профиль не меняется).

    write_to — ответ на вопрос (нужен, если plan.ask; иначе игнорируется, если Write to уже есть).
    Новый Write to (выбранный молча или ответом) записывается как primary во ВСТРОЕННУЮ копию целевой карты.
    Прежние правила этих нот (delete/keep/map) заменяются."""
    plan = assign_plan(p, notes, articulation)
    out = copy.deepcopy(p)
    wt = plan.write_to if plan.write_to is not None else write_to
    if plan.others:
        if wt is None:
            raise ValueError(f'"{plan.name}" is on several notes: choose the Write to note')
        if wt not in plan.targets:
            raise ValueError(f"note {wt} is not a note of {plan.name!r}")
        if primary_note(p.target_map, plan.name) != wt:
            _set_primary(out.target_map, list(plan.targets), wt)
    for n in plan.same:
        out.rules[n] = Rule.map_to(n)
    for n in plan.others:
        out.rules[n] = Rule.map_to(wt)
    return out


def connect_same_numbers(p: RemapProfile, notes: list[int], targets: list[int]) -> tuple[RemapProfile, list[int]]:
    """Перетаскивание на группу цели: каждой ноте, чей номер среди targets, — n → n.

    Ноты без совпадения и ноты, у которых уже есть правило map, не трогаются; вопросов нет.
    Возвращает новый профиль и подключённые ноты (по возрастанию)."""
    out = copy.deepcopy(p)
    wanted = set(targets)
    done = []
    for n in sorted(set(notes)):
        rule = out.rules.get(n)
        if n in wanted and (rule is None or rule.action != "map"):
            out.rules[n] = Rule.map_to(n)
            done.append(n)
    return out, done


def number_matches(p: RemapProfile) -> list[int]:
    """«Match by number»: ноты исходной карты БЕЗ правила (не зачёркнутые, не подключённые), чей номер есть в
    целевой карте (по возрастанию). Для обратного направления — вызывать на p.reversed()."""
    if p.source_map is None or p.target_map is None:
        return []
    return [n for n in sorted(p.source_map.names) if n not in p.rules and n in p.target_map.names]


def match_by_number(p: RemapProfile) -> tuple[RemapProfile, list[int]]:
    """n → n для всех number_matches(p) (как двойной клик по строке Unassigned: connect_same_numbers).
    Возвращает новый профиль и подключённые ноты."""
    notes = number_matches(p)
    if not notes:
        return copy.deepcopy(p), []
    return connect_same_numbers(p, notes, list(p.target_map.names))


def legacy_profile() -> RemapProfile:
    """Схема GM → SD3 из первой версии программы: NOTE_MAP + явное удаление всех остальных нот.

    Это ручная схема пользователя, а НЕ встроенный шаблон (не данные плагина) — только для кода и тестов.
    """
    rules = {n: Rule.map_to(NOTE_MAP[n]) if n in NOTE_MAP else Rule.delete() for n in range(128)}
    return RemapProfile(name="GM → SD3 (legacy)", rules=rules)
