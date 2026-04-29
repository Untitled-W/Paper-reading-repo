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
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


PROXY_URL = "http://127.0.0.1:7890"
ARXIV_APIS = [
    "https://export.arxiv.org/api/query",
    "http://export.arxiv.org/api/query",
]
ARXIV_ABS_URLS = [
    "https://arxiv.org/abs/{arxiv_id}",
    "https://export.arxiv.org/abs/{arxiv_id}",
    "http://export.arxiv.org/abs/{arxiv_id}",
]
ARXIV_PDF_URLS = [
    "https://arxiv.org/pdf/{arxiv_id}",
    "https://arxiv.org/pdf/{arxiv_id}.pdf",
    "https://export.arxiv.org/pdf/{arxiv_id}.pdf",
    "http://export.arxiv.org/pdf/{arxiv_id}.pdf",
]
ARXIV_EPRINT = "https://arxiv.org/e-print/{arxiv_id}"
SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))
CLASH_CONFIG = Path.home() / ".config" / "clash" / "config.yaml"
DEFAULT_CLASH_CANDIDATES = [
    "DIRECT",
    "自动选择",
    "🇭🇰|香港家宽-直连",
    "🇸🇬|新加坡-进阶IEPL 02",
    "🇯🇵|日本原生-直连",
    "🇺🇸|美国-直连",
]
_PROXY_SELECTION_CACHE: dict[str, str] = {}


def ensure_proxy_env() -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.setdefault(key, PROXY_URL)


def parse_simple_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def get_clash_settings() -> dict[str, str]:
    return parse_simple_yaml(CLASH_CONFIG)


def get_proxy_url() -> str:
    settings = get_clash_settings()
    mixed_port = settings.get("mixed-port", "7890")
    return f"http://127.0.0.1:{mixed_port}"


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
        select_best_proxy_for_url(request.full_url)
        proxy_url = get_proxy_url()
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[key] = proxy_url
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def clash_api_get(path: str) -> dict:
    settings = get_clash_settings()
    controller = settings.get("external-controller", "")
    secret = settings.get("secret", "")
    if not controller:
        raise RuntimeError("Clash external-controller is not configured")
    headers = ["-H", f"Authorization: Bearer {secret}"] if secret else []
    result = subprocess.run(
        ["curl.exe", "-s", *headers, f"http://{controller}{path}"],
        text=True,
        encoding="utf-8",
        errors="ignore",
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or f"Clash API GET failed: {path}")
    return json.loads(result.stdout)


