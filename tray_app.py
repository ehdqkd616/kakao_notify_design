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


# ── 공통 팔레트 ──────────────────────────────────────────────────────────────
_BG     = "#0d1117"
_BG2    = "#161b22"
_BG3    = "#21262d"
_FG     = "#e6edf3"
_FG2    = "#8b949e"
_GREEN  = "#3fb950"
_RED    = "#f85149"
_YELLOW = "#d29922"
_BLUE   = "#58a6ff"

_BTN  = dict(font=("Segoe UI", 9, "bold"), relief="flat", padx=14, pady=6, cursor="hand2", bd=0)
_SBTN = dict(font=("Segoe UI", 8, "bold"), relief="flat", padx=10, pady=4, cursor="hand2", bd=0)


# ── 규칙 편집 다이얼로그 ──────────────────────────────────────────────────────

class _RuleDialog:
    def __init__(self, parent: tk.Misc, rule_manager: RuleManager,
                 rule: dict | None = None, on_done=None):
        self._rm = rule_manager
        self._rule = rule
        self._on_done = on_done

        win = tk.Toplevel(parent)
        win.title("규칙 추가" if rule is None else "규칙 수정")
        win.geometry("500x280")
        win.resizable(False, False)
        win.configure(bg=_BG2)
        win.grab_set()
        self._win = win
        self._build()

    def _build(self):
        win, r = self._win, self._rule or {}
        lbl_cfg = dict(bg=_BG2, fg=_FG, font=("Segoe UI", 9))
        ent_cfg = dict(bg=_BG3, fg=_FG, insertbackground=_FG, relief="flat", bd=4)

        rows = tk.Frame(win, bg=_BG2, padx=16, pady=16)
        rows.pack(fill="both", expand=True)
        rows.columnconfigure(1, weight=1)

        # 채팅방 이름
        tk.Label(rows, text="채팅방 이름:", **lbl_cfg).grid(row=0, column=0, sticky="w", pady=7)
        self._keyword = tk.StringVar(value=r.get("keyword", ""))
        tk.Entry(rows, textvariable=self._keyword, width=34, **ent_cfg).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        # 매칭 방식
        tk.Label(rows, text="매칭 방식:", **lbl_cfg).grid(row=1, column=0, sticky="w", pady=7)
        self._type = tk.StringVar(value=r.get("type", "exact"))
        om = tk.OptionMenu(rows, self._type, "exact", "contains", "regex")
        om.config(bg=_BG3, fg=_FG, activebackground=_BG3, activeforeground=_FG,
                  highlightthickness=0, bd=0, font=("Segoe UI", 9), relief="flat")
        om["menu"].config(bg=_BG3, fg=_FG, activebackground=_BLUE, activeforeground="white")
        om.grid(row=1, column=1, sticky="w", padx=(8, 0))

        # 알림음
        tk.Label(rows, text="알림음 파일:", **lbl_cfg).grid(row=2, column=0, sticky="w", pady=7)
        self._sound = tk.StringVar(value=r.get("sound", ""))
        tk.Entry(rows, textvariable=self._sound, width=30, **ent_cfg).grid(
            row=2, column=1, sticky="ew", padx=(8, 4))
        tk.Button(rows, text="찾기", bg=_BG3, fg=_FG2,
                  command=self._browse, **_SBTN).grid(row=2, column=2)

        # 음소거
        tk.Label(rows, text="음소거:", **lbl_cfg).grid(row=3, column=0, sticky="w", pady=7)
        self._mute = tk.BooleanVar(value=r.get("mute", False))
        tk.Checkbutton(rows, variable=self._mute, bg=_BG2, fg=_FG,
                       selectcolor=_BG3, activebackground=_BG2,
                       font=("Segoe UI", 9)).grid(row=3, column=1, sticky="w", padx=(8, 0))

        # 버튼
        bf = tk.Frame(win, bg=_BG, pady=10)
        bf.pack(fill="x", padx=12)
        tk.Button(bf, text="저장", bg="#1f6feb", fg="white",
                  command=self._save, **_BTN).pack(side="right", padx=4)
        tk.Button(bf, text="취소", bg=_BG3, fg=_FG2,
                  command=win.destroy, **_BTN).pack(side="right")

    def _browse(self):
        path = filedialog.askopenfilename(
            title="알림음 선택",
            filetypes=[("오디오 파일", "*.mp3 *.wav *.ogg"), ("모든 파일", "*.*")],
            parent=self._win,
        )
        if path:
            self._sound.set(path)

    def _save(self):
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


