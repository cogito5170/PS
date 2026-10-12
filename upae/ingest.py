"""Universal ingestion layer: connectors turn files into normalised *document
records*.  Acquisition is separated from analysis: connectors never interpret
claims, they only read text and metadata that is actually present.

Document record (dict): key, kind, text | pages, metadata fields (see
eval/DATASET_FORMAT.md §2), plus ``connector`` and optional ``access_status``.
Missing metadata stays missing — connectors never invent authors or dates.
"""
from __future__ import annotations

import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

META_KEYS = {
    "key", "kind", "title", "author", "publisher", "published", "url", "canonical_url",
    "doi", "isbn", "language", "pages", "text", "reproduces", "translation_of", "cites",
    "retracted", "basis", "synthetic", "license", "version", "retrieved_at", "ocr",
}


class Connector:
    name = "base"
    suffixes: tuple[str, ...] = ()

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def load(self, path: Path) -> list[dict]:  # pragma: no cover - interface
        raise NotImplementedError


def _clean(doc: dict, connector: str, default_key: str) -> dict:
    out = {k: v for k, v in doc.items() if k in META_KEYS and v not in (None, "")}
    extra = {k: v for k, v in doc.items() if k not in META_KEYS}
    out.setdefault("key", default_key)
    out["connector"] = connector
    if extra:
        out["metadata"] = extra
    return out


class JsonConnector(Connector):
    name = "json"
    suffixes = (".json", ".jsonl")

    def load(self, path: Path) -> list[dict]:
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".jsonl":
            items = [json.loads(line) for line in raw.splitlines() if line.strip()]
        else:
            data = json.loads(raw)
            items = data.get("documents", data) if isinstance(data, dict) else data
            if isinstance(items, dict):
                items = [items]
        return [_clean(d, self.name, f"{path.stem}#{i}" if len(items) > 1 else path.stem)
                for i, d in enumerate(items)]


_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.lower() in ("true", "false"):
            meta[k.strip()] = v.lower() == "true"
        elif v.startswith("[") and v.endswith("]"):
            meta[k.strip()] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            meta[k.strip()] = v.strip("'\"")
    return meta, text[m.end():]


class TextConnector(Connector):
    name = "text"
    suffixes = (".txt", ".md", ".markdown")

    def load(self, path: Path) -> list[dict]:
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        meta.setdefault("key", path.stem)
        meta["text"] = body
        return [_clean(meta, self.name, path.stem)]


class _HtmlText(HTMLParser):
    BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "td", "figcaption"}
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._depth_skip = 0
        self._in_block = 0
        self._heading: Optional[str] = None
        self.meta: dict = {}
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._depth_skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content")
            mapping = {"author": "author", "article:author": "author",
                       "article:published_time": "published", "date": "published",
                       "og:site_name": "publisher", "dc.publisher": "publisher",
                       "citation_doi": "doi", "dc.identifier": "doi", "og:title": "title"}
            if name in mapping and content:
                self.meta.setdefault(mapping[name], content)
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical" and a.get("href"):
            self.meta["canonical_url"] = a["href"]
        elif tag == "html" and a.get("lang"):
            self.meta["language"] = a["lang"].split("-")[0]
        if tag in self.BLOCK:
            self._flush()
            self._in_block += 1
            if tag.startswith("h") and len(tag) == 2:
                self._heading = tag

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._depth_skip:
            self._depth_skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            if self._heading == tag:
                text = " ".join("".join(self._buf).split())
                self._buf = []
                if text:
                    self.blocks.append("# " + text)
                self._heading = None
            else:
                self._flush()
            self._in_block = max(0, self._in_block - 1)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._depth_skip and self._in_block:
            self._buf.append(data)

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        if text:
            self.blocks.append(text)
        self._buf = []


def html_to_text(html: str) -> tuple[str, dict]:
    p = _HtmlText()
    p.feed(html)
    p._flush()
    meta = dict(p.meta)
    if p.title.strip():
        meta.setdefault("title", " ".join(p.title.split()))
    return "\n\n".join(p.blocks), meta


