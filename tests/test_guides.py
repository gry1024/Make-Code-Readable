"""Regression coverage for legacy lessons, grouped explanations and source links."""
import json
import tempfile
import unittest
from pathlib import Path

from mcr.schema import validate_file
from mcr.tutorial import prepare_guides


class GuideTests(unittest.TestCase):
    def test_line_and_range_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("x = (\n    1\n)\n", encoding="utf8")
            target = root / "ann.json"
            def validate(ranges):
                lines = [dict(n=n, zh="表达式", en="Expression", **end) for n, end in ranges]
                block = dict(start=1, end=3, summary_zh="取值", summary_en="Value", lines=lines)
                target.write_text(json.dumps(dict(file="a.py", blocks=[block])), encoding="utf8")
                return validate_file(target, root)
            self.assertEqual(validate([(1, {}), (2, {}), (3, {})]), [])
            self.assertEqual(validate([(1, {"end": 3})]), [])
            for bad in [[(1, {"end": 2})], [(1, {"end": 3}), (2, {})], [(1, {"end": 4})]]:
                with self.subTest(bad=bad):
                    self.assertTrue(validate(bad))

    def test_link_validation_and_symbol_overlay(self):
        file = dict(path="module.py", language="python", blocks=[],
                    code="class A:\n    async def run(self):\n        pass\n",
                    symbols=[dict(name="A.run", start=2, end=3, zh="异步入口", en="Async entry")])
        ref = dict(file="module.py", start=2, end=3, zh="进入方法", en="Enter method")
        title = dict(zh="入口", en="Entry")
        chapter = dict(id="entry", title=title, body=title, refs=[ref])
        guide = dict(chapters=[chapter])
        prepare_guides([file], guide)
        self.assertEqual([s["name"] for s in file["symbols"]], ["A", "A.run"])
        self.assertEqual(file["symbols"][1]["en"], "Async entry")
        for broken in [
            dict(chapters=[dict(chapter, refs=[dict(ref, end=9)])]),
            dict(chapters=[dict(chapter, refs=[dict(ref, file="missing.py")])]),
            dict(chapters=[chapter, chapter]),
            dict(chapters=[chapter], edges=[{"from":"entry", "to":"missing", **title}]),
        ]:
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                prepare_guides([dict(file, symbols=[])], broken)


if __name__ == "__main__":
    unittest.main()
