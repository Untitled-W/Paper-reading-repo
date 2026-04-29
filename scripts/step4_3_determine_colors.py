from pathlib import Path
import time

from common import build_arg_parser, normalize_arxiv_id, print_banner, read_json, write_json


def main() -> int:
    parser = build_arg_parser("Determine citation colors based on local vault and global cache.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    args = parser.parse_args()

    start = time.perf_counter()
    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    vault_root = survey_dir.parent.parent
    citation_path = survey_dir / "citation_semantic_abbrevs.json"
    cache_path = vault_root / "paper_database" / "Introduction" / "cite_short_cache.json"
    output_path = survey_dir / ".overlay_build" / "color_mapping.json"

    citations = read_json(citation_path, {})
    cache = read_json(cache_path, {})
    local_ids = {p.name.split("-", 1)[0] for p in (vault_root / "survey_reading").glob("*") if p.is_dir()}

    color_mapping = {}
    for bib_key, record in citations.items():
        ref_id = record.get("ref_id") or record.get("eprint") or bib_key
        if ref_id in local_ids:
            color = "citegreen"
        elif ref_id in cache:
            color = "citeyellow"
        else:
            color = "citered"
        color_mapping[bib_key] = color

    write_json(output_path, color_mapping)
    elapsed = time.perf_counter() - start

    print_banner(f"STEP 4.3 COMPLETE - {arxiv_id}")
    print(f"mapping: {output_path}")
    print(f"entries: {len(color_mapping)}")
    print(f"elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
