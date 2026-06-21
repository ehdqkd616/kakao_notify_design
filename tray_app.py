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
    # 카카오 노란 원
    draw.ellipse([2, 2, size - 2, size - 2], fill="#FFCD00")
    # 말풍선 점 세 개
    dot = size // 10
    cx = size // 2
    for offset in (-size // 6, 0, size // 6):
        draw.ellipse([cx + offset - dot, size // 2 - dot, cx + offset + dot, size // 2 + dot], fill="#3C1E1E")
    return img


# ────────────────────────────────────────────────
# 규칙 편집 다이얼로그
# ────────────────────────────────────────────────

class _RuleDialog:
    def __init__(self, parent, rule_manager: RuleManager, rule: dict | None = None, on_done=None):
        self._rm = rule_manager
        self._rule = rule
        self._on_done = on_done

        self._win = tk.Toplevel(parent)
        self._win.title("규칙 추가" if rule is None else "규칙 수정")
        self._win.geometry("460x260")
        self._win.resizable(False, False)
        self._win.grab_set()
        self._build()

    def _build(self):
        win = self._win
        r = self._rule or {}

        pad = {"padx": 12, "pady": 6}

        ttk.Label(win, text="채팅방 이름:").grid(row=0, column=0, sticky=tk.W, **pad)
        self._keyword = tk.StringVar(value=r.get("keyword", ""))
        ttk.Entry(win, textvariable=self._keyword, width=32).grid(row=0, column=1, columnspan=2, sticky=tk.W, **pad)

        ttk.Label(win, text="매칭 방식:").grid(row=1, column=0, sticky=tk.W, **pad)
        self._type = tk.StringVar(value=r.get("type", "exact"))
        ttk.Combobox(win, textvariable=self._type, values=["exact", "contains", "regex"],
                     width=14, state="readonly").grid(row=1, column=1, sticky=tk.W, **pad)

        ttk.Label(win, text="알림음 파일:").grid(row=2, column=0, sticky=tk.W, **pad)
        self._sound = tk.StringVar(value=r.get("sound", ""))
        ttk.Entry(win, textvariable=self._sound, width=28).grid(row=2, column=1, sticky=tk.W, **pad)
        ttk.Button(win, text="찾기", command=self._browse).grid(row=2, column=2, padx=4)

        ttk.Label(win, text="음소거:").grid(row=3, column=0, sticky=tk.W, **pad)
        self._mute = tk.BooleanVar(value=r.get("mute", False))
        ttk.Checkbutton(win, variable=self._mute).grid(row=3, column=1, sticky=tk.W, **pad)

        btn_frame = ttk.Frame(win)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=18)
        ttk.Button(btn_frame, text="저장", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="취소", command=self._win.destroy).pack(side=tk.LEFT)

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


# ────────────────────────────────────────────────
# 설정 창
# ────────────────────────────────────────────────

class SettingsWindow:
    def __init__(self, config: ConfigManager, rule_manager: RuleManager):
        self.config = config
        self.rule_manager = rule_manager
        self._open = False

    def show(self):
        if self._open:
            return
        self._open = True
        try:
            self._run()
        finally:
            self._open = False

    def _run(self):
        root = tk.Tk()
        root.title("KakaoNotify 설정")
        root.geometry("720x520")
        root.minsize(600, 420)

        # ── 일반 설정 ──
        top = ttk.LabelFrame(root, text="일반 설정", padding=10)
        top.pack(fill=tk.X, padx=12, pady=8)

        self._kakao_mute_var = tk.BooleanVar(value=self.config.kakao_mute)
        ttk.Checkbutton(top, text="카카오톡 기본 알림음 음소거 (pycaw 필요)", variable=self._kakao_mute_var).pack(anchor=tk.W)

        self._autostart_var = tk.BooleanVar(value=self.config.autostart)
        ttk.Checkbutton(top, text="Windows 시작 시 자동 실행", variable=self._autostart_var).pack(anchor=tk.W)

        ds_frame = ttk.Frame(top)
        ds_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(ds_frame, text="기본 알림음:").pack(side=tk.LEFT)
        self._default_sound_var = tk.StringVar(value=self.config.default_sound)
        ttk.Entry(ds_frame, textvariable=self._default_sound_var, width=42).pack(side=tk.LEFT, padx=6)
        ttk.Button(ds_frame, text="찾기", command=lambda: self._browse_default(root)).pack(side=tk.LEFT)

        # ── 규칙 목록 ──
        rule_frame = ttk.LabelFrame(root, text="채팅방별 알림음 규칙", padding=10)
        rule_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        toolbar = ttk.Frame(rule_frame)
        toolbar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(toolbar, text="+ 추가", command=lambda: self._add(root, tree)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="수정", command=lambda: self._edit(root, tree)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="삭제", command=lambda: self._delete(root, tree)).pack(side=tk.LEFT, padx=2)

        cols = ("채팅방 이름", "매칭 방식", "알림음 파일", "음소거")
        tree = ttk.Treeview(rule_frame, columns=cols, show="headings", height=10)
        tree.heading("채팅방 이름", text="채팅방 이름")
        tree.heading("매칭 방식", text="매칭 방식")
        tree.heading("알림음 파일", text="알림음 파일")
        tree.heading("음소거", text="음소거")
        tree.column("채팅방 이름", width=140, minwidth=100)
        tree.column("매칭 방식", width=80, minwidth=60)
        tree.column("알림음 파일", width=340, minwidth=200)
        tree.column("음소거", width=60, minwidth=50)
        sb = ttk.Scrollbar(rule_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh(tree)

        # ── 하단 버튼 ──
        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill=tk.X, padx=12, pady=10)
        ttk.Button(btn_frame, text="저장", command=lambda: self._save(root)).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btn_frame, text="취소", command=root.destroy).pack(side=tk.RIGHT)

        root.mainloop()

    def _refresh(self, tree: ttk.Treeview):
        tree.delete(*tree.get_children())
        for rule in self.config.rules:
            tree.insert("", tk.END, iid=rule.get("id", ""), values=(
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

    def _add(self, parent, tree):
        _RuleDialog(parent, self.rule_manager, on_done=lambda: self._refresh(tree))

    def _edit(self, parent, tree):
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "수정할 규칙을 선택하세요.", parent=parent)
            return
        rule = next((r for r in self.config.rules if r.get("id") == sel[0]), None)
        if rule:
            _RuleDialog(parent, self.rule_manager, rule=rule, on_done=lambda: self._refresh(tree))

    def _delete(self, parent, tree):
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("선택 없음", "삭제할 규칙을 선택하세요.", parent=parent)
            return
        if messagebox.askyesno("삭제 확인", "선택한 규칙을 삭제하시겠습니까?", parent=parent):
            self.rule_manager.remove_rule(sel[0])
            self._refresh(tree)

    def _save(self, root):
        self.config.kakao_mute = self._kakao_mute_var.get()
        self.config.autostart = self._autostart_var.get()
        self.config.default_sound = self._default_sound_var.get()
        self.config.save()
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.", parent=root)
        root.destroy()


# ────────────────────────────────────────────────
# 트레이 앱
# ────────────────────────────────────────────────

class TrayApp:
    def __init__(self, config: ConfigManager, rule_manager: RuleManager, on_quit=None):
        self.config = config
        self.rule_manager = rule_manager
        self.on_quit = on_quit
        self._active = True
        self._icon: pystray.Icon | None = None
        self._settings = SettingsWindow(config, rule_manager)

    @property
    def is_active(self) -> bool:
        return self._active

    def _open_settings(self, icon, item):
        threading.Thread(target=self._settings.show, daemon=True).start()

    def _toggle_active(self, icon, item):
        self._active = not self._active
        print(f"[Tray] {'활성화' if self._active else '비활성화'}")

    def _quit(self, icon, item):
        if self.on_quit:
            self.on_quit()
        icon.stop()

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("설정 열기", self._open_settings, default=True),
            pystray.MenuItem(
                "활성화",
                self._toggle_active,
                checked=lambda item: self._active,
            ),
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
