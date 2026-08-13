# Personal website — Benedikt Brückner

Static single-page site. No framework, no build toolchain beyond one Python
script, no runtime dependencies in the browser.

## Layout

```
publications.bib     source of truth for the publication list
templates/index.html the page, with a <!--PUBLICATIONS--> placeholder
assets/              favicon, and portrait.jpg if you add one
build.py             publications.bib + template -> docs/index.html
docs/                generated output — this is what gets served
```

`docs/` is generated. Don't edit it; edit the template or the `.bib` and
rebuild. It **is** committed, because GitHub Pages serves from `/docs`.

## Build

```bash
uv run python build.py
```

## Preview locally

```bash
uv run python -m http.server 4321 --directory docs
```

## Adding a publication

Add an entry to `publications.bib` and rebuild. Nothing else to touch — the
list, the year grouping, the DOI/arXiv buttons and the BibTeX panels are all
generated from it.

Follow the format policy in the file header: full given names (never
initials), DOI and pages where known, acronyms braced. That file is written
for *other people's* bibliographies, so it errs towards completeness — the
opposite of the house style in the papers repo.

Three non-standard fields drive the page and are stripped from the BibTeX the
copy buttons emit, so nobody pastes them into a real `.tex`:

| field | purpose |
| --- | --- |
| `shortvenue` | human-readable venue label (`AAAI 2025`) |
| `status` | `preprint` or `workshop` renders a badge |
| `equal` | 1-indexed authors sharing the equal-contribution asterisk |

### Work under review — keep it out of this repository

`publications.bib` is committed to a **public** repository. It is readable by
anyone, indexed by GitHub search and mirrored by code-search sites, whatever
the deployed page happens to show. Some venues object to authors stating
publicly that a paper is under submission with them, and leaving it off the
rendered page does nothing about the source file sitting next to it.

So under-review work does not go in this file at all. It belongs in the CV,
which is not published. `build.py` **refuses to build** on finding an entry
with `status = {under-review}`, rather than quietly skipping it — a silent
skip would protect the page while leaving the actual exposure untouched, and
would invite exactly the wrong kind of confidence.

Add the paper once it is accepted, with its real venue and DOI.

## Adding a photo

Drop it at `assets/portrait.jpg` (or `.png`, `.webp`, `.avif`) and rebuild.
The header lays out correctly with or without it — the generator emits an
`<img>` only when the file exists. Roughly 4:5 portrait crop, at least 300 px
wide.

## Deployment

`docs/` is committed, so there is nothing for the host to build — both
options below simply serve the committed files.

**Cloudflare Pages.** Connect the GitHub repo, leave the *build command*
empty and set the *build output directory* to `docs`. Cloudflare serves what
is committed and never runs Python, so `uv` and the dependencies are only
ever needed locally. Cloudflare Pages also works with a **private**
repository, which is the option to take if you would rather the source not be
public at all.

**GitHub Pages**, as an alternative: repository settings → Pages → *Deploy
from a branch*, branch `main`, folder `/docs`.

> **Rebuild before you push.** Nothing rebuilds the page for you. Editing
> `templates/index.html` or `publications.bib` and pushing without running
> `uv run python build.py` first leaves the live site silently unchanged.

## Notes on two deliberate choices

**The publication list is static HTML, not JavaScript.** Crawlers — Google
Scholar included — index what the server sends. A JS-built list looks like an
empty page to them. JavaScript on the page only adds the fold and the copy
buttons.

**The email address is assembled at runtime** and appears nowhere in the
served HTML, not even in an `href`. That defeats bulk regex harvesting; it
does not defeat a scraper that runs JavaScript, and nothing client-side
would. Without JS the `[at]`/`[dot]` form stays readable. Consider also
publishing a rotatable alias rather than a real mailbox.

Note that this repository is public, so the base64 in the template is
trivially readable by anyone who looks at the source. The obfuscation is
aimed at bulk scrapers of the rendered page, not at a person — it was never
going to hide the address from someone who wants it.
