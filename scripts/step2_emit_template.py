from pathlib import Path
import time

from common import (
    build_arg_parser,
    collect_bib_files,
    normalize_arxiv_id,
    parse_bib_entries,
    print_banner,
    read_json,
    stable_ref_id,
    write_json,
)


def main() -> int:
    parser = build_arg_parser("Parse bib files and emit citation_semantic_abbrevs.json template.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    args = parser.parse_args()

    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    latex_root = survey_dir / ".arxiv_latex_build" / "latex_arxiv_raw"
    output_path = survey_dir / "citation_semantic_abbrevs.json"
    existing = read_json(output_path, {})

    total_start = time.perf_counter()
    parse_start = time.perf_counter()
    records = {}
    for bib_file in collect_bib_files(latex_root):
        entries = parse_bib_entries(bib_file.read_text(encoding="utf-8", errors="ignore"))
        for bib_key, payload in entries.items():
            fields = payload["fields"]
            bib_title = fields.get("title", bib_key)
            ref_id, ref_id_type = stable_ref_id(fields, bib_key, bib_title)
            eprint = fields.get("eprint", "")
            records[bib_key] = {
                "bib_title": bib_title,
                "cite_short": existing.get(bib_key, {}).get("cite_short", ""),
                "ref_id": ref_id,
                "ref_id_type": ref_id_type,
                "url": fields.get("url", ""),
                "eprint": eprint,
                "status": existing.get(bib_key, {}).get("status", "todo"),
            }
    parse_elapsed = time.perf_counter() - parse_start

    write_start = time.perf_counter()
    ordered = dict(sorted(records.items()))
    write_json(output_path, ordered)
    write_elapsed = time.perf_counter() - write_start
    total_elapsed = time.perf_counter() - total_start

    print_banner(f"STEP 2 COMPLETE - {arxiv_id}")
    print(f"template: {output_path}")
    print(f"bib_entries: {len(ordered)}")
    print(f"parse: {parse_elapsed:.2f}s")
    print(f"write: {write_elapsed:.2f}s")
    print(f"total: {total_elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
