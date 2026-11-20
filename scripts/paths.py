"""用户数据位置。默认 ~/.weread-vocab，可用 WEREAD_VOCAB_HOME 整体改到别处。

Key 与产物都不进 skill 安装目录。
"""
from __future__ import annotations

import os


def home_dir():
    return os.environ.get("WEREAD_VOCAB_HOME") or os.path.join(
        os.path.expanduser("~"), ".weread-vocab")


def out_dir():
    return os.path.join(home_dir(), "out")


def data_dir():
    return os.path.join(home_dir(), "data")


def key_file():
    return os.environ.get("WEREAD_KEY_FILE") or os.path.join(home_dir(), "api_key")


def cache_file():
    return os.environ.get("WEREAD_WORD_CACHE") or os.path.join(
        home_dir(), "word_cache.json")
