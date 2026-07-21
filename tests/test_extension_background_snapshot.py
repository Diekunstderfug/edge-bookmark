"""Independent tests for bookmark API and snapshot export background modules."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionBackgroundSnapshotTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          const bookmarkApiPath = {json.dumps(str(EXTENSION / 'background' / 'bookmark_api.js'))};
          const snapshotExportPath = {json.dumps(str(EXTENSION / 'background' / 'snapshot_export.js'))};
          {body}
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_bookmark_api_wraps_callbacks_and_runtime_errors(self) -> None:
        result = self._node_eval(
            """
            globalThis.chrome = {
              runtime: { lastError: null },
              bookmarks: {
                getTree(callback) { callback([{ id: '0', children: [] }]); },
                search(query, callback) {
                  if (query === 'fail') {
                    chrome.runtime.lastError = { message: 'search failed' };
                    callback();
                    chrome.runtime.lastError = null;
                    return;
                  }
                  callback(query === 'empty' ? undefined : [{ id: 'b1' }]);
                },
              },
            };
            require(bookmarkApiPath);
            const api = globalThis.BookmarkAdvisor.Background.BookmarkApi;
            (async () => {
              const tree = await api.call('getTree');
              const found = await api.search('match');
              const empty = await api.search('empty');
              let error = '';
              try { await api.search('fail'); } catch (caught) { error = caught.message; }
              console.log(JSON.stringify({ tree, found, empty, error, frozen: Object.isFrozen(api) }));
            })();
            """
        )
        self.assertEqual(result["tree"], [{"id": "0", "children": []}])
        self.assertEqual(result["found"], [{"id": "b1"}])
        self.assertEqual(result["empty"], [])
        self.assertEqual(result["error"], "search failed")
        self.assertTrue(result["frozen"])

    def test_bookmark_api_reports_missing_permission(self) -> None:
        result = self._node_eval(
            """
            globalThis.chrome = { runtime: { lastError: null } };
            require(bookmarkApiPath);
            let error = '';
            try {
              globalThis.BookmarkAdvisor.Background.BookmarkApi.assertAvailable();
            } catch (caught) {
              error = caught.message;
            }
            console.log(JSON.stringify({ error }));
            """
        )
        self.assertEqual(
            result["error"],
            "Bookmark permission is unavailable. Enable the extension's Bookmarks permission, then reload the extension.",
        )

    def test_snapshot_export_preserves_tree_shape_and_metadata(self) -> None:
        result = self._node_eval(
            """
            const tree = [{
              id: '0', title: '', children: [{
                id: '1', title: '收藏夹栏', folderType: 'bookmarks-bar', syncing: true,
                children: [
                  {
                    id: 'b1', title: 'Example',
                    url: 'HTTPS://Example.COM:443/a%20b/?utm_source=x&z=2&a=1#part',
                  },
                  {
                    id: '2', title: '子目录', syncing: false,
                    children: [{ id: 'b2', title: '', url: 'https://Sub.Example.com:8443/' }],
                  },
                  { id: '3', title: '空目录' },
                ],
              }],
            }];
            globalThis.chrome = {
              runtime: { lastError: null },
              bookmarks: { getTree(callback) { callback(tree); } },
            };
            require(bookmarkApiPath);
            require(snapshotExportPath);
            const exporter = globalThis.BookmarkAdvisor.Background.SnapshotExport;
            (async () => {
              const snapshot = await exporter.exportCurrentSnapshot();
              console.log(JSON.stringify(snapshot));
            })();
            """
        )
        created_at = result.pop("created_at")
        self.assertRegex(created_at, r"^\d{4}-\d{2}-\d{2}T.*Z$")
        self.assertEqual(
            result,
            {
                "snapshot_version": "1",
                "source": "edge-extension",
                "source_path": "edge-bookmarks-api",
                "folders": [
                    {
                        "id": "1",
                        "name": "收藏夹栏",
                        "path": "/收藏夹栏",
                        "parent_path": None,
                        "root_key": "收藏夹栏",
                        "depth": 0,
                        "bookmark_count": 1,
                        "subfolder_count": 2,
                        "folder_type": "bookmarks-bar",
                        "syncing": True,
                    },
                    {
                        "id": "2",
                        "name": "子目录",
                        "path": "/收藏夹栏/子目录",
                        "parent_path": "/收藏夹栏",
                        "root_key": "",
                        "depth": 1,
                        "bookmark_count": 1,
                        "subfolder_count": 0,
                        "folder_type": "",
                        "syncing": False,
                    },
                    {
                        "id": "3",
                        "name": "空目录",
                        "path": "/收藏夹栏/空目录",
                        "parent_path": "/收藏夹栏",
                        "root_key": "",
                        "depth": 1,
                        "bookmark_count": 0,
                        "subfolder_count": 0,
                        "folder_type": "",
                        "syncing": None,
                    },
                ],
                "bookmarks": [
                    {
                        "id": "b1",
                        "title": "Example",
                        "url": "HTTPS://Example.COM:443/a%20b/?utm_source=x&z=2&a=1#part",
                        "normalized_url": "https://example.com/a b?a=1&z=2",
                        "domain": "example.com",
                        "folder_id": "1",
                        "folder_path": "/收藏夹栏",
                        "top_level_folder": "",
                        "root_key": "收藏夹栏",
                        "path": "/收藏夹栏/Example",
                        "depth": 1,
                    },
                    {
                        "id": "b2",
                        "title": "",
                        "url": "https://Sub.Example.com:8443/",
                        "normalized_url": "https://sub.example.com:8443/",
                        "domain": "sub.example.com:8443",
                        "folder_id": "2",
                        "folder_path": "/收藏夹栏/子目录",
                        "top_level_folder": "子目录",
                        "root_key": "收藏夹栏",
                        "path": "/收藏夹栏/子目录/",
                        "depth": 2,
                    },
                ],
            },
        )

    def test_folder_listing_sorts_a_copy_with_chinese_locale(self) -> None:
        result = self._node_eval(
            """
            const tree = [{ id: '0', title: '', children: [
              { id: '2', title: 'B', children: [] },
              { id: '1', title: 'A', children: [] },
            ] }];
            globalThis.chrome = {
              runtime: { lastError: null },
              bookmarks: { getTree(callback) { callback(tree); } },
            };
            require(bookmarkApiPath);
            require(snapshotExportPath);
            (async () => {
              const folders = await globalThis.BookmarkAdvisor.Background.SnapshotExport.listFolders();
              console.log(JSON.stringify(folders.map((folder) => folder.path)));
            })();
            """
        )
        self.assertEqual(result, ["/A", "/B"])

    def test_url_helpers_are_reusable_and_keep_existing_edge_cases(self) -> None:
        result = self._node_eval(
            """
            globalThis.chrome = {
              runtime: { lastError: null },
              bookmarks: { getTree(callback) { callback([]); } },
            };
            require(bookmarkApiPath);
            require(snapshotExportPath);
            const background = globalThis.BookmarkAdvisor.Background;
            const utils = background.BookmarkUtils;
            console.log(JSON.stringify({
              sameNormalize: utils.normalizeUrl === background.SnapshotExport.normalizeUrl,
              sameDomain: utils.extractDomain === background.SnapshotExport.extractDomain,
              empty: utils.normalizeUrl(''),
              invalid: utils.normalizeUrl('not a URL'),
              malformedEscape: utils.normalizeUrl('https://example.com/%zz'),
              cleaned: utils.normalizeUrl('http://EXAMPLE.com:80/a///?b=2&utm_x=1&a=3&a=1&empty='),
              domain: utils.extractDomain('https://Example.COM:9443/a'),
              invalidDomain: utils.extractDomain('not a URL'),
              frozen: Object.isFrozen(utils),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "sameNormalize": True,
                "sameDomain": True,
                "empty": "",
                "invalid": "not a URL",
                "malformedEscape": "https://example.com/%zz",
                "cleaned": "http://example.com/a?a=1&a=3&b=2",
                "domain": "example.com:9443",
                "invalidDomain": "",
                "frozen": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
