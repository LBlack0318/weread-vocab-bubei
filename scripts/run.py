"""微信读书划线 → 不背单词自制词书。

流程：取划线 → 弹窗选书 → 抽词 → 词表外的词联网校验 → 出 txt + review.md。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apikey  # noqa: E402
import bbdc_upload  # noqa: E402
import dialogs  # noqa: E402
import extract  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
import verify  # noqa: E402
from weread_client import Gateway, WeReadError  # noqa: E402


def _force_utf8_stdio():
    """重定向到管道时 Windows 默认用 GBK，中文/勾号会 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


_force_utf8_stdio()


def log(msg=""):
    print(msg, flush=True)


def _date_of(ts):
    try:
        ts = int(ts)
        if ts <= 0:
            return ""
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _since_epoch(text):
    if not text:
        return None
    return int(_dt.datetime.combine(_dt.date.fromisoformat(text), _dt.time.min).timestamp())


def slug(text, limit=40):
    bad = '\\/:*?"<>|\r\n\t'
    out = "".join("_" if c in bad else c for c in (text or "")).strip(" ._")
    return (out or "book")[:limit]


# --------------------------- 选书 ---------------------------

def pick_books(args):
    """返回 [{'bookId','title','author','count'}]；用户取消返回 []。"""
    gw = Gateway(interactive=not args.no_prompt,
                 use_saved_key=args.use_saved_key,
                 remember_key=args.remember_key)
    notebooks = gw.notebooks()
    since = _since_epoch(args.since)

    books = []
    for nb in notebooks:
        title = (nb.get("book") or {}).get("title") or f"book:{nb.get('bookId')}"
        author = (nb.get("book") or {}).get("author") or ""
        count = int(nb.get("noteCount") or 0)
        if args.book_id:
            if str(nb.get("bookId")) != str(args.book_id):
                continue
        elif args.book:
            if args.book.lower() not in title.lower():
                continue
        elif not args.all and not count:
            continue
        if args.all and not count:
            continue
        if since and int(nb.get("sort") or 0) and int(nb.get("sort")) < since:
            continue
        books.append({"bookId": nb.get("bookId"), "title": title,
                      "author": author, "count": count})

    if not (args.all or args.book or args.book_id):
        items = [{"title": b["title"], "count": b["count"]} for b in books]
        if not items:
            log("没有找到有划线的书。")
            return []
        log(f"· 有划线的书 {len(items)} 本，等你选择…")
        picked = dialogs.pick_books(items, allow_gui=not args.no_gui)
        if picked is None:
            raise RuntimeError("当前环境无法交互选择，请用 --all / --book / --book-id 指定")
        if not picked:
            log("已取消。")
            return []
        books = [books[i] for i in picked]

    return gw, books


# --------------------------- 抽词 ---------------------------

def collect(sources, args, stopwords):
    stats = {"word": 0, "phrase": 0, "skip:sentence": 0, "skip:cjk": 0,
             "skip:non_english": 0, "skip:empty": 0, "skip:noise": 0,
             "phrase_empty": 0, "extracted": 0, "skipped_samples": []}
    ordered = {}
    for src in sources:
        kind, words, phrase = extract.words_from(
            src["text"], stopwords,
            max_tokens=args.max_tokens, max_chars=args.max_chars,
            allow_mixed=args.allow_mixed, lemma=not args.no_lemma,
        )
        stats[kind] = stats.get(kind, 0) + 1
        if kind.startswith("skip"):
            if len(stats["skipped_samples"]) < 15:
                stats["skipped_samples"].append({
                    "reason": {
                        "skip:sentence": "整句",
                        "skip:cjk": "含中文",
                        "skip:non_english": "非英文",
                        "skip:empty": "空",
                        "skip:noise": "单个字母",
                    }.get(kind, kind),
                    "text": extract.clean(src["text"])[:80],
                })
            continue
        if kind == "phrase" and not words:
            stats["phrase_empty"] += 1
            continue
        stats["extracted"] += len(words)
        if kind == "word" and len(words) == 1 and extract.normalize(phrase) == words[0]:
            phrase = ""
        for word in words:
            if word in ordered:
                continue
            ordered[word] = {
                "word": word, "phrase": phrase, "book": src["book"],
                "author": src["author"], "chapter": src["chapter"], "date": src["date"],
            }
    return ordered, stats


