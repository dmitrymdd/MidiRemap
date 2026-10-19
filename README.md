# MidiRemap

Convert drum MIDI files from one note layout to another.

Drop in a `.mid` file with a drum part, pick a remap profile, and get the same file back with
the notes renumbered for your drum plugin. Timing, velocities, tempo and all other events stay
exactly as they were.

## Download

Get the latest Windows build from the [Releases](https://github.com/dmitrymdd/MidiRemap/releases) page.
Unzip the folder anywhere and run `MidiRemap.exe`. No installation is needed.

## How to use

1. **Load a MIDI file.** Drag a `.mid` file into the window, click the drop area to browse,
   or copy the file in Explorer and press **Ctrl+V** in MidiRemap.
2. **Pick a remap profile** from the list.
3. **Convert.** Click **Convert** or press **Enter**. The result is saved next to the source
   file as `<name>_remapped.mid`.
4. **Use the result.** Drag the output card straight into your DAW, or press **Ctrl+C** and
   paste the file into a folder or any DAW that accepts pasted files.
   **Show in folder** opens the output location.

After each conversion MidiRemap shows a report:

- how many hits were remapped, deleted or kept on their original note;
- notes that have no rule in the profile;
- duplicate hits merged when several source notes map to one target note;
- overlapping hits on the same target note;
- warnings, for example when the file has notes on several tracks or channels, or when a note
  lands on a slot that is empty or holds a different articulation in the target layout.

MIDI files do not say which layout they use, so you always choose the profile yourself.
All tracks and all MIDI channels are converted.

### Keyboard shortcuts

| Key    | Action                       |
|--------|------------------------------|
| Enter  | Convert                      |
| Ctrl+V | Load a MIDI file copied in Explorer |
| Ctrl+C | Copy the output file         |
| Esc    | Clear                        |

## Remap profiles

A profile says what happens to each source note:

- **map**: move it to another note;
- **delete**: drop it;
- **keep**: leave it on the same note.

Notes that are not listed in the profile are kept on the same note. Several source notes may
map to one target note. This is the usual case for plugin articulations. Hits that land on the
same target note at the same tick are merged into one, and the highest velocity is kept.

Profiles are stored as JSON files in `%APPDATA%\MidiRemap\profiles\`. Click **Refresh** after
adding a file there. Example:

```json
{
  "format": 1,
  "name": "My kit",
  "source_map": null,
  "target_map": null,
  "rules": [
    {"src": 36, "action": "map", "dst": 36},
    {"src": 42, "action": "map", "dst": 8},
    {"src": 60, "action": "delete"}
  ]
}
```

`source_map` and `target_map` are optional note-name maps (`{"name": ..., "names": {"36": "Kick"}}`).
When a target map is present, MidiRemap uses it to warn about notes that land on empty or
mismatched slots.

## Running from source

Requires Python 3.10 or newer on Windows.

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m midiremap
```

Run the tests with `.venv\Scripts\python -m pytest`.
