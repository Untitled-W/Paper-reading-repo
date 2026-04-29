import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


PROXY_URL = "http://127.0.0.1:7890"
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF_URLS = [
    "https://arxiv.org/pdf/{arxiv_id}.pdf",
    "https://export.arxiv.org/pdf/{arxiv_id}.pdf",
    "http://export.arxiv.org/pdf/{arxiv_id}.pdf",
]
ARXIV_EPRINT = "https://arxiv.org/e-print/{arxiv_id}"
SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))


def ensure_proxy_env() -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.setdefault(key, PROXY_URL)


def normalize_arxiv_id(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("arxiv:"):
        value = value.split(":", 1)[1]
    return value


def normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def normalize_arxiv_like(value: str) -> str:
    cleaned = normalize_arxiv_id(value)
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", cleaned)
    if match:
        return match.group(1)
    legacy = re.search(r"([a-z\-]+\/\d{7}(?:v\d+)?)", cleaned, re.IGNORECASE)
    if legacy:
        return legacy.group(1)
    return cleaned


def extract_arxiv_id_from_url(url: str) -> str:
    if not url:
        return ""
    patterns = [
        r"arxiv\.org/(?:abs|pdf|e-print)/([^/?#]+)",
        r"export\.arxiv\.org/(?:abs|pdf)/([^/?#]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return normalize_arxiv_like(match.group(1).replace(".pdf", ""))
    return ""


def extract_doi(value: str) -> str:
    if not value:
        return ""
    lowered = value.strip()
    doi_patterns = [
        r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
        r"doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
    ]
    for pattern in doi_patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


def extract_arxiv_id_from_text(text: str) -> str:
    if not text:
        return ""
    candidates = [
        r"arXiv\s*[: ]\s*(\d{4}\.\d{4,5}(?:v\d+)?)",
        r"arXiv\s*[: ]\s*([a-z\-]+/\d{7}(?:v\d+)?)",
        r"arxiv\.org/(?:abs|pdf|e-print)/([^/?#]+)",
    ]
    for pattern in candidates:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_arxiv_like(match.group(1).replace(".pdf", ""))
    return ""


def make_title_fingerprint(title: str) -> str:
    normalized = normalize_whitespace(title).lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"title:{digest}"


def stable_ref_id(fields: dict, bib_key: str, bib_title: str) -> tuple[str, str]:
    eprint = normalize_whitespace(fields.get("eprint", ""))
    archive_prefix = normalize_whitespace(fields.get("archiveprefix", "")).lower()
    url = normalize_whitespace(fields.get("url", ""))
    doi = extract_doi(fields.get("doi", "")) or extract_doi(url)
    searchable_text = " ".join(
        normalize_whitespace(fields.get(name, ""))
        for name in ("journal", "note", "booktitle", "howpublished", "publisher")
    )

    if eprint and (archive_prefix == "arxiv" or re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", eprint) or re.fullmatch(r"[a-z\-]+/\d{7}(?:v\d+)?", eprint, re.IGNORECASE)):
        return normalize_arxiv_like(eprint), "arxiv"

    arxiv_from_url = extract_arxiv_id_from_url(url)
    if arxiv_from_url:
        return arxiv_from_url, "arxiv"

    arxiv_from_text = extract_arxiv_id_from_text(searchable_text)
    if arxiv_from_text:
        return arxiv_from_text, "arxiv"

    if doi:
        return f"doi:{doi}", "doi"

    if url:
        return f"url:{url}", "url"

    return make_title_fingerprint(bib_title or bib_key), "title"


def slugify_title(title: str, max_words: int = 8) -> str:
    ascii_title = title.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", ascii_title.lower())
    return "-".join(words[:max_words]) or "untitled-survey"


def survey_dir_name(arxiv_id: str, title: str) -> str:
    return f"{arxiv_id}-{slugify_title(title)}"


def _open_url(request: urllib.request.Request, timeout: int, use_proxy: bool):
    if use_proxy:
        ensure_proxy_env()
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def fetch_url(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "codex-arxiv-survey-refresh/1.0"},
    )
    last_error = None
    for use_proxy in (True, False):
        try:
            with _open_url(request, timeout=timeout, use_proxy=use_proxy) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise last_error


def stream_download(url: str, output_path: Path, timeout: int = 120) -> tuple[int, float]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "codex-arxiv-survey-refresh/1.0"},
    )
    last_error = None
    for use_proxy in (True, False):
        start = time.perf_counter()
        total_bytes = 0
        try:
            with _open_url(request, timeout=timeout, use_proxy=use_proxy) as response, output_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 128)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total_bytes += len(chunk)
            elapsed = time.perf_counter() - start
            return total_bytes, elapsed
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if output_path.exists():
                output_path.unlink()
    raise last_error


