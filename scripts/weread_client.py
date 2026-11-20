"""微信读书 Agent API Gateway 的极简客户端（仅标准库）。

接口约定（与官方 weread-skills 一致）：
  POST https://i.weread.qq.com/api/agent/gateway
  Authorization: Bearer $WEREAD_API_KEY
  body = {"api_name": "/book/bookmarklist", ...业务参数平铺..., "skill_version": "1.0.6"}

业务参数必须平铺在 body 顶层，不要包在 params/data 里。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

import apikey

DEFAULT_GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
DEFAULT_SKILL_VERSION = "1.0.6"


class WeReadError(RuntimeError):
    """网关返回 errcode != 0，或网络层失败。"""


class Gateway:
    def __init__(self, api_key=None, url=None, skill_version=DEFAULT_SKILL_VERSION,
                 timeout=30, interactive=True, use_saved_key=False, remember_key=False):
        if api_key is None:
            api_key, self.key_source = apikey.resolve(
                interactive=interactive, use_saved=use_saved_key, save=remember_key)
        else:
            self.key_source = "given"
        self.api_key = apikey.sanitize(api_key) if api_key else ""
        if not self.api_key:
            raise WeReadError(apikey.HELP)
        self.url = url or os.environ.get("WEREAD_GATEWAY_URL") or DEFAULT_GATEWAY
        self.skill_version = skill_version or os.environ.get(
            "WEREAD_SKILL_VERSION", DEFAULT_SKILL_VERSION
        )
        self.timeout = timeout
        self._upgrade_notice_shown = False

    # ---------- 底层请求 ----------

    def call(self, api_name, **payload):
        body = {"api_name": api_name}
        body.update({k: v for k, v in payload.items() if v is not None})
        body["skill_version"] = self.skill_version
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        last_err = None
        for attempt in range(3):
            req = urllib.request.Request(
                self.url,
                data=data,
                method="POST",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "weread-vocab-bubei/0.1",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                if e.code in (401, 403):
                    raise WeReadError(
                        f"鉴权失败（HTTP {e.code}）。WEREAD_API_KEY 无效或已失效，"
                        f"请到 https://weread.qq.com/r/weread-skills 重新获取。{detail}"
                    )
                last_err = f"HTTP {e.code} {detail}".strip()
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(getattr(e, "reason", e))
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        else:
            raise WeReadError(f"调用 {api_name} 失败：{last_err}")

        try:
            resp = json.loads(raw)
        except json.JSONDecodeError:
            raise WeReadError(f"{api_name} 返回非 JSON：{raw[:200]}")

        if isinstance(resp, dict) and resp.get("upgrade_info") and not self._upgrade_notice_shown:
            self._upgrade_notice_shown = True
            info = resp["upgrade_info"]
            ver = info.get("latest_version") if isinstance(info, dict) else None
            print(f"! 微信读书 skill 有新版本{f'（{ver}）' if ver else ''}，不影响本次结果",
                  file=sys.stderr)

        code = resp.get("errcode", 0) if isinstance(resp, dict) else 0
        if code not in (0, None):
            msg = resp.get("errmsg") or resp.get("errmsg_text") or ""
            raise WeReadError(f"{api_name} 返回 errcode={code} {msg}")
        return resp

    # ---------- 业务封装 ----------

    def api_list(self):
        return self.call("/_list")

    def notebooks(self, count=100, max_pages=50):
        """遍历 /user/notebooks 到 hasMore=0，返回 books 列表。"""
        out, last_sort, pages = [], None, 0
        while pages < max_pages:
            resp = self.call("/user/notebooks", count=count, lastSort=last_sort)
            books = resp.get("books") or []
            out.extend(books)
            pages += 1
            if not resp.get("hasMore") or not books:
                break
            last_sort = books[-1].get("sort")
            if last_sort is None:
                break
        return out

    def search(self, keyword, count=10):
        resp = self.call("/store/search", keyword=keyword, scope=10, count=count,
                         context="查找书籍以导出划线")
        return resp

    def bookmarks(self, book_id):
        """返回 (highlights, chapters, book)。

        highlights[i] = {bookmarkId, chapterUid, markText, createTime, type, range}
        """
        resp = self.call("/book/bookmarklist", bookId=str(book_id))
        highlights = resp.get("updated") or []
        chapters = {c.get("chapterUid"): c for c in (resp.get("chapters") or [])}
        book = resp.get("book") or {}
        return highlights, chapters, book

    def verify(self):
        resp = self.call("/user/notebooks", count=1)
        return resp


def book_title(book_obj, book_id):
    if isinstance(book_obj, dict):
        for k in ("title", "bookName", "name"):
            v = book_obj.get(k)
            if v:
                return str(v)
    return f"book:{book_id}"
