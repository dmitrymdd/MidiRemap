from __future__ import annotations
import os, sys

def enable_windows_dpi_awareness():
    """Make Tk render sharply on high-DPI Windows displays."""
    if os.name != "nt":
        return
    try:
        import ctypes
        # Per-monitor v2 gives crisp text/widgets on modern Windows.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()  # legacy fallback
    except Exception:
        pass

enable_windows_dpi_awareness()

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from midiremap.core import convert_midi as core_convert_midi
from midiremap.core.legacy_map import NOTE_MAP

try:
    from tkinterdnd2 import DND_FILES, COPY, TkinterDnD
    DND_OK = True
except ImportError:
    DND_FILES, COPY, TkinterDnD, DND_OK = 'DND_Files', 'copy', None, False

EXTS = {'.mid', '.midi'}
BG, PANEL, PANEL2 = '#111318', '#191d25', '#222733'
FG, MUTED, ACCENT, GREEN, RED, BORDER = '#f0f2f7', '#9ba4b5', '#7c8cff', '#59d6a2', '#ff737e', '#303643'


def is_midi(path):
    return bool(path) and Path(path).suffix.lower() in EXTS and Path(path).is_file()


def convert_midi(src: Path, dst: Path):
    return core_convert_midi(src, dst, NOTE_MAP)


def clipboard_files():
    """Return Windows Explorer file objects copied to clipboard, if available."""
    if os.name != 'nt':
        return []
    try:
        import win32clipboard, win32con
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                return list(win32clipboard.GetClipboardData(win32con.CF_HDROP))
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return []
    return []


def copy_file_to_clipboard(path):
    """Copy the output as a file object so Explorer/DAWs can paste it."""
    if os.name != 'nt' or not os.path.isfile(path):
        return False
    try:
        import win32clipboard, win32con
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, [os.path.abspath(path)])
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:
        return False


