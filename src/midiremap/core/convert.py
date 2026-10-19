"""Движок конвертации MIDI по профилю ремапа (без Qt и без UI)."""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import mido

from .notemap import normalize_name
from .profile import Action, RemapProfile, Rule, check_note

NOTE_TYPES = ('note_on', 'note_off')
DEFAULT_RULE = Rule.keep()

RuleOrigin = Literal["override", "profile", "default"]


def _is_note_on(msg) -> bool:
    """note_on с velocity 0 — это note_off."""
    return msg.type == 'note_on' and msg.velocity > 0


@dataclass
class Analysis:
    note_counts: dict[int, int]  # исх. нота -> число note_on (velocity > 0); нота только с note_off -> 0
    note_tracks: list[int]       # индексы дорожек (с 0), где есть нотные события
    note_channels: list[int]     # MIDI-каналы (с 0; пользователю показывать +1)
    unresolved: list[int]        # ноты из файла, для которых в профиле нет правила

    @property
    def multi_location(self) -> bool:
        return len(self.note_tracks) > 1 or len(self.note_channels) > 1


@dataclass
class NoteResult:
    src: int
    count: int          # note_on (velocity > 0) этой ноты в исходном файле
    action: Action
    dst: int | None     # итоговый номер (для keep — тот же); None для delete
    origin: RuleOrigin  # откуда правило: override / profile / default (keep по умолчанию)


@dataclass
class ConversionReport:
    notes: dict[int, NoteResult] = field(default_factory=dict)  # по исходным нотам из файла
    merged: int = 0            # note_on, слитых с другими (многие-в-одну, один тик)
    merged_note_offs: int = 0  # note_off слитых групп, кроме самого позднего
    deleted: int = 0           # note_on, удалённых правилом delete
    overlaps: int = 0          # перекрытия одной целевой ноты на разных тиках (не трогаем, только считаем)
    orphan_note_offs: int = 0  # note_off без предшествующего note_on (ремапятся и проходят как есть)
    unresolved_kept: list[int] = field(default_factory=list)  # ноты без правила, оставленные на месте
    # совместимость со старым convert_midi: нотные события записаны / не записаны, прочие события
    stats: dict[str, int] = field(default_factory=lambda: {'mapped': 0, 'removed': 0, 'other': 0})
    warnings: list[str] = field(default_factory=list)


def effective_rule(note: int, profile: RemapProfile,
                   overrides: Mapping[int, Rule] | None = None) -> tuple[Rule, RuleOrigin]:
    """Приоритет: overrides > правила профиля > keep по умолчанию."""
    if overrides and note in overrides:
        return overrides[note], "override"
    if note in profile.rules:
        return profile.rules[note], "profile"
    return DEFAULT_RULE, "default"


def _scan(midi: mido.MidiFile) -> Analysis:
    counts: dict[int, int] = {}
    tracks: set[int] = set()
    channels: set[int] = set()
    for i, track in enumerate(midi.tracks):
        for msg in track:
            if msg.type in NOTE_TYPES:
                counts[msg.note] = counts.get(msg.note, 0) + _is_note_on(msg)
                tracks.add(i)
                channels.add(msg.channel)
    return Analysis(dict(sorted(counts.items())), sorted(tracks), sorted(channels), [])


def analyze(src_path: str | Path, profile: RemapProfile) -> Analysis:
    a = _scan(mido.MidiFile(str(src_path)))
    a.unresolved = [n for n in a.note_counts if n not in profile.rules]
    return a


@dataclass
class _Group:
    """note_on одной целевой ноты на одном канале, попавшие в одно окно слияния."""
    tick: int
    ons: list[int] = field(default_factory=list)   # индексы событий в дорожке
    offs: list[int] = field(default_factory=list)  # их note_off, в порядке появления