# ── 설정 창 ─────────────────────────────────────────────────────────────────

class SettingsWindow:
    def __init__(self, root: tk.Tk, config: ConfigManager, rule_manager: RuleManager):
        self._root = root
        self.config = config
        self.rule_manager = rule_manager
        self._win: tk.Toplevel | None = None

    def open(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            return

        win = tk.Toplevel(self._root)
        win.title("KakaoNotify 설정")
        win.geometry("740x580")
        win.minsize(600, 460)
        win.configure(bg=_BG)
        win.grab_set()
        self._win = win
        self._build(win)

    def _build(self, win: tk.Toplevel):
        ent_cfg = dict(bg=_BG3, fg=_FG, insertbackground=_FG, relief="flat", bd=4)

        # ── 일반 설정 ──
        gen = tk.Frame(win, bg=_BG2, padx=14, pady=12)
        gen.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(gen, text="일반 설정", font=("Segoe UI", 9, "bold"),
                 bg=_BG2, fg=_FG2).pack(anchor="w", pady=(0, 8))

        self._kakao_mute_var = tk.BooleanVar(value=self.config.kakao_mute)
        tk.Checkbutton(gen, text="카카오톡 기본 알림음 음소거",
                       variable=self._kakao_mute_var,
                       bg=_BG2, fg=_FG, selectcolor=_BG3, activebackground=_BG2,
                       font=("Segoe UI", 9)).pack(anchor="w")

        self._autostart_var = tk.BooleanVar(value=self.config.autostart)
        tk.Checkbutton(gen, text="Windows 시작 시 자동 실행",
                       variable=self._autostart_var,
                       bg=_BG2, fg=_FG, selectcolor=_BG3, activebackground=_BG2,
                       font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))

        ds = tk.Frame(gen, bg=_BG2)
        ds.pack(fill="x", pady=(10, 0))
        tk.Label(ds, text="기본 알림음:", bg=_BG2, fg=_FG,
                 font=("Segoe UI", 9)).pack(side="left")
        self._default_sound_var = tk.StringVar(value=self.config.default_sound)
        tk.Entry(ds, textvariable=self._default_sound_var, width=42, **ent_cfg).pack(
            side="left", padx=6)
        tk.Button(ds, text="찾기", bg=_BG3, fg=_FG2,
                  command=lambda: self._browse_default(win), **_SBTN).pack(side="left")

        # ── 규칙 목록 ──
        rf = tk.Frame(win, bg=_BG2, padx=14, pady=12)
        rf.pack(fill="both", expand=True, padx=12, pady=4)

        # 툴바
        tb = tk.Frame(rf, bg=_BG2)
        tb.pack(fill="x", pady=(0, 6))
        tk.Label(tb, text="채팅방별 알림음 규칙", font=("Segoe UI", 9, "bold"),
                 bg=_BG2, fg=_FG2).pack(side="left")

        # Treeview 다크 스타일
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Dark.Treeview", background=_BG3, foreground=_FG,
                        fieldbackground=_BG3, rowheight=26, borderwidth=0)
        style.configure("Dark.Treeview.Heading", background=_BG2, foreground=_FG2,
                        borderwidth=0, relief="flat")
        style.map("Dark.Treeview", background=[("selected", "#1f6feb")])

        cols = ("채팅방 이름", "매칭 방식", "알림음 파일", "음소거")
        tree = ttk.Treeview(rf, columns=cols, show="headings",
                             height=10, style="Dark.Treeview")
        for col, w in zip(cols, (130, 80, 340, 60)):
            tree.heading(col, text=col)
            tree.column(col, width=w, minwidth=40)

        sb = ttk.Scrollbar(rf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)

        # 버튼 (tree 정의 후 — 클로저가 tree를 캡처)
        tk.Button(tb, text="+ 추가", bg=_BG3, fg=_FG,
                  command=lambda: _RuleDialog(win, self.rule_manager,
                                              on_done=lambda: self._refresh(tree)),
                  **_SBTN).pack(side="left", padx=(12, 2))
        tk.Button(tb, text="수정", bg=_BG3, fg=_FG,
                  command=lambda: self._edit(win, tree), **_SBTN).pack(side="left", padx=2)
        tk.Button(tb, text="삭제", bg=_BG3, fg=_RED,
                  command=lambda: self._delete(win, tree), **_SBTN).pack(side="left", padx=2)

        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        self._refresh(tree)

        # 저장 / 취소
        bf = tk.Frame(win, bg=_BG, pady=10)
        bf.pack(fill="x", padx=12)
        tk.Button(bf, text="저장", bg="#1f6feb", fg="white",
                  command=lambda: self._save(win), **_BTN).pack(side="right", padx=4)
        tk.Button(bf, text="취소", bg=_BG3, fg=_FG2,
                  command=win.destroy, **_BTN).pack(side="right")

    def _refresh(self, tree: ttk.Treeview):
        tree.delete(*tree.get_children())
        for rule in self.config.rules:
            tree.insert("", "end", iid=rule.get("id", ""), values=(
                rule.get("keyword", ""),
                rule.get("type", "exact"),
                rule.get("sound", ""),
                "예" if rule.get("mute") else "아니오",
            ))

    def _browse_default(self, parent):
        path = filedialog.askopenfilename(
            title="기본 알림음 선택",
            filetypes=[("오디오 파일", "*.mp3 *.wav *.ogg"), ("모든 파일", "*.*")],
            parent=parent,
        )
        if path:
            self._default_sound_var.set(path)

    def _edit(self, parent, tree: ttk.Treeview):
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "수정할 규칙을 선택하세요.", parent=parent)
            return
        rule = next((r for r in self.config.rules if r.get("id") == sel[0]), None)
        if rule:
            _RuleDialog(parent, self.rule_manager, rule=rule,
                        on_done=lambda: self._refresh(tree))

    def _delete(self, parent, tree: ttk.Treeview):
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "삭제할 규칙을 선택하세요.", parent=parent)
            return
        if messagebox.askyesno("삭제 확인", "선택한 규칙을 삭제하시겠습니까?", parent=parent):
            self.rule_manager.remove_rule(sel[0])
            self._refresh(tree)

    def _save(self, win: tk.Toplevel):
        self.config.kakao_mute = self._kakao_mute_var.get()
        self.config.autostart = self._autostart_var.get()
        self.config.default_sound = self._default_sound_var.get()
        self.config.save()
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.", parent=win)
        win.destroy()


