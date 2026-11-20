"""划线文本 → 词汇：判定粒度、抽词、清洗、词形还原。

只收"单词级 / 短语级"划线；整句、含中文、非英文一律跳过（--allow-mixed 可放宽中文）。
短语因为不背单词不支持词组，会被拆成实词，短语原文留作 review.md 的上下文。
"""
from __future__ import annotations

import os
import re

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\u2019\-]*")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CJK_PUNCT_RE = re.compile(r"[\u3000-\u303f\uff01-\uff5e]")
SENTENCE_MARK_RE = re.compile(r"[.!?;:]")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2028\u2029\ufeff]")
CVC_RE = re.compile(r"^[^aeiou][aeiou][bdgklmnpvz]$")

# 划线两端可能被多划进来的东西：引号、括号、句读、项目符号、中文标点等
EDGE_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~‘’“”…·•–—、。，；：！？（）【】《》「」『』〈〉")
# 跨行断字：inter-\nesting → interesting
HYPHEN_BREAK_RE = re.compile(r"(?<=[A-Za-z])[-‐]\s*\n\s*(?=[a-z])")
# 行首编号：1. / 1) / 1、/ · / •
LIST_MARK_RE = re.compile(r"^\s*(?:\d{1,3}[.)、]|[•·*\-–—])\s+")

MAX_TOKENS_DEFAULT = 4
MAX_CHARS_DEFAULT = 50
MIN_LATIN_RATIO = 0.75

# 允许收下的两个字母的词；其余两字母 token 多半是划歪的碎片或外语虚词
TWO_LETTER_OK = {
    "am", "an", "as", "at", "be", "by", "do", "go", "he", "hi", "if", "in",
    "is", "it", "me", "my", "no", "of", "on", "or", "so", "to", "up", "us",
    "we", "ok", "oh", "ah", "ex", "ox", "ax", "ad", "id", "yo", "ha",
}

# -ing 形式本身是独立形容词，还原成动词/名词会丢词义，保持原样
ING_ADJECTIVES = {
    "interesting", "exciting", "surprising", "amazing", "annoying", "confusing",
    "embarrassing", "disappointing", "satisfying", "challenging", "rewarding",
    "demanding", "promising", "outstanding", "striking", "moving", "touching",
    "convincing", "depressing", "encouraging", "frightening", "terrifying",
    "thrilling", "exhausting", "fascinating", "inspiring", "frustrating",
    "overwhelming", "underlying", "upcoming", "ongoing", "willing", "unwilling",
    "appealing", "disturbing", "astonishing", "breathtaking", "compelling",
    "charming", "shocking", "stunning", "worrying", "pleasing", "lasting",
}

# 原形长得像复数、不能被去 s 的词
PROTECTED = {
    "news", "series", "species", "means", "physics", "mathematics", "economics",
    "politics", "ethics", "athletics", "gymnastics", "linguistics", "statistics",
    "business", "class", "glass", "pass", "process", "access", "success", "boss",
    "loss", "cross", "press", "stress", "progress", "canvas", "campus", "virus",
    "bonus", "focus", "status", "genius", "chaos", "analysis", "basis", "crisis",
    "thesis", "hypothesis", "axis", "surplus", "census", "always", "perhaps",
    "towards", "across", "unless", "this", "his", "its", "us", "as", "is", "was",
    "has", "does", "yes", "whereas", "nevertheless", "gas", "bias", "ethos",
}

