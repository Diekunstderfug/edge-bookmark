"""Unit tests for background job-type orchestration."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionJobHandlersTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'job_handlers.js'))});
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
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_generate_exports_calls_llm_saves_and_finishes(self) -> None:
        result = self._node_eval(
            """
            const calls = [];
            const snapshot = { bookmarks: [{ id: 'b1' }], folders: [{ id: 'f1' }] };
            const reviewedPlan = { actions: [{ action_id: 'a1' }] };
            const controller = { signal: 'controller-marker' };
            const handlers = BookmarkAdvisor.Background.JobHandlers.create({
              protocol: BookmarkAdvisor.Protocol,
              snapshotExport: {
                exportCurrentSnapshot: async () => { calls.push(['snapshot']); return snapshot; },
              },
              runLlm: async (job, mode, payload, receivedController) => {
                calls.push(['llm', job.id, mode, payload, receivedController === controller]);
                return { reviewed_plan: reviewedPlan };
              },
              executePlan: async () => { throw new Error('unexpected execute'); },
              saveLastPlan: async (plan) => calls.push(['save', plan]),
            });
            const stages = [];
            const progress = [];
            const finishes = [];
            const options = {
              apiKey: 'secret', apiBaseUrl: 'https://example.test/v1', apiStyle: 'responses',
              model: 'm', maxActions: 12, requestTimeoutMs: 3456, maxRetries: 2,
              focusPath: '/A', userInstruction: 'tidy', preferences: { language: 'zh' },
            };
            const returned = await handlers.run(
              { id: 'job-g', type: BookmarkAdvisor.Protocol.JOB_TYPES.GENERATE_AI_PLAN },
              { options },
              {
                controller,
                ensureOffscreen: async () => calls.push(['ensure']),
                setStage: async (_job, stage) => stages.push(stage),
                onProgress: async (message) => progress.push(message),
                finish: async (job, value, message) => finishes.push([job.id, value, message]),
              },
            );
            console.log(JSON.stringify({ calls, stages, progress, finishes, returned, snapshot }));
            """
        )
        self.assertEqual(result["stages"], ["export", "llm", "save"])
        self.assertEqual(result["calls"][0], ["snapshot"])
        self.assertEqual(result["calls"][1], ["ensure"])
        self.assertEqual(result["calls"][2][0:3], ["llm", "job-g", "generate"])
        self.assertTrue(result["calls"][2][4])
        llm_payload = result["calls"][2][3]
        self.assertEqual(llm_payload["snapshot"], result["snapshot"])
        self.assertEqual(llm_payload["apiKey"], "secret")
        self.assertNotIn("options", llm_payload)
        self.assertEqual(result["calls"][3], ["save", {"actions": [{"action_id": "a1"}]}])
        self.assertEqual(result["finishes"][0][0], "job-g")
        self.assertEqual(result["finishes"][0][2], "AI plan generated.")
        self.assertEqual(result["returned"], {"reviewed_plan": {"actions": [{"action_id": "a1"}]}})
        self.assertEqual(result["progress"][0], "Exporting current bookmarks...")
        self.assertEqual(result["progress"][-1], "AI plan generated and saved for popup restore.")

    def test_revise_keeps_plan_outside_options_and_rejects_invalid_plan(self) -> None:
        result = self._node_eval(
            """
            const seen = [];
            const handlers = BookmarkAdvisor.Background.JobHandlers.create({
              protocol: BookmarkAdvisor.Protocol,
              snapshotExport: { exportCurrentSnapshot: async () => ({ bookmarks: [], folders: [] }) },
              runLlm: async (_job, mode, payload) => {
                seen.push({ mode, payload });
                return { reviewed_plan: { actions: [] } };
              },
              executePlan: async () => {},
              saveLastPlan: async () => {},
            });
            const context = {
              setStage: async () => {}, onProgress: async () => {}, finish: async () => {},
            };
            const job = { id: 'job-r', type: BookmarkAdvisor.Protocol.JOB_TYPES.REVISE_AI_PLAN };
            const plan = { plan_version: '2', actions: [] };
            await handlers.run(job, { options: { model: 'm' }, plan }, context);
            let invalid = '';
            try { await handlers.run(job, { options: {}, plan: {} }, context); }
            catch (error) { invalid = error.message; }
            console.log(JSON.stringify({ seen, invalid }));
            """
        )
        self.assertEqual(result["seen"][0]["mode"], "revise")
        self.assertEqual(result["seen"][0]["payload"]["plan"], {"plan_version": "2", "actions": []})
        self.assertEqual(result["seen"][0]["payload"]["options"]["model"], "m")
        self.assertIn("snapshot", result["seen"][0]["payload"]["options"])
        self.assertEqual(
            result["invalid"],
            "Load a reviewed plan before asking the LLM to revise it.",
        )

    def test_apply_delegates_to_executor_and_unsupported_type_fails_closed(self) -> None:
        result = self._node_eval(
            """
            const calls = [];
            const handlers = BookmarkAdvisor.Background.JobHandlers.create({
              protocol: BookmarkAdvisor.Protocol,
              snapshotExport: { exportCurrentSnapshot: async () => ({}) },
              runLlm: async () => ({}),
              executePlan: async (plan, focusPath, onProgress, job) => {
                calls.push({ plan, focusPath, sameProgress: onProgress === progress, job });
                return { succeeded: [], failures: [] };
              },
              saveLastPlan: async () => {},
            });
            const progress = async () => {};
            const finishes = [];
            const plan = { actions: [] };
            const returned = await handlers.run(
              { id: 'job-a', type: BookmarkAdvisor.Protocol.JOB_TYPES.APPLY_REVIEWED_PLAN },
              { plan, focusPath: '/Scope' },
              { onProgress: progress, finish: async (...args) => finishes.push(args) },
            );
            let unsupported = '';
            try { await handlers.run({ id: 'x', type: 'unknown' }, {}, {}); }
            catch (error) { unsupported = error.message; }
            console.log(JSON.stringify({ calls, finishes, returned, unsupported }));
            """
        )
        self.assertEqual(
            result["calls"],
            [{"plan": {"actions": []}, "focusPath": "/Scope", "sameProgress": True, "job": {"id": "job-a"}}],
        )
        self.assertEqual(result["finishes"][0][0]["id"], "job-a")
        self.assertEqual(result["finishes"][0][2], "Execution complete.")
        self.assertEqual(result["returned"], {"succeeded": [], "failures": []})
        self.assertEqual(result["unsupported"], "Unsupported background job type: unknown")


if __name__ == "__main__":
    unittest.main()
