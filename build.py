#!/usr/bin/env python
"""Build the site: publications.bib + templates/index.html -> docs/index.html.

The publication list is rendered as STATIC HTML at build time, not by
JavaScript in the browser. That matters: Google Scholar and other crawlers
index what the server sends, and a JS-built list looks like an empty page to
them. JavaScript on the page only adds the fold and the copy buttons.

Run:  uv run python build.py
"""
from __future__ import annotations

import html
import re
import shutil
import sys
import textwrap
from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser

ROOT = Path(__file__).parent
BIB = ROOT / "publications.bib"
TEMPLATE = ROOT / "templates" / "index.html"
ASSETS = ROOT / "assets"
OUT_DIR = ROOT / "docs"          # GitHub Pages can serve straight from /docs
OUT = OUT_DIR / "index.html"

MY_NAME = "Brückner"

# Fields build.py uses for display but that must never reach a visitor's
# clipboard, since they are not real BibTeX.
DISPLAY_ONLY = {"shortvenue", "status", "equal"}
BIB_META = {"ID", "ENTRYTYPE"}

# bibtexparser lowercases every field name, so match on lowercase here...
FIELD_ORDER = [
    "author", "editor", "title", "booktitle", "journal", "howpublished",
    "series", "volume", "number", "pages", "publisher", "year",
    "doi", "url", "eprint", "archiveprefix", "primaryclass", "note",
]
# ...and restore the conventional camelCase when writing it back out. BibTeX
# field names are case-insensitive, but `archiveprefix` looks like a typo.
CANONICAL_CASE = {"archiveprefix": "archivePrefix", "primaryclass": "primaryClass"}

BADGES = {
    "preprint": "Preprint",
    "workshop": "Workshop",
}

# publications.bib is committed to a PUBLIC repository, so simply keeping
# under-review work off the rendered page is not enough — the source file is
# readable by anyone regardless of what gets deployed. Excluding such entries
# at build time would protect the page while leaving the real exposure
# untouched, and would invite false confidence. So the build refuses outright:
# the entry has to leave the file. Under-review work belongs in the CV.
FORBIDDEN_STATUS = {"under-review"}

# Within a single year, order by how established the work is — mirroring the
# grouping in the CV: published venue, then preprint, then workshop. Sorting
# is stable, so ties keep the order given in the .bib. This beats relying on
# file position, which would put any newly appended entry last inside its year.
STATUS_RANK = {"": 0, "preprint": 1, "workshop": 2}

# ── LaTeX -> Unicode ────────────────────────────────────────────────────────
ACCENTS = {
    '"': {"a": "ä", "e": "ë", "i": "ï", "o": "ö", "u": "ü", "y": "ÿ",
          "A": "Ä", "E": "Ë", "I": "Ï", "O": "Ö", "U": "Ü"},
    "'": {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "y": "ý",
          "c": "ć", "n": "ń", "s": "ś", "z": "ź",
          "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"},
    "`": {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù",
          "A": "À", "E": "È", "I": "Ì", "O": "Ò", "U": "Ù"},
    "^": {"a": "â", "e": "ê", "i": "î", "o": "ô", "u": "û",
          "A": "Â", "E": "Ê", "I": "Î", "O": "Ô", "U": "Û"},
    "~": {"a": "ã", "n": "ñ", "o": "õ", "A": "Ã", "N": "Ñ", "O": "Õ"},
    "c": {"c": "ç", "s": "ş", "C": "Ç", "S": "Ş"},
    "v": {"c": "č", "s": "š", "z": "ž", "r": "ř", "C": "Č", "S": "Š", "Z": "Ž"},
}
SUPS = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
        "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻",
        "n": "ⁿ", "i": "ⁱ"}

# matches \"u  \"{u}  {\"u}  {\"{u}}
_ACC_RE = re.compile(r"\{?\\([\"'`^~cv])\s*\{?([A-Za-z])\}?\}?")
_SUP_RE = re.compile(r"\\textsuperscript\s*\{([^}]*)\}")


