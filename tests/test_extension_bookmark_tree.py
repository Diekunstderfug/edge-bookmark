"""Bookmark tree index and locator module tests."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionBookmarkTreeTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'background' / 'bookmark_tree.js'))});
          (async () => {{
            {body}
          }})().catch((error) => {{
            process.stderr.write(error && error.stack ? error.stack : String(error));
            process.exit(1);
          }});
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_execution_context_keeps_bidirectional_path_index_in_sync(self) -> None:
        result = self._node_eval(
            """
            const tree = { id: '0', title: '', children: [{
              id: '1', title: '收藏夹栏', children: [{
                id: '2', title: 'Old', children: [{ id: '3', title: 'Nested', children: [] }]
              }]
            }] };
            const api = { get: async () => [], getTree: async () => [tree], search: async () => [] };
            const module = BookmarkAdvisor.Background.BookmarkTree.create({ api, normalizeUrl: (url) => url });
            const context = module.createExecutionContext(tree);
            context.renamePrefix('/收藏夹栏/Old', '/收藏夹栏/New');
            const afterRename = {
              old: context.pathToId.has('/收藏夹栏/Old'),
              renamed: context.pathToId.get('/收藏夹栏/New'),
              nested: context.pathToId.get('/收藏夹栏/New/Nested'),
              reverse: context.idToPath.get('3'),
            };
            context.removePrefix('/收藏夹栏/New');
            console.log(JSON.stringify({
              afterRename,
              remaining: [...context.pathToId.entries()],
              removedReverse: context.idToPath.has('2') || context.idToPath.has('3'),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "afterRename": {
                    "old": False,
                    "renamed": "2",
                    "nested": "3",
                    "reverse": "/收藏夹栏/New/Nested",
                },
                "remaining": [["/收藏夹栏", "1"]],
                "removedReverse": False,
            },
        )

    def test_bookmark_locator_fails_closed_on_id_mismatch_and_falls_back_when_stale(self) -> None:
        result = self._node_eval(
            """
            const nodes = {
              root: { id: '0', title: '', children: [] },
              '10': { id: '10', parentId: '2', title: 'Wrong', url: 'https://wrong.example' },
              '20': { id: '20', parentId: '2', title: 'Expected', url: 'https://example.com' },
            };
            const api = {
              get: async (id) => {
                if (id === 'stale') throw new Error('not found');
                return nodes[id] ? [nodes[id]] : [];
              },
              getTree: async () => [nodes.root],
              search: async (query) => query.url === 'https://example.com' ? [nodes['20']] : [],
            };
            const module = BookmarkAdvisor.Background.BookmarkTree.create({ api, normalizeUrl: (url) => url });
            const idToPath = new Map([['2', '/收藏夹栏/Source']]);
            let mismatch = '';
            try {
              await module.resolveBookmarkId({
                bookmark_locator: { id: '10', title: 'Expected', url: 'https://example.com' },
              }, idToPath);
            } catch (error) {
              mismatch = error.message;
            }
            const fallback = await module.resolveBookmarkId({
              bookmark_locator: {
                id: 'stale', title: 'Expected', url: 'https://example.com',
                folder_path: '/收藏夹栏/Source',
              },
            }, idToPath);
            console.log(JSON.stringify({ mismatch, fallback }));
            """
        )
        self.assertIn("did not match", result["mismatch"])
        self.assertEqual(result["fallback"], "20")

    def test_ensure_folder_path_creates_only_missing_segments_and_updates_indexes(self) -> None:
        result = self._node_eval(
            """
            let sequence = 10;
            const creates = [];
            const api = {
              create: async (payload) => {
                creates.push(payload);
                sequence += 1;
                return { id: String(sequence), title: payload.title, parentId: payload.parentId };
              },
              get: async () => [], getTree: async () => [], search: async () => [],
            };
            const module = BookmarkAdvisor.Background.BookmarkTree.create({ api, normalizeUrl: (url) => url });
            const pathToId = new Map([['/收藏夹栏', '1'], ['/收藏夹栏/Existing', '2']]);
            const idToPath = new Map([['1', '/收藏夹栏'], ['2', '/收藏夹栏/Existing']]);
            const first = await module.ensureFolderPath('/收藏夹栏/Existing/New/Leaf', pathToId, idToPath);
            const second = await module.ensureFolderPath('/收藏夹栏/Existing/New/Leaf', pathToId, idToPath);
            console.log(JSON.stringify({
              first,
              second,
              creates,
              leafId: pathToId.get('/收藏夹栏/Existing/New/Leaf'),
              reverse: idToPath.get(first.id),
            }));
            """
        )
        self.assertEqual(len(result["creates"]), 2)
        self.assertEqual(len(result["first"]["createdFolders"]), 2)
        self.assertEqual(result["second"]["createdFolders"], [])
        self.assertEqual(result["first"]["id"], result["second"]["id"])
        self.assertEqual(result["reverse"], "/收藏夹栏/Existing/New/Leaf")


if __name__ == "__main__":
    unittest.main()
