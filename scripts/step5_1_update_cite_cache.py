from pathlib import Path
import time

from common import build_arg_parser, normalize_arxiv_id, now_shanghai, print_banner, read_json, require_filled_citations, write_json


def main() -> int:
    parser = build_arg_parser("Update global cite_short cache from survey output.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    args = parser.parse_args()

    start = time.perf_counter()
    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    vault_root = survey_dir.parent.parent
    citation_path = survey_dir / "citation_semantic_abbrevs.json"
    cache_path = vault_root / "paper_database" / "Introduction" / "cite_short_cache.json"

    citations = read_json(citation_path, {})
    require_filled_citations(citations)
    cache = read_json(cache_path, {})
    added = 0
    updated = 0
    for _, record in citations.items():
        ref_id = record.get("ref_id") or record.get("eprint")
        if not ref_id or not record.get("cite_short"):
            continue
        payload = {
            "ref_id_type": record.get("ref_id_type", ""),
            "bib_title": record.get("bib_title", ""),
            "cite_short": record.get("cite_short", ""),
            "added_time": now_shanghai(),
            "added_by_human": False,
            "source_survey": arxiv_id,
        }
        if ref_id in cache:
            updated += 1
        else:
            added += 1
        cache[ref_id] = payload

    write_json(cache_path, cache)
    elapsed = time.perf_counter() - start

    print_banner(f"STEP 5.1 COMPLETE - {arxiv_id}")
    print(f"cache: {cache_path}")
    print(f"added: {added}")
    print(f"updated: {updated}")
    print(f"elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
