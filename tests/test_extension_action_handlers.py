"""Independent tests for the background action handler table."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACTION_HANDLERS = ROOT / "extension" / "background" / "action_handlers.js"


class ExtensionActionHandlersTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(ACTION_HANDLERS))});
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

    def test_handler_table_preserves_mutations_indexes_and_undo_timing(self) -> None:
        result = self._node_eval(
            """
            const events = [];
            const nodes = {
              rename: { id: 'rename', title: 'Old', parentId: 'work' },
              empty: { id: 'empty', title: 'Empty', parentId: 'work' },
              folder: { id: 'folder', title: 'SourceFolder', parentId: 'work' },
              bookmark: { id: 'bookmark', title: 'Page', url: 'https://page.example', parentId: 'work' },
              duplicate: { id: 'duplicate', title: 'Dup', url: 'https://dup.example', parentId: 'work' },
            };
            const bookmarkApi = {
              get: async (id) => [nodes[id]],
              getChildren: async () => [],
              getTree: async () => [{ id: '0', children: [] }],
              update: async (id, changes) => events.push(`update:${id}:${changes.title}`),
              remove: async (id) => events.push(`remove:${id}`),
              move: async (id, destination) => events.push(`move:${id}:${destination.parentId}`),
            };
            const bookmarkTree = {
              ensureFolderPath: async (path) => {
                events.push(`ensure:${path}`);
                if (path.endsWith('/New/Child')) {
                  return {
                    id: 'new-child',
                    createdFolders: [
                      { id: 'new', parentId: 'work', title: 'New', path: '/收藏夹栏/Work/New' },
                      { id: 'new-child', parentId: 'new', title: 'Child', path: '/收藏夹栏/Work/New/Child' },
                    ],
                  };
                }
                return { id: `destination:${path}`, createdFolders: [] };
              },
              expectedFolderPath: (action) => action.from_path || '',
              nodeParentPath: async (parentId) => parentId === 'work' ? '/收藏夹栏/Work' : '',
              removeFolderPathIndexPrefix: (_pathToId, prefix) => events.push(`index-remove:${prefix}`),
              resolveBookmarkId: async (action) => action.bookmark_locator.id,
              resolveFolderId: async (action) => action.folder_locator.id,
              updateFolderPathIndexPrefix: (_pathToId, oldPath, newPath) => events.push(`index-rename:${oldPath}:${newPath}`),
            };
            const executionPolicy = {
              checkActionPolicy: () => ({ allowed: true }),
              assertPathWithinFocus: (path, focus, label) => events.push(`actual:${label}:${path}:${focus}`),
              knownQuarantinePath: (focus) => `${focus}/_Quarantine`,
              quarantinePathFromBookmarkTree: () => { throw new Error('known focus quarantine should win'); },
            };
            const undoLog = {
              recordCreatedFolder: async (_executionId, _action, before) => events.push(`undo-created:${before.id}`),
              recordRenamedFolder: async (_executionId, _action, before) => events.push(`undo-renamed:${before.id}:${before.title}`),
              recordDeletedFolder: async (_executionId, _action, before) => events.push(`undo-deleted:${before.id}:${before.path}`),
              recordMovedNode: async (_executionId, _action, before) => events.push(`undo-moved:${before.id}:${before.parentId}`),
            };
            const handlers = BookmarkAdvisor.Background.ActionHandlers.create({
              bookmarkApi, bookmarkTree, executionPolicy, undoLog,
            });
            const context = {
              focusPath: '/收藏夹栏/Work',
              executionId: 'exec-1',
              pathToId: new Map([['/收藏夹栏/Work', 'work']]),
              idToPath: new Map([['work', '/收藏夹栏/Work']]),
            };

            await handlers.apply({ action_type: 'create_folder', target_path: '/收藏夹栏/Work/New/Child' }, context);
            await handlers.apply({
              action_type: 'rename_folder', to_name: 'Renamed', from_path: '/收藏夹栏/Work/Old',
              folder_locator: { id: 'rename' },
            }, context);
            await handlers.apply({
              action_type: 'delete_empty_folder', from_path: '/收藏夹栏/Work/Empty',
              folder_locator: { id: 'empty' },
            }, context);
            await handlers.apply({
              action_type: 'move_folder', from_path: '/收藏夹栏/Work/SourceFolder',
              to_path: '/收藏夹栏/Work/Folders', folder_locator: { id: 'folder' },
            }, context);
            await handlers.apply({
              action_type: 'move_bookmark', to_path: '/收藏夹栏/Work/Pages',
              bookmark_locator: { id: 'bookmark' },
            }, context);
            await handlers.apply({
              action_type: 'remove_duplicate', bookmark_locator: { id: 'duplicate' },
            }, context);
            await handlers.apply({ action_type: 'keep_for_review' }, context);

            console.log(JSON.stringify({ events }));
            """
        )
        events = result["events"]
        self.assertEqual(
            events[:3],
            [
                "ensure:/收藏夹栏/Work/New/Child",
                "undo-created:new",
                "undo-created:new-child",
            ],
        )
        self.assertLess(events.index("undo-renamed:rename:Old"), events.index("update:rename:Renamed"))
        self.assertLess(events.index("remove:empty"), events.index("undo-deleted:empty:/收藏夹栏/Work/Empty"))
        self.assertLess(events.index("undo-moved:folder:work"), events.index("move:folder:destination:/收藏夹栏/Work/Folders"))
        self.assertLess(events.index("undo-moved:bookmark:work"), events.index("move:bookmark:destination:/收藏夹栏/Work/Pages"))
        self.assertLess(events.index("undo-moved:duplicate:work"), events.index("move:duplicate:destination:/收藏夹栏/Work/_Quarantine"))
        self.assertIn(
            "index-rename:/收藏夹栏/Work/SourceFolder:/收藏夹栏/Work/Folders/SourceFolder",
            events,
        )
        self.assertIn("index-remove:/收藏夹栏/Work/Empty", events)

    def test_actual_source_scope_is_checked_before_destination_or_mutation(self) -> None:
        result = self._node_eval(
            """
            let ensureCalls = 0;
            let moveCalls = 0;
            let undoCalls = 0;
            const bookmarkApi = {
              get: async (id) => [{ id, title: 'Outside', url: id === 'folder' ? undefined : 'https://example.com', parentId: 'personal' }],
              getTree: async () => [],
              move: async () => { moveCalls += 1; },
            };
            const bookmarkTree = {
              ensureFolderPath: async () => { ensureCalls += 1; return { id: 'destination', createdFolders: [] }; },
              expectedFolderPath: (action) => action.from_path || '',
              nodeParentPath: async () => '/收藏夹栏/Personal',
              resolveBookmarkId: async (action) => action.bookmark_locator.id,
              resolveFolderId: async (action) => action.folder_locator.id,
              updateFolderPathIndexPrefix: () => {},
            };
            const executionPolicy = {
              // 模拟 plan 声称 source 在 focus 内，因此 preflight 会放行。
              checkActionPolicy: () => ({ allowed: true }),
              assertPathWithinFocus: (path, focus, label) => {
                if (path !== focus && !path.startsWith(`${focus}/`)) {
                  throw new Error(`${label} ${path} is outside focus scope ${focus}`);
                }
              },
              knownQuarantinePath: (focus) => `${focus}/_Quarantine`,
              quarantinePathFromBookmarkTree: () => '',
            };
            const undoLog = {
              recordCreatedFolder: async () => { undoCalls += 1; },
              recordRenamedFolder: async () => { undoCalls += 1; },
              recordDeletedFolder: async () => { undoCalls += 1; },
              recordMovedNode: async () => { undoCalls += 1; },
            };
            const handlers = BookmarkAdvisor.Background.ActionHandlers.create({
              bookmarkApi, bookmarkTree, executionPolicy, undoLog,
            });
            const context = {
              focusPath: '/收藏夹栏/Work', executionId: 'exec-1',
              pathToId: new Map(), idToPath: new Map(),
            };
            const actions = [
              { action_type: 'move_bookmark', from_path: '/收藏夹栏/Work', to_path: '/收藏夹栏/Work/Dest', bookmark_locator: { id: 'bookmark' } },
              { action_type: 'move_folder', from_path: '/收藏夹栏/Work/Claimed', to_path: '/收藏夹栏/Work/Dest', folder_locator: { id: 'folder' } },
              { action_type: 'remove_duplicate', from_path: '/收藏夹栏/Work', bookmark_locator: { id: 'duplicate' } },
            ];
            const errors = [];
            for (const action of actions) {
              try {
                await handlers.apply(action, context);
              } catch (error) {
                errors.push(error.message);
              }
            }
            console.log(JSON.stringify({ errors, ensureCalls, moveCalls, undoCalls }));
            """
        )
        self.assertEqual(len(result["errors"]), 3)
        self.assertTrue(all("outside focus scope" in error for error in result["errors"]))
        self.assertEqual(result["ensureCalls"], 0)
        self.assertEqual(result["moveCalls"], 0)
        self.assertEqual(result["undoCalls"], 0)

    def test_delete_empty_folder_uses_remove_as_atomic_arbiter(self) -> None:
        result = self._node_eval(
            """
            async function run(children) {
              const events = [];
              const bookmarkApi = {
                get: async () => [{ id: 'empty', title: 'Empty', parentId: 'work' }],
                remove: async () => { events.push('remove'); throw new Error('remove failed'); },
                getChildren: async () => { events.push('getChildren'); return children; },
              };
              const bookmarkTree = {
                resolveFolderId: async () => 'empty',
                expectedFolderPath: () => '/收藏夹栏/Work/Empty',
                nodeParentPath: async () => '/收藏夹栏/Work',
                removeFolderPathIndexPrefix: () => events.push('index-remove'),
              };
              const executionPolicy = { checkActionPolicy: () => ({ allowed: true }) };
              const undoLog = {
                recordDeletedFolder: async () => events.push('undo'),
              };
              const handlers = BookmarkAdvisor.Background.ActionHandlers.create({
                bookmarkApi, bookmarkTree, executionPolicy, undoLog,
              });
              let error = '';
              try {
                await handlers.apply(
                  { action_type: 'delete_empty_folder', folder_locator: { id: 'empty' } },
                  { executionId: 'exec-1', pathToId: new Map(), idToPath: new Map() },
                );
              } catch (caught) {
                error = caught.message;
              }
              return { error, events };
            }
            console.log(JSON.stringify({
              nonEmpty: await run([{ id: 'child' }]),
              otherFailure: await run([]),
            }));
            """
        )
        self.assertEqual(
            result["nonEmpty"]["error"],
            "delete_empty_folder requires the folder to be empty",
        )
        self.assertEqual(result["otherFailure"]["error"], "remove failed")
        self.assertEqual(result["nonEmpty"]["events"], ["remove", "getChildren"])
        self.assertEqual(result["otherFailure"]["events"], ["remove", "getChildren"])

    def test_duplicate_uses_locale_root_quarantine_and_never_removes(self) -> None:
        result = self._node_eval(
            """
            let removeCalls = 0;
            const ensuredPaths = [];
            const moved = [];
            const recorded = [];
            const tree = [{ id: '0', children: [{ id: '1', title: 'Favorites bar', children: [] }] }];
            const bookmarkApi = {
              get: async () => [{ id: 'duplicate', title: 'Dup', url: 'https://example.com', parentId: '1' }],
              getTree: async () => tree,
              move: async (id, destination) => moved.push({ id, parentId: destination.parentId }),
              remove: async () => { removeCalls += 1; },
            };
            const bookmarkTree = {
              resolveBookmarkId: async () => 'duplicate',
              nodeParentPath: async () => '/Favorites bar',
              ensureFolderPath: async (path) => {
                ensuredPaths.push(path);
                return { id: 'quarantine', createdFolders: [{ id: 'quarantine', path }] };
              },
            };
            const executionPolicy = {
              checkActionPolicy: () => ({ allowed: true }),
              assertPathWithinFocus: () => {},
              knownQuarantinePath: () => '',
              quarantinePathFromBookmarkTree: (value) => {
                if (value !== tree) throw new Error('expected current bookmark tree');
                return '/Favorites bar/_Quarantine';
              },
            };
            const undoLog = {
              recordMovedNode: async (_executionId, _action, before) => recorded.push(before),
            };
            const handlers = BookmarkAdvisor.Background.ActionHandlers.create({
              bookmarkApi, bookmarkTree, executionPolicy, undoLog,
            });
            await handlers.apply(
              { action_type: 'remove_duplicate', bookmark_locator: { id: 'duplicate' } },
              { executionId: 'exec-1', pathToId: new Map(), idToPath: new Map([['1', '/Favorites bar']]) },
            );
            console.log(JSON.stringify({ removeCalls, ensuredPaths, moved, recorded }));
            """
        )
        self.assertEqual(result["removeCalls"], 0)
        self.assertEqual(result["ensuredPaths"], ["/Favorites bar/_Quarantine"])
        self.assertEqual(result["moved"], [{"id": "duplicate", "parentId": "quarantine"}])
        self.assertEqual(result["recorded"][0]["parentId"], "1")

    def test_only_created_folder_segments_receive_undo_records(self) -> None:
        result = self._node_eval(
            """
            const recorded = [];
            let call = 0;
            const bookmarkTree = {
              ensureFolderPath: async () => {
                call += 1;
                return call === 1
                  ? { id: 'leaf', createdFolders: [] }
                  : { id: 'leaf', createdFolders: [{ id: 'leaf', path: '/Root/New' }] };
              },
            };
            const handlers = BookmarkAdvisor.Background.ActionHandlers.create({
              bookmarkApi: {},
              bookmarkTree,
              executionPolicy: { checkActionPolicy: () => ({ allowed: true }) },
              undoLog: { recordCreatedFolder: async (_id, _action, folder) => recorded.push(folder.id) },
            });
            const action = { action_type: 'create_folder', target_path: '/Root/New' };
            await handlers.apply(action, { executionId: 'exec-1' });
            await handlers.apply(action, {});
            console.log(JSON.stringify({ recorded }));
            """
        )
        self.assertEqual(result["recorded"], [])


if __name__ == "__main__":
    unittest.main()
