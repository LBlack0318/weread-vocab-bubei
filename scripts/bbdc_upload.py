"""把词书 txt 直接提交到不背单词（bbdc.cn）。

端点来自浏览器抓包（一次真实上传）：
    POST https://bbdc.cn/lexis/book/file/submit
    multipart/form-data，字段名 file，filename 用真实文件名
鉴权靠 cookie：JSESSIONID + hanhan（另有两枚统计 cookie 可有可无）。

Cookie 只从用户目录或环境变量读，不写进 skill 目录：
    ~/.weread-vocab/bbdc_cookies.txt     一行原始 cookie 串
    或环境变量 BBDC_COOKIE
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import paths

ENDPOINT = "https://bbdc.cn/lexis/book/file/submit"
REFERER = "https://bbdc.cn/lexis_book_index"
ORIGIN = "https://bbdc.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0")


def cookie_file():
    return os.environ.get("BBDC_COOKIE_FILE") or os.path.join(
        paths.home_dir(), "bbdc_cookies.txt")


def load_cookie(explicit=None):
    if explicit:
        return explicit.strip()
    env = (os.environ.get("BBDC_COOKIE") or "").strip()
    if env:
        return env
    try:
        with open(cookie_file(), encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def save_cookie(cookie):
    path = cookie_file()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(cookie.strip() + "\n")
    return path


def mask_cookie(cookie):
    parts = []
    for item in cookie.split(";"):
        item = item.strip()
        if not item:
            continue
        name, _, value = item.partition("=")
        keep = {"JSESSIONID", "hanhan", "acw_tc"}
        if name in keep:
            parts.append(f"{name}={value[:6]}…")
        else:
            parts.append(f"{name}=…")
    return "; ".join(parts)


def build_multipart(filepath, field="file"):
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as fh:
        content = fh.read()
    chunks = [
        f"--{boundary}\r\n".encode(),
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
         % (field, filename)).encode("utf-8"),
        b"Content-Type: text/plain\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return boundary, b"".join(chunks)


def submit(filepath, cookie, endpoint=ENDPOINT, timeout=120, retries=3):
    boundary, body = build_multipart(filepath)
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Cookie": cookie,
        "Origin": ORIGIN,
        "Referer": REFERER,
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    last = ""
    for attempt in range(retries):
        req = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw[:2000]}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")[:400]
            if exc.code in (401, 403):
                raise RuntimeError(
                    f"鉴权失败（HTTP {exc.code}）。cookie 过期了，浏览器里重新登录后"
                    f"再抓一次。{body_text}")
            last = f"HTTP {exc.code} {body_text}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(getattr(exc, "reason", exc))[:120]
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"提交失败：{last}")


SAVE_ENDPOINT = "https://bbdc.cn/lexis/book/save"


def _headers(url_referer=REFERER, content_type=None, cookie=""):
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": cookie,
        "Origin": ORIGIN,
        "Referer": url_referer,
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _post_json(url, body, headers, timeout, retries=3):
    last = ""
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw[:2000]}
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")[:400]
            if exc.code in (401, 403):
                raise RuntimeError(
                    f"鉴权失败（HTTP {exc.code}）。cookie 过期了，浏览器里重新登录后"
                    f"再抓一次。{text}")
            last = f"HTTP {exc.code} {text}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(getattr(exc, "reason", exc))[:120]
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败：{last}")


def save_book(words, name, desc="", exam="", cookie="", endpoint=SAVE_ENDPOINT,
              timeout=60):
    """第二步：把识别通过的词提交成词书（form-urlencoded）。"""
    payload = urllib.parse.urlencode({
        "wordList": ",".join(words),
        "desc": desc,
        "name": name,
        "exam": exam,
    }, encoding="utf-8").encode()
    headers = _headers(content_type="application/x-www-form-urlencoded; charset=UTF-8",
                       cookie=cookie)
    return _post_json(endpoint, payload, headers, timeout)


def upload_and_save(filepath, name, desc="", exam="", cookie=None,
                    prune_unknown=True, log=print):
    """完整链路：提交文件拿识别结果 → 用识别通过的词创建词书。

    返回 dict(submit=..., save=..., known=[...], unknown=[...])。
    """
    cookie = cookie or load_cookie()
    result = submit(filepath, cookie)
    body = result.get("data_body") or {}
    known = [w for w in (body.get("knowList") or "").split(",") if w]
    unknown = [w for w in (body.get("unknowList") or "").split(",") if w]
    log(f"  平台识别 {len(known)}/{len(known) + len(unknown)} 词"
        + (f"，未识别 {'、'.join(unknown[:10])}" if unknown else ""))

    words = known if prune_unknown else known + unknown
    if len(words) < 20:
        raise RuntimeError(f"只有 {len(words)} 个可用词，平台要求 ≥20，未创建词书")

    saved = save_book(words, name=name, desc=desc, exam=exam, cookie=cookie)
    return {"submit": result, "save": saved, "known": known, "unknown": unknown,
            "name": name, "count": len(words)}


def summarize(result):
    """把回包压成几行人类可读的话。"""
    lines = []
    code = result.get("result_code")
    lines.append(f"result_code={code}")
    body = result.get("data_body")
    if isinstance(body, dict):
        for key in ("bookId", "bookName", "name", "book_id", "id", "wordCount",
                    "totalCount", "validCount", "invalidCount", "status"):
            if key in body:
                lines.append(f"{key}={body[key]}")
        for key in ("words", "invalidWords", "unmatchedWords", "failWords"):
            value = body.get(key)
            if isinstance(value, list):
                sample = value[:10]
                lines.append(f"{key}: {len(value)} 个 {sample}")
    elif body is not None:
        lines.append(f"data_body={str(body)[:200]}")
    if "_raw" in result:
        lines.append(f"raw={result['_raw'][:200]}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="提交词书到不背单词")
    ap.add_argument("file", help="要上传的 txt")
    ap.add_argument("--cookie", help="直接给 cookie 串（默认读用户目录文件/环境变量）")
    ap.add_argument("--save-cookie", action="store_true", help="把 --cookie 存到用户目录")
    ap.add_argument("--dry-run", action="store_true", help="只检查文件和 cookie，不发请求")
    ap.add_argument("--json", action="store_true", help="打印完整回包")
    ap.add_argument("--save-book", action="store_true",
                    help="识别通过后直接创建词书")
    ap.add_argument("--name", help="词书名称（默认用文件名）")
    ap.add_argument("--desc", default="", help="词书简介")
    ap.add_argument("--exam", default="", help="考试分类代码，如 KY（考研）")
    args = ap.parse_args(argv)

    if not os.path.exists(args.file):
        print(f"✗ 找不到文件 {args.file}")
        return 1
    words = [w for w in open(args.file, encoding="utf-8-sig").read().split() if w]
    print(f"· 文件：{os.path.basename(args.file)}，{len(words)} 词")

    cookie = load_cookie(args.cookie)
    if not cookie:
        print("✗ 没有 bbdc cookie。放到 ~/.weread-vocab/bbdc_cookies.txt，"
              "或用 --cookie 传入")
        return 1
    print(f"· cookie：{mask_cookie(cookie)}")
    if args.save_cookie and args.cookie:
        print(f"✓ 已保存到 {save_cookie(args.cookie)}")

    if args.dry_run:
        print("（dry-run，未发送）")
        return 0

    try:
        result = submit(args.file, cookie)
    except RuntimeError as exc:
        print(f"✗ {exc}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
    else:
        print(summarize(result))

    if args.save_book:
        body = result.get("data_body") or {}
        known = [w for w in (body.get("knowList") or "").split(",") if w]
        if len(known) < 20:
            print(f"✗ 可用词只有 {len(known)} 个，平台要求 ≥20，未创建")
            return 2
        name = args.name or os.path.splitext(os.path.basename(args.file))[0]
        try:
            saved = save_book(known, name=name, desc=args.desc, exam=args.exam,
                              cookie=cookie)
        except RuntimeError as exc:
            print(f"✗ 创建词书失败：{exc}")
            return 1
        if saved.get("result_code") == 200:
            print(f"✓ 已创建词书《{name}》（{len(known)} 词）")
        else:
            print(f"✗ 创建被拒：{saved.get('error_body') or saved}")
            return 2
    return 0 if result.get("result_code") in (200, "200", None) else 2


if __name__ == "__main__":
    raise SystemExit(main())
