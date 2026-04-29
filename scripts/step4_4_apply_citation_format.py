from pathlib import Path
import re
import shutil
import time
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from common import (
    build_arg_parser,
    find_main_tex,
    inject_header_once,
    normalize_arxiv_id,
    print_banner,
    read_json,
    require_filled_citations,
    run_command,
)


HEADER_SNIPPET = r"""
\definecolor{citegreen}{RGB}{200,255,200}
\definecolor{citeyellow}{RGB}{255,255,200}
\definecolor{citered}{RGB}{255,200,200}
\setlength{\fboxsep}{0.5pt}
\renewcommand*{\backref}[1]{}
\renewcommand*{\backrefalt}[4]{%
  \ifcase #1 %
  \or\space {\footnotesize cited on p.~#2}%
  \else\space {\footnotesize cited on pp.~#2}%
  \fi
}
\makeatletter
\newcommand{\overlaybibnum}[1]{%
  \@ifundefined{b@#1}{?}{\csname b@#1\endcsname}%
}
\makeatother
\newcommand{\papercite}[3]{\hyperlink{overlaybib.#3}{\colorbox{#1}{\scriptsize\textbf{[\overlaybibnum{#3}:#2]}}}}
""".strip()


def compact_cite_short(value: str, max_len: int = 8) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "")).strip()
    if len(cleaned) <= max_len:
        return cleaned
    acronym = "".join(ch for ch in cleaned if ch.isupper() or ch.isdigit() or ch == "-")
    acronym = acronym[:max_len].strip("-")
    if len(acronym) >= 3:
        return acronym
    token = cleaned.split()[0]
    token = re.sub(r"[^A-Za-z0-9\-]", "", token)
    if len(token) <= max_len:
        return token
    return token[: max_len - 1] + "~"


def enable_pagebackref(main_tex: Path) -> None:
    text = main_tex.read_text(encoding="utf-8", errors="ignore")
    patterns = [
        (r"\\usepackage\{hyperref\}", r"\\usepackage[pagebackref]{hyperref}"),
        (r"\\usepackage\[(?P<opts>[^\]]*)\]\{hyperref\}", None),
    ]
    if r"\usepackage[pagebackref]{hyperref}" in text or "pagebackref" in text:
        return
    direct = re.sub(patterns[0][0], patterns[0][1], text, count=1)
    if direct != text:
        main_tex.write_text(direct, encoding="utf-8")
        return

    def add_option(match: re.Match) -> str:
        opts = match.group("opts").strip()
        if "pagebackref" in opts:
            return match.group(0)
        if opts:
            return rf"\usepackage[{opts},pagebackref]{{hyperref}}"
        return r"\usepackage[pagebackref]{hyperref}"

    updated = re.sub(patterns[1][0], add_option, text, count=1)
    if updated != text:
        main_tex.write_text(updated, encoding="utf-8")


def ensure_required_table_packages(main_tex: Path) -> None:
    text = main_tex.read_text(encoding="utf-8", errors="ignore")
    if re.search(r"\\usepackage(?:\[[^\]]*\])?\{array\}", text):
        return
    anchor = re.search(r"\\usepackage(?:\[[^\]]*\])?\{makecell\}", text)
    if anchor:
        insert_at = anchor.end()
        text = text[:insert_at] + "\n\\usepackage{array}" + text[insert_at:]
        main_tex.write_text(text, encoding="utf-8")


def patch_bbl_targets(workdir: Path, main_tex: Path) -> None:
    bbl_path = workdir / f"{main_tex.stem}.bbl"
    if not bbl_path.exists():
        return
    text = bbl_path.read_text(encoding="utf-8", errors="ignore")
    updated = re.sub(
        r"\\bibitem\{([^}]+)\}",
        lambda m: rf"\bibitem{{{m.group(1)}}}\hypertarget{{overlaybib.{m.group(1)}}}{{}}",
        text,
    )
    if updated != text:
        bbl_path.write_text(updated, encoding="utf-8")


def replace_citations_outside_table_envs(tex: str, replacer) -> str:
    env_pattern = re.compile(
        r"(\\begin\{(?:table\*?|tabularx?|longtable|array)\}.*?\\end\{(?:table\*?|tabularx?|longtable|array)\})",
        re.DOTALL,
    )
    parts = env_pattern.split(tex)
    for idx in range(0, len(parts), 2):
        parts[idx] = re.sub(r"\\cite\{([^}]+)\}", replacer, parts[idx])
    return "".join(parts)


