import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmark_advisor.utils import atomic_write_json


class AtomicWriteJsonTest(unittest.TestCase):
    def test_normal_write(self):
        """Write a dict to a new file and read it back."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.json"
            data = {"name": "test", "value": 42}
            atomic_write_json(dest, data)
            with open(dest, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_overwrite_existing_file(self):
        """Second write replaces the first atomically."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.json"
            atomic_write_json(dest, {"version": 1})
            atomic_write_json(dest, {"version": 2})
            with open(dest, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, {"version": 2})

    def test_utf8_round_trip(self):
        """Non-ASCII characters (CJK, emoji) survive a write-read cycle."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cjk.json"
            data = {
                "folder": "编程工具",
                "label": "検索エンジン",
                "emoji": "🔖📌",
            }
            atomic_write_json(dest, data)
            raw = dest.read_text(encoding="utf-8")
            self.assertIn("编程工具", raw)
            self.assertIn("検索エンジン", raw)
            self.assertIn("🔖📌", raw)
            self.assertNotIn("\\u", raw)
            loaded = json.loads(raw)
            self.assertEqual(loaded, data)

    def test_nested_parent_dir_creation(self):
        """Parent directories are created automatically."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a" / "b" / "c" / "deep.json"
            data = [1, 2, 3]
            atomic_write_json(dest, data)
            with open(dest, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, [1, 2, 3])

    def test_temp_cleanup_after_success(self):
        """No stale .atomic_*.tmp files remain after a successful write."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.json"
            atomic_write_json(dest, {"ok": True})
            tmp_files = [
                f
                for f in os.listdir(tmp)
                if f.startswith(".atomic_") and f.endswith(".tmp")
            ]
            self.assertEqual(tmp_files, [])

    def test_failed_serialization_preserves_existing_file(self):
        """If json.dump raises, the old file stays intact and temp is cleaned."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.json"
            original = {"version": 1, "label": "编程"}
            atomic_write_json(dest, original)

            with self.assertRaises(TypeError):
                atomic_write_json(dest, {"bad": object()})

            with open(dest, encoding="utf-8") as f:
                self.assertEqual(json.load(f), original)

            tmp_files = [
                f
                for f in os.listdir(tmp)
                if f.startswith(".atomic_") and f.endswith(".tmp")
            ]
            self.assertEqual(tmp_files, [])

    def test_list_data(self):
        """Top-level list data is written and readable."""
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "list.json"
            data = [
                {"action": "move", "target": "收藏夹栏/量化"},
                {"action": "rename", "target": "生信和基因组学"},
            ]
            atomic_write_json(dest, data)
            with open(dest, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)


if __name__ == "__main__":
    unittest.main()