def _convert_track(track: mido.MidiTrack, rule_for: Callable[[int], Rule],
                   report: ConversionReport, window: int) -> mido.MidiTrack:
    # 1) Решение по каждому событию: None — удалить, иначе сообщение (time подставляется в шаге 3).
    out: list = []
    pending: dict[tuple[int, int], deque[_Group]] = {}  # (канал, исх. нота) -> группы её незакрытых note_on
    last_group: dict[tuple[int, int], _Group] = {}      # (канал, цел. нота) -> последняя группа
    sounding: Counter[tuple[int, int]] = Counter()      # (канал, цел. нота) -> звучащих note_on
    groups: list[_Group] = []
    now = 0
    for i, msg in enumerate(track):
        now += msg.time
        if msg.type not in NOTE_TYPES:
            out.append(msg)
            continue
        rule = rule_for(msg.note)
        if rule.action == 'delete':
            out.append(None)
            report.deleted += _is_note_on(msg)
            continue
        target = rule.dst if rule.action == 'map' else msg.note
        out.append(msg.copy(note=target))
        src_key, tgt_key = (msg.channel, msg.note), (msg.channel, target)
        if _is_note_on(msg):
            group = last_group.get(tgt_key)
            if group is None or now - group.tick > window:
                if sounding[tgt_key]:
                    report.overlaps += 1
                group = last_group[tgt_key] = _Group(now)
                groups.append(group)
            group.ons.append(i)
            pending.setdefault(src_key, deque()).append(group)
            sounding[tgt_key] += 1
        else:
            queue = pending.get(src_key)
            if queue:
                queue.popleft().offs.append(i)
                sounding[tgt_key] -= 1
            else:
                report.orphan_note_offs += 1

    # 2) Многие-в-одну: один note_on с максимальной velocity, из note_off группы — только самый поздний.
    for group in groups:
        if len(group.ons) < 2:
            continue
        first, *rest = group.ons
        out[first] = out[first].copy(velocity=max(out[j].velocity for j in group.ons))
        for j in rest:
            out[j] = None
        report.merged += len(rest)
        for j in group.offs[:-1]:  # offs идут в порядке времени, последний — самый поздний
            out[j] = None
        report.merged_note_offs += max(len(group.offs) - 1, 0)

    # 3) Сборка дорожки. Логика carry — эталон: время удалённых событий переносится на следующее,
    #    абсолютное время оставшихся событий и длина дорожки не меняются.
    stats = report.stats
    new_track = mido.MidiTrack()
    carry = 0
    for msg, new in zip(track, out):
        carry += msg.time
        if new is None:
            stats['removed'] += 1
            continue
        new_track.append(new.copy(time=carry))
        stats['mapped' if msg.type in NOTE_TYPES else 'other'] += 1
        carry = 0
    if carry:
        if new_track and new_track[-1].type == 'end_of_track':
            new_track[-1].time += carry
        else:
            new_track.append(mido.MetaMessage('end_of_track', time=carry))
    return new_track


def _warnings(profile: RemapProfile, scan: Analysis, notes: dict[int, NoteResult]) -> list[str]:
    warnings: list[str] = []
    if scan.multi_location:
        tracks = ", ".join(str(t + 1) for t in scan.note_tracks)
        channels = ", ".join(str(c + 1) for c in scan.note_channels)
        warnings.append(f"Notes found in several tracks/channels (tracks: {tracks}; channels: {channels}); "
                        "all of them are remapped with the same profile.")
    tm, sm = profile.target_map, profile.source_map
    if tm is None:
        warnings.append("The profile has no target map, so target notes were not checked.")
        return warnings
    for n, r in notes.items():
        if r.action == 'keep' and n not in tm.names:
            warnings.append(f"Note {n} is kept as is, but the target map has no note {n}. "
                            "It will probably not sound.")
        elif r.action == 'keep':
            tgt_name = tm.names[n]
            src_name = sm.names.get(n) if sm is not None else None
            if src_name is None:
                warnings.append(f"Note {n} is kept as is. Its source name is unknown, "
                                f"and in the target map it is \"{tgt_name}\".")
            elif normalize_name(src_name) != normalize_name(tgt_name):
                warnings.append(f"Note {n} \"{src_name}\" is kept as is, but in the target map it is \"{tgt_name}\".")
        elif r.action == 'map' and r.dst not in tm.names:
            warnings.append(f"Note {n} → {r.dst}: the target map has no note {r.dst}.")
    return warnings


def convert(src: str | Path, dst: str | Path, profile: RemapProfile,
            overrides: Mapping[int, Rule] | None = None,
            merge_window_ticks: int = 0) -> ConversionReport:
    """Конвертирует MIDI по профилю. Ремапятся все каналы и дорожки.

    overrides — решения пользователя для этой конвертации; в профиль ядро их не записывает.
    merge_window_ticks — допуск слияния многие-в-одну; пока поддерживается только 0 (точный тик).
    """
    if merge_window_ticks < 0:
        raise ValueError("merge_window_ticks cannot be negative")
    if merge_window_ticks > 0:
        raise ValueError("merge_window_ticks > 0: not supported yet")
    for n, rule in (overrides or {}).items():
        check_note(n, "overrides")
        if not isinstance(rule, Rule):
            raise TypeError(f"override for note {n} must be a Rule, got {type(rule).__name__}")

    midi = mido.MidiFile(str(src))
    scan = _scan(midi)
    report = ConversionReport()
    rules: dict[int, Rule] = {}
    for n, count in scan.note_counts.items():
        rule, origin = effective_rule(n, profile, overrides)
        rules[n] = rule
        dst_note = None if rule.action == 'delete' else (rule.dst if rule.action == 'map' else n)
        report.notes[n] = NoteResult(n, count, rule.action, dst_note, origin)
        if origin == "default":
            report.unresolved_kept.append(n)

    out = mido.MidiFile(type=midi.type, ticks_per_beat=midi.ticks_per_beat)
    out.charset = midi.charset
    for track in midi.tracks:
        out.tracks.append(_convert_track(track, rules.__getitem__, report, merge_window_ticks))
    report.warnings = _warnings(profile, scan, report.notes)
    out.save(str(dst))
    return report


def convert_midi(src: Path, dst: Path, note_map: Mapping[int, int]) -> dict:
    """Совместимость со старым UI: ноты вне note_map удаляются. Возвращает stats {'mapped','removed','other'}."""
    rules = {n: Rule.delete() for n in range(128)}
    rules.update({s: Rule.map_to(d) for s, d in note_map.items()})
    return convert(src, dst, RemapProfile(name="note_map", rules=rules)).stats
