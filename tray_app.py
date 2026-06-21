import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pystray
from PIL import Image, ImageDraw

from config import ConfigManager
from rule_manager import RuleManager


def _make_icon_image(size: int = 64) -> Image.Image:
    icon_path = Path(__file__).parent / "assets" / "icon.ico"
    if icon_path.exists():
        return Image.open(icon_path).resize((size, size))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill="#FFCD00")
    dot = size // 10
    cx = size // 2
    for offset in (-size // 6, 0, size // 6):
        draw.ellipse([cx + offset - dot, size // 2 - dot,
                      cx + offset + dot, size // 2 + dot], fill="#3C1E1E")
    return img


# ────────────────────────────────────────────────
# 단일 tkinter 루프 관리자
# 모든 창(설정, 로그)을 하나의 메인루프에서 Toplevel로 띄운다.
# ────────────────────────────────────────────────

class _TkManager:
    def __init__(self):
        self._root: tk.Tk | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="TkLoop")
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        self._root = tk.Tk()
        self._root.withdraw()   # 루트 창은 숨김
        self._ready.set()
        self._root.mainloop()

    def schedule(self, fn) -> None:
        """tkinter 스레드에서 fn을 실행하도록 예약 (스레드 안전)."""
        if self._root:
            self._root.after(0, fn)

    @property
    def root(self) -> tk.Tk:
        return self._root


# ────────────────────────────────────────────────
# 규칙 편집 다이얼로그
# ────────────────────────────────────────────────

class _RuleDialog:
    def __init__(self, parent: tk.Misc, rule_manager: RuleManager,
                 rule: dict | None = None, on_done=None):
        self._rm = rule_manager
        self._rule = rule
        self._on_done = on_done

        win = tk.Toplevel(parent)
        win.title("규칙 추가" if rule is None else "규칙 수정")
        win.geometry("460x260")
        win.resizable(False, False)
        win.grab_set()
        self._win = win
        self._build()

    def _build(self) -> None:
        win, r = self._win, self._rule or {}
        pad = {"padx": 12, "pady": 6}

        ttk.Label(win, text="채팅방 이름:").grid(row=0, column=0, sticky=tk.W, **pad)
        self._keyword = tk.StringVar(value=r.get("keyword", ""))
        ttk.Entry(win, textvariable=self._keyword, width=32).grid(
            row=0, column=1, columnspan=2, sticky=tk.W, **pad)

        ttk.Label(win, text="매칭 방식:").grid(row=1, column=0, sticky=tk.W, **pad)
        self._type = tk.StringVar(value=r.get("type", "exact"))
        ttk.Combobox(win, textvariable=self._type,
                     values=["exact", "contains", "regex"],
                     width=14, state="readonly").grid(row=1, column=1, sticky=tk.W, **pad)

        ttk.Label(win, text="알림음 파일:").grid(row=2, column=0, sticky=tk.W, **pad)
        self._sound = tk.StringVar(value=r.get("sound", ""))
        ttk.Entry(win, textvariable=self._sound, width=28).grid(
            row=2, column=1, sticky=tk.W, **pad)
        ttk.Button(win, text="찾기", command=self._browse).grid(row=2, column=2, padx=4)

        ttk.Label(win, text="음소거:").grid(row=3, column=0, sticky=tk.W, **pad)
        self._mute = tk.BooleanVar(value=r.get("mute", False))
        ttk.Checkbutton(win, variable=self._mute).grid(row=3, column=1, sticky=tk.W, **pad)

        bf = ttk.Frame(win)
        bf.grid(row=4, column=0, columnspan=3, pady=18)
        ttk.Button(bf, text="저장", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(bf, text="취소", command=win.destroy).pack(side=tk.LEFT)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="알림음 선택",
            filetypes=[("오디오 파일", "*.mp3 *.wav *.ogg"), ("모든 파일", "*.*")],
            parent=self._win,
        )
        if path:
            self._sound.set(path)

    def _save(self) -> None:
        keyword = self._keyword.get().strip()
        if not keyword:
            messagebox.showwarning("입력 오류", "채팅방 이름을 입력하세요.", parent=self._win)
            return
        data = {
            "type": self._type.get(),
            "keyword": keyword,
            "sound": self._sound.get().strip(),
            "mute": self._mute.get(),
        }
        if self._rule:
            self._rm.update_rule(self._rule["id"], data)
        else:
            self._rm.add_rule(data)
        if self._on_done:
            self._on_done()
        self._win.destroy()


# ────────────────────────────────────────────────
# 실시간 로그 창
# ────────────────────────────────────────────────

class LogWindow:
    def __init__(self, tk_mgr: _TkManager, log_queue: queue.Queue):
        self._mgr = tk_mgr
        self._queue = log_queue
        self._win: tk.Toplevel | None = None

    def open(self) -> None:
        """tkinter 스레드에서 호출된다."""
        if self._win and self._win.winfo_exists():
            self._win.lift()
            return

        win = tk.Toplevel(self._mgr.root)
        win.title("KakaoNotify 실시간 로그")
        win.geometry("760x440")
        win.minsize(500, 300)
        self._win = win

        toolbar = ttk.Frame(win)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Label(toolbar, text="실시간 로그", font=("", 9, "bold")).pack(side=tk.LEFT)

        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        txt = tk.Text(
            frame, state=tk.DISABLED, wrap=tk.WORD,
            bg="#1e1e1e", fg="#d4d4d4",
            font=("Consolas", 9), relief=tk.FLAT, padx=6, pady=4,
        )
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        txt.tag_configure("ts",    foreground="#858585")
        txt.tag_configure("error", foreground="#f48771")
        txt.tag_configure("warn",  foreground="#cca700")
        txt.tag_configure("kakao", foreground="#4ec9b0")
        txt.tag_configure("sound", foreground="#9cdcfe")

        bottom = ttk.Frame(win)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 6))
        auto_scroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="자동 스크롤", variable=auto_scroll).pack(side=tk.LEFT)
        ttk.Button(bottom, text="지우기",
                   command=lambda: (txt.configure(state=tk.NORMAL),
                                    txt.delete("1.0", tk.END),
                                    txt.configure(state=tk.DISABLED))
                   ).pack(side=tk.RIGHT)

        def poll() -> None:
            while True:
                try:
                    msg = self._queue.get_nowait()
                except queue.Empty:
                    break
                self._append(txt, msg)
            if auto_scroll.get():
                txt.see(tk.END)
            if win.winfo_exists():
                win.after(200, poll)

        poll()

    def _append(self, txt: tk.Text, msg: str) -> None:
        txt.configure(state=tk.NORMAL)
        if msg.startswith("[") and "]" in msg:
            ts, rest = msg.split("]", 1)
            txt.insert(tk.END, ts + "]", "ts")
            msg = rest

        lower = msg.lower()
        tag = ("error" if ("오류" in lower or "error" in lower) else
               "warn"  if ("경고" in lower or "warn"  in lower) else
               "kakao" if ("수신" in lower or "카카오" in lower) else
               "sound" if ("재생" in lower or "sound" in lower) else "")
        txt.insert(tk.END, msg, tag)
        txt.configure(state=tk.DISABLED)


