"""API Key 的来源与保存。

优先级：环境变量 WEREAD_API_KEY → （可选）已保存的 Key → 弹窗询问。

默认**每次运行都询问**，不静默复用；想记住用 --remember-key，想复用用 --use-saved-key。
Key 只存在用户目录，绝不写进 skill 安装目录，日志里只出现掩码。
"""
from __future__ import annotations

import getpass
import os
import re
import sys

import paths

ENV_VAR = "WEREAD_API_KEY"
PROMPT_TITLE = "微信读书 · 输入 API Key"
PROMPT_TEXT = (
    "请粘贴 WEREAD_API_KEY（wrk- 开头）：\n\n"
    "去 https://weread.qq.com/r/weread-skills 登录后复制。\n"
    "Key 只保存在本机，不会写入 skill 目录。"
)
HELP = (
    "没有可用的 WEREAD_API_KEY。三种办法任选：\n"
    "  1. 直接重跑，会弹窗询问（交互式终端下会提示粘贴）\n"
    "  2. 设置环境变量：$env:WEREAD_API_KEY = 'wrk-xxxx'\n"
    "  3. 之前用 --remember-key 存过，就加 --use-saved-key 复用\n"
    "获取 Key：https://weread.qq.com/r/weread-skills"
)


class KeyMissing(RuntimeError):
    """拿不到 Key，且当前无法交互询问。"""


def key_file():
    return paths.key_file()


def mask(key):
    key = (key or "").strip()
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def read_stored():
    try:
        with open(key_file(), encoding="utf-8-sig") as fh:
            key = fh.read().strip()
    except OSError:
        return None
    return key or None


def write_stored(key):
    """保存失败不致命：返回 None，调用方继续用内存里的 Key。"""
    path = key_file()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(key.strip() + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path
    except OSError as exc:
        print(f"! Key 没能保存到 {path}（{exc.strerror or exc}），本次仍可使用",
              file=sys.stderr)
        return None


def forget():
    try:
        os.remove(key_file())
        return True
    except OSError:
        return False


def _prompt_gui():
    """弹出系统对话框让用户粘贴。没有图形环境就返回 None。"""
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except Exception:
        return None
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        value = simpledialog.askstring(PROMPT_TITLE, PROMPT_TEXT, show="*", parent=root)
    except Exception:
        return None
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    value = (value or "").strip()
    return value or None


def _prompt_console():
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            value = getpass.getpass("粘贴 WEREAD_API_KEY（输入不回显）：")
            return (value or "").strip() or None
    except Exception:
        pass
    return None


def sanitize(key):
    """Key 只允许 ASCII 字母数字和 -_，其余（空格、中文、换行）一律剥掉。"""
    cleaned = re.sub(r"[^A-Za-z0-9\-_]", "", (key or "").strip())
    return cleaned


def resolve(interactive=True, save=False, use_saved=False, force_prompt=False):
    """返回 (key, 来源)；来源 ∈ env / file / prompt。

    默认每次都问；use_saved=True 才复用已保存的 Key。
    """
    if not force_prompt:
        env = sanitize(os.environ.get(ENV_VAR))
        if env:
            return env, "env"
        if use_saved:
            stored = sanitize(read_stored())
            if stored:
                return stored, "file"

    if not interactive:
        raise KeyMissing(HELP)

    key = None
    for _ in range(3):
        raw = _prompt_gui() or _prompt_console()
        if not raw:
            raise KeyMissing("已取消输入 Key。" + HELP)
        candidate = sanitize(raw)
        if candidate.startswith("wrk-") and len(candidate) > 12:
            key = candidate
            break
        print(f"! 这不像 API Key（应形如 wrk-xxxxxxxx，实际拿到 {len(raw)} 个字符，"
              f"其中字母数字 {len(candidate)} 个）。重新弹窗…", file=sys.stderr)
    if not key:
        raise KeyMissing("连续 3 次输入的都不是 wrk- 开头的 Key。\n" + HELP)

    if save:
        path = write_stored(key)
        if path:
            print(f"✓ Key 已记住：{path}（下次可加 --use-saved-key）")
    return key, "prompt"