def verify_unknown(words, enabled=True):
    """词表外的词联网查词典：真词保留、查不到丢弃、网络失败保留但标记。"""
    notes = {"verified": {}, "invalid": [], "unverified": []}
    if not enabled:
        return words, notes
    unknown = [w for w in words if not extract.in_lexicon(w)]
    if not unknown:
        return words, notes

    log(f"· 词表外的词 {len(unknown)} 个，联网校验中…")
    checker = verify.WordChecker()
    results = checker.check_many(unknown)
    dropped = []
    for word in unknown:
        item = results.get(word) or {}
        status = item.get("status")
        if status == verify.VALID:
            notes["verified"][word] = item.get("def") or ""
        elif status == verify.INVALID:
            notes["invalid"].append(word)
            dropped.append(word)
        else:
            notes["unverified"].append(word)

    if dropped:
        log(f"  ✗ 词典查不到，丢弃 {len(dropped)} 个：" + ", ".join(dropped[:12])
            + (" …" if len(dropped) > 12 else ""))
    if notes["verified"]:
        log(f"  ✓ 词典确认 {len(notes['verified'])} 个")
    if notes["unverified"]:
        log(f"  ! 网络失败、未验证保留 {len(notes['unverified'])} 个")
    return [w for w in words if w not in set(dropped)], notes


# --------------------------- 产出 ---------------------------

def emit(ordered, stats, args, state, state_path, book_title, notes,
         file_stem, today):
    candidates = {}
    for item in state["pool"]:
        word = item.get("word")
        if not word or word in state["exported"]:
            continue
        # 待攒池按书隔离：别的书攒的词不该混进这本的词书
        if not args.merge and book_title and item.get("book") \
                and item["book"] != book_title:
            continue
        candidates[word] = item
    for word, rec in ordered.items():
        if word not in state["exported"] and word not in candidates:
            candidates[word] = rec

    words = list(candidates)
    if args.sort == "alpha":
        words.sort()

    log(f"  抽词 {stats['extracted']} → 去重 {len(ordered)}"
        f" → 已导出 {len(ordered) - len([w for w in ordered if w in candidates])}"
        f" → 候选 {len(words)}")

    if not words:
        log("  没有新词。")
        return None

    if len(words) < args.min_words:
        # 只替换本书的条目，别把别的书的待攒词冲掉
        others = [p for p in state["pool"] if (p.get("book") or "") != book_title]
        state["pool"] = others + [dict(candidates[w], book=book_title) for w in words]
        store.save_state(state, state_path)
        log(f"  ! 只有 {len(words)} 个词，不背单词至少需要 {args.min_words} 个，"
            f"已进待攒池")
        return None

    if args.dry_run:
        log(f"  （dry-run）前 20 个：" + ", ".join(words[:20]))
        return None

    records = [candidates[w] for w in words]
    txt = store.write_wordbook(args.out, words, name=file_stem, today=today)
    md = store.write_review(args.out, records, stats, name=file_stem.replace("wordbook", "review"),
                            today=today, min_words=args.min_words,
                            book_title=book_title, notes=notes)
    for word in words:
        state["exported"][word] = {
            "book": candidates[word].get("book"),
            "date": candidates[word].get("date") or today,
            "exported_on": today,
        }
    state["pool"] = [p for p in state["pool"] if p.get("word") not in set(words)]
    state["generated"].append({"file": os.path.basename(txt), "count": len(words),
                               "date": today, "book": book_title})
    store.save_state(state, state_path)
    log(f"  ✓ {txt}（{len(words)} 词）")
    log(f"  ✓ {md}")

    if args.upload or args.create:
        _push_to_bbdc(txt, words, args, book_title, file_stem)
    return txt