IRREGULAR = {
    # be / have / do / go
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be", "been": "be",
    "being": "be", "has": "have", "had": "have", "having": "have", "does": "do",
    "did": "do", "done": "do", "doing": "do", "goes": "go", "went": "go",
    "gone": "go", "going": "go", "dying": "die", "lying": "lie", "tying": "tie",
    "vying": "vie",
    # 高频不规则动词
    "said": "say", "made": "make", "took": "take", "taken": "take", "came": "come",
    "saw": "see", "seen": "see", "knew": "know", "known": "know", "got": "get",
    "gotten": "get", "gave": "give", "given": "give", "found": "find",
    "thought": "think", "told": "tell", "became": "become", "left": "leave",
    "felt": "feel", "brought": "bring", "began": "begin", "begun": "begin",
    "kept": "keep", "held": "hold", "wrote": "write", "written": "write",
    "stood": "stand", "heard": "hear", "meant": "mean", "met": "meet", "ran": "run",
    "paid": "pay", "sat": "sit", "spoke": "speak", "spoken": "speak", "led": "lead",
    "grew": "grow", "grown": "grow", "lost": "lose", "fell": "fall",
    "fallen": "fall", "sent": "send", "built": "build", "understood": "understand",
    "drew": "draw", "drawn": "draw", "broke": "break", "broken": "break",
    "spent": "spend", "rose": "rise", "risen": "rise", "drove": "drive",
    "driven": "drive", "bought": "buy", "wore": "wear", "worn": "wear",
    "chose": "choose", "chosen": "choose", "ate": "eat", "eaten": "eat",
    "threw": "throw", "thrown": "throw", "caught": "catch", "taught": "teach",
    "fought": "fight", "sought": "seek", "sold": "sell", "shot": "shoot",
    "flew": "fly", "flown": "fly", "forgot": "forget", "forgotten": "forget",
    "hid": "hide", "hidden": "hide", "hung": "hang", "slept": "sleep",
    "swept": "sweep", "wept": "weep", "crept": "creep", "dealt": "deal",
    "dreamt": "dream", "leapt": "leap", "learnt": "learn", "spelt": "spell",
    "burnt": "burn", "struck": "strike", "stuck": "stick", "dug": "dig",
    "won": "win", "spun": "spin", "swam": "swim", "swum": "swim", "sang": "sing",
    "sung": "sing", "drank": "drink", "drunk": "drink", "rang": "ring",
    "rung": "ring", "shrank": "shrink", "sank": "sink", "sunk": "sink",
    "woke": "wake", "woken": "wake", "bore": "bear", "born": "bear",
    "tore": "tear", "torn": "tear", "mistook": "mistake",
    "undertook": "undertake", "forgave": "forgive", "forgiven": "forgive",
    "froze": "freeze", "frozen": "freeze", "shook": "shake", "shaken": "shake",
    "bit": "bite", "bitten": "bite", "blew": "blow", "blown": "blow",
    "fled": "flee", "laid": "lay", "lain": "lie", "lit": "light", "rode": "ride",
    "ridden": "ride", "shone": "shine", "swore": "swear", "sworn": "swear",
    "wound": "wind",
    # 名词不规则复数
    "children": "child", "men": "man", "women": "woman", "feet": "foot",
    "teeth": "tooth", "mice": "mouse", "geese": "goose", "people": "person",
    "lives": "life", "knives": "knife", "wives": "wife", "leaves": "leaf",
    "wolves": "wolf", "shelves": "shelf", "halves": "half", "loaves": "loaf",
    "thieves": "thief", "criteria": "criterion", "phenomena": "phenomenon",
    "analyses": "analysis", "crises": "crisis", "theses": "thesis",
    "hypotheses": "hypothesis", "bacteria": "bacterium", "indices": "index",
    "matrices": "matrix", "vertices": "vertex", "oxen": "ox",
    # 比较级
    "better": "good", "best": "good", "worse": "bad", "worst": "bad",
    "further": "far", "farther": "far", "furthest": "far", "farthest": "far",
    "less": "little", "least": "little",
}


def load_stopwords(path=None):
    path = path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets",
        "stopwords.txt",
    )
    words = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                w = line.strip().lower()
                if w and not w.startswith("#"):
                    words.add(w)
    return words