# ── 메인 앱 (트레이 + 메인 윈도우) ──────────────────────────────────────────

class TrayApp:
    KK_YELLOW = "#FAE100"

    def __init__(self, config: ConfigManager, rule_manager: RuleManager,
                 log_queue: queue.Queue, on_quit=None):
        self.on_quit = on_quit
        self._config = config
        self._rule_manager = rule_manager
        self._log_queue = log_queue
        self._active = True
        self._tray: pystray.Icon | None = None
        self._icon_img = _make_icon_image(64)
        self._all_lines: list[tuple[str, str]] = []

        self._root = self._build_window()
        self._settings = SettingsWindow(self._root, config, rule_manager)
        self._build_tray()

    # ── 윈도우 구성 ──────────────────────────────────────────────────────────

    def _build_window(self) -> tk.Tk:
        root = tk.Tk()
        root.title("KakaoNotify")
        root.geometry("820x580")
        root.minsize(660, 440)
        root.configure(bg=_BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            from PIL import ImageTk
            _tk_icon = ImageTk.PhotoImage(
                self._icon_img.resize((32, 32), Image.LANCZOS)
            )
            root.iconphoto(True, _tk_icon)
            self._tk_icon = _tk_icon  # GC 방지
        except Exception:
            pass

        self._build_header(root)
        self._build_controls(root)
        self._build_log_area(root)
        root.after(200, self._poll_log)
        return root

    def _build_header(self, root: tk.Tk):
        hdr = tk.Frame(root, bg=self.KK_YELLOW, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  🔔  KakaoNotify",
                 font=("Segoe UI", 14, "bold"),
                 bg=self.KK_YELLOW, fg="#1a1400").pack(side="left", padx=14)
        tk.Label(hdr, text="카카오톡 채팅방별 알림음 커스터마이저",
                 font=("Segoe UI", 9),
                 bg=self.KK_YELLOW, fg="#7a6200").pack(side="right", padx=14)

    def _build_controls(self, root: tk.Tk):
        bar = tk.Frame(root, bg=_BG2, pady=9)
        bar.pack(fill="x")

        self._dot = tk.Label(bar, text="●", font=("Segoe UI", 15),
                              bg=_BG2, fg=_GREEN)
        self._dot.pack(side="left", padx=(14, 4))
        self._status_lbl = tk.Label(bar, text="감지 중",
                                     font=("Segoe UI", 10, "bold"),
                                     bg=_BG2, fg=_FG)
        self._status_lbl.pack(side="left", padx=(0, 20))

        self._btn_toggle = tk.Button(bar, text="⏸  일시 정지",
                                      bg=_YELLOW, fg="#0d1117",
                                      command=self._toggle_active, **_BTN)
        self._btn_toggle.pack(side="left", padx=3)

        # self._settings 가 아직 없으므로 lambda로 지연 참조
        tk.Button(bar, text="⚙  설정",
                  bg=_BLUE, fg="white",
                  command=lambda: self._settings.open(),
                  **_BTN).pack(side="left", padx=3)

        tk.Button(bar, text="🔽  트레이로",
                  bg=_BG3, fg=_FG2,
                  command=self._hide_to_tray, **_BTN).pack(side="right", padx=10)

    def _build_log_area(self, root: tk.Tk):
        lhdr = tk.Frame(root, bg=_BG, pady=5)
        lhdr.pack(fill="x", padx=12)

        tk.Label(lhdr, text="실시간 로그",
                 font=("Segoe UI", 9, "bold"),
                 bg=_BG, fg=_FG2).pack(side="left")

        self._filter_var = tk.StringVar(value="ALL")
        for txt, col in [("ALL", _FG2), ("알림", _GREEN), ("오류", _RED)]:
            tk.Radiobutton(
                lhdr, text=txt, variable=self._filter_var, value=txt,
                command=self._apply_filter,
                bg=_BG, fg=col, selectcolor=_BG3,
                activebackground=_BG, font=("Segoe UI", 8),
                relief="flat",
            ).pack(side="left", padx=5)

        self._auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(lhdr, text="자동 스크롤",
                       variable=self._auto_var,
                       bg=_BG, fg=_FG2, selectcolor=_BG3,
                       activebackground=_BG,
                       font=("Segoe UI", 8)).pack(side="right")
        tk.Button(lhdr, text="지우기", bg=_BG, fg=_FG2,
                  font=("Segoe UI", 8), relief="flat", bd=0,
                  command=self._clear_log).pack(side="right", padx=8)

        wrap = tk.Frame(root, bg=_BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._log_txt = tk.Text(
            wrap,
            font=("Consolas", 8),
            bg="#010409", fg="#c9d1d9",
            relief="flat", bd=0, state="disabled", wrap="none",
            selectbackground="#264f78",
        )
        sby = tk.Scrollbar(wrap, orient="vertical", command=self._log_txt.yview, bg=_BG2)
        sbx = tk.Scrollbar(wrap, orient="horizontal", command=self._log_txt.xview, bg=_BG2)
        self._log_txt.configure(yscrollcommand=sby.set, xscrollcommand=sbx.set)
        sby.pack(side="right", fill="y")
        sbx.pack(side="bottom", fill="x")
        self._log_txt.pack(fill="both", expand=True)

        self._log_txt.tag_configure("TS",     foreground="#30363d")
        self._log_txt.tag_configure("notify", foreground=_GREEN)
        self._log_txt.tag_configure("error",  foreground=_RED)
        self._log_txt.tag_configure("ocr",    foreground=_BLUE)
        self._log_txt.tag_configure("warn",   foreground=_YELLOW)

    # ── 트레이 ───────────────────────────────────────────────────────────────

    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem(
                "KakaoNotify 열기",
                lambda i, it: self._root.after(0, self._show_from_tray),
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "활성화",
                lambda i, it: self._root.after(0, self._toggle_active),
                checked=lambda item: self._active,
            ),
            pystray.MenuItem(
                "설정 열기",
                lambda i, it: self._root.after(0, self._settings.open),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "종료",
                lambda i, it: self._root.after(0, self._quit_app),
            ),
        )
        self._tray = pystray.Icon(
            "KakaoNotify", self._icon_img, "KakaoNotify", menu
        )
        threading.Thread(target=self._tray.run, daemon=True, name="TrayIcon").start()

    # ── 상태 토글 ────────────────────────────────────────────────────────────

    def _toggle_active(self):
        self._active = not self._active
        if self._active:
            self._dot.config(fg=_GREEN)
            self._status_lbl.config(text="감지 중")
            self._btn_toggle.config(text="⏸  일시 정지", bg=_YELLOW, fg="#0d1117")
        else:
            self._dot.config(fg=_RED)
            self._status_lbl.config(text="일시 정지")
            self._btn_toggle.config(text="▶  재개", bg=_GREEN, fg="#0d1117")
        print(f"[Tray] {'활성화' if self._active else '비활성화'}")

    # ── 트레이 숨기기 / 복원 ─────────────────────────────────────────────────

    def _hide_to_tray(self):
        self._root.withdraw()

    def _show_from_tray(self):
        self._root.deiconify()
        self._root.lift()

    # ── 로그 ─────────────────────────────────────────────────────────────────

    def _poll_log(self):
        changed = False
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            tag = self._classify(line)
            self._all_lines.append((line, tag))
            if len(self._all_lines) > 2000:
                self._all_lines = self._all_lines[-2000:]
            if self._passes_filter(tag, self._filter_var.get()):
                self._append_line(line, tag)
                changed = True

        if changed and self._auto_var.get():
            self._log_txt.see("end")

        if self._root.winfo_exists():
            self._root.after(200, self._poll_log)

    @staticmethod
    def _classify(line: str) -> str:
        lo = line.lower()
        if "오류" in lo or "error" in lo:
            return "error"
        if "ocr" in lo:
            return "ocr"
        if "경고" in lo or "warn" in lo:
            return "warn"
        if "수신" in lo:
            return "notify"
        return ""

    @staticmethod
    def _passes_filter(tag: str, flt: str) -> bool:
        if flt == "ALL":
            return True
        if flt == "알림":
            return tag == "notify"
        if flt == "오류":
            return tag == "error"
        return True

    def _apply_filter(self):
        flt = self._filter_var.get()
        self._log_txt.config(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.config(state="disabled")
        for line, tag in self._all_lines[-500:]:
            if self._passes_filter(tag, flt):
                self._append_line(line, tag)
        if self._auto_var.get():
            self._log_txt.see("end")

    def _append_line(self, line: str, tag: str):
        self._log_txt.config(state="normal")
        if line.startswith("[") and "]  " in line:
            idx = line.index("]  ") + 3
            self._log_txt.insert("end", line[:idx], "TS")
            self._log_txt.insert("end", line[idx:], tag)
        else:
            self._log_txt.insert("end", line, tag)
        if int(self._log_txt.index("end-1c").split(".")[0]) > 2000:
            self._log_txt.delete("1.0", "400.0")
        self._log_txt.config(state="disabled")

    def _clear_log(self):
        self._log_txt.config(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.config(state="disabled")
        self._all_lines.clear()

    # ── 종료 ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._hide_to_tray()

    def _quit_app(self):
        if self.on_quit:
            self.on_quit()
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        self._root.after(0, self._root.destroy)

    # ── 진입점 ───────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._root.mainloop()

    @property
    def is_active(self) -> bool:
        return self._active
