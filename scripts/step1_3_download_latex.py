from pathlib import Path
import tarfile
import tempfile
import time

from common import (
    ARXIV_EPRINT,
    build_arg_parser,
    format_bytes,
    format_rate,
    format_seconds,
    normalize_arxiv_id,
    print_banner,
    stream_download,
)


def main() -> int:
    parser = build_arg_parser("Download and extract arXiv source into survey directory.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    args = parser.parse_args()

    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    raw_dir = survey_dir / ".arxiv_latex_build" / "latex_arxiv_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    archive_path = Path(tempfile.gettempdir()) / f"{arxiv_id.replace('/', '_')}_arxiv_source.tar"
    total_start = time.perf_counter()
    size, download_elapsed = stream_download(ARXIV_EPRINT.format(arxiv_id=arxiv_id), archive_path)

    extract_start = time.perf_counter()
    with tarfile.open(archive_path) as tar:
        tar.extractall(raw_dir)
    extract_elapsed = time.perf_counter() - extract_start
    total_elapsed = time.perf_counter() - total_start

    print_banner(f"STEP 1.3 COMPLETE - {arxiv_id}")
    print(f"latex_dir: {raw_dir}")
    print(f"archive_size: {format_bytes(size)}")
    print(f"download: {format_seconds(download_elapsed)}")
    print(f"extract: {format_seconds(extract_elapsed)}")
    print(f"speed: {format_rate(size, download_elapsed)}")
    print(f"total: {format_seconds(total_elapsed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