def delatex(s: str, *, dashes: bool = False) -> str:
    """LaTeX source -> plain Unicode text, for display on the page."""
    if not s:
        return ""
    s = _ACC_RE.sub(lambda m: ACCENTS.get(m.group(1), {}).get(m.group(2), m.group(2)), s)
    s = re.sub(r"\{?\\ss\}?", "ß", s)
    s = _SUP_RE.sub(lambda m: "".join(SUPS.get(c, c) for c in m.group(1)), s)
    s = re.sub(r"\\(?:emph|textit|textbf|text)\s*\{([^}]*)\}", r"\1", s)
    for esc, plain in (("\\&", "&"), ("\\_", "_"), ("\\%", "%"),
                       ("\\$", "$"), ("\\#", "#"), ("~", " ")):
        s = s.replace(esc, plain)
    if dashes:
        s = s.replace("--", "–")
    s = s.replace("{", "").replace("}", "")
    return " ".join(s.split())


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def split_authors(raw: str) -> list[str]:
    """Split a BibTeX author field, normalising 'Last, First' to 'First Last'."""
    out = []
    for name in re.split(r"\s+and\s+", " ".join(raw.split())):
        name = name.strip()
        if not name:
            continue
        if "," in name:
            last, _, first = name.partition(",")
            name = f"{first.strip()} {last.strip()}".strip()
        out.append(name)
    return out


# ── BibTeX re-serialisation ─────────────────────────────────────────────────
def render_bibtex(entry: dict) -> str:
    """Re-emit an entry with standard fields only, wrapped and aligned.

    Display-only fields are dropped so nobody pastes `shortvenue` into their
    bibliography. LaTeX escaping is preserved verbatim — this is meant to be
    copied into a real .tex project.
    """
    keys = [k for k in FIELD_ORDER if entry.get(k)]
    keys += sorted(k for k in entry
                   if k not in FIELD_ORDER and k not in DISPLAY_ONLY and k not in BIB_META
                   and entry.get(k))
    lines = [f"@{entry['ENTRYTYPE']}{{{entry['ID']},"]
    for name in keys:
        value = " ".join(entry[name].split())
        # width 14, not 13: `archivePrefix` is exactly 13 characters and would
        # otherwise butt straight up against the `=`.
        prefix = f"  {CANONICAL_CASE.get(name, name):<14}= {{"
        body = textwrap.fill(
            value, width=78,
            initial_indent=prefix, subsequent_indent=" " * len(prefix),
            break_long_words=False, break_on_hyphens=False,
        )
        lines.append(body + "},")
    lines.append("}")
    return "\n".join(lines)


# ── HTML rendering ──────────────────────────────────────────────────────────
def title_link(entry: dict) -> str | None:
    if entry.get("doi"):
        return "https://doi.org/" + delatex(entry["doi"])
    if entry.get("url"):
        return delatex(entry["url"])
    if entry.get("eprint"):
        return "https://arxiv.org/abs/" + delatex(entry["eprint"])
    return None


def render_pub(entry: dict) -> str:
    title = esc(delatex(entry["title"]))
    equal = {int(i) for i in entry.get("equal", "").replace(" ", "").split(",") if i}

    names = []
    for idx, raw in enumerate(split_authors(entry["author"]), start=1):
        name = esc(delatex(raw))
        star = "<sup>*</sup>" if idx in equal else ""
        if MY_NAME in delatex(raw):
            names.append(f'<span class="me">{name}</span>{star}')
        else:
            names.append(f"{name}{star}")
    authors = ", ".join(names)

    venue = esc(delatex(entry.get("shortvenue") or entry.get("booktitle")
                        or entry.get("journal") or entry.get("howpublished") or ""))
    status = entry.get("status", "")
    if status in BADGES:
        venue += f' <span class="badge {esc(status)}">{esc(BADGES[status])}</span>'

    link = title_link(entry)
    heading = (f'<a class="u" href="{esc(link)}">{title}</a>' if link else title)

    actions = ['<button class="btn" aria-expanded="false" data-bib>BibTeX</button>']
    if entry.get("doi"):
        actions.append(f'<a class="btn" href="https://doi.org/{esc(delatex(entry["doi"]))}">DOI</a>')
    if entry.get("eprint"):
        actions.append(f'<a class="btn" href="https://arxiv.org/abs/{esc(delatex(entry["eprint"]))}">arXiv</a>')
    actions.append('<button class="btn" data-copy>Copy</button>')
    actions.append('<span class="copied">Copied</span>')

    bib = esc(render_bibtex(entry))
    return f"""      <article class="pub">
        <h3 class="pub-title">{heading}</h3>
        <div class="authors">{authors}</div>
        <div class="venue">{venue}</div>
        <div class="actions">{"".join(actions)}</div>
        <div class="bib"><div><pre>{bib}</pre></div></div>
      </article>"""


