"""Independent tests for the background undo log module."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionUndoLogTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'undo_log.js'))});
          const storageKey = BookmarkAdvisor.Protocol.STORAGE_KEYS.UNDO_LOG;
          const state = new Map();
          const storage = {{
            async get(key) {{ return state.get(key); }},
            async set(key, value) {{ state.set(key, value); }},
          }};
          const calls = [];
          const bookmarkApi = {{
            async move(id, destination) {{ calls.push(['move', id, destination]); }},
            async update(id, changes) {{ calls.push(['update', id, changes]); }},
            async remove(id) {{ calls.push(['remove', id]); }},
          }};
          const bookmarkTree = {{
            async ensureFolderPath(path) {{ calls.push(['ensureFolderPath', path]); }},
          }};
          const undoLog = BookmarkAdvisor.Background.UndoLog.create({{
            storage, bookmarkApi, bookmarkTree,
          }});
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
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_semantic_recorders_keep_the_existing_entry_shape(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                """
                Math.random = () => 0.5;
                await undoLog.recordMovedNode(
                  'exec-1',
                  { action_id: 'a-move', action_type: 'move_bookmark' },
                  { id: 'b1', parentId: 'source', title: 'Bookmark', url: 'https://example.com' },
                );
                await undoLog.recordRenamedFolder(
                  'exec-1',
                  { action_id: 'a-rename', action_type: 'rename_folder' },
                  { id: 'f1', title: 'Old title' },
                );
                await undoLog.recordCreatedFolder(
                  'exec-1',
                  { action_id: 'a-create', action_type: 'create_folder' },
                  { id: 'f2', parentId: 'root', title: 'New', path: '/Root/New' },
                );
                await undoLog.recordDeletedFolder(
                  'exec-1',
                  { action_id: 'a-delete', action_type: 'delete_empty_folder' },
                  { id: 'f3', parentId: 'root', title: 'Deleted', path: '/Root/Deleted' },
                );
                const log = state.get(storageKey);
                console.log(JSON.stringify({
                  frozen: Object.isFrozen(undoLog),
                  entries: log.map((entry) => ({
                    execution_id: entry.execution_id,
                    action_id: entry.action_id,
                    action_type: entry.action_type,
                    before: entry.before,
                    undo_action: entry.undo_action,
                    undo_id_ok: /^undo-\\d+-8$/.test(entry.undo_id),
                    timestamp_ok: /^\\d{4}-\\d{2}-\\d{2}T/.test(entry.timestamp),
                  })),
                }));
                """
            ),
        )
        self.assertTrue(result["frozen"])
        entries = cast(list[dict[str, object]], result["entries"])
        self.assertEqual(
            [entry["undo_action"] for entry in entries],
            [
                {"type": "move", "id": "b1", "parentId": "source"},
                {"type": "rename", "id": "f1", "title": "Old title"},
                {"type": "delete_folder", "id": "f2"},
                {"type": "create_folder", "path": "/Root/Deleted"},
            ],
        )
        self.assertTrue(all(entry["undo_id_ok"] for entry in entries))
        self.assertTrue(all(entry["timestamp_ok"] for entry in entries))
        self.assertEqual(entries[0]["before"], {
            "id": "b1",
            "parentId": "source",
            "title": "Bookmark",
            "url": "https://example.com",
        })

    def test_record_undo_compatibility_api_keeps_only_twenty_execution_ids(self) -> None:
        result = self._node_eval(
            """
            for (let index = 0; index < 21; index += 1) {
              await undoLog.recordUndo(
                `exec-${index}`,
                { action_id: `action-${index}`, action_type: 'move_bookmark' },
                { id: `bookmark-${index}`, parentId: 'source' },
                undoLog.TYPES.MOVE,
              );
              if (index === 0) {
                await undoLog.recordUndo(
                  'exec-0',
                  { action_id: 'action-0-extra', action_type: 'move_bookmark' },
                  { id: 'bookmark-0-extra', parentId: 'source' },
                  undoLog.TYPES.MOVE,
                );
              }
            }
            const log = state.get(storageKey);
            console.log(JSON.stringify({
              length: log.length,
              executionIds: [...new Set(log.map((entry) => entry.execution_id))],
              containsOldest: log.some((entry) => entry.execution_id === 'exec-0'),
            }));
            """
        )
        self.assertEqual(result["length"], 20)
        self.assertFalse(result["containsOldest"])
        self.assertEqual(result["executionIds"], [f"exec-{index}" for index in range(1, 21)])

    def test_undo_last_execution_replays_in_reverse_and_retains_older_batches(self) -> None:
        result = self._node_eval(
            """
            await undoLog.recordMovedNode(
              'older', { action_type: 'move_bookmark' }, { id: 'old', parentId: 'old-parent' },
            );
            await undoLog.recordMovedNode(
              'latest', { action_type: 'move_bookmark' }, { id: 'b1', parentId: 'p1' },
            );
            await undoLog.recordRenamedFolder(
              'latest', { action_type: 'rename_folder' }, { id: 'f1', title: 'Before' },
            );
            await undoLog.recordCreatedFolder(
              'latest', { action_type: 'create_folder' }, { id: 'f2', path: '/Root/Created' },
            );
            await undoLog.recordDeletedFolder(
              'latest', { action_type: 'delete_empty_folder' }, { id: 'f3', path: '/Root/Deleted' },
            );
            const report = await undoLog.undoLastExecution();
            console.log(JSON.stringify({
              calls,
              report,
              remaining: state.get(storageKey).map((entry) => entry.execution_id),
            }));
            """
        )
        self.assertEqual(
            result["calls"],
            [
                ["ensureFolderPath", "/Root/Deleted"],
                ["remove", "f2"],
                ["update", "f1", {"title": "Before"}],
                ["move", "b1", {"parentId": "p1"}],
            ],
        )
        report = result["report"]
        self.assertEqual(report["execution_id"], "latest")
        self.assertEqual(report["count"], 4)
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["hasMore"])
        self.assertEqual(result["remaining"], ["older"])

    def test_empty_and_failed_undo_match_existing_report_semantics(self) -> None:
        result = self._node_eval(
            """
            const empty = await undoLog.undoLastExecution();
            bookmarkApi.remove = async (id) => { throw new Error(`cannot remove ${id}`); };
            await undoLog.recordCreatedFolder(
              'latest', { action_type: 'create_folder' }, { id: 'f1', path: '/Root/New' },
            );
            const entryId = state.get(storageKey)[0].undo_id;
            const failed = await undoLog.undoLastExecution();
            console.log(JSON.stringify({
              empty,
              failed,
              expectedFailureId: entryId,
              remaining: state.get(storageKey),
            }));
            """
        )
        self.assertEqual(
            result["empty"],
            {"undone": False, "reason": "No undo log entries found."},
        )
        self.assertEqual(result["failed"]["count"], 0)
        self.assertEqual(
            result["failed"]["failures"],
            [{
                "undo_id": result["expectedFailureId"],
                "error": "cannot remove f1",
            }],
        )
        self.assertFalse(result["failed"]["hasMore"])
        self.assertEqual(result["remaining"], [])


if __name__ == "__main__":
    unittest.main()
