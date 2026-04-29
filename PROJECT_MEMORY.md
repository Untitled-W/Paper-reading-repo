# Project Memory

Last updated: 2026-04-30 07:15:00 +08:00

## Purpose

This file is a long-term engineering memory for the repository. Record stable process decisions, confirmed bugs, root causes, and durable workarounds here. Do not use it for temporary chat notes.

## Repository Conventions

- `survey_reading/` is local working data and should stay ignored by git.
- `scripts/__pycache__/` should stay ignored by git and must not be tracked.
- Index records in `paper_database/Introduction/INDEX.md` must use full timestamps, not date-only values.

## Confirmed Workflow Notes

### arXiv download and network behavior

- arXiv access is not reliably stable across direct download, proxy download, API access, and command-line fetch methods.
- The codebase now includes arXiv network probing support so download strategy can be chosen based on actual reachability instead of assumption.
- Clash-based proxy probing and candidate selection logic exists in the scripts and should be preferred over hard-coded single-path networking assumptions.

### Git / repo setup

- The local repository has been initialized and linked to:
  - `git@github.com:Untitled-W/Paper-reading-repo.git`
- `survey_reading/` is intentionally excluded from version control to avoid large local paper assets polluting the repo.

## Confirmed Bugs And Fixes

### 1. Index timestamp bug

Problem:
- Index entries only stored dates, which lost intra-day ordering and made later auditing difficult.

Fix:
- Updated the relevant skill/process and scripts to store full timestamps.
- Existing old entries were backfilled from available JSON metadata where possible.

Affected areas:
- `SKILL.md`
- `paper_database/Introduction/INDEX.md`
- `scripts/step5_2_add_to_index.py`

### 2. Python cache tracking bug

Problem:
- `scripts/__pycache__/` should never have been tracked.

Fix:
- Added it to `.gitignore`.
- Removed tracked cache files from the git index.

Affected areas:
- `.gitignore`

### 3. Broken overlay PDF output under restricted MiKTeX execution

Problem:
- Overlay PDF builds could succeed superficially but produce structurally broken PDFs that failed to open correctly.

Confirmed symptoms:
- Missing `trailer`
- Missing `startxref`
- Missing `%%EOF`
- `pdfinfo` errors such as trailer dictionary failures

Root cause:
- MiKTeX-related execution under restricted conditions could not write all required auxiliary/log output correctly, leading to truncated or invalid PDF artifacts.

Fix / rule:
- PDF rebuild steps involving MiKTeX / `pdflatex` must be executed in an environment where MiKTeX can write normally.
- Do not trust file existence alone; validate suspicious outputs with `pdfinfo` when needed.

Affected areas:
- `scripts/step4_4_apply_citation_format.py`

### 4. Table rendering corruption when recompiling some arXiv LaTeX sources locally

Problem:
- For paper `2504.03515`, the original arXiv PDF rendered tables correctly, but the local overlay build rendered tables incorrectly.

What was ruled out:
- This was not caused only by citation overlay replacement.
- Skipping citation replacement inside table-like environments reduced some risk but did not solve the table corruption.
- Adding the `array` package did not resolve the issue.

Confirmed root cause:
- Local MiKTeX recompilation of the raw arXiv LaTeX source diverged from arXiv's official PDF build result.
- The raw local compile itself emitted extensive table/alignment errors.

Observed log patterns:
- `Undefined control sequence`
- `Missing # inserted in alignment preamble`
- `Something's wrong--perhaps a missing \\item`
- Large `Overfull \\hbox` warnings around table ranges

Durable workaround:
- For affected papers, preserve the original arXiv PDF pages for table-heavy pages instead of trusting local full-source recompilation for those pages.
- The current overlay script includes a fallback that swaps detected table pages back to the original PDF after overlay build.

Tradeoff:
- Pages swapped back to the original PDF will not preserve overlay citation enhancements from the local rebuild.
- This is acceptable when layout fidelity is more important than per-page overlay augmentation.

Affected areas:
- `scripts/step4_4_apply_citation_format.py`

## Paper-Specific Record

### 2504.03515

Paper:
- `Dexterous Manipulation through Imitation Learning: A Survey`

Confirmed issues encountered:
- Initial overlay PDF was corrupted and unreadable.
- Rebuilt PDF became structurally valid after proper execution context.
- All tables still rendered incorrectly under local LaTeX recompilation.

Final resolution:
- Rebuilt overlay PDF successfully.
- Replaced table pages with original arXiv PDF pages.

Current known swapped pages:
- `6, 10, 11, 12, 14, 16, 18, 19, 20`

Final artifact:
- `survey_reading/2504.03515-dexterous-manipulation-through-imitation-learning-a-survey/2504.03515_overlay.pdf`

## Maintenance Rule

When a new bug is confirmed, append:

1. The stable symptom.
2. The confirmed root cause, if known.
3. The fix or workaround.
4. The scripts/files/processes affected.

Prefer concise engineering facts over narrative.
