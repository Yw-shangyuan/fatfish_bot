from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "plugin"))

import qr_portal
from store import StoreError, UserContextStore


class MemoryExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix=".panel-export-test-",
            dir=Path(__file__).resolve().parent,
        )
        qr_portal.MEMORY_DATA_DIR = str(Path(self.temp.name) / "data")
        self.store = UserContextStore(qr_portal.MEMORY_DATA_DIR)
        self.qq = "10001"
        self.store.enable_user(self.qq)
        self.store.write_document(self.qq, "intro", "基本介绍")
        self.store.append_memory_note(self.qq, "喜欢简洁回答")
        self.store.append_owner_guidance("先给结论")

    def tearDown(self):
        self.temp.cleanup()

    def test_user_zip_contains_only_user_files_and_hash_manifest(self):
        payload, filename = qr_portal.memory_export_zip(self.qq)
        self.assertTrue(filename.endswith(".zip"))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"intro.md", "memory.md", "manifest.json"},
            )
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertNotIn(self.qq, json.dumps(manifest))
            self.assertNotIn(self.qq, filename)
            self.assertIn("喜欢简洁回答", archive.read("memory.md").decode("utf-8"))
            self.assertNotIn("先给结论", archive.read("memory.md").decode("utf-8"))

    def test_unbound_user_is_rejected(self):
        with self.assertRaises(StoreError):
            qr_portal.memory_export_zip("10002")

    def test_invalid_qq_is_rejected(self):
        with self.assertRaises(ValueError):
            qr_portal.memory_export_zip("not-a-qq")

    def test_owner_guidance_zip_is_separate(self):
        payload, filename = qr_portal.owner_guidance_export_zip()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"owner_guidance.md", "manifest.json"},
            )
            self.assertIn("先给结论", archive.read("owner_guidance.md").decode("utf-8"))

    def test_page_contains_native_export_form(self):
        html = qr_portal.memory_card()
        self.assertIn('form="memory-export"', html)
        self.assertIn("memory_export", html)
        self.assertIn("owner_guidance_export", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