def _push_to_bbdc(txt, words, args, book_title="", file_stem=""):
    """提交到不背单词：拿平台识别结果；--create 时再创建词书。"""
    cookie = bbdc_upload.load_cookie()
    if not cookie:
        log("  ! 没找到 bbdc cookie，跳过上传")
        log("    把浏览器 cookie 存到 " + bbdc_upload.cookie_file())
        return
    log("  · 提交到不背单词…")
    try:
        result = bbdc_upload.submit(txt, cookie)
    except RuntimeError as exc:
        log(f"  ! 上传失败：{exc}")
        return

    body = result.get("data_body") or {}
    known = [w for w in (body.get("knowList") or "").split(",") if w]
    unknown = [w for w in (body.get("unknowList") or "").split(",") if w]
    total = len(known) + len(unknown)
    log(f"  ✓ 平台识别 {len(known)}/{total} 词")
    if unknown:
        log("    未识别：" + "、".join(unknown[:15]) + (" …" if len(unknown) > 15 else ""))
    if args.prune_unknown and unknown:
        with open(txt, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(known) + "\n")
        log(f"    ✓ 已剔除未识别词，重写 {os.path.basename(txt)}（{len(known)} 词）")
        try:
            again = bbdc_upload.submit(txt, cookie)
            again_unknown = (again.get("data_body") or {}).get("unknowList") or ""
            log(f"    二次识别未识别：{again_unknown or '无'}")
        except RuntimeError as exc:
            log(f"    ! 二次提交失败：{exc}")

    if not args.create:
        return
    name = args.book_name or book_title or file_stem or "微信读书词书"
    try:
        saved = bbdc_upload.save_book(known, name=name, desc=args.desc,
                                      exam=args.exam, cookie=cookie)
    except RuntimeError as exc:
        log(f"  ! 创建词书失败：{exc}")
        return
    if saved.get("result_code") == 200:
        log(f"  ✓ 已创建词书《{name}》（{len(known)} 词）")
        args._created = True
    else:
        err = saved.get("error_body") or saved.get("_raw") or saved
        log(f"  ! 创建被拒：{err}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="微信读书划线 → 不背单词自制词书")
    src = ap.add_argument_group("数据来源（都不给就弹窗选书）")
    src.add_argument("--all", action="store_true", help="所有有划线的书，各出一本")
    src.add_argument("--book", help="书名关键词")
    src.add_argument("--book-id", help="直接指定 bookId")
    src.add_argument("--text", help="本地划线文本（每行一条），- 表示 stdin")
    src.add_argument("--since", help="只取该日期之后的划线，如 2026-06-01")

    ap.add_argument("--out", default=paths.out_dir(), help="产物目录")
    ap.add_argument("--data", default=paths.data_dir(), help="state 目录")
    ap.add_argument("--name", help="指定产物文件名前缀")
    ap.add_argument("--merge", action="store_true", help="多本书合并成一本词书")
    ap.add_argument("--min-words", type=int, default=store.MIN_WORDS_DEFAULT)
    ap.add_argument("--max-tokens", type=int, default=extract.MAX_TOKENS_DEFAULT)
    ap.add_argument("--max-chars", type=int, default=extract.MAX_CHARS_DEFAULT)
    ap.add_argument("--sort", choices=["appearance", "alpha"], default="appearance")
    ap.add_argument("--no-lemma", action="store_true")
    ap.add_argument("--allow-mixed", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="跳过词表外词的联网校验")
    ap.add_argument("--upload", action="store_true",
                    help="生成后直接提交到不背单词，看平台识别结果")
    ap.add_argument("--create", action="store_true",
                    help="配合 --upload：识别通过后直接创建词书")
    ap.add_argument("--book-name", help="词书名称（默认用书名）")
    ap.add_argument("--desc", default="", help="词书简介")
    ap.add_argument("--exam", default="", help="考试分类代码，如 KY（考研）")
    ap.add_argument("--prune-unknown", action="store_true",
                    help="配合 --upload：平台识别不了就剔除并重传")
    ap.add_argument("--no-gui", action="store_true", help="不弹窗，改用命令行输入")
    ap.add_argument("--no-prompt", action="store_true", help="不弹 Key 窗口（自动化用）")
    ap.add_argument("--remember-key", action="store_true", help="把这次输入的 Key 记住")
    ap.add_argument("--use-saved-key", action="store_true", help="复用之前记住的 Key")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true", help="只验证 Key")
    ap.add_argument("--set-key", action="store_true", help="输入并记住 Key")
    ap.add_argument("--forget-key", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)

    try:
        if args.forget_key:
            path = apikey.key_file()
            log(f"✓ 已删除 {path}" if apikey.forget() else f"· {path} 本来就不存在")
            return 0

        if args.set_key:
            key, source = apikey.resolve(interactive=True, save=True, force_prompt=True)
            log(f"✓ Key 已记住（{apikey.mask(key)}）→ {apikey.key_file()}")
            return 0

        if args.verify:
            gw = Gateway(interactive=not args.no_prompt,
                         use_saved_key=args.use_saved_key,
                         remember_key=args.remember_key)
            gw.verify()
            log(f"✓ API Key 有效（来源 {gw.key_source}，{apikey.mask(gw.api_key)}）")
            return 0

        if args.stats:
            state, _ = store.load_state(args.data)
            log(f"已导出词：{len(state['exported'])}")
            log(f"待攒池：{len(state['pool'])} 个")
            log(f"历史产出：{len(state['generated'])} 次")
            for g in state["generated"][-3:]:
                log(f"  - {g.get('file')}（{g.get('count')} 词，{g.get('date')}）")
            return 0

        state, state_path = store.load_state(args.data)
        today = _dt.date.today().isoformat()
        stopwords = extract.load_stopwords()

        if args.text:
            sources = _sources_from_text(args.text, args.book or "手动粘贴")
            ordered, stats = collect(sources, args, stopwords)
            log(f"· 来源：本地文本 {len(sources)} 行")
            words_before = len(ordered)
            kept, notes = verify_unknown(list(ordered), enabled=not args.no_verify)
            ordered = {w: ordered[w] for w in kept}
            log(f"  划线 {len(sources)} 条 → 收下 {stats['word'] + stats['phrase']} 条"
                f"（单词级 {stats['word']}、短语级 {stats['phrase']}）")
            emit(ordered, stats, args, state, state_path,
                 args.book or "手动粘贴", notes,
                 args.name or f"wordbook_paste_{today}", today)
            return 0

        gateway, books = pick_books(args)
        if not books:
            return 0
        books = [{"bookId": b["bookId"], "title": b["title"],
                  "author": b["author"], "count": b["count"]} for b in books]
        log(f"· 选中 {len(books)} 本：" + "、".join(b["title"] for b in books))

        merged_ordered, merged_stats = {}, {}
        for book in books:
            log()
            log(f"《{book['title']}》")
            try:
                highlights, chapters, bookinfo = gateway.bookmarks(book["bookId"])
            except WeReadError as exc:
                log(f"  ! 跳过：{exc}")
                continue
            since = _since_epoch(args.since)
            sources = []
            for h in highlights:
                ts = h.get("createTime") or 0
                if since and int(ts or 0) and int(ts) < since:
                    continue
                chapter = ""
                ch = chapters.get(h.get("chapterUid"))
                if isinstance(ch, dict):
                    chapter = ch.get("title") or ""
                sources.append({"book": bookinfo.get("title") or book["title"],
                                "author": bookinfo.get("author") or book["author"],
                                "chapter": chapter,
                                "text": h.get("markText") or "",
                                "date": _date_of(ts)})
            ordered, stats = collect(sources, args, stopwords)
            log(f"  划线 {len(sources)} 条 → 收下 {stats['word'] + stats['phrase']} 条"
                f"（单词级 {stats['word']}、短语级 {stats['phrase']}）"
                f"，跳过 {sum(v for k, v in stats.items() if k.startswith('skip:'))}")

            kept, notes = verify_unknown(list(ordered), enabled=not args.no_verify)
            dropped = set(ordered) - set(kept)
            ordered = {w: ordered[w] for w in kept}
            if dropped:
                stats["skip:noise"] = stats.get("skip:noise", 0) + len(dropped)

            if args.merge:
                for w, rec in ordered.items():
                    merged_ordered.setdefault(w, rec)
                if not merged_stats:
                    merged_stats = stats
            else:
                stem = args.name or f"wordbook_{slug(book['title'])}_{today}"
                emit(ordered, stats, args, state, state_path,
                     book["title"], notes, stem, today)

        if args.merge and merged_ordered:
            kept, notes = verify_unknown(list(merged_ordered), enabled=not args.no_verify)
            merged_ordered = {w: merged_ordered[w] for w in kept}
            stem = args.name or f"wordbook_合并_{today}"
            emit(merged_ordered, merged_stats, args, state, state_path,
                 "、".join(b["title"] for b in books), notes, stem, today)
    except (WeReadError, apikey.KeyMissing, RuntimeError) as exc:
        log(f"✗ {exc}")
        return 1
    except PermissionError as exc:
        log(f"✗ 写不了 {exc.filename}。用 --out / --data 指定可写目录")
        return 1

    log()
    if getattr(args, "_created", False):
        log("词书已建好：手机 App → 计划/仪表盘 → 换本词书 → 我的自制")
    else:
        log("下一步：bbdc.cn → 登录 → 右上角菜单「自制词书」→ 上传对应 txt → 识别 → 命名")
        log("        然后 App：计划/仪表盘 → 换本词书 → 我的自制")
    return 0


def _sources_from_text(path, book_name):
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8-sig") as fh:
            raw = fh.read()
    out = []
    for line in raw.splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            out.append({"book": book_name, "author": "", "chapter": "",
                        "text": text, "date": ""})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
