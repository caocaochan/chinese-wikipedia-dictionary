"""Turn the lead section of a Chinese Wikipedia article into a short plain-text gloss."""

import html
import re

LIMIT = 150  # target length of a gloss, in characters

# ---------------------------------------------------------------------------
# Regexes

RE_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.S)
RE_REF = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?(?:</ref\s*>|$)", re.S | re.I)
RE_DROP_ELEMENTS = re.compile(
    r"<(gallery|math|chem|ce|timeline|syntaxhighlight|source|score|imagemap|mapframe|"
    r"maplink|graph|templatestyles|references|inputbox|categorytree|hiero)\b[^>]*?"
    r"(?:/>|>.*?</\1\s*>)",
    re.S | re.I,
)
RE_HEADING = re.compile(r"^=+[^=\n].*?=+\s*$", re.M)
RE_LANGCONV = re.compile(r"-\{(?!\{)(.*?)\}-", re.S)
RE_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
RE_EXTLINK = re.compile(r"\[(?:https?:|ftp:)?//[^\s\]]*\s*([^\]]*)\]")
RE_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
RE_TABLE = re.compile(r"\{\|(?:(?!\{\|).)*?\|\}", re.S)
RE_TAG = re.compile(r"</?[a-zA-Z][^<>]*?/?>")
RE_MAGIC = re.compile(r"__[A-Z_]+__")
RE_NAMED_ARG = re.compile(r"^\s*([^=]+?)\s*=(.*)$", re.S)
RE_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]")
RE_LANG_PREFIX = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]+)*$")

FILE_NS = {"file", "image", "文件", "檔案", "档案", "图像", "圖像", "媒体", "媒體", "media", "图片", "圖片"}
CATEGORY_NS = {"category", "分类", "分類"}
RE_FILE_START = re.compile(r"\[\[\s*:?\s*(?:" + "|".join(FILE_NS) + r")\s*:", re.I)

LANG_NAMES = {
    "en": "英语", "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语", "ru": "俄语",
    "es": "西班牙语", "it": "意大利语", "la": "拉丁语", "pt": "葡萄牙语", "ar": "阿拉伯语",
    "vi": "越南语", "th": "泰语", "mn": "蒙古语", "bo": "藏语", "ug": "维吾尔语",
    "ms": "马来语", "id": "印尼语", "nl": "荷兰语", "sv": "瑞典语", "pl": "波兰语",
    "cs": "捷克语", "el": "希腊语", "grc": "古希腊语", "he": "希伯来语", "tr": "土耳其语",
    "fa": "波斯语", "hi": "印地语", "sa": "梵语", "uk": "乌克兰语", "fi": "芬兰语",
    "da": "丹麦语", "no": "挪威语", "nb": "挪威语", "hu": "匈牙利语", "ro": "罗马尼亚语",
    "tl": "他加禄语", "km": "高棉语", "lo": "老挝语", "my": "缅甸语", "ta": "泰米尔语",
    "yue": "粤语", "nan": "闽南语", "hak": "客家语", "zh": "中文", "eo": "世界语",
    "ga": "爱尔兰语", "cy": "威尔士语", "is": "冰岛语", "et": "爱沙尼亚语", "lv": "拉脱维亚语",
    "lt": "立陶宛语", "sr": "塞尔维亚语", "hr": "克罗地亚语", "bg": "保加利亚语",
    "sk": "斯洛伐克语", "sl": "斯洛文尼亚语", "ka": "格鲁吉亚语", "hy": "亚美尼亚语",
    "az": "阿塞拜疆语", "kk": "哈萨克语", "uz": "乌兹别克语", "ur": "乌尔都语", "bn": "孟加拉语",
    "ne": "尼泊尔语", "si": "僧伽罗语", "sw": "斯瓦希里语", "ca": "加泰罗尼亚语", "eu": "巴斯克语",
}

