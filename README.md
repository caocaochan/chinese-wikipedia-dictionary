# Chinese Wikipedia Dictionary

Chinese Wikipedia article titles with a short definition taken from the opening of each article, for looking up names, places, works, organisations and technical terms that general dictionaries do not cover.

## Yomitan

Download [`wikipedia_zh.zip`](https://github.com/caocaochan/chinese-wikipedia-dictionary/releases/latest/download/wikipedia_zh.zip) and import it from Yomitan's **Dictionaries** settings.

For automatic updates, add this stable dictionary index URL in Yomitan:
`https://raw.githubusercontent.com/caocaochan/chinese-wikipedia-dictionary/main/index.json`
The index points to the ZIP attached to the latest GitHub release, so the URL
does not change between releases.

A new release is built automatically on the 5th of each month from the newest complete Wikipedia dump. If no newer dump is out yet, that month is skipped.

## Contents

<!-- stats:start -->
- 2,112,712 headwords from the zhwiki dump of 2026-11-01, 3,952,585 simplified and traditional lookup entries
- Yomitan package: dictionary format 3, 235 MB
<!-- stats:end -->
- Pinyin readings and a simplified Chinese definition: the first one or two sentences of the article, up to about 150 characters
- Simplified and traditional lookup forms, including Taiwan and Hong Kong character variants such as 台灣/臺灣 and 裡/裏
- Redirects are included as headwords, so alternative names, former names and abbreviations find the article they point to (毛主席 shows 毛泽东)
- Articles that share a name are listed as numbered senses: the main article first, then the others by how often Wikipedia links to them, each with its title qualifier in parentheses, e.g. `(越南)` under 东京
- No frequency rankings

Built from the zhwiki [MediaWiki Content Current](https://dumps.wikimedia.org/other/mediawiki_content_history/readme.html) dumps. Disambiguation pages, date and year articles, and titles longer than 16 characters (Yomitan's default scan length) are left out. Definitions are converted to simplified Chinese with OpenCC; readings come from pypinyin and may be wrong for some names. The term data is about 1.6 GB once unpacked, so importing takes a while.

## Building

Requires Python 3 and about 7 GB of disk space for the dump and intermediate files.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python build_dictionary.py all --date latest
```

Steps can be run separately: `latest-date` (prints the newest complete dump), `download` (fetches and checksums the dump into `data/dump`), `extract` (writes glosses, redirects and link counts to `data/work`, one process per dump file) and `build` (writes `dist/wikipedia_zh.zip`, `index.json`, `source_attribution.txt` and the stats above). `--min-links N` leaves out articles with fewer than N incoming links from other articles, for a smaller dictionary.

The [monthly workflow](.github/workflows/monthly-build.yml) runs these steps, attaches the ZIP to a release tagged with the dump date, then commits the new `index.json` so Yomitan's updater sees the new revision. It can also be started by hand from the Actions tab.

## Files

- `index.json` — stable Yomitan update index; use its raw GitHub URL above
- `source_attribution.txt` — attribution and license notes included in the Yomitan package
- `build_dictionary.py` — download, extract and build steps
- `wikitext.py` — turns an article's lead section into a plain-text definition
- `.github/workflows/monthly-build.yml` — monthly build and release
- `README.md` — project and installation notes

## License

Text from [Chinese Wikipedia](https://zh.wikipedia.org/) by Wikipedia contributors, licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The dictionary is distributed under the same license.