def _strip_edges(text):
    while text and (text[0] in EDGE_PUNCT or text[0].isspace()):
        text = text[1:]
    while text and (text[-1] in EDGE_PUNCT or text[-1].isspace()):
        text = text[:-1]
    return text


def clean(text):
    """去掉多划进来的字母残渣之外的一切噪声：零宽字符、跨行断字、中文标点、
    多余空白、行首编号、两端标点引号。"""
    if not text:
        return ""
    t = ZERO_WIDTH_RE.sub("", str(text))
    t = t.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    t = HYPHEN_BREAK_RE.sub("", t)          # inter-\n esting → interesting
    t = CJK_PUNCT_RE.sub(" ", t)            # 中文标点只是噪声，不当语言信号
    t = re.sub(r"\s+", " ", t)
    t = LIST_MARK_RE.sub("", t.strip())     # 1. / 1、 / • 开头的编号
    return _strip_edges(t)


def _latin_ratio(text):
    letters = sum(1 for c in text if c.isascii() and c.isalpha())
    visible = sum(1 for c in text if not c.isspace())
    return letters / visible if visible else 0.0


def classify(text, max_tokens=MAX_TOKENS_DEFAULT, max_chars=MAX_CHARS_DEFAULT,
             allow_mixed=False):
    """判定划线粒度。

    返回 dict(kind, tokens, latin_ratio)。kind ∈
    word / phrase / skip:cjk / skip:non_english / skip:sentence / skip:empty
    """
    raw = clean(text)
    if not raw:
        return {"kind": "skip:empty", "tokens": [], "latin_ratio": 0.0}

    mixed = bool(CJK_RE.search(raw))
    working = raw
    if mixed:
        if not allow_mixed:
            return {"kind": "skip:cjk", "tokens": [], "latin_ratio": 0.0}
        working = CJK_RE.sub(" ", raw)

    tokens = [t for t in TOKEN_RE.findall(working) if len(t.strip("'-")) > 0]
    ratio = _latin_ratio(working)

    if not tokens or ratio < MIN_LATIN_RATIO:
        return {"kind": "skip:non_english", "tokens": [], "latin_ratio": ratio}
    if len(working) > max_chars or len(tokens) > max_tokens:
        return {"kind": "skip:sentence", "tokens": tokens, "latin_ratio": ratio}
    if SENTENCE_MARK_RE.search(working):
        return {"kind": "skip:sentence", "tokens": tokens, "latin_ratio": ratio}
    if "," in working and len(tokens) >= 3:
        return {"kind": "skip:sentence", "tokens": tokens, "latin_ratio": ratio}

    return {
        "kind": "word" if len(tokens) == 1 else "phrase",
        "tokens": tokens,
        "latin_ratio": ratio,
    }


def normalize(word):
    w = word.replace("\u2019", "'").strip("-'\u2014 ")
    w = w.lower()
    if len(w) > 3 and w.endswith("'s"):
        w = w[:-2]
    if len(w) > 2 and w.endswith("'"):
        w = w[:-1]
    return w


def _undouble(stem):
    if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
        return stem[:-1]
    return stem


LEXICON = None          # word -> 词频，惰性加载
_LEXICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "lexicon.tsv"
)


