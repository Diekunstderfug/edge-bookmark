"""Unit tests for normalized AI planning snapshots."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionAiSnapshotModelTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'path_utils.js'))});
          require({json.dumps(str(EXTENSION / 'ai' / 'snapshot_model.js'))});
          const model = BookmarkAdvisor.AI.SnapshotModel;
          {body}
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_focus_filter_keeps_ancestors_but_not_prefix_siblings(self) -> None:
        result = self._node_eval(
            """
            const snapshot = model.buildPlanningSnapshot({
              created_at: '2026-01-01T00:00:00.000Z',
              folders: [
                { id: 1, name: 'A', path: '/A' },
                { id: 2, name: 'Work', path: '/A/Work' },
                { id: 3, name: 'Sub', path: '/A/Work/Sub' },
                { id: 4, name: 'Sibling', path: '/A/Workspace' },
              ],
              bookmarks: [
                { id: 10, title: 'Inside', url: 'https://example.com', folder_path: '/A/Work' },
                { id: 11, title: 'Nested', url: 'https://nested.example.com', folder_path: '/A/Work/Sub' },
                { id: 12, title: 'Sibling', url: 'https://sibling.example.com', folder_path: '/A/Workspace' },
              ],
            }, '/A/Work');
            console.log(JSON.stringify({
              folders: snapshot.folders.map((item) => item.path),
              bookmarks: snapshot.bookmarks.map((item) => item.id),
              snapshot,
            }));
            """
        )
        self.assertEqual(result["folders"], ["/A", "/A/Work", "/A/Work/Sub"])
        self.assertEqual(result["bookmarks"], ["10", "11"])
        self.assertEqual(result["snapshot"]["snapshot_version"], "2")
        self.assertEqual(result["snapshot"]["focus_path"], "/A/Work")
        self.assertEqual(result["snapshot"]["bookmarks"][0]["review_status"], "fast_reviewed")

    def test_url_review_skips_internal_local_and_ip_addresses(self) -> None:
        result = self._node_eval(
            """
            const urls = [
              'https://example.com', 'file:///tmp/a', 'http://localhost/a',
              'http://printer.local/a', 'http://192.0.2.1/a', 'http://[::1]/a',
              'javascript:alert(1)', 'not a url',
            ];
            console.log(JSON.stringify(urls.map((url) => model.urlRequiresReview(url))));
            """
        )
        self.assertEqual(result, [True, False, False, False, False, False, False, False])

    def test_normalization_and_locator_keep_only_planner_contract_fields(self) -> None:
        result = self._node_eval(
            """
            const bookmark = model.normalizeBookmark({
              id: 12, title: 34, url: 'https://x.test', depth: '2.9', extra: 'drop',
            });
            const folder = model.normalizeFolder({ id: 9, depth: -1, bookmark_count: '3.8' });
            console.log(JSON.stringify({ bookmark, folder, locator: model.bookmarkLocator(bookmark) }));
            """
        )
        self.assertEqual(result["bookmark"]["id"], "12")
        self.assertEqual(result["bookmark"]["title"], "34")
        self.assertEqual(result["bookmark"]["depth"], 2)
        self.assertNotIn("extra", result["bookmark"])
        self.assertEqual(result["folder"]["depth"], 0)
        self.assertEqual(result["folder"]["bookmark_count"], 3)
        self.assertEqual(
            set(result["locator"]),
            {"id", "title", "url", "normalized_url", "folder_path"},
        )


if __name__ == "__main__":
    unittest.main()