def render_publications(entries: list[dict]) -> str:
    entries = sorted(entries, key=lambda e: (-int(e["year"]),
                                             STATUS_RANK.get(e.get("status", ""), 0)))
    any_equal = any(e.get("equal") for e in entries)

    out = []
    if any_equal:
        out.append('    <p class="footnote">* equal contribution</p>')
    current = None
    for e in entries:
        if e["year"] != current:
            if current is not None:
                out.append("    </div>")
            current = e["year"]
            out.append('    <div class="yeargroup">')
            out.append(f'      <div class="year">{esc(current)}</div>')
        out.append(render_pub(e))
    if current is not None:
        out.append("    </div>")
    return "\n".join(out)


def find_portrait() -> Path | None:
    for ext in ("jpg", "jpeg", "png", "webp", "avif"):
        for cand in (ASSETS / f"portrait.{ext}", ASSETS / f"portrait.{ext.upper()}"):
            if cand.exists():
                return cand
    return None


def main() -> int:
    if not BIB.exists() or not TEMPLATE.exists():
        print(f"missing {BIB if not BIB.exists() else TEMPLATE}", file=sys.stderr)
        return 1

    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    with BIB.open(encoding="utf-8") as f:
        db = bibtexparser.load(f, parser)
    if not db.entries:
        print("no entries parsed from publications.bib", file=sys.stderr)
        return 1

    for e in db.entries:
        for field in ("author", "title", "year"):
            if not e.get(field):
                print(f"{e.get('ID')}: missing {field}", file=sys.stderr)
                return 1

    template = TEMPLATE.read_text(encoding="utf-8")
    if "<!--PUBLICATIONS-->" not in template:
        print("template has no <!--PUBLICATIONS--> placeholder", file=sys.stderr)
        return 1

    forbidden = [e for e in db.entries if e.get("status") in FORBIDDEN_STATUS]
    if forbidden:
        print("refusing to build. publications.bib is committed to a public "
              "repository,\nso these entries would be readable there by anyone "
              "even though they would\nnever appear on the page. Remove them "
              "from the file -- the CV is the place\nfor work under review:",
              file=sys.stderr)
        for e in forbidden:
            print(f"    {e['ID']}  (status = {e.get('status')})", file=sys.stderr)
        return 1

    page = template.replace("<!--PUBLICATIONS-->", render_publications(db.entries))

    portrait = find_portrait()
    if portrait:
        img = (f'<img class="portrait" src="assets/{portrait.name}"\n'
               f'           alt="Benedikt Brückner">')
    else:
        img = "<!-- no portrait: drop one at assets/portrait.jpg and rebuild -->"
    page = page.replace("<!--PORTRAIT-->", img)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if ASSETS.exists():
        shutil.copytree(ASSETS, OUT_DIR / "assets", dirs_exist_ok=True)
    OUT.write_text(page, encoding="utf-8")

    years = sorted({e["year"] for e in db.entries}, reverse=True)
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(page):,} bytes)")
    # ASCII only in console output: the Windows console codepage mangles
    # en/em dashes. The generated HTML is written as explicit UTF-8 and is
    # unaffected by this.
    print(f"  {len(db.entries)} publications, {years[-1]}-{years[0]}")
    print(f"  with DOI: {sum(1 for e in db.entries if e.get('doi'))}"
          f"   with arXiv: {sum(1 for e in db.entries if e.get('eprint'))}")
    print(f"  portrait: {portrait.name if portrait else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
