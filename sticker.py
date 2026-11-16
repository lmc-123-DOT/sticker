#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
桌面贴纸 · 三年规划
------------------------------------------------
无边框 / 置顶 / 圆角的小贴纸，贴在桌面上看规划。
· 三个页签：大一 / 大二 / 大三
· 点条目打勾，勾选状态自动存盘
· 左键按住拖动，右键出菜单
· 规划内容在 plans.json，随时改
"""

import ctypes
import json
import os
import sys
import traceback
from datetime import date, datetime

# DPI 感知必须在建窗口之前设置，否则 125%/150% 缩放下会糊
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk, colorchooser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)

# 数据统一放程序目录下的 data\（安装后就是 D:\...\大肥鱼桌面贴纸\data）
DATA_DIR = os.path.join(APP_DIR, "data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = APP_DIR

PLANS_PATH = os.path.join(DATA_DIR, "plans.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

BG = "#FFF9F0"       # 纸的颜色
BORDER = "#E8DCC6"   # 包边
TEXT = "#3B342C"
MUTED = "#A29684"
DONE_C = "#AFA18C"
HOVER = "#F6EDDD"

TARGET = date(2029, 4, 15)   # 专升本大概日期，只用来算倒计时

DEFAULT_PLANS = {
    "title": "三年规划",
    "footer": "",
    "phases": [
        {
            "id": "y1",
            "name": "大一",
            "sub": "破局与输出",
            "accent": "#3E9E6E",
            "groups": [
                {"title": "目标", "items": []},
            ],
        },
        {
            "id": "y2",
            "name": "大二",
            "sub": "深水区与护城河",
            "accent": "#C08421",
            "groups": [
                {"title": "目标", "items": []},
            ],
        },
        {
            "id": "y3",
            "name": "大三",
            "sub": "亮剑与实战",
            "accent": "#C8553D",
            "groups": [
                {"title": "目标", "items": []},
            ],
        },
    ],
}


def load_json(path, default):
    if not os.path.exists(path):
        return json.loads(json.dumps(default))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def log_crash():
    """pythonw 没有控制台，出错就写文件，别让窗口默默不见"""
    try:
        with open(os.path.join(APP_DIR, "crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def auto_phase():
    today = date.today()
    if today < date(2027, 9, 1):
        return "y1"
    if today < date(2028, 9, 1):
        return "y2"
    return "y3"


_MUTEX = None


def single_instance_ok():
    """命名互斥量：同一时间只允许一个贴纸；进程退出自动释放"""
    global _MUTEX
    try:
        k32 = ctypes.windll.kernel32
        _MUTEX = k32.CreateMutexW(None, False, "Local\\DafyuDesktopSticker")
        return k32.GetLastError() != 183      # ERROR_ALREADY_EXISTS
    except Exception:
        return True


class Sticker:
    W = 384          # 贴纸宽度
    PAD = 16         # 内边距
    RADIUS = 18      # 圆角

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.report_callback_exception = lambda *a: log_crash()

        self.plans = load_json(PLANS_PATH, DEFAULT_PLANS)
        self.state = load_json(
            STATE_PATH, {"phase": auto_phase(), "done": [], "x": None, "y": None}
        )
        self.state.setdefault("done", [])
        self.phase_id = self.state.get("phase") or auto_phase()
        self.editor = None
        self._plans_mtime = 0

        self._pick_fonts()
        self._build()

        x, y = self.state.get("x"), self.state.get("y")
        self.pos = (x, y) if isinstance(x, int) and isinstance(y, int) else None

        self._render()
        self._relayout()

        self.root.update_idletasks()
        self._strip_caption()
        self.root.update_idletasks()
        self._round_corners()
        self._save_state()

        self._plans_mtime = os.path.getmtime(PLANS_PATH) if os.path.exists(PLANS_PATH) else 0
        if not os.environ.get("STICKER_NO_SINK"):
            self.root.after(300, self._set_bottom)
            self.root.after(30000, self._keep_bottom)
        self.root.after(1200, self._watch_plans)

    # ---------- 字体 ----------
    def _pick_fonts(self):
        fams = set(tkfont.families(self.root))
        for cand in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "SimHei"):
            if cand in fams:
                family = cand
                break
        else:
            family = "TkDefaultFont"
        f = lambda size, bold=False, strike=False: tkfont.Font(
            family=family, size=size, weight="bold" if bold else "normal",
            overstrike=strike,
        )
        self.f_title = f(13, True)
        self.f_tab = f(10)
        self.f_tab_on = f(10, True)
        self.f_sub = f(8)
        self.f_group = f(10, True)
        self.f_item = f(10)
        self.f_done = f(10, strike=True)
        self.f_foot = f(8)

    # ---------- 界面骨架 ----------
    def _build(self):
        self.root.configure(bg=BORDER)

        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(shell, bg=BG)
        head.pack(fill="x", padx=self.PAD, pady=(10, 0))
        head.configure(cursor="fleur")

        self.bar = tk.Frame(head, bg="#3E9E6E", width=3, height=16)
        self.bar.pack(side="left", padx=(1, 9), pady=4)
        self.bar.pack_propagate(False)

        self.lbl_title = tk.Label(
            head, text=self.plans.get("title", "三年规划"),
            font=self.f_title, fg=TEXT, bg=BG, anchor="w", cursor="fleur",
        )
        self.lbl_title.pack(side="left")

        close = tk.Label(head, text="✕", font=self.f_item, fg=MUTED, bg=BG,
                         cursor="hand2", padx=6)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._quit())
        close.bind("<Enter>", lambda e: close.configure(fg="#C8553D"))
        close.bind("<Leave>", lambda e: close.configure(fg=MUTED))

        tabbar = tk.Frame(shell, bg=BG)
        tabbar.pack(fill="x", padx=self.PAD, pady=(6, 0))
        tabbar.configure(cursor="fleur")

        self.tabbar = tabbar
        self.tabs = {}
        self._rebuild_tabs()

        self.lbl_sub = tk.Label(tabbar, text="", font=self.f_sub, fg=MUTED, bg=BG)
        self.lbl_sub.pack(side="right")

        tk.Frame(shell, bg="#F1E7D6", height=1).pack(fill="x", padx=self.PAD, pady=(8, 2))

        # 内容区（可滚动）
        wrap = tk.Frame(shell, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll(-1))
        self.canvas.bind("<Button-5>", lambda e: self._scroll(1))

        self.body = tk.Frame(self.canvas, bg=BG)
        self.win_id = self.canvas.create_window(
            self.PAD, 0, window=self.body, anchor="nw", width=self.W - 2 - 2 * self.PAD
        )

        foot = tk.Frame(shell, bg=BG)
        foot.pack(fill="x", padx=self.PAD, pady=(4, 10))

        self.lbl_days = tk.Label(foot, text="", font=self.f_foot, fg=MUTED, bg=BG, anchor="w")
        self.lbl_days.pack(side="left")
        self.lbl_foot = tk.Label(foot, text=self.plans.get("footer", ""), font=self.f_foot,
                                 fg=MUTED, bg=BG, anchor="e", wraplength=self.W - 2 - 2 * self.PAD - 110,
                                 justify="right")
        self.lbl_foot.pack(side="right")

        # 拖拽：标题、页签栏、边角、页脚都能拖
        for w in (head, self.lbl_title, tabbar, foot, self.lbl_days, shell):
            self._bind_drag(w)

        # 右键菜单
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="编辑规划内容…", command=self.open_editor)
        self.menu.add_command(label="用记事本改 plans.json", command=self._open_plans)
        self.menu.add_command(label="重新载入规划", command=self._reload_plans)
        self.menu.add_separator()
        self.menu.add_command(label="退出贴纸", command=self._quit)
        for w in (shell, self.body, self.canvas, self.lbl_title):
            w.bind("<Button-3>", self._popup)
        for w in (head, self.lbl_title):
            w.bind("<Double-Button-1>", lambda e: self.open_editor())

    def _bind_drag(self, widget):
        widget.bind("<Button-1>", self._drag_start, add="+")
        widget.bind("<B1-Motion>", self._drag_move, add="+")
        widget.bind("<ButtonRelease-1>", self._drag_end, add="+")

    # ---------- 拖拽 ----------
    def _drag_start(self, e):
        self._offset = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if not getattr(self, "_offset", None):
            return
        x = e.x_root - self._offset[0]
        y = e.y_root - self._offset[1]
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, e):
        self._offset = None
        self.pos = (self.root.winfo_x(), self.root.winfo_y())
        self._save_state()

    # ---------- 右键 ----------
    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _open_plans(self):
        if not os.path.exists(PLANS_PATH):
            save_json(PLANS_PATH, self.plans)
        try:
            os.startfile(PLANS_PATH)
        except Exception:
            pass

    # ---------- 页签 ----------
    def _rebuild_tabs(self):
        for lb in self.tabs.values():
            lb.destroy()
        self.tabs = {}
        for ph in self.plans.get("phases", []):
            lb = tk.Label(self.tabbar, text=ph.get("name", "?"), font=self.f_tab, fg=MUTED,
                          bg=BG, padx=10, pady=3, cursor="hand2")
            lb.pack(side="left", padx=(0, 2))
            lb.bind("<Button-1>", lambda e, pid=ph.get("id"): self._switch(pid))
            self.tabs[ph.get("id")] = lb

    def apply_plans(self, plans):
        """编辑器保存后用新的规划刷新贴纸"""
        self.plans = plans
        try:
            save_json(PLANS_PATH, plans)
            self._plans_mtime = os.path.getmtime(PLANS_PATH)
        except Exception:
            pass
        ids = [p.get("id") for p in self.plans.get("phases", [])]
        if self.phase_id not in ids:
            self.phase_id = ids[0] if ids else "y1"
        self._rebuild_tabs()
        self._render()
        self._relayout()

    def _reload_plans(self):
        self.apply_plans(load_json(PLANS_PATH, DEFAULT_PLANS))

    # ---------- 编辑器 ----------
    def open_editor(self):
        try:
            if self.editor is not None and self.editor.winfo_exists():
                self.editor.lift()
                self.editor.focus_force()
                return
        except Exception:
            pass
        self.editor = Editor(self)

    # ---------- 压到最底层 ----------
    def _hwnd(self):
        try:
            wid = self.root.winfo_id()
            return ctypes.windll.user32.GetParent(wid) or wid
        except Exception:
            return 0

    def _set_bottom(self):
        """贴到最底层：插到「桌面窗口上面那一个窗口」的后面，也就是
        比壁纸高、比所有软件都低。配合 WS_EX_NOACTIVATE，点它不会往上跳。"""
        try:
            hwnd = self._hwnd()
            pm = ctypes.windll.user32.FindWindowW("Progman", None)
            if not pm:
                return
            above = ctypes.windll.user32.GetWindow(pm, 3)   # GW_HWNDPREV：桌面上面那个窗口
            after = above if above else 1                    # 兜底 HWND_BOTTOM
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
            ctypes.windll.user32.SetWindowPos(
                hwnd, after, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def _keep_bottom(self):
        self._set_bottom()
        self.root.after(30000, self._keep_bottom)

    # ---------- 盯住 plans.json ----------
    def _watch_plans(self):
        try:
            if os.path.exists(PLANS_PATH):
                m = os.path.getmtime(PLANS_PATH)
                if m != self._plans_mtime:
                    self._plans_mtime = m
                    self.apply_plans(load_json(PLANS_PATH, DEFAULT_PLANS))
        except Exception:
            pass
        self.root.after(1500, self._watch_plans)

    # ---------- 当前页 ----------
    def current_phase(self):
        for ph in self.plans["phases"]:
            if ph["id"] == self.phase_id:
                return ph
        return self.plans["phases"][0]

    def _switch(self, pid):
        if pid == self.phase_id:
            return
        self.phase_id = pid
        self.state["phase"] = pid
        self._save_state()
        self._render()
        self._relayout()
        self.canvas.yview_moveto(0)

    # ---------- 渲染 ----------
    def _render(self):
        ph = self.current_phase()
        accent = ph.get("accent", "#3E9E6E")

        for w in self.body.winfo_children():
            w.destroy()

        for pid, lb in self.tabs.items():
            if pid == ph["id"]:
                lb.configure(fg=accent, font=self.f_tab_on, bg="#F5ECDB")
            else:
                lb.configure(fg=MUTED, font=self.f_tab, bg=BG)
        self.bar.configure(bg=accent)

        wrap_len = self.W - 2 - 2 * self.PAD - 34
        total = 0
        done_n = 0
        for gi, g in enumerate(ph.get("groups", [])):
            tk.Label(
                self.body, text=g["title"], font=self.f_group, fg=accent, bg=BG,
                anchor="w", justify="left",
            ).pack(fill="x", pady=(10 if gi else 0, 3))

            for ii, it in enumerate(g["items"]):
                key = f'{ph["id"]}-{gi}-{ii}'
                done = key in self.state["done"]
                total += 1
                if done:
                    done_n += 1

                row = tk.Frame(self.body, bg=BG)
                row.pack(fill="x", pady=1)

                chk = tk.Label(row, text="☑" if done else "☐", font=self.f_item,
                               fg=accent if done else MUTED, bg=BG, width=2,
                               anchor="w", cursor="hand2")
                chk.pack(side="left", anchor="n")

                txt = tk.Label(
                    row, text=it,
                    font=self.f_done if done else self.f_item,
                    fg=DONE_C if done else TEXT,
                    bg=BG, anchor="w", justify="left",
                    wraplength=wrap_len, cursor="hand2",
                )
                txt.pack(side="left", fill="x", expand=True)

                for w in (chk, txt):
                    w.bind("<Button-1>", lambda e, k=key: self._toggle(k))
                    w.bind("<Enter>", lambda e, pair=(chk, txt):
                           [x.configure(bg=HOVER) for x in pair])
                    w.bind("<Leave>", lambda e, pair=(chk, txt):
                           [x.configure(bg=BG) for x in pair])

        days = (TARGET - date.today()).days
        if days > 0:
            self.lbl_days.configure(text=f"专升本约剩 {days} 天")
        else:
            self.lbl_days.configure(text="该考试了")
        self.lbl_foot.configure(text=self.plans.get("footer", ""))
        sub = ph.get("sub", "")
        self.lbl_sub.configure(text=f"{sub} · {done_n}/{total}" if total else sub, fg=accent)

    def _toggle(self, key):
        done = self.state["done"]
        if key in done:
            done.remove(key)
        else:
            done.append(key)
        yview = self.canvas.yview()
        self._save_state()
        self._render()
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(yview[0])

    # ---------- 尺寸与圆角 ----------
    def _relayout(self):
        self.root.update_idletasks()
        need = self.body.winfo_reqheight() + 2
        max_h = int(self.root.winfo_screenheight() * 0.62)
        view_h = min(need, max_h)
        self.canvas.configure(height=view_h)
        self.canvas.configure(scrollregion=(0, 0, self.W - 2 - 2 * self.PAD, need))
        self.root.update_idletasks()

        h = self.root.winfo_reqheight()
        if self.pos is None:
            sw = self.root.winfo_screenwidth()
            x = max(16, sw - self.W - 56)
            y = 96
        else:
            x, y = self.pos
        self.root.geometry(f"{self.W}x{h}+{x}+{y}")
        self.pos = (x, y)
        self.root.update_idletasks()
        self._round_corners()

    def _strip_caption(self):
        """把 Windows 的标题栏彻底剥掉，顺手设成不抢焦点、不进 Alt+Tab"""
        try:
            hwnd = self._hwnd()
            GWL_STYLE = -16
            GWL_EXSTYLE = -20
            WS_CAPTION = 0x00C00000
            WS_POPUP = 0x80000000
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_STYLE, (style & ~WS_CAPTION) | WS_POPUP
            )
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            )
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x20
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
        except Exception:
            pass

    def _round_corners(self):
        try:
            wid = self.root.winfo_id()
            hwnd = ctypes.windll.user32.GetParent(wid) or wid
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, w + 1, h + 1, self.RADIUS * 2, self.RADIUS * 2
            )
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    # ---------- 滚轮 ----------
    def _on_wheel(self, e):
        self._scroll(-1 if e.delta > 0 else 1)

    def _scroll(self, step):
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        self.canvas.yview_scroll(step, "units")

    # ---------- 存盘 ----------
    def _save_state(self):
        self.state["phase"] = self.phase_id
        if self.pos:
            self.state["x"] = int(self.pos[0])
            self.state["y"] = int(self.pos[1])
        try:
            save_json(STATE_PATH, self.state)
        except Exception:
            pass

    def _quit(self):
        self._save_state()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class Editor(tk.Toplevel):
    """改文字用的窗口：左边不管，上面选页，中间是内容，底部保存"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("编辑规划内容")
        self.plans = json.loads(json.dumps(app.plans, ensure_ascii=False))
        self.cur = 0
        self.var_phase = tk.IntVar(value=0)
        self.resizable(True, True)
        self._build()
        self._load(0)
        self._center()
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _center(self):
        self.update_idletasks()
        w, h = 1040, 780
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{max(30, (sw - w) // 2)}+{max(30, (sh - h) // 3)}")

    def _build(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        bar = ttk.Frame(root)
        bar.pack(fill="x")
        ttk.Label(bar, text="阶段：").pack(side="left")
        for i, ph in enumerate(self.plans.get("phases", [])):
            ttk.Radiobutton(bar, text=ph.get("name", "第%d页" % (i + 1)),
                            variable=self.var_phase, value=i,
                            command=lambda i=i: self._switch(i)).pack(side="left", padx=(0, 12))

        row = ttk.Frame(root)
        row.pack(fill="x", pady=(10, 4))
        ttk.Label(row, text="页签名").pack(side="left")
        self.e_name = ttk.Entry(row, width=7)
        self.e_name.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="副标题").pack(side="left")
        self.e_sub = ttk.Entry(row, width=16)
        self.e_sub.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="主题色").pack(side="left")
        self.e_color = ttk.Entry(row, width=9)
        self.e_color.pack(side="left", padx=(6, 6))
        self.swatch = tk.Frame(row, width=18, height=18, bg="#3E9E6E", bd=1, relief="solid")
        self.swatch.pack(side="left", padx=(0, 8))
        ttk.Button(row, text="选色", width=5, command=self._pick_color).pack(side="left")

        ttk.Label(root, text="内容：以 # 开头是一组标题，其余每行一条，空行自动忽略").pack(
            anchor="w", pady=(10, 2))

        # 底部两行先占位，免得内容区把它们顶出窗口
        row4 = ttk.Frame(root)
        row4.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(row4, text="保存并应用", command=self._save).pack(side="right")
        ttk.Button(row4, text="关闭", command=self._close).pack(side="right", padx=8)
        self.lbl_status = ttk.Label(row4, text="改完点「保存并应用」，贴纸立刻变", foreground="#8A7F70")
        self.lbl_status.pack(side="left")

        row3 = ttk.Frame(root)
        row3.pack(side="bottom", fill="x", pady=(10, 4))
        ttk.Label(row3, text="贴纸标题").pack(side="left")
        self.e_title = ttk.Entry(row3, width=12)
        self.e_title.pack(side="left", padx=(6, 16))
        ttk.Label(row3, text="底部小字").pack(side="left")
        self.e_foot = ttk.Entry(row3, width=30)
        self.e_foot.pack(side="left", padx=6)

        box = ttk.Frame(root)
        box.pack(fill="both", expand=True)
        self.txt = tk.Text(box, wrap="word", undo=True, font=self.app.f_item,
                           relief="solid", bd=1, highlightthickness=0, padx=8, pady=6)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---- 数据 <-> 界面 ----
    @staticmethod
    def _phase_text(ph):
        out = []
        for g in ph.get("groups", []):
            out.append("# " + g.get("title", ""))
            out.extend(g.get("items", []))
            out.append("")
        return "\n".join(out).strip() + "\n"

    @staticmethod
    def _groups_from_text(text):
        groups = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                groups.append({"title": line.lstrip("#").strip(), "items": []})
            else:
                if not groups:
                    groups.append({"title": "其他", "items": []})
                groups[-1]["items"].append(line)
        return groups

    @staticmethod
    def _valid_color(c):
        return (len(c) == 7 and c.startswith("#")
                and all(ch in "0123456789abcdefABCDEF" for ch in c[1:]))

    def _refresh_swatch(self, color):
        if self._valid_color(color):
            self.swatch.configure(bg=color)

    def _pick_color(self):
        cur = self.e_color.get().strip()
        rgb, hexv = colorchooser.askcolor(color=cur if self._valid_color(cur) else "#3E9E6E",
                                          parent=self, title="选一个主题色")
        if hexv:
            self.e_color.delete(0, "end")
            self.e_color.insert(0, hexv.upper())
            self._refresh_swatch(hexv.upper())

    def _load(self, i):
        self.cur = i
        ph = self.plans["phases"][i]
        self.var_phase.set(i)
        for entry, val in ((self.e_name, ph.get("name", "")),
                           (self.e_sub, ph.get("sub", "")),
                           (self.e_color, ph.get("accent", "#3E9E6E")),
                           (self.e_title, self.plans.get("title", "三年规划")),
                           (self.e_foot, self.plans.get("footer", ""))):
            entry.delete(0, "end")
            entry.insert(0, val)
        self._refresh_swatch(ph.get("accent", "#3E9E6E"))
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", self._phase_text(ph))

    def _commit(self):
        ph = self.plans["phases"][self.cur]
        name = self.e_name.get().strip()
        if name:
            ph["name"] = name
        ph["sub"] = self.e_sub.get().strip()
        color = self.e_color.get().strip()
        if self._valid_color(color):
            ph["accent"] = color.upper()
        ph["groups"] = self._groups_from_text(self.txt.get("1.0", "end"))
        title = self.e_title.get().strip()
        if title:
            self.plans["title"] = title
        self.plans["footer"] = self.e_foot.get().strip()

    def _switch(self, i):
        if i == self.cur:
            return
        self._commit()
        self._load(i)

    def _save(self):
        self._commit()
        self.app.apply_plans(self.plans)
        self.lbl_status.configure(
            text="已保存 " + datetime.now().strftime("%H:%M:%S") + "，贴纸已经跟着变了",
            foreground="#3E9E6E")

    def _close(self):
        self.app.editor = None
        self.destroy()


def main():
    # 只允许一个实例（用命名互斥量，进程一死就自动释放，不会像端口那样卡在 TIME_WAIT）
    if not single_instance_ok():
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo("桌面贴纸", "贴纸已经在桌面上了～")
        return

    if not os.path.exists(PLANS_PATH):
        try:
            save_json(PLANS_PATH, DEFAULT_PLANS)
        except Exception:
            pass

    app = Sticker()
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_crash()
        raise
