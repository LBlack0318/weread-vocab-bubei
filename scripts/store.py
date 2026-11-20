"""状态文件、≥20 词门槛、产物落盘。"""
from __future__ import annotations

import datetime as _dt
import json
import os

MIN_WORDS_DEFAULT = 20


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def load_state(data_dir):
    """只读：目录不存在就返回空 state，不创建目录（--stats 在只读环境也能跑）。"""
    path = os.path.join(data_dir, "state.json")
    if not os.path.exists(path):
        return {"exported": {}, "pool": [], "generated": []}, path
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (json.JSONDecodeError, OSError):
        state = {}
    state.setdefault("exported", {})
    state.setdefault("pool", [])
    state.setdefault("generated", [])
    return state, path


def save_state(state, path):
    _ensure_dir(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _unique_path(out_dir, stem, ext):
    path = os.path.join(out_dir, f"{stem}{ext}")
    i = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{stem}_{i}{ext}")
        i += 1
    return path


def write_wordbook(out_dir, words, name=None, today=None):
    """一行一个英文单词，UTF-8 无 BOM，末尾换行。"""
    _ensure_dir(out_dir)
    stem = name or f"wordbook_{today or _dt.date.today().isoformat()}"
    stem = stem[:-4] if stem.lower().endswith(".txt") else stem
    path = _unique_path(out_dir, stem, ".txt")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(words) + "\n")
    return path


def write_review(out_dir, records, stats, name=None, today=None,
                 min_words=MIN_WORDS_DEFAULT, book_title="", notes=None):
    """给人看的核对表：词 + 划线原文 + 书名 + 章节 + 日期 + 联网校验结果。"""
    _ensure_dir(out_dir)
    stem = name or f"review_{today or _dt.date.today().isoformat()}"
    stem = stem[:-3] if stem.lower().endswith(".md") else stem
    path = _unique_path(out_dir, stem, ".md")

    by_book = {}
    for rec in records:
        by_book.setdefault(rec["book"], []).append(rec)

    lines = [f"# 生词核对表 {today or _dt.date.today().isoformat()}", ""]
    lines.append(f"- 词数：**{len(records)}**")
    if book_title:
        lines.append(f"- 来源书：{book_title}")
    else:
        lines.append(f"- 来源书：{len(by_book)} 本")
    lines.append("")
    lines.append("## 抽取统计")
    lines.append("")
    lines.append("| 类别 | 条数 |")
    lines.append("|---|---|")
    for label, key in (
        ("单词级划线（收）", "word"),
        ("短语级划线（收）", "phrase"),
        ("整句划线（跳过）", "skip:sentence"),
        ("含中文（跳过）", "skip:cjk"),
        ("非英文（跳过）", "skip:non_english"),
        ("单个字母（跳过）", "skip:noise"),
        ("空划线（跳过）", "skip:empty"),
        ("短语里没有实词（跳过）", "phrase_empty"),
    ):
        lines.append(f"| {label} | {stats.get(key, 0)} |")
    lines.append("")

    notes = notes or {}
    verified = notes.get("verified") or {}
    invalid = notes.get("invalid") or []
    unverified = notes.get("unverified") or []
    if verified or invalid or unverified:
        lines.append("## 词表外的词（联网校验）")
        lines.append("")
        lines.append(f"- 词典确认：{len(verified)} 个")
        lines.append(f"- 查无此词、已丢弃：{len(invalid)} 个")
        lines.append(f"- 网络失败、未验证：{len(unverified)} 个")
        lines.append("")
        if verified:
            lines.append("**词典确认**")
            lines.append("")
            for word, definition in list(verified.items())[:50]:
                lines.append(f"- `{word}` — {definition or '（无释义）'}")
            lines.append("")
        if invalid:
            lines.append("**已丢弃（词典查不到）**：" + "、".join(f"`{w}`" for w in invalid))
            lines.append("")
        if unverified:
            lines.append("**未验证（网络不可用，保留）**：" + "、".join(f"`{w}`" for w in unverified))
            lines.append("")

    for book, recs in by_book.items():
        lines.append(f"## {book}（{len(recs)} 词）")
        lines.append("")
        for rec in recs:
            ctx = rec.get("phrase") or ""
            meta = " · ".join(x for x in (rec.get("chapter"), rec.get("date")) if x)
            tail = f" — “{ctx}”" if ctx else ""
            meta_txt = f" <sub>{meta}</sub>" if meta else ""
            lines.append(f"- **{rec['word']}**{tail}{meta_txt}")
        lines.append("")

    skipped = stats.get("skipped_samples") or []
    if skipped:
        lines.append("## 被跳过的划线样例")
        lines.append("")
        for s in skipped[:15]:
            lines.append(f"- <sub>{s['reason']}</sub> {s['text']}")
        lines.append("")

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return path
