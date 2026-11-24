"""Scan a repo and split annotatable source files into ordered batches.

Creates <repo>/.mcr/manifest.json used by the MCR skill to annotate large
repositories incrementally and resumably.

Usage:
    python3 -m mcr.scan <repo> [--batch-files 5] [--batch-lines 1200]
    python3 -m mcr.scan <repo> --next     # print the next pending batch
"""

import argparse
import json
import os
import sys

SKIP_DIRS = {
    ".git", ".mcr", "node_modules", "dist", "build", "target", "vendor",
    ".venv", "venv", "__pycache__", ".next", ".nuxt", "coverage", ".idea",
    ".vscode", "out", "bin", "obj", ".tox", ".pytest_cache", ".cache",
}
SKIP_FILES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "cargo.lock",
    "poetry.lock", "composer.lock", "gemfile.lock", "uv.lock",
}
SOURCE_EXT = {
    ".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".cc", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".sh", ".bash", ".zsh", ".json", ".yaml", ".yml", ".toml",
    ".md", ".html", ".xml", ".css", ".scss", ".sql", ".lua", ".vue",
    ".svelte", ".r", ".scala",
}
ENTRY_NAMES = {
    "main", "index", "app", "cli", "server", "mod", "lib", "__main__",
}
MAX_LINES = 2000


def is_source_file(name: str) -> bool:
    lower = name.lower()
    if lower in SKIP_FILES or lower.endswith((".min.js", ".min.css", ".pb.go")):
        return False
    if lower == "dockerfile" or lower == "makefile":
        return True
    return os.path.splitext(lower)[1] in SOURCE_EXT


def count_lines(path: str) -> int:
    try:
        with open(path, "rb") as f:
            data = f.read()
        if b"\x00" in data[:4096]:
            return -1
        return data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)
    except OSError:
        return -1


def priority(rel: str, readme_text: str) -> int:
    stem = os.path.splitext(os.path.basename(rel))[0].lower()
    score = 0
    if stem in ENTRY_NAMES:
        score += 40
    if readme_text and rel in readme_text:
        score += 25
    score -= rel.count("/")
    return score


def scan(repo: str, batch_files: int, batch_lines: int):
    repo = os.path.abspath(repo)
    readme_text = ""
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        p = os.path.join(repo, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                readme_text = f.read()
            break

    entries, oversized = [], []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not is_source_file(name):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, repo).replace(os.sep, "/")
            n = count_lines(full)
            if n < 0:
                continue
            if n > MAX_LINES:
                oversized.append({"path": rel, "lines": n})
                continue
            entries.append({
                "path": rel,
                "lines": n,
                "priority": priority(rel, readme_text),
                "status": "pending",
            })

    entries.sort(key=lambda e: (-e["priority"], e["lines"], e["path"]))
    batches, cur, cur_lines = [], [], 0
    for e in entries:
        if cur and (len(cur) >= batch_files or cur_lines + e["lines"] > batch_lines):
            batches.append(cur)
            cur, cur_lines = [], 0
        cur.append(e)
        cur_lines += e["lines"]
    if cur:
        batches.append(cur)

    return {
        "repo": os.path.basename(repo) or repo,
        "batch_files": batch_files,
        "batch_lines": batch_lines,
        "batches": [{"id": i + 1, "files": b} for i, b in enumerate(batches)],
        "oversized_skipped": oversized,
    }


def main(argv=None):
    p = argparse.ArgumentParser(prog="mcr.scan", description=__doc__)
    p.add_argument("repo")
    p.add_argument("--batch-files", type=int, default=5)
    p.add_argument("--batch-lines", type=int, default=1200)
    p.add_argument("--next", action="store_true", help="print the next pending batch and exit")
    args = p.parse_args(argv)

    mcr_dir = os.path.join(args.repo, ".mcr")
    manifest_path = os.path.join(mcr_dir, "manifest.json")

    if args.next:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for b in manifest["batches"]:
            pending = [e for e in b["files"] if e["status"] == "pending"]
            if pending:
                print(f"batch {b['id']}:")
                for e in pending:
                    print(f"  {e['path']} ({e['lines']} lines)")
                return
        print("all batches done")
        return

    manifest = scan(args.repo, args.batch_files, args.batch_lines)
    os.makedirs(os.path.join(mcr_dir, "annotations"), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    total = sum(len(b["files"]) for b in manifest["batches"])
    print(f"{total} source files → {len(manifest['batches'])} batches (manifest: {manifest_path})")
    for b in manifest["batches"]:
        lines = sum(e["lines"] for e in b["files"])
        print(f"  batch {b['id']}: {len(b['files'])} files, {lines} lines")
        for e in b["files"]:
            print(f"    {e['path']} ({e['lines']})")
    if manifest["oversized_skipped"]:
        print(f"skipped {len(manifest['oversized_skipped'])} oversized files (> {MAX_LINES} lines):")
        for e in manifest["oversized_skipped"]:
            print(f"    {e['path']} ({e['lines']})")


if __name__ == "__main__":
    sys.exit(main())
