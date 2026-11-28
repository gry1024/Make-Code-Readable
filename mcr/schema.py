"""Validate MCR annotation JSON files against the source repo.

Usage: python -m mcr.schema <annotations_dir> <repo_path>
"""

import json
import os
import sys

REQUIRED_BLOCK_KEYS = ("start", "end", "summary_zh", "summary_en", "lines")
REQUIRED_LINE_KEYS = ("n", "zh", "en")


def annotation_filename(rel_path: str) -> str:
    return rel_path.replace("/", "__") + ".json"


def count_lines(source_path: str) -> int:
    with open(source_path, "rb") as f:
        data = f.read()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def validate_file(ann_path: str, repo_path: str) -> list:
    errors = []
    try:
        with open(ann_path, encoding="utf-8") as f:
            ann = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return [f"{ann_path}: invalid JSON: {e}"]

    rel = ann.get("file")
    if not rel:
        return [f"{ann_path}: missing 'file' field"]

    src = os.path.join(repo_path, rel)
    if not os.path.isfile(src):
        errors.append(f"{ann_path}: source file not found in repo: {rel}")
        total = None
    else:
        total = count_lines(src)

    blocks = ann.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        errors.append(f"{ann_path}: 'blocks' must be a non-empty list")
        return errors

    prev_end = 0
    for i, b in enumerate(blocks):
        where = f"{ann_path}: block #{i}"
        for k in REQUIRED_BLOCK_KEYS:
            if k not in b:
                errors.append(f"{where}: missing key '{k}'")
        if errors and any(f"{where}: missing" in e for e in errors):
            continue
        start, end = b["start"], b["end"]
        if not (isinstance(start, int) and isinstance(end, int) and 1 <= start <= end):
            errors.append(f"{where}: bad range {start}-{end}")
            continue
        if start <= prev_end:
            errors.append(f"{where}: overlaps previous block (starts {start}, prev ends {prev_end})")
        if total is not None and end > total:
            errors.append(f"{where}: end {end} beyond file length {total}")
        prev_end = max(prev_end, end)

        seen = set()
        for j, ln in enumerate(b.get("lines", [])):
            lwhere = f"{where} line #{j}"
            for k in REQUIRED_LINE_KEYS:
                if k not in ln:
                    errors.append(f"{lwhere}: missing key '{k}'")
            n = ln.get("n")
            last = ln.get("end", n)
            if type(n) is not int or type(last) is not int or not start <= n <= last <= end:
                errors.append(f"{lwhere}: invalid explanation range {n}-{last} in {start}-{end}")
                continue
            span = range(n, last + 1)
            if seen.intersection(span):
                errors.append(f"{lwhere}: overlapping explanation at {n}-{last}")
            seen.update(span)
            for lang in ("zh", "en"):
                if not isinstance(ln.get(lang), str) or not ln[lang].strip():
                    errors.append(f"{lwhere}: missing {lang} explanation")

    if total is not None and blocks:
        covered = []
        for b in blocks:
            if isinstance(b.get("start"), int) and isinstance(b.get("end"), int):
                covered.append((b["start"], b["end"]))
        covered.sort()
        gaps = []
        cursor = 1
        for s, e in covered:
            if s > cursor:
                gaps.append((cursor, s - 1))
            cursor = max(cursor, e + 1)
        if cursor <= total:
            gaps.append((cursor, total))
        for gs, ge in gaps:
            errors.append(f"{ann_path}: uncovered source lines {gs}-{ge}")

        explained = set()
        for b in blocks:
            for ln in b.get("lines", []):
                first = ln.get("n")
                last = ln.get("end", first)
                if type(first) is int and type(last) is int and 1 <= first <= last <= total:
                    explained.update(range(first, last + 1))
        with open(src, encoding="utf-8", errors="replace") as f:
            src_lines = f.read().splitlines()
        missing = [i for i, text in enumerate(src_lines, 1)
                   if text.strip() and i not in explained]
        if missing:
            shown = ", ".join(str(i) for i in missing[:12])
            more = f" … +{len(missing) - 12} more" if len(missing) > 12 else ""
            errors.append(
                f"{ann_path}: {len(missing)} non-blank line(s) without explanation "
                f"(uncovered source): {shown}{more}")

    return errors


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    ann_dir, repo_path = argv[1], argv[2]
    files = sorted(f for f in os.listdir(ann_dir) if f.endswith(".json"))
    if not files:
        print(f"no .json annotation files in {ann_dir}")
        return 1
    all_errors = []
    for name in files:
        all_errors.extend(validate_file(os.path.join(ann_dir, name), repo_path))
    if all_errors:
        for e in all_errors:
            print("ERROR:", e)
        print(f"\n{len(all_errors)} error(s) in {len(files)} file(s)")
        return 1
    print(f"OK: {len(files)} annotation file(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