# Templates whose output is the Nth positional argument.
POSITIONAL = {
    "lang": 1, "langx": 1, "le": 0, "ill": 0, "ilh": 0, "illm": 0, "internal link helper": 0,
    "link": 0, "nowrap": 0, "nobr": 0, "small": 0, "big": 0, "smaller": 0, "larger": 0,
    "abbr": 0, "abbrlink": 0, "tooltip": 0, "unicode": 0, "ruby": 0, "ruby-ja": 0,
    "nihongo": 0, "mvar": 0, "math": 0, "val": 0, "sic": 0, "lang-zh": 0, "zhd": 0,
    "transl": -1, "color": -1, "colour": -1, "font color": -1, "nihongo2": 0, "linktext": None,
    "ublist": None, "hlist": None, "flatlist": None, "plainlist": None, "le2": 0, "en": 0,
    # Rare-character and pronunciation helpers: {{Zy|亳|bó|ㄅㄛˋ|bok3}} -> 亳
    "zy": 0, "注音": 0, "僻字": 0, "rare": 0, "ruby-zh": 0, "ruby-zh-p": 0, "linkcolor": 0,
    "vert": 0, "jpn": 0, "korean": 0, "需要消歧义": 0, "transliteration": -1, "lang-zh-hant": 0,
    "单双书名号转换": 0, "單雙書名號轉換": 0, "书名号": 0, "nowrap begin": None,
}
LITERAL = {"!": "|", "=": "=", "·": "·", "middot": "·", "dot": "·", "ndash": "–", "mdash": "—",
           "spaces": " ", "space": " ", "nbsp": " ", "shy": "", "zwsp": "", "-": "", "'": "'"}
BIRTH_DATE = {"birth date", "birth date and age", "death date", "death date and age",
              "start date", "end date", "dts", "date", "出生日期", "出生日期和年龄", "逝世日期",
              "逝世日期和年龄"}


# ---------------------------------------------------------------------------
# Small helpers

def has_cjk(s):
    return RE_CJK.search(s) is not None


def _args(inner):
    parts = inner.split("|")
    name = parts[0].strip().replace("_", " ")
    for prefix in ("Template:", "template:", "模板:", "subst:", "safesubst:"):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    positional, named = [], {}
    for p in parts[1:]:
        m = RE_NAMED_ARG.match(p)
        if m and not m.group(1).isdigit() and "[" not in m.group(1):
            named[m.group(1).strip().lower()] = m.group(2).strip()
        elif m and m.group(1).isdigit():
            idx = int(m.group(1)) - 1
            if idx < 0 or idx > 50:  # "0=" or absurd indexes: treat as named
                named[m.group(1)] = m.group(2).strip()
                continue
            while len(positional) <= idx:
                positional.append("")
            positional[idx] = m.group(2).strip()
        else:
            positional.append(p.strip())
    return name, positional, named


def _date(pos):
    y, m, d = (pos + ["", "", ""])[:3]
    out = ""
    if y.isdigit():
        out += f"{y}年"
    if m.isdigit():
        out += f"{int(m)}月"
    if d.isdigit():
        out += f"{int(d)}日"
    return out


def _with_unit(v, suffix):
    if not v:
        return ""
    return v if v.endswith(suffix) else v + suffix


# ---------------------------------------------------------------------------
# Wikitext constructs

def _langconv(m):
    """-{ ... }- language-conversion markup: keep the zh-Hans text."""
    s = m.group(1)
    if "|" in s:
        flag, rest = s.split("|", 1)
        if re.fullmatch(r"[A-Za-z;+\-\s]{1,6}", flag.strip()):
            flag = flag.strip()
            if any(c in flag for c in "HT-RD") and "A" not in flag:
                return ""
            s = rest
    if re.search(r"(?:^|;)\s*zh(?:-[a-zA-Z]+)?\s*:", s):
        variants = {}
        for part in s.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                k = k.strip().lower()
                if "=>" in k:
                    k = k.split("=>")[-1].strip()
                variants[k] = v.strip()
        for k in ("zh-hans", "zh-cn", "zh-sg", "zh-my", "zh", "zh-hant", "zh-tw", "zh-hk", "zh-mo"):
            if variants.get(k):
                return variants[k]
        return next(iter(variants.values()), "")
    return s


