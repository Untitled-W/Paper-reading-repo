from pathlib import Path
import time

from common import (
    ARXIV_PDF_URLS,
    build_arg_parser,
    format_bytes,
    format_rate,
    format_seconds,
    normalize_arxiv_id,
    print_banner,
    stream_download,
)


def main() -> int:
    parser = build_arg_parser("Download arXiv PDF into survey directory.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    args = parser.parse_args()

    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    pdf_path = survey_dir / "source" / f"{arxiv_id}.pdf"

    total_start = time.perf_counter()
    errors = []
    size = 0
    elapsed = 0.0
    for template in ARXIV_PDF_URLS:
        try:
            size, elapsed = stream_download(template.format(arxiv_id=arxiv_id), pdf_path)
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{template}: {exc}")
    else:
        raise RuntimeError("PDF download failed across all candidates:\n" + "\n".join(errors))
    total_elapsed = time.perf_counter() - total_start

    print_banner(f"STEP 1.2 COMPLETE - {arxiv_id}")
    print(f"pdf: {pdf_path}")
    print(f"size: {format_bytes(size)}")
    print(f"download: {format_seconds(elapsed)}")
    print(f"speed: {format_rate(size, elapsed)}")
    print(f"total: {format_seconds(total_elapsed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