def load_lexicon(path=None):
    """词表用于校验还原结果，避免造出 snif / assembl 这种非词。"""
    global LEXICON
    if LEXICON is not None:
        return LEXICON
    LEXICON = {}
    target = path or _LEXICON_PATH
    try:
        with open(target, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                word = line.strip().lower()
                if word:
                    LEXICON[word] = -i          # 行首越靠前越常用
    except OSError:
        pass
    return LEXICON


def _best_candidate(candidates, lexicon):
    """按词频挑，用于 hoping→hope 这类同形歧义。"""
    hits = [(lexicon.get(c), c) for c in candidates if c in lexicon]
    if not hits:
        return None
    return max(hits)[1]


def _first_in(candidates, lexicon):
    """按给定优先级挑，用于复数 spines→spine 这类不该看词频的场景。"""
    for c in candidates:
        if c in lexicon:
            return c
    return None


def _pick(candidates, lexicon, by_freq=True):
    """返回词表里能验证的候选；一个都验证不了就返回 None（调用方保留原形）。"""
    if not lexicon:
        return candidates[0]
    chosen = (_best_candidate(candidates, lexicon) if by_freq
              else _first_in(candidates, lexicon))
    return chosen


def in_lexicon(word):
    """词是否在自带词表里（用于决定要不要联网校验）。"""
    return normalize(word) in load_lexicon()


def lemmatize(word):
    """保守的词形还原：有词表就按词表校验，拿不准保留原形，绝不造词。"""
    w = normalize(word)
    if not w:
        return w
    if w in IRREGULAR:
        return IRREGULAR[w]
    if w in PROTECTED or w in ING_ADJECTIVES or len(w) <= 3:
        return w

    lexicon = load_lexicon()

    # 高置信规则：不依赖词表
    if w.endswith("ies") and len(w) >= 5:
        if not w[:-3].endswith("v"):      # movies → movie
            return w[:-3] + "y"
        return w[:-1]
    if w.endswith("ied") and len(w) >= 5:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "sses", "xes", "zes")):
        return w[:-2]                     # watches → watch
    if w.endswith("oes") and len(w) >= 5:
        return w[:-2]                     # heroes → hero
    if w.endswith("eed") and not w.endswith("eeded") and len(w) >= 5:
        return w[:-1]                     # agreed → agree

    # 需要词表判断的：-ing / -ed / 复数
    picked = None
    if w.endswith("ing") and len(w) >= 6:
        stem = w[:-3]
        if len(stem) >= 3:
            picked = _pick([_undouble(stem), stem, stem + "e"], lexicon)
    elif w.endswith("ed") and len(w) >= 5:
        stem = w[:-2]
        if len(stem) >= 3:
            picked = _pick([_undouble(stem), stem, stem + "e"], lexicon)
    elif w.endswith(("ses", "zes")) and len(w) >= 5:
        picked = _pick([w[:-1], w[:-2]], lexicon, by_freq=False)   # houses → house
    elif w.endswith("s") and not w.endswith(("ss", "us", "is", "os")):
        picked = _pick([w[:-1], w[:-2]], lexicon, by_freq=False)   # spines → spine
    if picked:
        return picked
    return w      # 验证不了就保留原样，绝不吐 lopsid / excruciat 这种残词


def words_from(highlight, stopwords, max_tokens=MAX_TOKENS_DEFAULT,
               max_chars=MAX_CHARS_DEFAULT, allow_mixed=False, lemma=True):
    """一条划线 → (kind, 收下的词, 短语原文)。"""
    info = classify(highlight, max_tokens=max_tokens, max_chars=max_chars,
                    allow_mixed=allow_mixed)
    kind = info["kind"]
    if not kind.startswith(("word", "phrase")):
        return kind, [], ""

    tokens = info["tokens"]
    if kind == "word":
        surface = tokens[0]
        low = normalize(surface)
        # 多划进来的孤立字母/外语虚词（"a"、"de" 之类）不是要背的词
        if len(low) < 2 or (len(low) == 2 and low not in TWO_LETTER_OK):
            return "skip:noise", [], ""
        # 单词级划线：用户明确划出来的，即使属停用词也保留
        word = lemmatize(surface) if lemma else low
        return kind, [word], clean(highlight)

    kept = []
    for raw_token in tokens:
        low = normalize(raw_token)
        if not low or len(low) < 2 or low in stopwords:
            continue
        # 短语内部的专名（首字母大写且非全大写）不收
        if raw_token[0].isupper() and not raw_token.isupper():
            continue
        kept.append(lemmatize(low) if lemma else low)
    return kind, kept, clean(highlight)
