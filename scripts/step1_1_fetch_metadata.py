from pathlib import Path
import time

from common import (
    build_arg_parser,
    fetch_arxiv_metadata,
    normalize_arxiv_id,
    print_banner,
    survey_dir_name,
    write_json,
)


def main() -> int:
    parser = build_arg_parser("Fetch arXiv metadata and create survey directory.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--vault-root", required=True)
    args = parser.parse_args()

    start = time.perf_counter()
    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    vault_root = Path(args.vault_root).resolve()
    metadata = fetch_arxiv_metadata(arxiv_id)

    survey_dir = vault_root / "survey_reading" / survey_dir_name(arxiv_id, metadata["title"])
    (survey_dir / "source").mkdir(parents=True, exist_ok=True)
    (survey_dir / ".arxiv_latex_build").mkdir(parents=True, exist_ok=True)
    (survey_dir / ".overlay_build").mkdir(parents=True, exist_ok=True)

    write_json(survey_dir / "metadata.json", metadata)

    elapsed = time.perf_counter() - start
    print_banner(f"STEP 1.1 COMPLETE - {arxiv_id}")
    print(f"title: {metadata['title']}")
    print(f"authors: {', '.join(metadata['authors'])}")
    print(f"survey_dir: {survey_dir}")
    print(f"elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
