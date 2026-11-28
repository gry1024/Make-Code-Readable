"""Resolve teaching outlines and verify that tutorial links land on bundled source."""
import ast


def python_outline(file):
    try:
        tree = ast.parse(file["code"])
    except (ValueError, SyntaxError):
        return []
    symbols = []
    definitions = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

    def visit(body, prefix=""):
        for node in body:
            if not isinstance(node, definitions):
                continue
            name = prefix + node.name
            symbol = {"name": name, "start": node.lineno, "end": node.end_lineno}
            # Old annotations may already describe this definition in its own block.
            block = next((b for b in file["blocks"] if b["start"] == node.lineno), {})
            for lang in ("zh", "en"):
                symbol[lang] = block.get("summary_" + lang, "")
            symbols.append(symbol)
            if isinstance(node, ast.ClassDef):
                visit(node.body, name + ".")

    visit(tree.body)
    return symbols


def bilingual(value, where):
    if not isinstance(value, dict) or any(
        not isinstance(value.get(k), str) or not value[k].strip() for k in ("zh", "en")
    ):
        raise ValueError(f"{where}: expected nonempty zh and en text")


def check_range(target, length, where):
    start, end = target.get("start"), target.get("end")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= length:
        raise ValueError(f"{where}: invalid source range {start}-{end} (length {length})")


def prepare_guides(files, structure):
    lengths = {f["path"]: len(f["code"].splitlines()) for f in files}
    for file in files:
        path = file["path"]
        outline = python_outline(file) if file["language"] == "python" else []
        by_start = {s["start"]: s for s in outline}
        for symbol in file.get("symbols", []):
            bilingual(symbol, path)
            check_range(symbol, lengths[path], path)
            if not isinstance(symbol.get("name"), str) or not symbol["name"].strip():
                raise ValueError(f"{path}: symbol needs a name")
            by_start[symbol["start"]] = symbol
        file["symbols"] = [by_start[n] for n in sorted(by_start)]

    chapters = structure.get("chapters", [])
    ids = set()
    for chapter in chapters:
        key = chapter.get("id")
        if not isinstance(key, str) or not key.strip() or key in ids:
            raise ValueError(f"invalid or duplicate chapter id: {key}")
        ids.add(key)
        for field in ("title", "body"):
            bilingual(chapter.get(field), f"{key}.{field}")
        if not chapter.get("refs"):
            raise ValueError(f"{key}: chapter needs a source reference")
        for ref in chapter["refs"]:
            path = ref.get("file")
            if path not in lengths:
                raise ValueError(f"{key}: unknown source file {path}")
            check_range(ref, lengths[path], f"{key}: {path}")
            bilingual(ref, f"{key}: {path}")
    for edge in structure.get("edges", []):
        if edge.get("from") not in ids or edge.get("to") not in ids:
            raise ValueError(f"unknown chapter in edge: {edge}")
        bilingual(edge, "edge")
