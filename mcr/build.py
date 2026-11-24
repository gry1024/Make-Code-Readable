"""Build a self-contained reader.html from a repo + MCR annotations.

Usage: python -m mcr.build <repo_path> --annotations <dir> --out reader.html
"""

import argparse
import datetime
import json
import os
import sys

from .schema import validate_file

VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "ini", ".ini": "ini", ".md": "markdown", ".html": "xml",
    ".xml": "xml", ".css": "css", ".scss": "scss", ".sql": "sql", ".lua": "lua",
    ".vue": "xml", ".svelte": "xml", ".r": "r", ".scala": "scala", ".pl": "perl",
    ".dockerfile": "dockerfile",
}


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_payload(repo_path: str, ann_dir: str):
    repo_path = os.path.abspath(repo_path)
    files = []
    errors = []
    for name in sorted(os.listdir(ann_dir)):
        if not name.endswith(".json"):
            continue
        ann_path = os.path.join(ann_dir, name)
        errors.extend(validate_file(ann_path, repo_path))
        with open(ann_path, encoding="utf-8") as f:
            ann = json.load(f)
        rel = ann.get("file", "")
        src = os.path.join(repo_path, rel)
        if not os.path.isfile(src):
            continue
        code = read_text(src)
        if ann.get("language") in (None, "", "auto"):
            ann["language"] = LANG_BY_EXT.get(os.path.splitext(rel)[1].lower(), "plaintext")
        files.append({
            "path": rel,
            "language": ann["language"],
            "note_zh": ann.get("note_zh", ""),
            "note_en": ann.get("note_en", ""),
            "code": code,
            "blocks": ann["blocks"],
        })
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        print("annotation validation failed; fix errors or run mcr.schema for details", file=sys.stderr)
        sys.exit(1)

    # Full-repo browsing: list every text file for the IDE tree, and include
    # source files without annotations so they open as plain code views.
    from .scan import SKIP_DIRS, is_source_file
    annotated = {f["path"] for f in files}
    tree = []
    for root, dirs, names in os.walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, repo_path).replace(os.sep, "/")
            try:
                size = os.path.getsize(full)
                with open(full, "rb") as fh:
                    if b"\x00" in fh.read(4096):
                        continue
            except OSError:
                continue
            tree.append(rel)
            if is_source_file(name) and size <= 200_000 and rel not in annotated:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    files.append({
                        "path": rel,
                        "language": LANG_BY_EXT.get(os.path.splitext(rel)[1].lower(), "plaintext"),
                        "note_zh": "", "note_en": "",
                        "code": fh.read(),
                        "blocks": [],
                    })
    structure = {}
    structure_path = os.path.join(repo_path, ".mcr", "structure.json")
    if os.path.isfile(structure_path):
        with open(structure_path, encoding="utf-8") as f:
            structure = json.load(f)

    files.sort(key=lambda f: f["path"])
    return {
        "repo": os.path.basename(repo_path.rstrip(os.sep)) or repo_path,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": files,
        "tree": sorted(tree),
        "structure": structure,
    }


def render(payload: dict) -> str:
    template = read_text(os.path.join(VIEWER_DIR, "template.html"))
    css = read_text(os.path.join(VIEWER_DIR, "style.css"))
    js = read_text(os.path.join(VIEWER_DIR, "app.js"))
    hljs = read_text(os.path.join(VIEWER_DIR, "vendor", "highlight.min.js"))
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = template
    html = html.replace("/*__MCR_CSS__*/", css)
    html = html.replace("/*__MCR_HLJS__*/", hljs)
    html = html.replace("/*__MCR_APP__*/", js)
    html = html.replace('"__MCR_DATA__"', data)
    html = html.replace("__MCR_TITLE__", payload["repo"])
    return html


def build(repo_path: str, ann_dir: str, out: str) -> str:
    payload = load_payload(repo_path, ann_dir)
    html = render(payload)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="mcr.build", description=__doc__)
    p.add_argument("repo", help="path to the source repository")
    p.add_argument("--annotations", required=True, help="directory of annotation JSON files")
    p.add_argument("--out", default="reader.html", help="output HTML path (default: reader.html)")
    args = p.parse_args(argv)
    out = build(args.repo, args.annotations, args.out)
    size = os.path.getsize(out)
    print(f"built {out} ({size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