class HtmlConnector(Connector):
    name = "html"
    suffixes = (".html", ".htm", ".xhtml")

    def load(self, path: Path) -> list[dict]:
        text, meta = html_to_text(path.read_text(encoding="utf-8", errors="replace"))
        meta["text"] = text
        meta.setdefault("kind", "web")
        if "canonical_url" in meta:
            meta.setdefault("url", meta["canonical_url"])
        return [_clean(meta, self.name, path.stem)]


class EpubConnector(Connector):
    """EPUB = zip of XHTML chapters. Chapters become sections (no page numbers:
    EPUB has none, and we do not invent them)."""
    name = "epub"
    suffixes = (".epub",)

    def load(self, path: Path) -> list[dict]:
        pages = []
        meta: dict = {"kind": "book"}
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm")))
            for n in z.namelist():
                if n.lower().endswith(".opf"):
                    opf = z.read(n).decode("utf-8", "replace")
                    for tag, key in (("dc:title", "title"), ("dc:creator", "author"),
                                     ("dc:publisher", "publisher"), ("dc:date", "published"),
                                     ("dc:language", "language")):
                        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", opf, re.S)
                        if m:
                            meta[key] = m.group(1).strip()
            for n in names:
                text, _ = html_to_text(z.read(n).decode("utf-8", "replace"))
                if text.strip():
                    pages.append({"page": None, "section": Path(n).stem, "text": text})
        meta["pages"] = pages
        return [_clean(meta, self.name, path.stem)]


class PdfConnector(Connector):
    """Uses ``pypdf`` when installed; otherwise records the document as
    unsupported rather than guessing its content."""
    name = "pdf"
    suffixes = (".pdf",)

    def load(self, path: Path) -> list[dict]:
        try:
            import logging

            from pypdf import PdfReader  # type: ignore
            logging.getLogger("pypdf").setLevel(logging.ERROR)
        except ImportError:
            return [{"key": path.stem, "kind": "other", "text": "", "connector": self.name,
                     "access_status": "unsupported_format",
                     "access_note": "PDF text extraction requires the optional 'pypdf' package"}]
        reader = PdfReader(str(path))
        pages = [{"page": i + 1, "text": (pg.extract_text() or "")} for i, pg in enumerate(reader.pages)]
        meta = {"kind": "paper", "pages": pages}
        info = reader.metadata or {}
        if info.get("/Title"):
            meta["title"] = str(info["/Title"])
        if info.get("/Author"):
            meta["author"] = str(info["/Author"])
        return [_clean(meta, self.name, path.stem)]


CONNECTORS: list[Connector] = [JsonConnector(), TextConnector(), HtmlConnector(),
                               EpubConnector(), PdfConnector()]


def load_path(path: str | Path, connectors: Optional[list[Connector]] = None) -> list[dict]:
    """Load every supported file under ``path`` (file or directory), sorted for
    deterministic identifiers.  Unsupported files are returned as unavailable
    documents so the limitation is reported, not silently dropped."""
    connectors = connectors or CONNECTORS
    root = Path(path)
    files = sorted(p for p in (root.rglob("*") if root.is_dir() else [root]) if p.is_file())
    docs: list[dict] = []
    for f in files:
        if f.name.startswith("."):
            continue
        conn = next((c for c in connectors if c.accepts(f)), None)
        if conn is None:
            docs.append({"key": f.stem, "kind": "other", "text": "", "connector": "none",
                         "access_status": "unsupported_format",
                         "access_note": f"no connector for '{f.suffix}' files"})
            continue
        try:
            docs.extend(conn.load(f))
        except Exception as exc:  # unreadable file: report, never guess its content
            docs.append({"key": f.stem, "kind": "other", "text": "", "connector": conn.name,
                         "access_status": "unavailable",
                         "access_note": f"{conn.name} connector could not read the file: "
                                        f"{type(exc).__name__}: {exc}"})
    return docs


# Registry of remote connectors (acquisition).  None ship enabled in the MVP; each
# must implement robots/terms/rate-limit checks before being registered.
REMOTE_CONNECTORS: dict[str, Callable[..., list[dict]]] = {}
