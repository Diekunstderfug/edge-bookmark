"""Independent tests for the popup runtime messaging client."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "extension" / "shared" / "message_protocol.js"
RUNTIME_CLIENT = ROOT / "extension" / "popup" / "runtime_client.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS tests")
class ExtensionPopupRuntimeClientTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          const protocolPath = {json.dumps(str(PROTOCOL))};
          const runtimeClientPath = {json.dumps(str(RUNTIME_CLIENT))};
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

    def test_sync_async_promise_and_undefined_responses_have_no_registration_side_effect(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                let runtimeRegistrations = 0;
                let storageRegistrations = 0;
                globalThis.chrome = {
                  runtime: {
                    lastError: null,
                    onMessage: { addListener: () => { runtimeRegistrations += 1; } },
                    sendMessage: (payload, callback) => {
                      if (payload.kind === 'sync') {
                        callback({ mode: 'sync' });
                        return undefined;
                      }
                      if (payload.kind === 'async') {
                        setTimeout(() => callback({ mode: 'async' }), 0);
                        return undefined;
                      }
                      if (payload.kind === 'promise') {
                        return Promise.resolve({ mode: 'promise' });
                      }
                      callback(undefined);
                      return undefined;
                    },
                  },
                  storage: {
                    onChanged: { addListener: () => { storageRegistrations += 1; } },
                  },
                };
                require(runtimeClientPath);
                const client = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
                  chrome: globalThis.chrome,
                  protocol: globalThis.BookmarkAdvisor.Protocol,
                });

                (async () => {
                  const sync = await client.send({ kind: 'sync' });
                  const asyncResponse = await client.send({ kind: 'async' });
                  const promiseResponse = await client.send({ kind: 'promise' });
                  const unknown = await client.send({ kind: 'unknown' });
                  console.log(JSON.stringify({
                    sync,
                    asyncResponse,
                    promiseResponse,
                    unknownIsUndefined: unknown === undefined,
                    runtimeRegistrations,
                    storageRegistrations,
                  }));
                })();
                """
            ),
        )
        self.assertEqual(result["sync"], {"mode": "sync"})
        self.assertEqual(result["asyncResponse"], {"mode": "async"})
        self.assertEqual(result["promiseResponse"], {"mode": "promise"})
        self.assertEqual(result["unknownIsUndefined"], True)
        self.assertEqual(result["runtimeRegistrations"], 0)
        self.assertEqual(result["storageRegistrations"], 0)

    def test_runtime_last_error_rejects_with_original_message(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const chromeApi = {
                  runtime: {
                    lastError: null,
                    sendMessage: (_payload, callback) => {
                      chromeApi.runtime.lastError = { message: 'Could not establish connection.' };
                      callback(undefined);
                      chromeApi.runtime.lastError = null;
                    },
                  },
                };
                require(runtimeClientPath);
                const client = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
                  chrome: chromeApi,
                  protocol: globalThis.BookmarkAdvisor.Protocol,
                });
                client.send({ type: 'test' }).then(
                  () => console.log(JSON.stringify({ resolved: true })),
                  (error) => console.log(JSON.stringify({
                    resolved: false,
                    name: error.name,
                    message: error.message,
                  })),
                );
                """
            ),
        )
        self.assertEqual(
            result,
            {
                "resolved": False,
                "name": "Error",
                "message": "Could not establish connection.",
            },
        )

    def test_send_message_synchronous_throw_and_returned_promise_rejection_propagate(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const chromeApi = {
                  runtime: {
                    lastError: null,
                    sendMessage: (payload, _callback) => {
                      if (payload.kind === 'throw') throw new Error('sync send failure');
                      return Promise.reject(new Error('async send failure'));
                    },
                  },
                };
                require(runtimeClientPath);
                const client = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
                  chrome: chromeApi,
                  protocol: globalThis.BookmarkAdvisor.Protocol,
                });
                (async () => {
                  const messages = [];
                  try { await client.send({ kind: 'throw' }); } catch (error) { messages.push(error.message); }
                  try { await client.send({ kind: 'reject' }); } catch (error) { messages.push(error.message); }
                  console.log(JSON.stringify(messages));
                })();
                """
            ),
        )
        self.assertEqual(result, ["sync send failure", "async send failure"])

    def test_timeout_uses_exact_existing_message_and_per_call_override(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                let timeoutCallback = null;
                let timeoutDelay = null;
                let clearCount = 0;
                let runtimeCallback = null;
                const timers = {
                  setTimeout: (callback, delay) => {
                    timeoutCallback = callback;
                    timeoutDelay = delay;
                    return 'timer-1';
                  },
                  clearTimeout: () => { clearCount += 1; },
                };
                const chromeApi = {
                  runtime: {
                    lastError: null,
                    sendMessage: (_payload, callback) => { runtimeCallback = callback; },
                  },
                };
                require(runtimeClientPath);
                const client = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
                  chrome: chromeApi,
                  protocol: globalThis.BookmarkAdvisor.Protocol,
                  timers,
                  timeoutMs: 999,
                });
                const pending = client.send({ type: 'never-responds' }, 321);
                timeoutCallback();
                runtimeCallback({ tooLate: true });
                pending.then(
                  () => console.log(JSON.stringify({ resolved: true })),
                  (error) => console.log(JSON.stringify({
                    resolved: false,
                    message: error.message,
                    timeoutDelay,
                    clearCount,
                  })),
                );
                """
            ),
        )
        self.assertEqual(result["resolved"], False)
        self.assertEqual(result["timeoutDelay"], 321)
        self.assertEqual(result["clearCount"], 0)
        self.assertEqual(
            result["message"],
            "Extension background task timed out. Reload the extension and check that "
            "Bookmark permission is enabled.",
        )

    def test_typed_wrappers_send_protocol_payloads_and_keep_existing_timeouts(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const payloads = [];
                const delays = [];
                const timers = {
                  setTimeout: (_callback, delay) => { delays.push(delay); return delays.length; },
                  clearTimeout: () => {},
                };
                const protocol = globalThis.BookmarkAdvisor.Protocol;
                const chromeApi = {
                  runtime: {
                    lastError: null,
                    sendMessage: (payload, callback) => {
                      payloads.push(payload);
                      const responses = {
                        [protocol.MESSAGE_TYPES.START_BACKGROUND_JOB]: { job: { id: 'job-1', status: 'running' } },
                        [protocol.MESSAGE_TYPES.GET_ACTIVE_JOB]: { job: { id: 'job-active' } },
                        [protocol.MESSAGE_TYPES.CANCEL_ACTIVE_JOB]: { cancelled: true },
                        [protocol.MESSAGE_TYPES.EXPORT_SNAPSHOT]: { snapshot_version: '1' },
                        [protocol.MESSAGE_TYPES.LIST_FOLDERS]: { folders: [{ id: 'f1' }] },
                        [protocol.MESSAGE_TYPES.UNDO_LAST_EXECUTION]: { undone: true },
                      };
                      callback(responses[payload.type]);
                    },
                  },
                };
                require(runtimeClientPath);
                const client = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
                  chrome: chromeApi,
                  protocol,
                  timers,
                });
                (async () => {
                  const responses = [
                    await client.startJob(protocol.JOB_TYPES.GENERATE_AI_PLAN, { options: { model: 'test' } }),
                    await client.getActiveJob(),
                    await client.cancel(),
                    await client.exportSnapshot(),
                    await client.listFolders(),
                    await client.undo(),
                  ];
                  console.log(JSON.stringify({ payloads, delays, responses }));
                })();
                """
            ),
        )
        self.assertEqual(
            result["payloads"],
            [
                {
                    "type": "start-background-job",
                    "job_type": "generate-ai-plan",
                    "payload": {"options": {"model": "test"}},
                },
                {"type": "get-active-job"},
                {"type": "cancel-active-job"},
                {"type": "export-snapshot"},
                {"type": "list-folders"},
                {"type": "undo-last-execution"},
            ],
        )
        self.assertEqual(result["delays"], [10000, 5000, 240000, 240000, 10000, 240000])
        self.assertEqual(result["responses"][0], {"job": {"id": "job-1", "status": "running"}})
        self.assertEqual(result["responses"][4], {"folders": [{"id": "f1"}]})

    def test_start_job_preserves_error_and_missing_job_record_messages(self) -> None:
        result = cast(
            list[str],
            self._node_eval(
                r"""
                let callCount = 0;
                const chromeApi = {
                  runtime: {
                    lastError: null,
                    sendMessage: (_payload, callback) => {
                      callCount += 1;
                      callback(callCount === 1 ? { error: 'Background job already running.' } : undefined);
                    },
                  },
                };
                require(runtimeClientPath);
                const client = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
                  chrome: chromeApi,
                  protocol: globalThis.BookmarkAdvisor.Protocol,
                });
                (async () => {
                  const messages = [];
                  try { await client.startJob('generate-ai-plan', {}); } catch (error) { messages.push(error.message); }
                  try { await client.startJob('generate-ai-plan', {}); } catch (error) { messages.push(error.message); }
                  console.log(JSON.stringify(messages));
                })();
                """
            ),
        )
        self.assertEqual(
            result,
            [
                "Background job already running.",
                "Background executor did not return a job record.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
