from pathlib import Path
import time

from common import (
    build_arg_parser,
    normalize_arxiv_id,
    now_shanghai,
    print_banner,
    read_json,
    survey_added_time_from_cache,
)


HEADER = "| 入库时间 | arXiv ID | 论文简称 | 标题 | 路径 |"
SEPARATOR = "|---------|----------|---------|------|------|"


def main() -> int:
    parser = build_arg_parser("Add survey to global index.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    parser.add_argument("--cite-short", required=True)
    args = parser.parse_args()

    start = time.perf_counter()
    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    vault_root = survey_dir.parent.parent
    metadata = read_json(survey_dir / "metadata.json", {})
    index_path = vault_root / "paper_database" / "Introduction" / "INDEX.md"
    cache_path = vault_root / "paper_database" / "Introduction" / "cite_short_cache.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_pdf = survey_dir / f"{arxiv_id}_overlay.pdf"
    if not overlay_pdf.exists():
        raise RuntimeError(f"Overlay PDF not found: {overlay_pdf}. Complete Step 4 first.")

    cache = read_json(cache_path, {})
    index_time = survey_added_time_from_cache(cache, arxiv_id) or now_shanghai()
    row = (
        f"| {index_time} | {arxiv_id} | {args.cite_short} | "
        f"{metadata.get('title', '')} | {survey_dir.relative_to(vault_root).as_posix()} |"
    )
    if index_path.exists():
        lines = [line.rstrip("\n") for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        body = [line for line in lines if line not in {HEADER, SEPARATOR} and f"| {arxiv_id} |" not in line]
    else:
        body = []

    content = "\n".join([HEADER, SEPARATOR, row, *body]) + "\n"
    index_path.write_text(content, encoding="utf-8")
    elapsed = time.perf_counter() - start

    print_banner(f"STEP 5.2 COMPLETE - {arxiv_id}")
    print(f"index: {index_path}")
    print(f"row: {row}")
    print(f"elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
