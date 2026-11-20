"""交互：让用户挑要导出的书。

优先弹窗（tkinter 多选列表），没有图形环境时退回命令行编号输入。
"""
from __future__ import annotations

import os
import sys

TITLE = "微信读书 · 选择要导出的书"


def gui_available():
    if os.environ.get("WEREAD_NO_GUI"):
        return False
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def _pick_gui(items):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(TITLE)
    root.geometry("560x420")
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    tk.Label(root, text="勾选要生成词书的书（Ctrl/Shift 多选）：",
             anchor="w").pack(fill="x", padx=10, pady=(10, 4))

    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scroll = tk.Scrollbar(frame, orient="vertical")
    listbox = tk.Listbox(frame, selectmode="extended",
                         yscrollcommand=scroll.set, activestyle="none")
    scroll.config(command=listbox.yview)
    scroll.pack(side="right", fill="y")
    listbox.pack(side="left", fill="both", expand=True)
    for i, item in enumerate(items):
        listbox.insert("end", f"{i + 1:>2}. {item['title']}   [{item['count']} 条划线]")
    listbox.selection_set(0)

    result = {"value": None}

    def ok(_event=None):
        result["value"] = list(listbox.curselection())
        root.destroy()

    def cancel(_event=None):
        result["value"] = []
        root.destroy()

    def select_all(_event=None):
        listbox.selection_set(0, "end")

    btns = tk.Frame(root)
    btns.pack(fill="x", padx=10, pady=10)
    tk.Button(btns, text="全选", width=8, command=select_all).pack(side="left")
    tk.Button(btns, text="取消", width=8, command=cancel).pack(side="right")
    tk.Button(btns, text="确定", width=8, default="active",
              command=ok).pack(side="right", padx=6)
    listbox.bind("<Double-Button-1>", ok)
    root.bind("<Return>", ok)
    root.bind("<Escape>", cancel)
    root.mainloop()
    return result["value"]


def _pick_console(items):
    if sys.stdin is None or not sys.stdin.isatty():
        return None
    print("\n有划线的书：")
    for i, item in enumerate(items, 1):
        print(f"  {i:>2}. {item['title']}  [{item['count']} 条划线]")
    print("  all = 全部")
    try:
        raw = input("要导出哪几本？（编号用逗号分隔，回车取消）：").strip()
    except (EOFError, KeyboardInterrupt):
        return []
    if not raw:
        return []
    if raw.lower() in ("all", "*", "全部"):
        return list(range(len(items)))
    picked = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(items):
            picked.append(int(part) - 1)
    return sorted(set(picked))


def pick_books(items, allow_gui=True):
    """返回索引列表；取消返回 []；无法交互返回 None。"""
    if not items:
        return []
    if allow_gui and gui_available():
        picked = _pick_gui(items)
        if picked is not None:
            return list(picked)
    return _pick_console(items)
