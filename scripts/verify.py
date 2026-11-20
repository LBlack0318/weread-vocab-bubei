"""词表外的词联网校验：查公开词典确认是不是真词。

结果三级：
  valid   词典里有 → 保留
  invalid 词典明确查不到 → 判为噪声/拼写碎片，丢弃
  unknown 网络失败/超时 → 保留，但在 review.md 里标记"未能联网验证"
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import paths

DICT_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
UA = "weread-vocab-bubei/0.1 (+local script)"

VALID, INVALID, UNKNOWN = "valid", "invalid", "unknown"


def _first_definition(payload):
    """从 dictionaryapi.dev 的回包里取一句最简释义。"""
    try:
        entries = payload if isinstance(payload, list) else payload.get("entries") or []
        for entry in entries:
            for meaning in entry.get("meanings") or []:
                pos = meaning.get("partOfSpeech") or ""
                for d in meaning.get("definitions") or []:
                    text = (d.get("definition") or "").strip()
                    if text:
                        return f"{pos}. {text}" if pos else text
    except (AttributeError, TypeError):
        pass
    return ""


class WordChecker:
    def __init__(self, cache_path=None, timeout=15, workers=4):
        self.cache_path = cache_path or paths.cache_file()
        self.timeout = timeout
        self.workers = workers
        self.cache = self._load()
        self.newly_checked = 0

    # ---------- 缓存 ----------

    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self):
        if not self.newly_checked:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.cache, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass          # 缓存写不了不影响主流程

    # ---------- 查询 ----------

    def _lookup(self, word):
        url = DICT_URL.format(word=urllib.parse.quote(word))
        last = ""
        for attempt in range(3):
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
                return VALID, _first_definition(payload)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return INVALID, ""
                last = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError) as exc:
                last = str(getattr(exc, "reason", exc))[:80]
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))     # 间歇性握手超时，退避重试
        return UNKNOWN, last

    def check(self, word):
        word = word.strip().lower()
        hit = self.cache.get(word)
        if hit and hit.get("status") in (VALID, INVALID):
            return hit["status"], hit.get("def", "")
        status, detail = self._lookup(word)
        if status != UNKNOWN:
            self.cache[word] = {"status": status, "def": detail,
                                "at": int(time.time())}
            self.newly_checked += 1
        return status, detail

    def check_many(self, words, progress=None):
        words = list(dict.fromkeys(w.strip().lower() for w in words if w.strip()))
        if not words:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=min(self.workers, len(words))) as pool:
            for word, (status, detail) in zip(words, pool.map(self.check, words)):
                results[word] = {"status": status, "def": detail}
                if progress:
                    progress(word, status)
        self.save()
        return results