def _link(m):
    inner = m.group(1)
    target, pipe, label = inner.partition("|")
    t = target.strip()
    colon = t.startswith(":")
    t = t.lstrip(":")
    if ":" in t:
        prefix = t.split(":", 1)[0].strip().lower()
        if prefix in FILE_NS:
            return ""
        if prefix in CATEGORY_NS and not colon:
            return ""
        if not colon and not pipe and RE_LANG_PREFIX.match(prefix):
            return ""  # interlanguage link
    if pipe:
        if label.strip():
            # File links use extra pipes; only the last part is a caption.
            return label.split("|")[-1] if "|" in label else label
        return re.sub(r"\s*[（(][^（）()]*[)）]\s*$", "", t)  # pipe trick
    if "#" in t:
        page, _, anchor = t.partition("#")
        return page or anchor
    return t


def _template(m, title):
    inner = m.group(1)
    head = inner.split("|", 1)[0].strip()
    low = head.lower()
    if low in LITERAL:
        return LITERAL[low]
    if low.startswith("#") or low.startswith("{"):
        return ""
    if low in ("pagename", "fullpagename", "pagenamee", "subpagename", "basepagename"):
        return title
    if low in ("pagenamebase", "pagename base"):
        return re.sub(r"\s*[（(][^（）()]*[)）]$", "", title)
    name, pos, named = _args(inner)
    n = name.lower()
    if n in LITERAL:
        return LITERAL[n]

    if n in ("lang", "langx", "lang-x") or n.startswith("lang-") or n == "lang2":
        if n.startswith("lang-") and n not in ("lang-x", "lang-zh"):
            code, text = n[5:], (pos[0] if pos else "")
        else:
            code, text = (pos[0].lower() if pos else ""), (pos[1] if len(pos) > 1 else "")
        if not text:
            return ""
        if n == "lang" or n == "lang-zh":
            return text
        lang = LANG_NAMES.get(code.split("-")[0])
        return f"{lang}：{text}" if lang else text
    if n.startswith("link-") or n in ("le", "ill", "ilh", "illm", "internal link helper", "link"):
        return pos[0] if pos else ""
    if n == "tsl":
        return pos[2] if len(pos) > 2 and pos[2] else (pos[1] if len(pos) > 1 else "")
    if n == "bd":
        dates = [p for p in pos[:4]]
        birth = "".join(dates[:2])
        death = "".join(dates[2:4])
        if birth and death:
            out = f"{birth}—{death}"
        elif birth:
            out = f"{birth}—"
        else:
            return ""
        # {{BD}} (uppercase) adds its own parentheses; {{bd}} does not.
        return f"（{out}）" if name.startswith("BD") else out
    if n in BIRTH_DATE:
        return _date(pos)
    if n in ("convert", "cvt"):
        if len(pos) >= 2:
            return f"{pos[0]}{pos[1] if not pos[1].isascii() else ' ' + pos[1]}"
        return pos[0] if pos else ""
    if n in ("circa", "c.", "约"):
        return "约" + pos[0] if pos else "约"
    if n in ("jpn", "nihongo", "nihongo2", "korean", "zh") and not pos:
        for k in ("j", "hangul", "s", "t", "text"):
            if named.get(k):
                return named[k]
        return ""
    if n in POSITIONAL:
        idx = POSITIONAL[n]
        vals = [p for p in pos if p]
        if idx is None:
            return "、".join(vals)
        try:
            return pos[idx]
        except IndexError:
            return named.get("text", "")
    return ""  # everything else (infoboxes, hatnotes, citations, notes, ...) is dropped


# ---------------------------------------------------------------------------
# Lead extraction

