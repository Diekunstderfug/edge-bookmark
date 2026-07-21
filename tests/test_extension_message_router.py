"""Independent contract tests for the background runtime message router."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "extension" / "shared" / "message_protocol.js"
MESSAGE_ROUTER = ROOT / "extension" / "background" / "message_router.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS tests")
class ExtensionMessageRouterTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          const protocolPath = {json.dumps(str(PROTOCOL))};
          const routerPath = {json.dumps(str(MESSAGE_ROUTER))};
          require(protocolPath);
          {body}
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_module_has_no_registration_side_effect_and_preserves_sync_return_contract(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                let registrations = 0;
                globalThis.chrome = {
                  runtime: { onMessage: { addListener: () => { registrations += 1; } } },
                };
                require(routerPath);

                const protocol = globalThis.BookmarkAdvisor.Protocol;
                const calls = [];
                const listener = globalThis.BookmarkAdvisor.Background.MessageRouter.create({
                  protocol,
                  lifecycle: {
                    start: async () => ({ job: { id: 'unused' } }),
                    waitForCompletion: async () => ({ status: 'succeeded' }),
                    runApplyForeground: async () => ({ status: 'succeeded', result: {} }),
                    getActive: async () => null,
                    cancel: async () => ({ cancelled: true }),
                  },
                  snapshotExport: {
                    exportCurrentSnapshot: async () => ({}),
                    listFolders: async () => [],
                  },
                  runDirectMutation: async (_name, callback) => callback(),
                  undoLastExecution: async () => ({ undone: false }),
                  handleLateOffscreenCompletion: async () => null,
                  handleOffscreenProgress: async (message) => { calls.push(message.message); },
                });

                function invoke(message) {
                  let callbackCalled = false;
                  let response;
                  let resolveCallback;
                  const callbackPromise = new Promise((resolve) => { resolveCallback = resolve; });
                  const returnValue = listener(message, null, (value) => {
                    callbackCalled = true;
                    response = value;
                    resolveCallback(value);
                  });
                  return { callbackCalled, callbackPromise, response, returnValue };
                }

                (async () => {
                  let unknownCallbackCount = 0;
                  const missingReturn = listener(null, null, () => { unknownCallbackCount += 1; });
                  const unknownReturn = listener(
                    { type: 'not-a-real-message' },
                    null,
                    () => { unknownCallbackCount += 1; },
                  );
                  const ready = invoke({ type: protocol.MESSAGE_TYPES.OFFSCREEN_READY });
                  const keepalive = invoke({ type: protocol.MESSAGE_TYPES.OFFSCREEN_KEEPALIVE });
                  const progress = invoke({
                    type: protocol.MESSAGE_TYPES.OFFSCREEN_PROGRESS,
                    jobId: 'job-1',
                    message: 'Parsing response',
                  });
                  const progressResponse = await progress.callbackPromise;
                  console.log(JSON.stringify({
                    registrations,
                    missingReturn: missingReturn === undefined ? 'undefined' : missingReturn,
                    unknownReturn: unknownReturn === undefined ? 'undefined' : unknownReturn,
                    unknownCallbackCount,
                    readyReturn: ready.returnValue,
                    readyCalledSynchronously: ready.callbackCalled,
                    readyResponse: ready.response,
                    keepaliveReturn: keepalive.returnValue,
                    keepaliveCalledSynchronously: keepalive.callbackCalled,
                    keepaliveResponse: keepalive.response,
                    progressReturn: progress.returnValue,
                    progressResponse,
                    progressCalls: calls,
                  }));
                })();
                """
            ),
        )
        self.assertEqual(result["registrations"], 0)
        self.assertEqual(result["missingReturn"], "undefined")
        self.assertEqual(result["unknownReturn"], "undefined")
        self.assertEqual(result["unknownCallbackCount"], 0)
        self.assertEqual(result["readyReturn"], True)
        self.assertEqual(result["readyCalledSynchronously"], True)
        self.assertEqual(result["readyResponse"], {"ok": True})
        self.assertEqual(result["keepaliveReturn"], True)
        self.assertEqual(result["keepaliveCalledSynchronously"], True)
        self.assertEqual(result["keepaliveResponse"], {"ok": True})
        self.assertEqual(result["progressReturn"], True)
        self.assertEqual(result["progressResponse"], {"ok": True})
        self.assertEqual(result["progressCalls"], ["Parsing response"])

    def test_start_get_cancel_export_list_and_undo_delegate_without_waiting(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                require(routerPath);
                const protocol = globalThis.BookmarkAdvisor.Protocol;
                const calls = [];
                let waitCount = 0;
                let undoCount = 0;
                const listener = globalThis.BookmarkAdvisor.Background.MessageRouter.create({
                  protocol,
                  lifecycle: {
                    start: async (type, payload) => {
                      calls.push(['start', type, payload]);
                      return { job: { id: 'job-ack', type, status: 'running' } };
                    },
                    waitForCompletion: async () => { waitCount += 1; return { status: 'succeeded' }; },
                    runApplyForeground: async () => ({ status: 'succeeded', result: {} }),
                    getActive: async () => ({ id: 'job-active', status: 'running' }),
                    cancel: async () => ({ cancelled: true }),
                  },
                  snapshotExport: {
                    exportCurrentSnapshot: async () => ({ snapshot_version: '1' }),
                    listFolders: async () => [{ id: 'f1', path: '/收藏夹栏' }],
                  },
                  runDirectMutation: async (name, callback) => {
                    calls.push(['lock', name]);
                    return callback();
                  },
                  undoLastExecution: async () => {
                    undoCount += 1;
                    return { undone: true, count: 1 };
                  },
                  handleLateOffscreenCompletion: async () => null,
                });

                function dispatch(message) {
                  let returnValue;
                  const response = new Promise((resolve) => {
                    returnValue = listener(message, null, resolve);
                  });
                  return response.then((value) => ({ returnValue, value }));
                }

                (async () => {
                  const started = await dispatch({
                    type: protocol.MESSAGE_TYPES.START_BACKGROUND_JOB,
                    job_type: protocol.JOB_TYPES.APPLY_REVIEWED_PLAN,
                    payload: { plan: { actions: [] } },
                  });
                  const active = await dispatch({ type: protocol.MESSAGE_TYPES.GET_ACTIVE_JOB });
                  const cancelled = await dispatch({ type: protocol.MESSAGE_TYPES.CANCEL_ACTIVE_JOB });
                  const snapshot = await dispatch({ type: protocol.MESSAGE_TYPES.EXPORT_SNAPSHOT });
                  const folders = await dispatch({ type: protocol.MESSAGE_TYPES.LIST_FOLDERS });
                  const undo = await dispatch({ type: protocol.MESSAGE_TYPES.UNDO_LAST_EXECUTION });
                  console.log(JSON.stringify({
                    returnValues: [started, active, cancelled, snapshot, folders, undo].map((item) => item.returnValue),
                    responses: {
                      started: started.value,
                      active: active.value,
                      cancelled: cancelled.value,
                      snapshot: snapshot.value,
                      folders: folders.value,
                      undo: undo.value,
                    },
                    calls,
                    waitCount,
                    undoCount,
                  }));
                })();
                """
            ),
        )
        self.assertEqual(result["returnValues"], [True, True, True, True, True, True])
        responses = cast(dict[str, object], result["responses"])
        self.assertEqual(
            responses["started"],
            {
                "job": {
                    "id": "job-ack",
                    "type": "apply-reviewed-plan",
                    "status": "running",
                }
            },
        )
        self.assertEqual(responses["active"], {"job": {"id": "job-active", "status": "running"}})
        self.assertEqual(responses["cancelled"], {"cancelled": True})
        self.assertEqual(responses["snapshot"], {"snapshot_version": "1"})
        self.assertEqual(responses["folders"], {"folders": [{"id": "f1", "path": "/收藏夹栏"}]})
        self.assertEqual(responses["undo"], {"undone": True, "count": 1})
        self.assertEqual(result["waitCount"], 0, "start-background-job must return before completion")
        self.assertEqual(result["undoCount"], 1)
        self.assertIn(["lock", "undo-last-execution"], result["calls"])

    def test_generate_revise_and_apply_compatibility_paths_return_full_results(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                require(routerPath);
                const protocol = globalThis.BookmarkAdvisor.Protocol;
                const calls = [];
                const lifecycle = {
                  start: async (type, payload) => {
                    calls.push(['start', type, payload]);
                    return { job: { id: type === protocol.JOB_TYPES.GENERATE_AI_PLAN ? 'generate-job' : 'revise-job' } };
                  },
                  waitForCompletion: async (jobId) => {
                    calls.push(['wait', jobId]);
                    if (jobId === 'revise-job') {
                      return {
                        status: protocol.JOB_STATUSES.SUCCEEDED,
                        result: { reviewed_plan: { plan_version: '2', marker: 'revised' } },
                      };
                    }
                    return { status: protocol.JOB_STATUSES.SUCCEEDED };
                  },
                  runApplyForeground: async (payload) => {
                    calls.push(['apply', payload]);
                    return {
                      status: protocol.JOB_STATUSES.SUCCEEDED,
                      result: { succeeded: [{ actionId: 'a1' }], failures: [] },
                    };
                  },
                  getActive: async () => null,
                  cancel: async () => ({ cancelled: true }),
                  loadLastPlan: async () => ({ plan: { plan_version: '2', marker: 'generated' } }),
                };
                const listener = globalThis.BookmarkAdvisor.Background.MessageRouter.create({
                  protocol,
                  lifecycle,
                  snapshotExport: {
                    exportCurrentSnapshot: async () => ({}),
                    listFolders: async () => [],
                  },
                  runDirectMutation: async (_name, callback) => callback(),
                  undoLastExecution: async () => ({ undone: false }),
                  handleLateOffscreenCompletion: async () => null,
                });

                function dispatch(message) {
                  let returnValue;
                  const response = new Promise((resolve) => {
                    returnValue = listener(message, null, resolve);
                  });
                  return response.then((value) => ({ returnValue, value }));
                }

                (async () => {
                  const generated = await dispatch({
                    type: protocol.MESSAGE_TYPES.GENERATE_AI_PLAN,
                    options: { model: 'test-model' },
                  });
                  const revised = await dispatch({
                    type: protocol.MESSAGE_TYPES.REVISE_AI_PLAN,
                    plan: { actions: [] },
                    options: { model: 'test-model-2' },
                  });
                  const applied = await dispatch({
                    type: protocol.MESSAGE_TYPES.APPLY_REVIEWED_PLAN,
                    plan: { actions: [{ action_id: 'a1' }] },
                    focusPath: '/收藏夹栏/AI',
                  });
                  console.log(JSON.stringify({ generated, revised, applied, calls }));
                })();
                """
            ),
        )
        self.assertEqual(result["generated"]["returnValue"], True)
        self.assertEqual(
            result["generated"]["value"],
            {"reviewed_plan": {"plan_version": "2", "marker": "generated"}},
        )
        self.assertEqual(
            result["revised"]["value"],
            {"reviewed_plan": {"plan_version": "2", "marker": "revised"}},
        )
        self.assertEqual(
            result["applied"]["value"],
            {"succeeded": [{"actionId": "a1"}], "failures": []},
        )
        calls = cast(list[list[object]], result["calls"])
        self.assertIn(["wait", "generate-job"], calls)
        self.assertIn(["wait", "revise-job"], calls)
        self.assertIn(
            [
                "apply",
                {
                    "plan": {"actions": [{"action_id": "a1"}]},
                    "focusPath": "/收藏夹栏/AI",
                },
            ],
            calls,
        )

    def test_offscreen_completion_and_async_failures_use_stable_error_envelope(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                require(routerPath);
                const protocol = globalThis.BookmarkAdvisor.Protocol;
                const logs = [];
                const listener = globalThis.BookmarkAdvisor.Background.MessageRouter.create({
                  protocol,
                  lifecycle: {
                    start: async () => ({ job: { id: 'unused' } }),
                    waitForCompletion: async () => ({ status: 'succeeded' }),
                    runApplyForeground: async () => ({ status: 'succeeded', result: {} }),
                    getActive: async () => { throw new Error('active read failed'); },
                    cancel: async () => ({ cancelled: true }),
                  },
                  snapshotExport: {
                    exportCurrentSnapshot: async () => { throw new Error('snapshot failed'); },
                    listFolders: async () => [],
                  },
                  runDirectMutation: async (_name, callback) => callback(),
                  undoLastExecution: async () => ({ undone: false }),
                  handleLateOffscreenCompletion: async (message) => {
                    if (message.type === protocol.MESSAGE_TYPES.OFFSCREEN_ERROR) {
                      throw new Error('late completion failed');
                    }
                    return { id: message.jobId };
                  },
                  logger: (message) => {
                    logs.push(message);
                    if (message === 'active read failed') throw new Error('logger failed');
                  },
                });

                function dispatch(message) {
                  let returnValue;
                  const response = new Promise((resolve) => {
                    returnValue = listener(message, null, resolve);
                  });
                  return response.then((value) => ({ returnValue, value }));
                }

                (async () => {
                  const restored = await dispatch({
                    type: protocol.MESSAGE_TYPES.OFFSCREEN_RESULT,
                    jobId: 'late-job',
                    result: {},
                  });
                  const lateFailure = await dispatch({
                    type: protocol.MESSAGE_TYPES.OFFSCREEN_ERROR,
                    jobId: 'failed-job',
                    error: 'provider error',
                  });
                  const snapshotFailure = await dispatch({ type: protocol.MESSAGE_TYPES.EXPORT_SNAPSHOT });
                  const activeFailure = await dispatch({ type: protocol.MESSAGE_TYPES.GET_ACTIVE_JOB });
                  console.log(JSON.stringify({ restored, lateFailure, snapshotFailure, activeFailure, logs }));
                })();
                """
            ),
        )
        self.assertEqual(result["restored"], {"returnValue": True, "value": {"ok": True, "recovered": True}})
        self.assertEqual(
            result["lateFailure"],
            {"returnValue": True, "value": {"ok": False, "error": "late completion failed"}},
        )
        self.assertEqual(
            result["snapshotFailure"],
            {"returnValue": True, "value": {"ok": False, "error": "snapshot failed"}},
        )
        self.assertEqual(
            result["activeFailure"],
            {"returnValue": True, "value": {"ok": False, "error": "active read failed"}},
        )
        self.assertIn("late completion failed", result["logs"])
        self.assertIn("snapshot failed", result["logs"])

    def test_compatibility_failures_keep_plan_and_execution_response_shapes(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                require(routerPath);
                const protocol = globalThis.BookmarkAdvisor.Protocol;
                const logs = [];
                let applyAttempt = 0;
                const listener = globalThis.BookmarkAdvisor.Background.MessageRouter.create({
                  protocol,
                  lifecycle: {
                    start: async (type) => type === protocol.JOB_TYPES.GENERATE_AI_PLAN
                      ? { error: 'busy' }
                      : { job: { id: 'revise-job' } },
                    waitForCompletion: async () => ({
                      status: protocol.JOB_STATUSES.FAILED,
                      error: 'revision failed',
                    }),
                    runApplyForeground: async () => {
                      applyAttempt += 1;
                      if (applyAttempt === 1) {
                        return { status: protocol.JOB_STATUSES.FAILED, error: 'apply failed' };
                      }
                      throw new Error('apply crashed');
                    },
                    getActive: async () => null,
                    cancel: async () => ({ cancelled: true }),
                  },
                  snapshotExport: {
                    exportCurrentSnapshot: async () => ({}),
                    listFolders: async () => [],
                  },
                  runDirectMutation: async (_name, callback) => callback(),
                  undoLastExecution: async () => ({ undone: false }),
                  handleLateOffscreenCompletion: async () => null,
                  logger: (message) => { logs.push(message); },
                });

                function dispatch(message) {
                  return new Promise((resolve) => listener(message, null, resolve));
                }

                (async () => {
                  const generated = await dispatch({ type: protocol.MESSAGE_TYPES.GENERATE_AI_PLAN });
                  const revised = await dispatch({ type: protocol.MESSAGE_TYPES.REVISE_AI_PLAN, plan: { actions: [] } });
                  const applyFailed = await dispatch({ type: protocol.MESSAGE_TYPES.APPLY_REVIEWED_PLAN, plan: { actions: [] } });
                  const applyCrashed = await dispatch({ type: protocol.MESSAGE_TYPES.APPLY_REVIEWED_PLAN, plan: { actions: [] } });
                  console.log(JSON.stringify({ generated, revised, applyFailed, applyCrashed, logs }));
                })();
                """
            ),
        )
        self.assertEqual(result["generated"], {"ok": False, "error": "busy"})
        self.assertEqual(result["revised"], {"ok": False, "error": "revision failed"})
        self.assertEqual(result["applyFailed"]["succeeded"], [])
        self.assertEqual(result["applyFailed"]["failures"][0]["error"], "apply failed")
        self.assertEqual(result["applyCrashed"]["failures"][0]["error"], "apply crashed")
        self.assertIn("AI planning failed: busy", result["logs"])
        self.assertIn("AI plan revision failed: revision failed", result["logs"])
        self.assertIn("Execution failed: apply failed", result["logs"])
        self.assertIn("Execution failed: apply crashed", result["logs"])


if __name__ == "__main__":
    unittest.main()
