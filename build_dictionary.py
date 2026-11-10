"""Build a Chinese Wikipedia dictionary for Yomitan.

Steps:
  latest-date  print the newest zhwiki dump date whose files are complete
  download     fetch the zhwiki "MediaWiki Content Current" XML dump
  extract      pull a short lead gloss, redirects and link counts out of each dump file
  build        group articles by headword and write the Yomitan ZIP
  all          download, extract and build

Example:
  python build_dictionary.py all --date latest
"""

import argparse
import collections
import datetime as dt
import hashlib
import json
import multiprocessing as mp
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from xml.etree.ElementTree import iterparse

import opencc
from pypinyin import Style, lazy_pinyin

from wikitext import has_cjk, lead_gloss

ROOT = Path(__file__).resolve().parent
DUMP_DIR = ROOT / "data" / "dump"
WORK_DIR = ROOT / "data" / "work"
DIST_DIR = ROOT / "dist"
BASE_URL = "https://dumps.wikimedia.org/other/mediawiki_content_current/zhwiki"
USER_AGENT = "chinese-wikipedia-dictionary-builder/1.0 (+https://github.com/caocaochan/chinese-wikipedia-dictionary)"

REPO = "caocaochan/chinese-wikipedia-dictionary"
ZIP_NAME = "wikipedia_zh.zip"
INDEX_URL = f"https://raw.githubusercontent.com/{REPO}/main/index.json"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/latest/download/{ZIP_NAME}"

BANK_SIZE = 10000
MAX_HEADWORD_LEN = 16  # Yomitan's default scan length
MAX_SENSES = 10

RE_DISAMBIG = re.compile(
    r"\{\{\s*(?:template:|模板:)?\s*(?:disambig\w*|dab|dis|disambiguation|hndis\w*|geodis|"
    r"shipindex|setindex|[^{}|\n]{0,10}消歧[义義][^{}|\n]{0,10})\s*[|}]",
    re.I,
)
RE_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁤﻿]")
RE_LINK_TARGET = re.compile(r"\[\[([^\[\]|#\n{}]+)")
RE_QUALIFIER = re.compile(r"^(.+?)\s*[（(]([^（）()]+)[）)]$")
RE_DATE_TITLE = re.compile(
    r"^(?:公元前|前)?\d+(?:年代?|世纪|世紀)(?:\d+月(?:\d+日)?)?$|^\d+月\d+日$|^\d+$"
)

_t2s = opencc.OpenCC("t2s")


def to_simplified(s):
    return _t2s.convert(s)


def polish(gloss):
    """Drop a parenthetical that only repeats the subject: 东京（东京）是… -> 东京是…"""
    return re.sub(r"^(.{1,30}?)（\1）", r"\1", gloss)