# ────────────────────────────────────────────────
# 설정 창
# ────────────────────────────────────────────────

class SettingsWindow:
    def __init__(self, tk_mgr: _TkManager, config: ConfigManager, rule_manager: RuleManager):
        self._mgr = tk_mgr
        self.config = config
        self.rule_manager = rule_manager
        self._win: tk.Toplevel | None = None

    def open(self) -> None:
        """tkinter 스레드에서 호출된다."""
        if self._win and self._win.winfo_exists():
            self._win.lift()
            return

        win = tk.Toplevel(self._mgr.root)
        win.title("KakaoNotify 설정")
        win.geometry("720x520")
        win.minsize(600, 420)
        self._win = win

        top = ttk.LabelFrame(win, text="일반 설정", padding=10)
        top.pack(fill=tk.X, padx=12, pady=8)

        self._kakao_mute_var = tk.BooleanVar(value=self.config.kakao_mute)
        ttk.Checkbutton(top, text="카카오톡 기본 알림음 음소거",
                        variable=self._kakao_mute_var).pack(anchor=tk.W)

        self._autostart_var = tk.BooleanVar(value=self.config.autostart)
        ttk.Checkbutton(top, text="Windows 시작 시 자동 실행",
                        variable=self._autostart_var).pack(anchor=tk.W)

        ds = ttk.Frame(top)
        ds.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(ds, text="기본 알림음:").pack(side=tk.LEFT)
        self._default_sound_var = tk.StringVar(value=self.config.default_sound)
        ttk.Entry(ds, textvariable=self._default_sound_var, width=42).pack(side=tk.LEFT, padx=6)
        ttk.Button(ds, text="찾기",
                   command=lambda: self._browse_default(win)).pack(side=tk.LEFT)

        rf = ttk.LabelFrame(win, text="채팅방별 알림음 규칙", padding=10)
        rf.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        tb = ttk.Frame(rf)
        tb.pack(fill=tk.X, pady=(0, 6))

        cols = ("채팅방 이름", "매칭 방식", "알림음 파일", "음소거")
        tree = ttk.Treeview(rf, columns=cols, show="headings", height=10)
        for col, w in zip(cols, (140, 80, 340, 60)):
            tree.heading(col, text=col)
            tree.column(col, width=w, minwidth=50)
        sb = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(tb, text="+ 추가",
                   command=lambda: _RuleDialog(win, self.rule_manager,
                                               on_done=lambda: self._refresh(tree))
                   ).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="수정",
                   command=lambda: self._edit(win, tree)).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="삭제",
                   command=lambda: self._delete(win, tree)).pack(side=tk.LEFT, padx=2)

        self._refresh(tree)

        bf = ttk.Frame(win)
        bf.pack(fill=tk.X, padx=12, pady=10)
        ttk.Button(bf, text="저장",
                   command=lambda: self._save(win)).pack(side=tk.RIGHT, padx=6)
        ttk.Button(bf, text="취소", command=win.destroy).pack(side=tk.RIGHT)

    def _refresh(self, tree: ttk.Treeview) -> None:
        tree.delete(*tree.get_children())
        for rule in self.config.rules:
            tree.insert("", tk.END, iid=rule.get("id", ""), values=(
                rule.get("keyword", ""),
                rule.get("type", "exact"),
                rule.get("sound", ""),
                "예" if rule.get("mute") else "아니오",
            ))

    def _browse_default(self, parent) -> None:
        path = filedialog.askopenfilename(
            title="기본 알림음 선택",
            filetypes=[("오디오 파일", "*.mp3 *.wav *.ogg"), ("모든 파일", "*.*")],
            parent=parent,
        )
        if path:
            self._default_sound_var.set(path)

    def _edit(self, parent, tree: ttk.Treeview) -> None:
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "수정할 규칙을 선택하세요.", parent=parent)
            return
        rule = next((r for r in self.config.rules if r.get("id") == sel[0]), None)
        if rule:
            _RuleDialog(parent, self.rule_manager, rule=rule,
                        on_done=lambda: self._refresh(tree))

    def _delete(self, parent, tree: ttk.Treeview) -> None:
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "삭제할 규칙을 선택하세요.", parent=parent)
            return
        if messagebox.askyesno("삭제 확인", "선택한 규칙을 삭제하시겠습니까?", parent=parent):
            self.rule_manager.remove_rule(sel[0])
            self._refresh(tree)

    def _save(self, win: tk.Toplevel) -> None:
        self.config.kakao_mute = self._kakao_mute_var.get()
        self.config.autostart = self._autostart_var.get()
        self.config.default_sound = self._default_sound_var.get()
        self.config.save()
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.", parent=win)
        win.destroy()