def replace_table_pages_with_original(survey_dir: Path, arxiv_id: str, overlay_pdf: Path) -> list[int]:
    original_pdf = survey_dir / "source" / f"{arxiv_id}.pdf"
    if not original_pdf.exists():
        return []

    original_reader = PdfReader(str(original_pdf))
    overlay_reader = PdfReader(str(overlay_pdf))
    page_count = min(len(original_reader.pages), len(overlay_reader.pages))
    writer = PdfWriter()
    replaced_pages: list[int] = []

    for page_index in range(page_count):
        original_text = (original_reader.pages[page_index].extract_text() or "").strip()
        first_line = next((line.strip() for line in original_text.splitlines() if line.strip()), "")
        if "TABLE " in original_text[:1200] or first_line.startswith("TABLE "):
            writer.add_page(original_reader.pages[page_index])
            replaced_pages.append(page_index + 1)
        else:
            writer.add_page(overlay_reader.pages[page_index])

    for page_index in range(page_count, len(overlay_reader.pages)):
        writer.add_page(overlay_reader.pages[page_index])

    buffer = BytesIO()
    writer.write(buffer)
    overlay_pdf.write_bytes(buffer.getvalue())
    return replaced_pages


def main() -> int:
    parser = build_arg_parser("Apply citation formatting and build overlay PDF.")
    parser.add_argument("arxiv_id")
    parser.add_argument("--survey-dir", required=True)
    args = parser.parse_args()

    total_start = time.perf_counter()
    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    survey_dir = Path(args.survey_dir).resolve()
    raw_dir = survey_dir / ".arxiv_latex_build" / "latex_arxiv_raw"
    workdir_root = survey_dir / ".overlay_build"
    workdir_root.mkdir(parents=True, exist_ok=True)
    workdir = workdir_root / f"workdir_{int(time.time())}"
    shutil.copytree(raw_dir, workdir)

    citations = read_json(survey_dir / "citation_semantic_abbrevs.json", {})
    require_filled_citations(citations)
    colors = read_json(survey_dir / ".overlay_build" / "color_mapping.json", {})
    main_tex = find_main_tex(workdir)
    enable_pagebackref(main_tex)
    ensure_required_table_packages(main_tex)
    inject_header_once(main_tex, HEADER_SNIPPET)

    rendered = {}

    def replace_match(match: re.Match) -> str:
        keys = [key.strip() for key in match.group(1).split(",") if key.strip()]
        parts = []
        for key in keys:
            record = citations.get(key)
            if not record:
                parts.append(match.group(0))
                continue
            color = colors.get(key, "citered")
            short = compact_cite_short(record["cite_short"])
            rendered[key] = rendered.get(key, 0) + 1
            parts.append(rf"\papercite{{{color}}}{{{short}}}{{{key}}}")
        joined = r"\allowbreak\hspace{0.12em}".join(parts)
        original_keys = ",".join(keys)
        return rf"\nocite{{{original_keys}}}{joined}"

    tex_files = sorted(workdir.rglob("*.tex"))
    for tex_file in tex_files:
        tex = tex_file.read_text(encoding="utf-8", errors="ignore")
        updated = replace_citations_outside_table_envs(tex, replace_match)
        if updated != tex:
            tex_file.write_text(updated, encoding="utf-8")

    compile_logs = []
    commands = [
        ["pdflatex", "-interaction=nonstopmode", main_tex.name],
        ["bibtex", main_tex.stem],
        ["pdflatex", "-interaction=nonstopmode", main_tex.name],
        ["pdflatex", "-interaction=nonstopmode", main_tex.name],
    ]
    for idx, command in enumerate(commands):
        result = run_command(command, workdir)
        compile_logs.append({"command": command, "returncode": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]})
        if command[0] == "bibtex":
            patch_bbl_targets(workdir, main_tex)
        if result.returncode != 0:
            built_pdf = workdir / f"{main_tex.stem}.pdf"
            output_written = "Output written on" in (result.stdout or "")
            if command[0] == "pdflatex" and built_pdf.exists() and built_pdf.stat().st_size > 0:
                continue
            raise RuntimeError(f"Command failed: {' '.join(command)}\n{result.stdout[-1000:]}\n{result.stderr[-1000:]}")

    output_pdf = survey_dir / f"{arxiv_id}_overlay.pdf"
    built_pdf = workdir / f"{main_tex.stem}.pdf"
    if not built_pdf.exists():
        raise RuntimeError(f"Expected built PDF at {built_pdf}")
    shutil.copy2(built_pdf, output_pdf)
    replaced_pages = replace_table_pages_with_original(survey_dir, arxiv_id, output_pdf)
    elapsed = time.perf_counter() - total_start

    print_banner(f"STEP 4.4 COMPLETE - {arxiv_id}")
    print(f"main_tex: {main_tex}")
    print(f"formatted_citations: {sum(rendered.values())}")
    print(f"overlay_pdf: {output_pdf}")
    if replaced_pages:
        print(f"table_pages_from_original: {replaced_pages}")
    print(f"elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