def fetch_arxiv_metadata(arxiv_id: str) -> dict:
    query = urllib.parse.urlencode({"search_query": f"id:{arxiv_id}", "start": 0, "max_results": 1})
    payload = fetch_url(f"{ARXIV_API}?{query}").decode("utf-8")
    root = ET.fromstring(payload)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise RuntimeError(f"No arXiv entry found for {arxiv_id}")
    title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
    summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
    authors = [author.findtext("atom:name", default="", namespaces=ns) for author in entry.findall("atom:author", ns)]
    published = entry.findtext("atom:published", default="", namespaces=ns)
    updated = entry.findtext("atom:updated", default="", namespaces=ns)
    links = {link.attrib.get("title") or link.attrib.get("rel") or "unknown": link.attrib.get("href") for link in entry.findall("atom:link", ns)}
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "summary": summary,
        "authors": authors,
        "published": published,
        "updated": updated,
        "entry_id": entry.findtext("atom:id", default="", namespaces=ns),
        "links": links,
    }


def write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


def format_rate(num_bytes: int, seconds: float) -> str:
    if seconds <= 0:
        return "inf B/s"
    return f"{format_bytes(int(num_bytes / seconds))}/s"


def format_seconds(seconds: float) -> str:
    return f"{seconds:.2f}s"


def print_banner(title: str) -> None:
    line = "=" * 60
    print(line)
    print(title)
    print(line)


def parse_bib_entries(bib_text: str) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    pattern = re.compile(r"@(?P<type>\w+)\s*\{\s*(?P<key>[^,]+),(?P<body>.*?)\n\}", re.DOTALL)
    field_pattern = re.compile(r"(?P<name>\w+)\s*=\s*(?P<value>\{(?:[^{}]|(?:\{[^{}]*\}))*\}|\"(?:[^\"\\]|\\.)*\"|[^,\n]+)", re.DOTALL)
    for match in pattern.finditer(bib_text):
        body = match.group("body")
        fields: dict[str, str] = {}
        for field_match in field_pattern.finditer(body):
            raw_value = field_match.group("value").strip().rstrip(",")
            if raw_value.startswith("{") and raw_value.endswith("}"):
                raw_value = raw_value[1:-1]
            if raw_value.startswith('"') and raw_value.endswith('"'):
                raw_value = raw_value[1:-1]
            fields[field_match.group("name").lower()] = " ".join(raw_value.split())
        entries[match.group("key").strip()] = {"entry_type": match.group("type").lower(), "fields": fields}
    return entries


def collect_bib_files(latex_root: Path) -> list[Path]:
    return sorted(p for p in latex_root.rglob("*.bib") if p.is_file())


def find_main_tex(workdir: Path) -> Path:
    candidates = sorted(workdir.glob("*.tex"))
    if not candidates:
        candidates = sorted(workdir.rglob("*.tex"))
    if not candidates:
        raise FileNotFoundError(f"No .tex files found under {workdir}")
    for candidate in candidates:
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if r"\begin{document}" in text:
            return candidate
    return candidates[0]


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="ignore",
        capture_output=True,
        check=False,
    )


def now_shanghai() -> str:
    return dt.datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def require_filled_citations(data: dict) -> None:
    missing = [key for key, value in data.items() if value.get("status") != "filled" or not value.get("cite_short") or not value.get("ref_id")]
    if missing:
        preview = ", ".join(missing[:10])
        raise RuntimeError(f"Step 3 not complete. Missing filled citations: {preview}")


def inject_header_once(tex_path: Path, snippet: str) -> None:
    text = tex_path.read_text(encoding="utf-8", errors="ignore")
    if snippet.strip() in text:
        return
    marker = r"\begin{document}"
    if marker not in text:
        raise RuntimeError(f"Cannot find {marker} in {tex_path}")
    text = text.replace(marker, snippet + "\n" + marker, 1)
    tex_path.write_text(text, encoding="utf-8")


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    return parser
