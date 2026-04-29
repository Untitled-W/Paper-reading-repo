from __future__ import annotations

import json
import urllib.parse

from common import (
    ARXIV_APIS,
    ARXIV_EPRINT,
    ARXIV_PDF_URLS,
    build_arg_parser,
    clash_api_get,
    clash_api_put,
    get_proxy_url,
    print_banner,
    probe_url_via_proxy,
    rank_clash_candidates,
)


def main() -> int:
    parser = build_arg_parser("Probe arXiv connectivity across Clash candidates.")
    parser.add_argument("arxiv_id")
    args = parser.parse_args()

    urls = [
        f"{ARXIV_APIS[0]}?{urllib.parse.urlencode({'search_query': f'id:{args.arxiv_id}', 'start': 0, 'max_results': 1})}",
        ARXIV_PDF_URLS[0].format(arxiv_id=args.arxiv_id),
        ARXIV_EPRINT.format(arxiv_id=args.arxiv_id),
    ]
    labels = ["api", "pdf", "eprint"]

    proxies = clash_api_get("/proxies")
    global_now = proxies["proxies"].get("GLOBAL", {}).get("now", "")
    candidates = rank_clash_candidates(proxies)
    proxy_url = get_proxy_url()

    print_banner(f"ARXIV NETWORK PROBE - {args.arxiv_id}")
    print(f"global_before: {global_now}")
    print(f"proxy_url: {proxy_url}")
    print(f"candidates: {', '.join(candidates)}")

    results = []
    for candidate in candidates:
        clash_api_put("/proxies/GLOBAL", {"name": candidate})
        row = {"candidate": candidate}
        for label, url in zip(labels, urls, strict=True):
            ok, elapsed, error = probe_url_via_proxy(url, proxy_url)
            row[label] = {
                "ok": ok,
                "elapsed": round(elapsed, 2),
                "error": error,
            }
        results.append(row)
        status = " ".join(f"{label}={'ok' if row[label]['ok'] else 'fail'}({row[label]['elapsed']}s)" for label in labels)
        print(f"{candidate}: {status}")

    if global_now:
        clash_api_put("/proxies/GLOBAL", {"name": global_now})
        print(f"global_restored: {global_now}")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