class App:
    def __init__(self, root):
        self.root = root
        self.root.title('MidiRemap')
        # DPI awareness is enabled before Tk is created; retain a comfortable
        # logical size and let Windows render at native display resolution.
        try:
            self.root.tk.call('tk', 'scaling', self.root.winfo_fpixels('1i') / 72.0)
        except tk.TclError:
            pass
        self.root.geometry('900x660')
        self.root.minsize(760, 560)
        self.root.configure(bg=BG)
        self.source = None
        self.output = None
        self.last_output = None
        self._style()
        self._ui()
        self._dnd()
        root.bind_all('<Control-v>', self.paste_file)
        root.bind_all('<Control-V>', self.paste_file)
        root.bind_all('<Control-c>', self.copy_output)
        root.bind_all('<Control-C>', self.copy_output)
        root.bind_all('<Return>', lambda e: self.convert())
        root.bind_all('<Escape>', lambda e: self.clear())

    def _style(self):
        s = ttk.Style()
        try: s.theme_use('clam')
        except tk.TclError: pass
        s.configure('TFrame', background=BG)
        s.configure('TLabel', background=BG, foreground=FG, font=('Segoe UI', 10))
        s.configure('Muted.TLabel', background=BG, foreground=MUTED, font=('Segoe UI', 9))
        s.configure('TButton', background=PANEL2, foreground=FG, borderwidth=0, padding=(12, 9), font=('Segoe UI Semibold', 10))
        s.map('TButton', background=[('active', '#30394a')], foreground=[('disabled', '#6e7480')])
        s.configure('Accent.TButton', background=ACCENT, foreground='#ffffff', padding=(15, 11), font=('Segoe UI Semibold', 10))
        s.map('Accent.TButton', background=[('active', '#96a2ff')])

    def _ui(self):
        root = ttk.Frame(self.root, padding=(25, 22)); root.pack(fill='both', expand=True)
        head = tk.Frame(root, bg=BG); head.pack(fill='x', pady=(0, 20))
        tk.Label(head, text='MR', bg=ACCENT, fg='white', font=('Segoe UI', 15, 'bold'), width=3, height=2).pack(side='left', padx=(0, 13))
        title = tk.Frame(head, bg=BG); title.pack(side='left')
        tk.Label(title, text='MidiRemap', bg=BG, fg=FG, font=('Segoe UI', 22, 'bold')).pack(anchor='w')
        tk.Label(title, text='Guitar Pro / Songsterr  →  Superior Drummer 3', bg=BG, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w')
        tk.Label(head, text='● READY', bg=BG, fg=GREEN, font=('Segoe UI', 9, 'bold')).pack(side='right', pady=8)

        self.drop = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, padx=20, pady=18)
        self.drop.pack(fill='x', pady=(0, 16))
        tk.Label(self.drop, text='↓', bg=PANEL, fg=ACCENT, font=('Segoe UI', 26, 'bold')).pack()
        tk.Label(self.drop, text='Перетащи сюда MIDI-файл', bg=PANEL, fg=FG, font=('Segoe UI', 13, 'bold')).pack(pady=(3, 4))
        tk.Label(self.drop, text='или нажми «Открыть файл»  ·  Ctrl+V — вставить файл из буфера', bg=PANEL, fg=MUTED, font=('Segoe UI', 9)).pack()
        for w in self.drop.winfo_children(): w.bind('<Button-1>', lambda e: self.choose())
        self.drop.bind('<Button-1>', lambda e: self.choose())

        tk.Label(root, text='SOURCE', bg=BG, fg=MUTED, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 5))
        self.src_card, self.src_name, self.src_path = self._card(root, 'Исходный файл', 'Файл не выбран')
        tk.Label(root, text='OUTPUT', bg=BG, fg=MUTED, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(13, 5))
        self.out_card, self.out_name, self.out_path = self._card(root, 'Результат', 'Ожидает преобразования')

        actions = tk.Frame(root, bg=BG); actions.pack(fill='x', pady=(18, 15))
        ttk.Button(actions, text='Преобразовать MIDI  →', style='Accent.TButton', command=self.convert).pack(side='left')
        ttk.Button(actions, text='Открыть файл…', command=self.choose).pack(side='left', padx=(9, 0))
        ttk.Button(actions, text='Папка результата', command=self.open_folder).pack(side='left', padx=(9, 0))
        ttk.Button(actions, text='Копировать файл  ⧉', command=self.copy_output).pack(side='right')

        self.status_box = tk.Frame(root, bg=PANEL, padx=13, pady=11); self.status_box.pack(fill='x', side='bottom')
        self.status_dot = tk.Label(self.status_box, text='●', bg=PANEL, fg=MUTED); self.status_dot.pack(side='left', padx=(0, 8))
        self.status = tk.StringVar(value='Готово к работе. Поддерживаются .mid и .midi.')
        tk.Label(self.status_box, textvariable=self.status, bg=PANEL, fg=MUTED, font=('Segoe UI', 9), anchor='w', justify='left', wraplength=680).pack(side='left', fill='x', expand=True)
        tk.Label(root, text='Enter — преобразовать    Ctrl+V — вставить    Ctrl+C — скопировать результат    Esc — сбросить', bg=BG, fg='#687183', font=('Segoe UI', 8)).pack(anchor='w', pady=(10, 0))

    def _card(self, parent, title, path):
        frame = tk.Frame(parent, bg=PANEL, padx=13, pady=10, highlightthickness=1, highlightbackground=BORDER)
        frame.pack(fill='x')
        tk.Label(frame, text='♫', bg=PANEL, fg=ACCENT, font=('Segoe UI', 17)).pack(side='left', padx=(0, 12))
        text = tk.Frame(frame, bg=PANEL); text.pack(side='left', fill='x', expand=True)
        name = tk.Label(text, text=title, bg=PANEL, fg=FG, font=('Segoe UI', 10, 'bold'), anchor='w'); name.pack(fill='x')
        p = tk.Label(text, text=path, bg=PANEL, fg=MUTED, font=('Segoe UI', 9), anchor='w'); p.pack(fill='x', pady=(3, 0))
        return frame, name, p

    def _dnd(self):
        if not DND_OK:
            self.set_status('Drag & drop не подключён. Установи зависимости из requirements.txt; кнопки и Ctrl+V доступны.', True)
            return
        for w in [self.root, self.drop, *self.drop.winfo_children(), self.src_card, self.src_name, self.src_path]:
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind('<<Drop>>', self.on_drop)
            except Exception: pass
        for w in [self.out_card, self.out_name, self.out_path]:
            try:
                w.drag_source_register(1, DND_FILES)
                w.dnd_bind('<<DragInitCmd>>', self.drag_output)
            except Exception: pass

    def drag_output(self, event=None):
        if self.last_output and os.path.isfile(self.last_output):
            return (COPY, DND_FILES, (self.last_output,))
        return (COPY, DND_FILES, ())

    def on_drop(self, event):
        try: paths = list(self.root.tk.splitlist(event.data))
        except tk.TclError: paths = [event.data.strip('{}')]
        files = [p for p in paths if is_midi(p)]
        if not files: self.set_status('Перетащи существующий .mid или .midi файл.', True)
        else:
            self.load(files[0])
            if len(files) > 1: self.set_status(f'Загружен первый из {len(files)} файлов. Программа обрабатывает по одному файлу.')
        return 'break'

    def choose(self):
        p = filedialog.askopenfilename(title='Выбрать MIDI-файл', filetypes=[('MIDI files', '*.mid *.midi'), ('All files', '*.*')])
        if p: self.load(p)

    def load(self, path):
        if not is_midi(path): self.set_status('Выбери существующий .mid или .midi файл.', True); return
        self.source = os.path.abspath(path)
        src = Path(self.source); self.output = str(src.with_name(src.stem + '_remapped.mid'))
        self.src_name.configure(text=src.name); self.src_path.configure(text=str(src.parent))
        self.out_name.configure(text=Path(self.output).name); self.out_path.configure(text=str(Path(self.output).parent))
        self.drop.configure(highlightbackground=ACCENT)
        self.set_status('Файл загружен. Нажми «Преобразовать MIDI» или Enter.')

    def clear(self):
        self.source = self.output = None
        self.src_name.configure(text='Исходный файл'); self.src_path.configure(text='Файл не выбран')
        self.out_name.configure(text='Результат'); self.out_path.configure(text='Ожидает преобразования')
        self.drop.configure(highlightbackground=BORDER); self.set_status('Выбор сброшен.')

    def paste_file(self, event=None):
        files = [p for p in clipboard_files() if is_midi(p)]
        if files:
            self.load(files[0]); return 'break'
        try:
            text = self.root.clipboard_get().strip().strip('"')
            if is_midi(text): self.load(text); return 'break'
        except tk.TclError: pass
        self.set_status('В буфере нет MIDI-файла. Скопируй файл в Проводнике и нажми Ctrl+V.', True)
        return 'break'

    def copy_output(self, event=None):
        path = self.last_output or self.output
        if path and os.path.isfile(path):
            if copy_file_to_clipboard(path): self.set_status('Файл результата скопирован как файл. Теперь его можно вставить в папку или поддерживающую вставку DAW.')
            else:
                self.root.clipboard_clear(); self.root.clipboard_append(path)
                self.set_status('Не удалось скопировать файл как объект; скопирован путь к нему.', True)
        else: self.set_status('Сначала преобразуй MIDI.', True)
        return 'break'

    def convert(self):
        if not self.source or not os.path.isfile(self.source): self.set_status('Сначала перетащи MIDI-файл или нажми «Открыть файл».', True); return
        src = Path(self.source); dst = Path(self.output or src.with_name(src.stem + '_remapped.mid'))
        if src.resolve() == dst.resolve(): dst = src.with_name(src.stem + '_remapped.mid')
        try: stats = convert_midi(src, dst)
        except Exception as exc:
            messagebox.showerror('MidiRemap — ошибка', f'Не удалось преобразовать MIDI:\n\n{exc}', parent=self.root)
            self.set_status('Ошибка преобразования.', True); return
        self.output = self.last_output = str(dst)
        self.out_name.configure(text=dst.name); self.out_path.configure(text=str(dst.parent))
        self.out_card.configure(highlightbackground=GREEN)
        self.set_status(f'Готово · нотных событий обработано: {stats["mapped"]} · неназначенных удалено: {stats["removed"]}')
        self.status_dot.configure(fg=GREEN)

    def open_folder(self):
        path = self.last_output or self.output
        if not path or not os.path.isfile(path): self.set_status('Папка результата появится после преобразования.', True); return
        folder = str(Path(path).parent)
        try:
            if os.name == 'nt': os.startfile(folder)
            elif sys.platform == 'darwin': __import__('subprocess').Popen(['open', folder])
            else: __import__('subprocess').Popen(['xdg-open', folder])
        except Exception as exc: self.set_status(f'Не удалось открыть папку: {exc}', True)

    def set_status(self, text, warning=False):
        self.status.set(text); self.status_dot.configure(fg=RED if warning else MUTED)


def main():
    root = TkinterDnD.Tk() if DND_OK else tk.Tk()
    App(root)
    root.mainloop()

if __name__ == '__main__': main()
