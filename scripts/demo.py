"""离线全流程演示：不需要 API Key、不联网、不碰真实账号。

    python scripts/demo.py            # 跑一遍并清理临时产物
    python scripts/demo.py --keep     # 保留产物，方便查看

它用本地 mock 替代三处外部依赖，然后走真实代码路径：
    微信读书网关 → 知乎划线 → 抽词 → 联网校验 → 出词书 → 提交不背单词建词书
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bbdc_upload  # noqa: E402
import dialogs  # noqa: E402
import run  # noqa: E402
import verify  # noqa: E402
from weread_client import Gateway  # noqa: E402

BOOK_A = "b1"
BOOK_B = "b2"

# 英文书：单词级划线为主
WORDS_A = [
    "resilience", "humility", "radical", "transparency", "iteration",
    "paradigm", "deliberate", "feedback", "retrospective", "adversity",
    "curtsied", "sniffing", "children", "running", "studied", "spines",
    "ill-advised", "tousled", "excruciating", "lopsided", "curtsy", "skitter",
]
# 混合书：短语 + 整句 + 中文 + 噪声
MIXED_B = [
    "in the long run", "take off", "“radical transparency”", "resilience.",
    "He was reluctant to admit that he had made a mistake.",
    "每一个优秀的人都在默默努力。", "de", "a", "1. dopamine", "inter-\n esting",
]

# 第二轮的“新划线”（够 20 个，能出新词书）
NEW_WORDS_A = [
    "precipice", "abyss", "thunderclap", "deafen", "anew", "seize", "shriek",
    "divulge", "vow", "clench", "rack", "armpit", "vein", "gasp", "stab",
    "vaguely", "protector", "etch", "crudely", "fracture", "crack", "clay",
    "filthy", "coat", "skull",
]

DICT = {
    "curtsy": (verify.VALID, "noun. A small bow performed by a woman."),
    "skitter": (verify.VALID, "verb. To move hurriedly or as by bouncing."),
    "tousled": (verify.VALID, "verb. To put into disorder."),
    "excruciating": (verify.VALID, "adjective. Intensely painful."),
    "lopsided": (verify.VALID, "adjective. Leaning to one side."),
    "ill-advised": (verify.VALID, "adjective. Carried out without wise counsel."),
    "zzqx": (verify.INVALID, ""),
}


def _marks(book_id, texts, base_ts):
    return [{"bookmarkId": f"{book_id}-{i}", "bookId": book_id, "chapterUid": 1,
             "markText": t, "createTime": base_ts + i, "type": 1}
            for i, t in enumerate(texts)]


FIXTURE = {"notebooks": {"hasMore": 0, "totalBookCount": 2, "totalNoteCount": 32,
                         "books": []}, "bookmarks": {}}
FIXTURE["bookmarks"][BOOK_A] = {
    "updated": _marks(BOOK_A, WORDS_A, 1763000000),
    "chapters": [{"chapterUid": 1, "chapterIdx": 1, "title": "第一章"}],
    "book": {"title": "示例英文书", "author": "某作者"},
}
FIXTURE["bookmarks"][BOOK_B] = {
    "updated": _marks(BOOK_B, MIXED_B, 1763000100),
    "chapters": [{"chapterUid": 1, "chapterIdx": 1, "title": "第二章"}],
    "book": {"title": "示例混合书", "author": "某作者"},
}
FIXTURE["notebooks"]["books"] = [
    {"bookId": BOOK_A, "book": {"title": "示例英文书", "author": "某作者"},
     "noteCount": len(WORDS_A), "sort": 1763000000},
    {"bookId": BOOK_B, "book": {"title": "示例混合书", "author": "某作者"},
     "noteCount": len(MIXED_B), "sort": 1763000100},
]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        api = body.get("api_name")
        if api == "/user/notebooks":
            payload = FIXTURE["notebooks"]
        elif api == "/book/bookmarklist":
            payload = FIXTURE["bookmarks"].get(body.get("bookId"))
        else:
            payload = {"errcode": 404, "errmsg": f"unknown {api}"}
        raw = json.dumps(payload or {"errcode": 404}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def pick_home(preferred=None):
    """挑一个可写目录当演示工作区（系统临时目录在受限环境里可能不可写）。"""
    cands = [preferred, os.environ.get("WEREAD_DEMO_HOME")]
    if preferred is None:
        cands.append(os.path.join(tempfile.gettempdir(), "weread-vocab-demo"))
    cands.append(os.path.join(os.getcwd(), ".demo-home"))
    for base in cands:
        if not base:
            continue
        try:
            os.makedirs(base, exist_ok=True)
            probe = os.path.join(base, "_probe")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return base
        except OSError:
            continue
    raise RuntimeError("找不到可写目录，用 WEREAD_DEMO_HOME 指定一个")


def banner(text):
    print()
    print("=" * 68)
    print(text)
    print("=" * 68)


def mock_bbdc():
    """把 bbdc 两步换成内存实现，并打印将要发送的内容。"""
    def fake_submit(path, cookie):
        with open(path, encoding="utf-8") as fh:
            words = [w for w in fh.read().split() if w]
        known = [w for w in words if w not in ("zzqx",)]
        unknown = [w for w in words if w not in known]
        print(f"  [mock bbdc] POST /lexis/book/file/submit  "
              f"{len(words)} 词 → 识别 {len(known)}，未识别 {unknown}")
        return {"result_code": 200,
                "data_body": {"knowList": ",".join(known),
                              "unknowList": ",".join(unknown)}}

    def fake_save(words, name, desc="", exam="", cookie="", **kw):
        print(f"  [mock bbdc] POST /lexis/book/save  name=《{name}》  "
              f"wordList={len(words)} 词  exam={exam or '(空)'}")
        return {"result_code": 200, "data_kind": "lexis_book", "data_body": {}}

    bbdc_upload.load_cookie = lambda *a, **k: "hanhan=demo"
    bbdc_upload.submit = fake_submit
    bbdc_upload.save_book = fake_save
    run.bbdc_upload.submit = fake_submit
    run.bbdc_upload.save_book = fake_save


def mock_dict():
    verify.WordChecker._lookup = lambda self, word: DICT.get(
        word, (verify.VALID, f"{word} 的模拟释义"))


def mock_picker(choice_index=0):
    def pick(items, allow_gui=True):
        print(f"  [模拟弹窗] {len(items)} 本书：")
        for i, item in enumerate(items):
            print(f"      {i + 1}. {item['title']}（{item['count']} 条划线）")
        picked = [choice_index]
        print(f"  [模拟弹窗] 你选了第 {choice_index + 1} 本")
        return picked
    dialogs.pick_books = pick


def main(argv=None):
    ap = argparse.ArgumentParser(description="离线全流程演示")
    ap.add_argument("--keep", action="store_true", help="保留产物")
    ap.add_argument("--home", help="演示工作区目录（默认自动挑可写的）")
    args = ap.parse_args(argv)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["WEREAD_API_KEY"] = "wrk-demo-key"
    os.environ["WEREAD_GATEWAY_URL"] = f"http://127.0.0.1:{port}/api/agent/gateway"

    home = pick_home(args.home)
    os.environ["WEREAD_VOCAB_HOME"] = home
    mock_bbdc()
    mock_dict()
    mock_picker()

    print("\n工作目录：", home)
    print("（Key、网关、词典、不背单词接口都用本地 mock，不联网）")

    banner("1) 新用户首次运行：空状态，选中《示例英文书》")
    run.main(["--no-gui"])

    banner("2) 立刻再跑一次：应该只有增量，没有新词")
    run.main(["--no-gui"])

    banner("3) 用户又划了 25 个新词：只出增量，并顺手自动建好词书")
    FIXTURE["bookmarks"][BOOK_A]["updated"] += _marks(BOOK_A, NEW_WORDS_A, 1763100000)
    FIXTURE["notebooks"]["books"][0]["noteCount"] += len(NEW_WORDS_A)
    run.main(["--no-gui", "--upload", "--create",
              "--book-name", "示例英文书 第二批", "--desc", "来自微信读书划线"])

    banner("4) 选另一本混合书：短语拆词、整句/中文/噪声被跳过，不满 20 进待攒池")
    mock_picker(choice_index=1)
    run.main(["--no-gui"])

    banner("产物")
    out = os.path.join(home, "out")
    for name in sorted(os.listdir(out)) if os.path.isdir(out) else []:
        path = os.path.join(out, name)
        size = os.path.getsize(path)
        print(f"  {name}  ({size} B)")
        if name.endswith(".txt"):
            words = open(path, encoding="utf-8").read().split()
            print(f"      → {len(words)} 词：{', '.join(words[:12])} …")

    server.shutdown()
    if args.keep:
        print("\n产物保留在：", home)
    else:
        shutil.rmtree(home, ignore_errors=True)
        print("\n临时产物已清理（加 --keep 可保留）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
