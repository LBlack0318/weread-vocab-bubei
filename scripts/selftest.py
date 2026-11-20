"""自检：用本地 mock gateway 跑通 取数 → 抽词 → 出词书 → 增量 全链路。

不联网、不需要真实 API Key：
    py scripts/selftest.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run  # noqa: E402

BOOK1_ID = "b1"
BOOK2_ID = "b2"
BOOK3_ID = "b3"

WORDS1 = ["resilience", "humility", "radical", "transparency", "iteration",
          "paradigm", "deliberate", "feedback", "retrospective", "adversity",
          "judgment", "boredom", "loneliness", "anxiety", "dopamine",
          "meditation", "solitude", "discipline", "principle", "conviction"]

HIGHLIGHTS2 = ["running", "studied", "children", "reluctantly",
               "in the long run", "come up with", "take off",
               "the bigger picture"]

HIGHLIGHTS3 = [
    "每一个优秀的人都在默默努力。",
    "He was reluctant to admit that he had made a mistake.",
    "こんにちは世界",
    "",
    "the quick brown fox jumps over the lazy dog",
]


def _marks(book_id, texts, base_ts, chapter=1):
    return [{"bookmarkId": f"{book_id}-{i}", "bookId": book_id,
             "chapterUid": chapter, "markText": t, "createTime": base_ts + i,
             "type": 1, "range": f"{i}-{i + 1}"} for i, t in enumerate(texts)]


FIXTURE = {
    "notebooks": {
        "books": [
            {"bookId": BOOK1_ID, "book": {"title": "原则", "author": "瑞·达利欧"},
             "noteCount": len(WORDS1), "reviewCount": 0, "bookmarkCount": 0,
             "readingProgress": 100, "markedStatus": 1, "sort": 1763000000},
            {"bookId": BOOK2_ID, "book": {"title": "刻意练习", "author": "艾利克森"},
             "noteCount": len(HIGHLIGHTS2), "reviewCount": 0, "bookmarkCount": 0,
             "readingProgress": 60, "markedStatus": 0, "sort": 1763000100},
            {"bookId": BOOK3_ID, "book": {"title": "中文散文", "author": "某某"},
             "noteCount": len(HIGHLIGHTS3), "reviewCount": 0, "bookmarkCount": 0,
             "readingProgress": 30, "markedStatus": 0, "sort": 1763000200},
        ],
        "totalBookCount": 3, "totalNoteCount": 32, "hasMore": 0,
    },
    "bookmarks": {
        BOOK1_ID: {
            "updated": _marks(BOOK1_ID, WORDS1, 1700000000),
            "chapters": [{"chapterUid": 1, "chapterIdx": 1, "title": "第一章"}],
            "book": {"title": "原则", "author": "瑞·达利欧"},
        },
        BOOK2_ID: {
            "updated": _marks(BOOK2_ID, HIGHLIGHTS2, 1763000000, chapter=2),
            "chapters": [{"chapterUid": 2, "chapterIdx": 2, "title": "第二章"}],
            "book": {"title": "刻意练习", "author": "艾利克森"},
        },
        BOOK3_ID: {
            "updated": _marks(BOOK3_ID, HIGHLIGHTS3, 1763000100, chapter=3),
            "chapters": [{"chapterUid": 3, "chapterIdx": 3, "title": "第三章"}],
            "book": {"title": "中文散文", "author": "某某"},
        },
    },
}


def _make_tmp():
    """挑一个可写目录当测试沙盒：环境变量 > 系统临时目录 > skill 同级 tmp/。

    注意：不用 tempfile.mkdtemp —— 它在 Windows 上按 0o700 建目录，
    某些受限令牌（如沙箱）之后无法往里面写文件；这里用 makedirs 建普通目录。
    """
    import uuid
    cands = [os.environ.get("WEREAD_SELFTEST_TMP")]
    cands.append(tempfile.gettempdir())
    cands.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "tmp"))
    for base in cands:
        if not base:
            continue
        path = os.path.join(base, "weread-selftest-" + uuid.uuid4().hex[:8])
        try:
            os.makedirs(base, exist_ok=True)
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, "_probe")
            open(probe, "w").close()
            os.remove(probe)
            return path
        except OSError:
            continue
    raise RuntimeError("找不到可写目录；请设置 WEREAD_SELFTEST_TMP")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        api = body.get("api_name")
        if not (self.headers.get("Authorization") or "").startswith("Bearer wrk-"):
            self._send({"errcode": -2010, "errmsg": "invalid api key"}, status=401)
            return
        if body.get("skill_version") is None:
            self._send({"errcode": -1, "errmsg": "missing skill_version"})
            return
        if api == "/user/notebooks":
            self._send(FIXTURE["notebooks"])
        elif api == "/book/bookmarklist":
            data = FIXTURE["bookmarks"].get(body.get("bookId"))
            self._send(data) if data else self._send({"errcode": 404, "errmsg": "no book"})
        else:
            self._send({"errcode": 404, "errmsg": f"unknown api {api}"})

    def _send(self, obj, status=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class SelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        os.environ["WEREAD_API_KEY"] = "wrk-test"
        os.environ["WEREAD_GATEWAY_URL"] = f"http://127.0.0.1:{cls.port}/api/agent/gateway"
        cls.tmp = _make_tmp()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        for k in ("WEREAD_API_KEY", "WEREAD_GATEWAY_URL"):
            os.environ.pop(k, None)
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run.main(argv)
        return code, buf.getvalue()

    def test_01_end_to_end(self):
        out = os.path.join(self.tmp, "o1")
        data = os.path.join(self.tmp, "d1")
        code, text = self._run(["--all", "--no-verify", "--merge", "--out", out, "--data", data])
        self.assertEqual(code, 0, text)
        txts = [f for f in os.listdir(out) if f.endswith(".txt")]
        self.assertEqual(len(txts), 1, text)
        path = os.path.join(out, txts[0])
        with open(path, encoding="utf-8") as fh:
            words = fh.read().split()
        self.assertGreaterEqual(len(words), 20)
        self.assertEqual(words, sorted(set(words), key=words.index))  # 无重复
        self.assertIn("resilience", words)
        self.assertIn("run", words)          # running → run
        self.assertNotIn("running", words)
        self.assertIn("study", words)        # studied → study
        self.assertIn("child", words)        # children → child
        self.assertIn("reluctantly", words)  # 不剥 -ly
        self.assertIn("long", words)         # 短语拆词
        self.assertNotIn("the", words)       # 停用词被滤
        self.assertNotIn("reluctant", words)  # 整句划线被跳过
        self.assertNotIn("quick", words)
        self.assertNotIn("fox", words)
        mds = [f for f in os.listdir(out) if f.endswith(".md")]
        self.assertEqual(len(mds), 1)
        with open(os.path.join(out, mds[0]), encoding="utf-8") as fh:
            review = fh.read()
        self.assertIn("抽取统计", review)
        self.assertIn("整句", review)

    def test_02_incremental(self):
        out = os.path.join(self.tmp, "o1")
        data = os.path.join(self.tmp, "d1")
        code, text = self._run(["--all", "--no-verify", "--merge", "--out", out, "--data", data])
        self.assertEqual(code, 0, text)
        self.assertIn("没有新词", text)
        self.assertEqual(len([f for f in os.listdir(out) if f.endswith(".txt")]), 1)

    def test_03_threshold_pool(self):
        out = os.path.join(self.tmp, "o3")
        data = os.path.join(self.tmp, "d3")
        code, text = self._run(["--all", "--no-verify", "--out", out, "--data", data, "--min-words", "999"])
        self.assertEqual(code, 0, text)
        self.assertIn("待攒池", text)
        self.assertFalse(os.path.exists(out) and any(f.endswith(".txt") for f in os.listdir(out)))
        with open(os.path.join(data, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertGreaterEqual(len(state["pool"]), 20)

    def test_04_text_mode(self):
        src = os.path.join(self.tmp, "paste.txt")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("\n".join(WORDS1))
        out = os.path.join(self.tmp, "o4")
        data = os.path.join(self.tmp, "d4")
        code, text = self._run(["--text", src, "--book", "粘贴书", "--no-verify", "--out", out, "--data", data])
        self.assertEqual(code, 0, text)
        txt = [f for f in os.listdir(out) if f.endswith(".txt")][0]
        with open(os.path.join(out, txt), encoding="utf-8") as fh:
            words = fh.read().split()
        self.assertEqual(len(words), len(WORDS1))

    def test_05_bad_key(self):
        os.environ["WEREAD_API_KEY"] = "bad"
        try:
            code, text = self._run(["--all", "--no-verify", "--out", os.path.join(self.tmp, "o5"),
                                    "--data", os.path.join(self.tmp, "d5")])
        finally:
            os.environ["WEREAD_API_KEY"] = "wrk-test"
        self.assertNotEqual(code, 0, text)
        self.assertIn("鉴权失败", text)

    def test_06_classify(self):
        import extract
        st = extract.load_stopwords()
        cases = {
            "resilience": "word",
            "in the long run": "phrase",
            "He was reluctant to admit it.": "skip:sentence",
            "每一个优秀的人都在默默努力。": "skip:cjk",
            "": "skip:empty",
            "how are you doing today my dear friend": "skip:sentence",
        }
        for text, want in cases.items():
            kind = extract.classify(text)["kind"]
            self.assertEqual(kind, want, f"{text!r} → {kind}, want {want}")
        words = extract.words_from("in the long run", st)[1]
        self.assertEqual(words, ["long", "run"])
        self.assertEqual(extract.lemmatize("practices"), "practice")
        self.assertEqual(extract.lemmatize("reluctantly"), "reluctantly")
        self.assertEqual(extract.lemmatize("companies"), "company")

    def test_07_noise_stripping(self):
        """多划的标点/空格/零宽/断字/编号都要清掉，且不能把词判成整句。"""
        import extract
        st = extract.load_stopwords()
        messy = {
            "resilience.": ("word", ["resilience"]),
            "  resilience  ": ("word", ["resilience"]),
            "“resilience”": ("word", ["resilience"]),
            "(resilience)": ("word", ["resilience"]),
            "resilience，": ("word", ["resilience"]),
            "resilience…": ("word", ["resilience"]),
            "resilience\ufeff": ("word", ["resilience"]),
            "1. resilience": ("word", ["resilience"]),
            "inter-\nesting": ("word", ["interesting"]),
            "resilience e": ("phrase", ["resilience"]),
            "a": ("skip:noise", []),
        }
        for text, (want_kind, want_words) in messy.items():
            kind, words, _ = extract.words_from(text, st)
            self.assertEqual(kind, want_kind, f"{text!r} → {kind}, want {want_kind}")
            self.assertEqual(words, want_words, f"{text!r} → {words}")


    def test_08_key_storage(self):
        """Key 只落用户目录，不写 skill 目录；env 优先于文件。"""
        import apikey
        old_env = os.environ.pop("WEREAD_API_KEY", None)
        old_file = os.environ.get("WEREAD_KEY_FILE")
        path = os.path.join(self.tmp, "keydir", "api_key")
        os.environ["WEREAD_KEY_FILE"] = path
        try:
            self.assertIsNone(apikey.read_stored())
            with self.assertRaises(apikey.KeyMissing):
                apikey.resolve(interactive=False, use_saved=True)
            self.assertFalse(os.path.exists(path), "resolve(interactive=False) 不该落盘")
            apikey.write_stored("wrk-stored-key-123")
            self.assertEqual(apikey.read_stored(), "wrk-stored-key-123")
            key, source = apikey.resolve(interactive=False, use_saved=True)
            self.assertEqual((key, source), ("wrk-stored-key-123", "file"))
            os.environ["WEREAD_API_KEY"] = "wrk-env-key"
            self.assertEqual(apikey.resolve(interactive=False, use_saved=True), ("wrk-env-key", "env"))
            os.environ.pop("WEREAD_API_KEY")
            self.assertEqual(apikey.mask("wrk-1234567890"), "wrk-…7890")
            self.assertTrue(apikey.forget())
            self.assertIsNone(apikey.read_stored())
        finally:
            if old_env is not None:
                os.environ["WEREAD_API_KEY"] = old_env
            if old_file is None:
                os.environ.pop("WEREAD_KEY_FILE", None)
            else:
                os.environ["WEREAD_KEY_FILE"] = old_file

    def test_09_no_prompt_flag(self):
        """--no-prompt 且无 Key：报错退出，不弹窗、不挂起。"""
        import apikey
        old_env = os.environ.pop("WEREAD_API_KEY", None)
        old_file = os.environ.get("WEREAD_KEY_FILE")
        os.environ["WEREAD_KEY_FILE"] = os.path.join(self.tmp, "keydir", "absent_key")
        try:
            code, text = self._run(["--all", "--no-prompt", "--no-verify",
                                    "--out", os.path.join(self.tmp, "o9"),
                                    "--data", os.path.join(self.tmp, "d9")])
        finally:
            if old_env is not None:
                os.environ["WEREAD_API_KEY"] = old_env
            if old_file is None:
                os.environ.pop("WEREAD_KEY_FILE", None)
            else:
                os.environ["WEREAD_KEY_FILE"] = old_file
        self.assertNotEqual(code, 0, text)
        self.assertIn("没有可用的 WEREAD_API_KEY", text)


    def test_10_first_run_prompt_saves_outside_skill(self):
        """首次无 Key：走询问 → 存到用户目录 → 下次直接复用。"""
        import apikey
        old_env = os.environ.pop("WEREAD_API_KEY", None)
        old_file = os.environ.get("WEREAD_KEY_FILE")
        path = os.path.join(self.tmp, "keydir2", "api_key")
        os.environ["WEREAD_KEY_FILE"] = path
        original = apikey._prompt_gui
        apikey._prompt_gui = lambda: "wrk-from-dialog-9999"
        try:
            key, source = apikey.resolve(interactive=True, save=True)
            self.assertEqual((key, source), ("wrk-from-dialog-9999", "prompt"))
            self.assertTrue(os.path.exists(path), "弹窗输入的 Key 应落盘到用户目录")
            skill_dir = os.path.dirname(HERE)
            self.assertFalse(os.path.abspath(path).startswith(os.path.abspath(skill_dir)),
                             "Key 不能写进 skill 目录")
            self.assertEqual(apikey.resolve(interactive=False, use_saved=True),
                             ("wrk-from-dialog-9999", "file"))
        finally:
            apikey._prompt_gui = original
            if old_env is not None:
                os.environ["WEREAD_API_KEY"] = old_env
            if old_file is None:
                os.environ.pop("WEREAD_KEY_FILE", None)
            else:
                os.environ["WEREAD_KEY_FILE"] = old_file


    def test_11_save_failure_is_not_fatal(self):
        """Key 存不下来时，本次运行仍应继续（只警告）。"""
        import apikey
        old_env = os.environ.pop("WEREAD_API_KEY", None)
        old_file = os.environ.get("WEREAD_KEY_FILE")
        blocker = os.path.join(self.tmp, "not_a_dir")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.environ["WEREAD_KEY_FILE"] = os.path.join(blocker, "api_key")
        original = apikey._prompt_gui
        apikey._prompt_gui = lambda: "wrk-unsavable-key"
        try:
            key, source = apikey.resolve(interactive=True, save=True)
            self.assertEqual(key, "wrk-unsavable-key")
            self.assertEqual(source, "prompt")
            self.assertIsNone(apikey.read_stored())
        finally:
            apikey._prompt_gui = original
            if old_env is not None:
                os.environ["WEREAD_API_KEY"] = old_env
            if old_file is None:
                os.environ.pop("WEREAD_KEY_FILE", None)
            else:
                os.environ["WEREAD_KEY_FILE"] = old_file


    def test_12_lemma_uses_lexicon(self):
        """还原结果必须在词表里；不能造出 snif / assembl 这类非词。"""
        import extract
        extract.load_lexicon()
        cases = {
            "sniffing": "sniff",        # 不是 snif
            "assembling": "assemble",   # 不是 assembl
            "rippling": "ripple",
            "spectacled": "spectacle",
            "running": "run",
            "hopping": "hop",
            "houses": "house",
            "things": "thing",
            "studied": "study",
            "reluctantly": "reluctantly",
        }
        for surface, expected in cases.items():
            self.assertEqual(extract.lemmatize(surface), expected, surface)

    def test_13_plural_and_short_tokens(self):
        import extract
        self.assertEqual(extract.lemmatize("spines"), "spine")
        self.assertEqual(extract.lemmatize("houses"), "house")
        self.assertEqual(extract.lemmatize("things"), "thing")
        st = extract.load_stopwords()
        self.assertEqual(extract.words_from("de", st)[0], "skip:noise")
        self.assertEqual(extract.words_from("a", st)[0], "skip:noise")
        self.assertEqual(extract.words_from("go", st)[0], "word")


    def test_14_online_verification(self):
        """词表外的词：真词保留、查不到丢弃、网络失败保留但标记。"""
        import verify
        old_cache = os.environ.get("WEREAD_WORD_CACHE")
        os.environ["WEREAD_WORD_CACHE"] = os.path.join(self.tmp, "cache.json")

        table = {
            "skitter": (verify.VALID, "v. move quickly"),
            "qqzzx": (verify.INVALID, ""),
            "curtsy": (verify.UNKNOWN, "timeout"),
        }

        def fake_lookup(self, word):
            return table[word]

        original = verify.WordChecker._lookup
        verify.WordChecker._lookup = fake_lookup
        try:
            kept, notes = run.verify_unknown(["skitter", "qqzzx", "curtsy"])
        finally:
            verify.WordChecker._lookup = original
            if old_cache is None:
                os.environ.pop("WEREAD_WORD_CACHE", None)
            else:
                os.environ["WEREAD_WORD_CACHE"] = old_cache
        self.assertEqual(kept, ["skitter", "curtsy"])
        self.assertEqual(notes["invalid"], ["qqzzx"])
        self.assertIn("skitter", notes["verified"])
        self.assertIn("curtsy", notes["unverified"])

    def test_16_key_sanitize(self):
        import apikey
        self.assertEqual(apikey.sanitize("  wrk-abc123  "), "wrk-abc123")
        self.assertEqual(apikey.sanitize("wrk-abc123\n"), "wrk-abc123")
        self.assertEqual(apikey.sanitize("wrk-abc 中文 123"), "wrk-abc123")
        self.assertEqual(apikey.sanitize(""), "")

    def test_15_slug(self):
        self.assertEqual(run.slug('A/B:C*D?E"F<G>H|I'), "A_B_C_D_E_F_G_H_I")
        self.assertLessEqual(len(run.slug("x" * 100)), 40)
        self.assertEqual(run.slug("   "), "book")


    def test_17_bbdc_multipart_and_summary(self):
        import bbdc_upload
        path = os.path.join(self.tmp, "wb.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("alpha\nbeta\n")
        boundary, body = bbdc_upload.build_multipart(path)
        self.assertIn(boundary.encode(), body)
        self.assertIn(b'name="file"', body)
        self.assertIn(b'filename="wb.txt"', body)
        self.assertIn("alpha\nbeta".encode(), body)
        self.assertTrue(body.rstrip().endswith(b"--"))

        masked = bbdc_upload.mask_cookie("JSESSIONID=abcdef123; hanhan=xyz789; foo=bar")
        self.assertIn("JSESSIONID=abcd", masked)
        self.assertIn("hanhan=xyz7", masked)
        self.assertNotIn("abcdef123", masked)

        text = bbdc_upload.summarize({"result_code": 200,
                                      "data_body": {"knowList": "a,b", "unknowList": "c"}})
        self.assertIn("result_code=200", text)

    def test_18_bbdc_cookie_source(self):
        import bbdc_upload
        old = os.environ.get("BBDC_COOKIE")
        old_file = os.environ.get("BBDC_COOKIE_FILE")
        path = os.path.join(self.tmp, "cookies.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("hanhan=fromfile\n")
        os.environ["BBDC_COOKIE_FILE"] = path
        try:
            self.assertEqual(bbdc_upload.load_cookie(), "hanhan=fromfile")
            os.environ["BBDC_COOKIE"] = "hanhan=fromenv"
            self.assertEqual(bbdc_upload.load_cookie(), "hanhan=fromenv")
            self.assertEqual(bbdc_upload.load_cookie("hanhan=explicit"), "hanhan=explicit")
        finally:
            for key, value in (("BBDC_COOKIE", old), ("BBDC_COOKIE_FILE", old_file)):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


    def test_19_save_book_payload(self):
        """第二步 /lexis/book/save：form-urlencoded，字段与编码要对。"""
        import urllib.parse
        import bbdc_upload as U
        captured = {}

        def fake_post(url, body, headers, timeout, retries=3):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {"result_code": 200, "data_kind": "lexis_book", "data_body": {}}

        original = U._post_json
        U._post_json = fake_post
        try:
            out = U.save_book(["alpha", "beta"], "词 书名", "简介", "KY", cookie="hanhan=x")
        finally:
            U._post_json = original

        self.assertEqual(out.get("result_code"), 200)
        self.assertTrue(captured["url"].endswith("/lexis/book/save"))
        self.assertIn("x-www-form-urlencoded", captured["headers"]["Content-Type"])
        parsed = urllib.parse.parse_qs(captured["body"].decode(), keep_blank_values=True)
        self.assertEqual(parsed["wordList"], ["alpha,beta"])
        self.assertEqual(parsed["name"], ["词 书名"])
        self.assertEqual(parsed["desc"], ["简介"])
        self.assertEqual(parsed["exam"], ["KY"])

    def test_20_upload_then_create_flow(self):
        """run.py --create：识别 → 用 knowList 建词书；<20 词要拦住。"""
        import types
        import bbdc_upload as U
        calls = {"submit": 0, "save": None}
        txt = os.path.join(self.tmp, "flow.txt")
        with open(txt, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(f"w{i}" for i in range(25)) + "\n")

        orig_submit, orig_save, orig_cookie = U.submit, U.save_book, U.load_cookie
        U.load_cookie = lambda *a, **k: "hanhan=x"
        U.submit = lambda path, cookie: {"result_code": 200, "data_body": {
            "knowList": ",".join(f"w{i}" for i in range(23)),
            "unknowList": "w23,w24"}}
        U.save_book = lambda words, name, desc="", exam="", cookie="", **k: (
            calls.__setitem__("save", (list(words), name)) or {"result_code": 200})
        args = types.SimpleNamespace(prune_unknown=False, create=True, book_name=None,
                                     desc="", exam="", upload=False)
        try:
            run._push_to_bbdc(txt, ["w0"], args, "测试书", "wordbook_x")
        finally:
            U.submit, U.save_book, U.load_cookie = orig_submit, orig_save, orig_cookie

        self.assertIsNotNone(calls["save"], "应调用 save_book")
        words, name = calls["save"]
        self.assertEqual(len(words), 23)
        self.assertEqual(name, "测试书")


if __name__ == "__main__":
    unittest.main(verbosity=2)