def clash_api_put(path: str, payload: dict) -> None:
    settings = get_clash_settings()
    controller = settings.get("external-controller", "")
    secret = settings.get("secret", "")
    if not controller:
        raise RuntimeError("Clash external-controller is not configured")
    headers = ["-H", f"Authorization: Bearer {secret}"] if secret else []
    result = subprocess.run(
        ["curl.exe", "-s", "-X", "PUT", *headers, "-H", "Content-Type: application/json", "-d", json.dumps(payload), f"http://{controller}{path}"],
        text=True,
        encoding="utf-8",
        errors="ignore",
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Clash API PUT failed: {path}")


def probe_url_via_proxy(url: str, proxy_url: str, timeout: int = 12) -> tuple[bool, float, str]:
    start = time.perf_counter()
    result = subprocess.run(
        ["curl.exe", "-L", "--fail", "--silent", "--show-error", "--max-time", str(timeout), "--proxy", proxy_url, "-o", "NUL", url],
        text=True,
        encoding="utf-8",
        errors="ignore",
        capture_output=True,
        check=False,
        timeout=timeout + 2,
    )
    elapsed = time.perf_counter() - start
    ok = result.returncode == 0
    return ok, elapsed, result.stderr.strip()


def rank_clash_candidates(proxies: dict) -> list[str]:
    available = proxies.get("proxies", {})
    ranked: list[tuple[int, int, str]] = []
    for name in DEFAULT_CLASH_CANDIDATES:
        if name not in available:
            continue
        history = available[name].get("history", [])
        nonzero = [item.get("delay", 0) for item in history if item.get("delay", 0) > 0]
        if nonzero:
            ranked.append((0, min(nonzero), name))
        else:
            ranked.append((1, 10**9, name))
    seen = {name for _, _, name in ranked}
    auto_group = available.get("自动选择", {}).get("all", [])
    for name in auto_group:
        if name in seen or name not in available:
            continue
        history = available[name].get("history", [])
        nonzero = [item.get("delay", 0) for item in history if item.get("delay", 0) > 0]
        if nonzero:
            ranked.append((0, min(nonzero), name))
    ranked.sort()
    return [name for _, _, name in ranked[:8]]


def select_best_proxy_for_url(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc or "default"
    if host in _PROXY_SELECTION_CACHE:
        return _PROXY_SELECTION_CACHE[host]
    settings = get_clash_settings()
    controller = settings.get("external-controller", "")
    if not controller:
        return "DIRECT"
    proxy_url = get_proxy_url()
    try:
        proxies = clash_api_get("/proxies")
        global_now = proxies["proxies"].get("GLOBAL", {}).get("now", "")
        candidates = rank_clash_candidates(proxies)
        best_name = ""
        best_elapsed = float("inf")
        for candidate in candidates:
            try:
                clash_api_put("/proxies/GLOBAL", {"name": candidate})
                ok, elapsed, _ = probe_url_via_proxy(url, proxy_url)
                if ok and elapsed < best_elapsed:
                    best_name = candidate
                    best_elapsed = elapsed
            except Exception:
                continue
        if best_name:
            clash_api_put("/proxies/GLOBAL", {"name": best_name})
            _PROXY_SELECTION_CACHE[host] = best_name
            return best_name
        if global_now:
            clash_api_put("/proxies/GLOBAL", {"name": global_now})
    except Exception:
        return "DIRECT"
    return "DIRECT"


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
    try:
        result = subprocess.run(
            ["curl.exe", "-L", "--fail", "--silent", "--show-error", url],
            text=False,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout
        last_error = RuntimeError(result.stderr.decode("utf-8", errors="ignore") or f"curl failed with {result.returncode}")
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
    curl_start = time.perf_counter()
    try:
        result = subprocess.run(
            ["curl.exe", "-L", "--fail", "--silent", "--show-error", "-o", str(output_path), url],
            text=True,
            encoding="utf-8",
            errors="ignore",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode == 0 and output_path.exists():
            elapsed = time.perf_counter() - curl_start
            return output_path.stat().st_size, elapsed
        if output_path.exists():
            output_path.unlink()
        last_error = RuntimeError(result.stderr or f"curl failed with {result.returncode}")
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        if output_path.exists():
            output_path.unlink()
    raise last_error


def _parse_arxiv_atom(payload: str, arxiv_id: str) -> dict:
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


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", value or "")
    return normalize_whitespace(cleaned.replace("&amp;", "&"))


def _parse_arxiv_abs_html(payload: str, arxiv_id: str) -> dict:
    title_match = re.search(r'<meta\s+name="citation_title"\s+content="([^"]+)"', payload, re.IGNORECASE)
    if not title_match:
        raise RuntimeError(f"Could not parse abstract page for {arxiv_id}")
    authors = re.findall(r'<meta\s+name="citation_author"\s+content="([^"]+)"', payload, re.IGNORECASE)
    published_match = re.search(r'<meta\s+name="citation_date"\s+content="([^"]+)"', payload, re.IGNORECASE)
    pdf_match = re.search(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"', payload, re.IGNORECASE)
    abs_match = re.search(r'<meta\s+name="citation_arxiv_id"\s+content="([^"]+)"', payload, re.IGNORECASE)
    abstract_match = re.search(r'<blockquote class="abstract[^"]*">.*?<span class="descriptor">Abstract:</span>(.*?)</blockquote>', payload, re.IGNORECASE | re.DOTALL)
    summary = _strip_html(abstract_match.group(1)) if abstract_match else ""
    entry_id = f"https://arxiv.org/abs/{abs_match.group(1) if abs_match else arxiv_id}"
    links = {"alternate": entry_id}
    if pdf_match:
        links["pdf"] = pdf_match.group(1)
    published = published_match.group(1) if published_match else ""
    return {
        "arxiv_id": arxiv_id,
        "title": _strip_html(title_match.group(1)),
        "summary": summary,
        "authors": [_strip_html(author) for author in authors],
        "published": published,
        "updated": published,
        "entry_id": entry_id,
        "links": links,
    }


def fetch_arxiv_metadata(arxiv_id: str) -> dict:
    query = urllib.parse.urlencode({"search_query": f"id:{arxiv_id}", "start": 0, "max_results": 1})
    errors = []
    for api in ARXIV_APIS:
        try:
            payload = fetch_url(f"{api}?{query}").decode("utf-8", errors="ignore")
            return _parse_arxiv_atom(payload, arxiv_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{api}: {exc}")
    for template in ARXIV_ABS_URLS:
        try:
            payload = fetch_url(template.format(arxiv_id=arxiv_id)).decode("utf-8", errors="ignore")
            return _parse_arxiv_abs_html(payload, arxiv_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{template}: {exc}")
    raise RuntimeError("Metadata fetch failed across all candidates:\n" + "\n".join(errors))


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


def survey_added_time_from_cache(cache: dict, arxiv_id: str) -> str:
    timestamps = sorted(
        value.get("added_time", "")
        for value in cache.values()
        if value.get("source_survey") == arxiv_id and value.get("added_time")
    )
    return timestamps[0] if timestamps else ""


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