def norm_title(t):
    t = t.replace("_", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t[:1].upper() + t[1:] if t else t


# ---------------------------------------------------------------------------
# download

def _open(url, start=0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if start:
        req.add_header("Range", f"bytes={start}-")
    return urllib.request.urlopen(req, timeout=120)


def latest_date():
    """Newest dump date whose bzip2 SHA256SUMS exists (it is written once the dump is complete)."""
    with _open(f"{BASE_URL}/") as r:
        listing = r.read().decode("utf-8", "replace")
    dates = sorted(set(re.findall(r'href="(\d{4}-\d{2}-\d{2})/"', listing)), reverse=True)
    for date in dates:
        try:
            with _open(f"{BASE_URL}/{date}/xml/bzip2/SHA256SUMS") as r:
                if r.read().strip():
                    return date
        except urllib.error.HTTPError:
            continue
    sys.exit("no complete zhwiki dump found")


def download(date):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{BASE_URL}/{date}/xml/bzip2"
    with _open(f"{base}/SHA256SUMS") as r:
        sums_text = r.read().decode()
    (DUMP_DIR / "SHA256SUMS").write_text(sums_text)
    sums = dict(reversed(line.split()) for line in sums_text.splitlines() if line.strip())
    for old in DUMP_DIR.glob("zhwiki-*.xml.bz2"):
        if old.name not in sums:
            old.unlink()  # files from an older dump
    for name, digest in sums.items():
        path = DUMP_DIR / name
        if path.exists() and sha256(path) == digest:
            print(f"have {name}", flush=True)
            continue
        print(f"downloading {name}", flush=True)
        fetch(f"{base}/{name}", path)
        if sha256(path) != digest:
            path.unlink()
            sys.exit(f"checksum mismatch for {name}")
    return [DUMP_DIR / n for n in sums]


def fetch(url, path, attempts=8):
    """Download with resume, retrying on dropped connections."""
    path.unlink(missing_ok=True)
    for attempt in range(1, attempts + 1):
        start = path.stat().st_size if path.exists() else 0
        try:
            with _open(url, start) as r, open(path, "ab" if start else "wb") as f:
                if start and r.status != 206:  # server ignored the Range header
                    f.truncate(0)
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"  attempt {attempt} failed: {e!r}", flush=True)
            time.sleep(min(60, 5 * attempt))
    sys.exit(f"could not download {url}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def dump_files():
    files = sorted(DUMP_DIR.glob("zhwiki-*.xml.bz2"))
    if not files:
        sys.exit("no dump files in data/dump; run the download step first")
    return files


# ---------------------------------------------------------------------------
# extract

def extract_file(path):
    """Write <name>.jsonl (articles and redirects) and <name>.links.tsv for one dump file."""
    import bz2

    path = Path(path)
    stem = path.name.removesuffix(".xml.bz2")
    out_path = WORK_DIR / f"{stem}.jsonl"
    links_path = WORK_DIR / f"{stem}.links.tsv"
    links = collections.Counter()
    start = time.time()
    n_pages = n_articles = n_redirects = 0

    with bz2.open(path, "rb") as f, open(out_path, "w", encoding="utf-8") as out:
        context = iterparse(f, events=("start", "end"))
        _, root = next(context)
        ns_uri = root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        T_PAGE, T_TITLE, T_NS, T_REDIRECT = (ns_uri + x for x in ("page", "title", "ns", "redirect"))
        T_TEXT = ns_uri + "text"
        for event, elem in context:
            if event != "end" or elem.tag != T_PAGE:
                continue
            n_pages += 1
            if elem.findtext(T_NS) == "0":
                title = elem.findtext(T_TITLE) or ""
                redirect = elem.find(T_REDIRECT)
                text = ""
                for t in elem.iter(T_TEXT):
                    text = t.text or ""
                if redirect is not None:
                    target = redirect.get("title") or ""
                    out.write(json.dumps({"t": title, "r": target}, ensure_ascii=False) + "\n")
                    n_redirects += 1
                elif text:
                    for target in RE_LINK_TARGET.findall(text):
                        links[target] += 1
                    if not RE_DISAMBIG.search(text) and not re.search(r"[（(]消歧[义義][）)]$", title):
                        try:
                            gloss = lead_gloss(text, title)
                        except Exception as e:  # keep going on odd pages
                            print(f"  {title}: {e!r}", flush=True)
                            gloss = ""
                        if gloss:
                            gloss = polish(to_simplified(gloss))
                            out.write(json.dumps({"t": title, "g": gloss, "n": len(text)}, ensure_ascii=False) + "\n")
                            n_articles += 1
            elem.clear()
            root.clear()
            if n_pages % 500000 == 0:
                print(f"  {stem}: {n_pages:,} pages, {time.time() - start:.0f}s", flush=True)

    with open(links_path, "w", encoding="utf-8") as f:
        for target, count in links.items():
            target = norm_title(target)
            if target:
                f.write(f"{target}\t{count}\n")
    print(f"  {stem}: done, {n_articles:,} articles, {n_redirects:,} redirects, "
          f"{time.time() - start:.0f}s", flush=True)
    return stem


def extract(files):
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for old in WORK_DIR.glob("*"):
        old.unlink()
    with mp.Pool(min(len(files), mp.cpu_count())) as pool:
        for stem in pool.imap_unordered(extract_file, [str(f) for f in files]):
            print(f"extracted {stem}", flush=True)


# ---------------------------------------------------------------------------
# build

def split_title(title):
    title = RE_INVISIBLE.sub("", title).strip()
    m = RE_QUALIFIER.match(title)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2).strip()
    return title, ""


def usable_headword(base):
    return (
        has_cjk(base)
        and len(base) <= MAX_HEADWORD_LEN
        and not RE_DATE_TITLE.match(base)
        and ":" not in base
    )


def reading(word):
    return "".join(lazy_pinyin(word, style=Style.TONE)).replace(" ", "")


def article_url(title):
    """Link to the article in simplified script. Non-ASCII stays unescaped (an IRI) to keep the file small."""
    path = title.replace(" ", "_")
    for ch, esc in (("%", "%25"), ("?", "%3F"), ("#", "%23"), ('"', "%22"), ("<", "%3C"), (">", "%3E")):
        path = path.replace(ch, esc)
    return f"https://zh.wikipedia.org/zh-hans/{path}"


def node(tag, content, kind=None, **extra):
    """Structured-content element; `kind` becomes data-sc-content for styles.css."""
    n = {"tag": tag, "content": content}
    if kind:
        n["data"] = {"content": kind}
    n.update(extra)
    return n


def form_row(simplified, s2t):
    """Traditional / simplified badges, the same header as the HYDCD and chengyu dictionaries."""
    traditional = s2t.convert(simplified)
    badges = [node("span", traditional, "traditional-term")]
    if simplified != traditional:
        badges.append(node("span", simplified, "simplified-term"))
    return node("span", [node("span", badges, "terms-parent")], "first-row-parent")


def headword_forms(simplified, originals, converters):
    forms = {simplified, *originals}
    for conv in converters:
        forms.add(conv.convert(simplified))
    return sorted(forms, key=lambda f: (f != simplified, f))


def build(date, min_links):
    files = sorted(WORK_DIR.glob("*.jsonl"))
    if not files:
        sys.exit("nothing in data/work; run the extract step first")
    start = time.time()

    def log(msg):
        print(f"{msg} ({time.time() - start:.0f}s)", flush=True)

    articles = {}  # title -> (gloss, size)
    redirects = {}  # title -> target
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if "r" in rec:
                    redirects[rec["t"]] = rec["r"]
                else:
                    gloss = rec["g"]
                    base = split_title(rec["t"])[0]
                    if gloss.startswith(base + base):  # e.g. (E)-二苯基乙烯(E)-二苯基乙烯是…
                        gloss = gloss[len(base):]
                    articles[rec["t"]] = (gloss, rec["n"])
    log(f"loaded {len(articles):,} articles, {len(redirects):,} redirects")

    # zhwiki resolves links between script variants automatically, so also
    # match titles by their simplified form.
    by_simplified = {}
    for title in articles:
        by_simplified.setdefault(to_simplified(title), title)

    def resolve(title, hops=3):
        for _ in range(hops):
            if title in articles:
                return title
            if title in redirects:
                target = redirects[title]
                if "#" in target:
                    return None  # section redirects would show the wrong gloss
                title = norm_title(target)
                continue
            return by_simplified.get(to_simplified(title))
        return None

    inlinks = collections.Counter()
    for path in WORK_DIR.glob("*.links.tsv"):
        with open(path, encoding="utf-8") as f:
            for line in f:
                target, _, count = line.rstrip("\n").rpartition("\t")
                inlinks[target] += int(count)
    linked = collections.Counter()
    for target, count in inlinks.items():
        art = target if target in articles else resolve(target)
        if art:
            linked[art] += count
    del inlinks
    log("counted links")

    # headword (simplified) -> {"forms": set, "senses": {article: (rank, text)}}
    groups = {}

    def add(base, qualifier, article):
        key = to_simplified(base)
        g = groups.setdefault(key, {"forms": set(), "senses": {}})
        g["forms"].add(base)
        gloss = articles[article][0]
        text = f"({to_simplified(qualifier)}) {gloss}" if qualifier else gloss
        # Unqualified titles (北京, or a redirect 北京 -> 北京市) are the primary
        # topic and come first; then the most-linked articles.
        rank = (1 if qualifier else 0, -linked[article], -articles[article][1])
        old = g["senses"].get(article)
        if old is None or rank < old[0]:
            g["senses"][article] = (rank, text)

    for title in articles:
        if linked[title] < min_links:
            continue
        base, qualifier = split_title(title)
        if usable_headword(base):
            add(base, qualifier, title)

    for title in redirects:
        art = resolve(title)
        if not art or linked[art] < min_links:
            continue
        base, qualifier = split_title(title)
        if usable_headword(base):
            add(base, qualifier, art)
    del redirects, by_simplified, linked, articles
    log(f"grouped {len(groups):,} headwords")

    index = make_index(len(groups), date)
    converters = [opencc.OpenCC(c) for c in ("s2t", "s2tw", "s2hk")]
    s2t = converters[0]
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DIST_DIR / ZIP_NAME
    n_entries = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("index.json", json.dumps(index, ensure_ascii=False, indent=2))
        z.writestr("source_attribution.txt", ATTRIBUTION.format(date=date))
        z.write(ROOT / "styles.css", "styles.css")  # shared with the HYDCD and chengyu dictionaries
        bank, bank_no = [], 0

        def flush():
            nonlocal bank, bank_no
            bank_no += 1
            z.writestr(f"term_bank_{bank_no}.json", json.dumps(bank, ensure_ascii=False, separators=(",", ":")))
            bank = []

        for seq, key in enumerate(sorted(groups), start=1):
            g = groups.pop(key)
            senses = sorted(g["senses"].items(), key=lambda kv: kv[1][0])[:MAX_SENSES]
            sense_list = {
                "tag": "ol",
                "content": [
                    {"tag": "li", "content": [
                        text + " ",
                        {"tag": "a", "href": article_url(article), "content": "维基百科"},
                    ]}
                    for article, (_, text) in senses
                ],
            }
            glossary = [{
                "type": "structured-content",
                "content": node("span", [form_row(key, s2t), sense_list], "wikipedia-entry", lang="zh-Hans"),
            }]
            pinyin = reading(key)
            for form in headword_forms(key, g["forms"], converters):
                bank.append([form, pinyin, "", "", 0, glossary, seq, ""])
                n_entries += 1
                if len(bank) >= BANK_SIZE:
                    flush()
            if seq % 500000 == 0:
                log(f"  {seq:,} headwords")
        if bank:
            flush()
    n_headwords = seq
    log(f"wrote {zip_path}: {n_headwords:,} headwords, {n_entries:,} entries")

    write_repo_files(index, date, n_headwords, n_entries, zip_path.stat().st_size)


def make_index(n_headwords, date):
    return {
        "title": "Wikipedia",
        "revision": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "format": 3,
        "sequenced": True,
        "sourceLanguage": "zh",
        "targetLanguage": "zh",
        "author": "Wikipedia contributors",
        "isUpdatable": True,
        "indexUrl": INDEX_URL,
        "downloadUrl": DOWNLOAD_URL,
        "url": f"https://github.com/{REPO}",
        "description": (
            f"{n_headwords:,} Chinese Wikipedia article titles with the first sentences of each "
            f"article as a simplified Chinese gloss, from the zhwiki dump of {date}. "
            "Simplified and traditional lookup forms; no frequency data."
        ),
        "attribution": (
            "Text from Chinese Wikipedia (https://zh.wikipedia.org/), by Wikipedia contributors, "
            "licensed under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). "
            "Article leads were shortened and converted to simplified Chinese."
        ),
    }


def write_repo_files(index, date, n_headwords, n_entries, zip_size):
    """index.json and source_attribution.txt at the repo root, README stats, release notes."""
    (ROOT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "source_attribution.txt").write_text(ATTRIBUTION.format(date=date), encoding="utf-8")

    stats = (
        f"- {n_headwords:,} headwords from the zhwiki dump of {date}, "
        f"{n_entries:,} simplified and traditional lookup entries\n"
        f"- Yomitan package: dictionary format 3, {zip_size / 1e6:.0f} MB"
    )
    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        text = re.sub(r"(<!-- stats:start -->\n).*?(\n<!-- stats:end -->)",
                      lambda m: m.group(1) + stats + m.group(2), text, flags=re.S)
        readme.write_text(text, encoding="utf-8")

    notes = (
        f"Chinese Wikipedia dictionary built from the zhwiki dump of {date}.\n\n{stats}\n\n"
        f"Import `{ZIP_NAME}` into Yomitan, or add this update URL in Yomitan:\n"
        f"`{INDEX_URL}`\n\n"
        "Text from Chinese Wikipedia by Wikipedia contributors, CC BY-SA 4.0.\n"
    )
    (DIST_DIR / "release_notes.md").write_text(notes, encoding="utf-8")


ATTRIBUTION = """Source attribution

Chinese Wikipedia (中文维基百科)
https://zh.wikipedia.org/
Text by Wikipedia contributors, licensed under the Creative Commons
Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0):
https://creativecommons.org/licenses/by-sa/4.0/

Source: zhwiki MediaWiki Content Current dump of {date}
https://dumps.wikimedia.org/other/mediawiki_content_current/zhwiki/

Changes: each definition is the opening one or two sentences of the
article's lead section, with markup removed, shortened to about 150
characters, and converted to simplified Chinese. Redirect titles are
listed as extra headwords for the article they point to. Each definition
links to its full article on Chinese Wikipedia. This dictionary is
distributed under the same CC BY-SA 4.0 license.
"""


# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["latest-date", "download", "extract", "build", "all"])
    p.add_argument("--date", default="latest", help="dump date (YYYY-MM-DD) or 'latest'")
    p.add_argument("--min-links", type=int, default=0,
                   help="skip articles with fewer incoming links from other articles")
    args = p.parse_args()

    date = args.date
    if args.step == "latest-date" or date == "latest":
        date = latest_date()
        if args.step == "latest-date":
            print(date)
            return
        print(f"using dump {date}", flush=True)

    if args.step in ("download", "all"):
        download(date)
    if args.step in ("extract", "all"):
        extract(dump_files())
    if args.step in ("build", "all"):
        build(date, args.min_links)


if __name__ == "__main__":
    main()
