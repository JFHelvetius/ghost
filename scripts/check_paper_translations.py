"""Check that the paper's translations are in step with the English source.

Run from the repo root:

    python scripts/check_paper_translations.py

The check is lightweight on purpose: full prose translations always drift
slightly, and we do not want CI to fail on every typo fix. Instead we
verify the *structural* invariants that matter for the Streamlit Paper
tab to render coherently across the three languages.

Checks performed:

1. **All three files exist** at their expected locations.
2. **Section count agreement.** Every translation has the same number of
   top-level (``##``) sections as the English source.
3. **Subsection count tolerance.** Each top-level section in a translation
   has ``±SUBSECTION_TOLERANCE`` of the English subsection count.
4. **Version-string agreement.** Every file mentions the same
   ``project-ghost==X.Y.Z`` version string.

Returns:
- Exit 0 if all checks pass.
- Exit 1 if any structural invariant is violated.
- Exit 2 if a file is missing.

Output is human-readable per-language with a final summary line.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Translations to check. Tuple of (language code, path-from-root).
_FILES: dict[str, Path] = {
    "EN": ROOT / "docs" / "paper" / "project_ghost_v0_2.md",
    "ES": ROOT / "docs" / "paper" / "es" / "proyecto_ghost_v0_2_ES.md",
    "ZH": ROOT / "docs" / "paper" / "zh" / "project_ghost_v0_2_ZH.md",
}

_SUBSECTION_TOLERANCE: int = 2
_VERSION_REGEX = re.compile(r"project-ghost==(\d+\.\d+\.\d+)")


def _section_counts(text: str) -> tuple[int, list[int]]:
    """Count top-level (## ) and per-section subsection (### ) headings.

    Returns ``(top_level_count, [subs_in_section_0, subs_in_section_1, ...])``.
    """
    lines = text.splitlines()
    top_level = 0
    subs_per_section: list[int] = []
    current_subs = 0
    inside_top = False
    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            if inside_top:
                subs_per_section.append(current_subs)
            top_level += 1
            current_subs = 0
            inside_top = True
        elif line.startswith("### ") and inside_top:
            current_subs += 1
    if inside_top:
        subs_per_section.append(current_subs)
    return top_level, subs_per_section


def _version_strings(text: str) -> set[str]:
    return set(_VERSION_REGEX.findall(text))


def main() -> int:
    # 1. Existence
    missing = [lang for lang, path in _FILES.items() if not path.exists()]
    if missing:
        for lang in missing:
            print(f"[{lang}] MISSING: {_FILES[lang]}")
        return 2

    contents = {lang: path.read_text(encoding="utf-8") for lang, path in _FILES.items()}

    # 2. Section count agreement
    en_top, en_subs = _section_counts(contents["EN"])
    print(f"[EN] {en_top} top-level sections, subsections per section: {en_subs}")

    failed: list[str] = []

    for lang in ("ES", "ZH"):
        tr_top, tr_subs = _section_counts(contents[lang])
        print(f"[{lang}] {tr_top} top-level sections, subsections per section: {tr_subs}")

        if tr_top != en_top:
            msg = (
                f"[{lang}] FAIL: top-level section count {tr_top} differs "
                f"from EN {en_top}"
            )
            print(msg)
            failed.append(msg)
            continue

        for i, (es_count, en_count) in enumerate(zip(tr_subs, en_subs, strict=False)):
            if abs(es_count - en_count) > _SUBSECTION_TOLERANCE:
                msg = (
                    f"[{lang}] FAIL: section {i} subsection count "
                    f"{es_count} differs from EN {en_count} by more "
                    f"than ±{_SUBSECTION_TOLERANCE}"
                )
                print(msg)
                failed.append(msg)

    # 3. Version-string agreement
    versions_by_lang = {lang: _version_strings(text) for lang, text in contents.items()}
    all_versions = Counter()
    for vs in versions_by_lang.values():
        all_versions.update(vs)
    en_versions = versions_by_lang["EN"]
    for lang in ("ES", "ZH"):
        tr_versions = versions_by_lang[lang]
        if tr_versions != en_versions:
            msg = (
                f"[{lang}] FAIL: version strings {sorted(tr_versions)} "
                f"differ from EN {sorted(en_versions)}"
            )
            print(msg)
            failed.append(msg)

    print()
    if failed:
        print(f"{len(failed)} translation invariant violation(s):")
        for f in failed:
            print(f"  - {f}")
        print(
            "\nFix the affected translation in docs/paper/{es,zh}/ to match "
            "the English source structure (top-level sections + subsection "
            "counts + version strings)."
        )
        return 1

    print("All three translations agree structurally with the EN source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