def _drop_files(s):
    """Remove [[File:...]] links, whose captions may hold nested links or stray brackets."""
    out, i = [], 0
    while True:
        m = RE_FILE_START.search(s, i)
        if not m:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:m.start()])
        depth, j, n = 0, m.start(), len(s)
        while j < n:
            if s.startswith("[[", j):
                depth += 1
                j += 2
            elif s.startswith("]]", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        if depth != 0:  # unclosed: drop to the end of the line only
            nl = s.find("\n", m.start())
            j = n if nl == -1 else nl
        i = j


def _sub_until_stable(regex, repl, s, limit=30):
    for _ in range(limit):
        new = regex.sub(repl, s)
        if new == s:
            return s
        s = new
    return s


def _tidy(s):
    s = s.replace("​", "").replace("﻿", "")
    s = re.sub(r"[ \t　\xa0]+", " ", s)
    s = re.sub(r"(?:[^\s（()）：:，、；;]{1,12}(?:语|語|文)|又称|又稱|全称|全稱|简称|簡稱|旧称|舊稱|原名|本名|别名|別名|学名|學名|英文|英语名)\s*[：:]\s*(?=[，,、；;）)]|$)", "", s)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"[（(]\s*[，,、；;：:\s]*[)）]", "", s)
        s = re.sub(r"([（(])\s*[，,、；;]+\s*", r"\1", s)
        s = re.sub(r"\s*[，,、；;]+\s*([)）])", r"\1", s)
        s = re.sub(r"([，、；])\s*[，、；]+", r"\1", s)
        s = re.sub(r"[，、；]\s*([。！？])", r"\1", s)
        s = re.sub(r"(?:[^\s（()）：:，、；;]{1,12}(?:语|語|文)|又称|又稱|全称|全稱|简称|簡稱|英文)\s*[：:]\s*(?=[，,、；;）)]|$)", "", s)
    s = re.sub(r"\s+([，。；：、）」』！？])", r"\1", s)
    s = re.sub(r"([（「『])\s+", r"\1", s)
    s = re.sub(r"(?<=[一-鿿，。；：、）」』]) (?=[一-鿿（「『])", "", s)
    s = re.sub(r"(?<=[一-鿿）」』]) (?=[一-鿿，。；：、])", "", s)
    return s.strip(" ，、；:：")


def _first_paragraph(s):
    for block in re.split(r"\n\s*\n", s):
        lines = []
        for line in block.split("\n"):
            st = line.strip()
            if not st or st[0] in "*#:;|!{}=":
                continue
            lines.append(st)
        text = _tidy(" ".join(lines))
        if len(text) >= 6 and has_cjk(text):
            return text
    return ""


OPEN = "（(「『【《“‘〈"
CLOSE = "）)」』】》”’〉"
ENDS = "。！？"


def _shorten(s, limit=LIMIT):
    """Keep up to two sentences, about `limit` characters."""
    sentences, cuts = [], []
    depth, start = 0, 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c in OPEN:
            depth += 1
        elif c in CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0 and c in ENDS:
            j = i + 1
            while j < n and (s[j] in ENDS or s[j] in "”’」』"):
                j += 1
            sentences.append(s[start:j])
            start = i = j
            if len(sentences) == 2:
                break
            continue
        elif depth == 0 and c in "，；：、" and not sentences:
            cuts.append(i)
        i += 1
    if start < n and len(sentences) < 2:
        sentences.append(s[start:])
    out = sentences[0].strip()
    if len(sentences) > 1 and len(out) + len(sentences[1].strip()) <= limit:
        out += sentences[1].strip()
    if len(out) <= limit:
        return out
    good = [c for c in cuts if limit * 0.4 <= c < limit]
    cut = good[-1] if good else limit
    return out[:cut].rstrip(" ，；：、") + "……"


def lead_gloss(text, title):
    """Return a short plain-text gloss for an article's wikitext, or ''."""
    s = RE_COMMENT.sub("", text)
    m = RE_HEADING.search(s)
    if m:
        s = s[: m.start()]
    s = RE_REF.sub("", s)
    s = RE_DROP_ELEMENTS.sub("", s)
    s = RE_LANGCONV.sub(_langconv, s)
    s = _drop_files(s)
    s = _sub_until_stable(RE_LINK, _link, s)
    s = RE_EXTLINK.sub(r"\1", s)
    s = _sub_until_stable(RE_TEMPLATE, lambda m: _template(m, title), s)
    s = _sub_until_stable(RE_TABLE, "", s)
    # Leftover unbalanced template/table openers: drop those lines.
    s = re.sub(r"^.*(?:\{\{|\}\}|\{\||\|\}).*$", "", s, flags=re.M)
    s = RE_TAG.sub("", s)
    s = RE_MAGIC.sub("", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"-{4,}", "", s)  # horizontal rules
    s = html.unescape(s)
    para = _first_paragraph(s)
    if not para:
        return ""
    base = re.sub(r"\s*[（(][^（）()]*[)）]$", "", title)
    if para[0] in "（(" and not para.startswith(base):
        # The subject was produced by a template we drop; put the title back.
        para = base + para
    return _shorten(para)
