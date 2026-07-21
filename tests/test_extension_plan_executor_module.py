"""Unit tests for the extracted reviewed-plan executor."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionPlanExecutorModuleTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'plan_schema.js'))});
          require({json.dumps(str(EXTENSION / 'shared' / 'path_utils.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'execution_policy.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'plan_executor.js'))});
          (async () => {{
            {body}
          }})().catch((error) => {{
            console.log(JSON.stringify({{ uncaught: error.message, name: error.name }}));
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

    def test_executor_applies_only_executable_actions_in_contract_order(self) -> None:
        result = self._node_eval(
            """
            const calls = [];
            const checkpoints = [];
            const progress = [];
            let report = null;
            const executor = BookmarkAdvisor.Background.PlanExecutor.create({
              actionHandlers: { apply: async (action) => calls.push(action.action_type) },
              bookmarkApi: { getTree: async () => [{ id: '0', title: '', children: [] }] },
              bookmarkTree: { buildFolderPathIndex: () => ({ pathToId: new Map(), idToPath: new Map() }) },
              checkpointStore: {
                save: async (value) => checkpoints.push(JSON.parse(JSON.stringify(value))),
                clear: async () => checkpoints.push('cleared'),
              },
              saveReport: async (value) => { report = value; },
              createExecutionId: () => 'exec-fixed',
              now: (() => { let value = 0; return () => new Date(1000 + value++ * 1000); })(),
            });
            const plan = {
              plan_version: '2', plan_kind: 'reviewed',
              actions: [
                { action_id: 'move', action_type: 'move_bookmark', status: 'approved', reason: 'x', confidence: 1,
                  bookmark_locator: { id: 'b1' }, to_path: '/收藏夹栏/B' },
                { action_id: 'rename', action_type: 'rename_folder', status: 'edited', reason: 'x', confidence: 1,
                  folder_locator: { id: 'f1' }, to_name: 'New' },
                { action_id: 'skip', action_type: 'create_folder', status: 'proposed', reason: 'x', confidence: 1,
                  target_path: '/收藏夹栏/Skipped' },
                { action_id: 'review', action_type: 'keep_for_review', status: 'approved', reason: 'x', confidence: 1,
                  details: { review_agreed: true } },
              ],
            };
            const returned = await executor.execute(plan, {
              onProgress: async (message) => progress.push(message),
            });
            console.log(JSON.stringify({ calls, checkpoints, progress, report, returned }));
            """
        )
        self.assertEqual(result["calls"], ["rename_folder", "move_bookmark", "keep_for_review"])
        self.assertEqual(result["checkpoints"][0]["totalActions"], 3)
        self.assertEqual(result["checkpoints"][-1], "cleared")
        self.assertEqual(len(result["returned"]["succeeded"]), 3)
        self.assertEqual(result["report"], result["returned"])
        self.assertEqual(result["progress"][0], "Starting plan execution...")
        self.assertEqual(result["progress"][-1], "Execution report saved for popup restore.")

    def test_stop_on_failure_requires_literal_true_and_preserves_current_behavior(self) -> None:
        result = self._node_eval(
            """
            async function run(stopValue) {
              const calls = [];
              const executor = BookmarkAdvisor.Background.PlanExecutor.create({
                actionHandlers: { apply: async (action) => {
                  calls.push(action.action_id);
                  if (action.action_id === 'first') throw new Error('boom');
                } },
                bookmarkApi: { getTree: async () => [{ id: '0', title: '', children: [] }] },
                bookmarkTree: { buildFolderPathIndex: () => ({ pathToId: new Map(), idToPath: new Map() }) },
                checkpointStore: { save: async () => {}, clear: async () => {} },
                saveReport: async () => {}, createExecutionId: () => 'exec-fixed',
              });
              const report = await executor.execute({
                plan_version: '2', summary: { stop_on_failure: stopValue }, actions: [
                  { action_id: 'first', action_type: 'move_bookmark', status: 'approved', bookmark_locator: { id: '1' } },
                  { action_id: 'second', action_type: 'move_bookmark', status: 'approved', bookmark_locator: { id: '2' } },
                ],
              });
              return { calls, succeeded: report.succeeded.length, failures: report.failures.length };
            }
            console.log(JSON.stringify({ literal: await run(true), truthy: await run('true'), absent: await run(undefined) }));
            """
        )
        self.assertEqual(result["literal"], {"calls": ["first"], "succeeded": 0, "failures": 1})
        self.assertEqual(result["truthy"]["calls"], ["first", "second"])
        self.assertEqual(result["absent"]["calls"], ["first", "second"])

    def test_executor_uses_injected_cancellation_boundary(self) -> None:
        result = self._node_eval(
            """
            let checks = 0;
            const executor = BookmarkAdvisor.Background.PlanExecutor.create({
              actionHandlers: { apply: async () => {} },
              bookmarkApi: { getTree: async () => [{ id: '0', title: '', children: [] }] },
              bookmarkTree: { buildFolderPathIndex: () => ({ pathToId: new Map(), idToPath: new Map() }) },
              checkpointStore: { save: async () => {}, clear: async () => {} },
              saveReport: async () => {}, createExecutionId: () => 'exec-fixed',
            });
            try {
              await executor.execute({ plan_version: '2', actions: [] }, {
                shouldCancel: async () => ++checks === 1,
              });
            } catch (error) {
              console.log(JSON.stringify({ name: error.name, message: error.message, checks }));
            }
            """
        )
        self.assertEqual(
            result,
            {"name": "AbortError", "message": "Cancelled by user.", "checks": 1},
        )


if __name__ == "__main__":
    unittest.main()