# ────────────────────────────────────────────────
# 트레이 앱
# ────────────────────────────────────────────────

class TrayApp:
    def __init__(self, config: ConfigManager, rule_manager: RuleManager,
                 log_queue: queue.Queue, on_quit=None):
        self.on_quit = on_quit
        self._active = True
        self._icon: pystray.Icon | None = None

        self._tk = _TkManager()
        self._settings = SettingsWindow(self._tk, config, rule_manager)
        self._log_win = LogWindow(self._tk, log_queue)

    @property
    def is_active(self) -> bool:
        return self._active

    def _open_settings(self, icon, item) -> None:
        self._tk.schedule(self._settings.open)

    def _open_log(self, icon, item) -> None:
        self._tk.schedule(self._log_win.open)

    def _toggle_active(self, icon, item) -> None:
        self._active = not self._active
        print(f"[Tray] {'활성화' if self._active else '비활성화'}")

    def _quit(self, icon, item) -> None:
        if self.on_quit:
            self.on_quit()
        icon.stop()

    def run(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("설정 열기", self._open_settings, default=True),
            pystray.MenuItem("로그 보기", self._open_log),
            pystray.MenuItem("활성화", self._toggle_active,
                             checked=lambda item: self._active),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", self._quit),
        )
        self._icon = pystray.Icon(
            name="KakaoNotify",
            icon=_make_icon_image(),
            title="KakaoNotify",
            menu=menu,
        )
        self._icon.run()
