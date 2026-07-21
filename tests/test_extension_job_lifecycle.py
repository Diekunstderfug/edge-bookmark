"""Independent tests for the extracted background-job lifecycle."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionJobLifecycleTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'job_store.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'job_lifecycle.js'))});

          const protocol = BookmarkAdvisor.Protocol;
          const values = new Map();
          const writes = [];
          let now = Date.parse('2026-07-10T08:00:00.000Z');
          const clone = (value) => value === undefined ? undefined : structuredClone(value);
          const storage = {{
            async get(key) {{ return clone(values.get(key)); }},
            async set(key, value) {{
              values.set(key, clone(value));
              writes.push([key, clone(value)]);
            }},
            async remove(key) {{ values.delete(key); }},
          }};
          const jobStore = BookmarkAdvisor.Background.JobStore.create({{
            storage,
            protocol,
            clock: () => now,
          }});
          const alarmEvents = [];
          const alarms = {{
            create(name, options) {{ alarmEvents.push(['create', name, options]); }},
            clear(name) {{ alarmEvents.push(['clear', name]); return Promise.resolve(true); }},
          }};
          const offscreenEvents = [];
          const baseOffscreen = {{
            async ensureDocument() {{ offscreenEvents.push('ensure'); return true; }},
            async closeDocument() {{ offscreenEvents.push('close'); return true; }},
            async cancel() {{ offscreenEvents.push('cancel'); return {{ ok: true }}; }},
            async ping() {{ return {{ ok: true, busy: false, jobId: null }}; }},
            async loadPersistedResult(jobId) {{
              const value = await storage.get(protocol.STORAGE_KEYS.OFFSCREEN_RESULT);
              if (!value || (jobId && value.jobId !== jobId)) return null;
              return value;
            }},
            async clearPersistedResult(jobId) {{
              const value = await storage.get(protocol.STORAGE_KEYS.OFFSCREEN_RESULT);
              if (!value || (jobId && value.jobId !== jobId)) return false;
              await storage.remove(protocol.STORAGE_KEYS.OFFSCREEN_RESULT);
              offscreenEvents.push(`clear:${{jobId || '*'}}`);
              return true;
            }},
          }};
          const savedPlans = [];
          const savedReports = [];

          function makeLifecycle(runHandler, overrides = {{}}) {{
            const offscreenClient = Object.assign({{}}, baseOffscreen, overrides.offscreenClient || {{}});
            return BookmarkAdvisor.Background.JobLifecycle.create({{
              protocol,
              jobStore,
              jobHandlers: {{ run: runHandler }},
              offscreenClient,
              storage,
              alarms,
              runId: overrides.runId || 'sw-current',
              jobIdFactory: overrides.jobIdFactory || ((milliseconds) => `job-${{milliseconds}}`),
              clock: {{
                now: () => now,
                sleep: async (milliseconds) => {{ now += milliseconds; }},
              }},
              saveLastPlan: async (plan) => {{
                savedPlans.push(clone(plan));
                await storage.set(protocol.STORAGE_KEYS.LAST_PLAN, {{
                  plan: clone(plan), saved_at: new Date(now).toISOString(),
                }});
              }},
              saveLastReport: async (report) => {{
                savedReports.push(clone(report));
                await storage.set(protocol.STORAGE_KEYS.LAST_REPORT, clone(report));
              }},
              log: (...parts) => offscreenEvents.push(`log:${{parts.join(' ')}}`),
            }});
          }}

          async function waitUntil(predicate, limit = 100) {{
            for (let index = 0; index < limit; index += 1) {{
              if (await predicate()) return;
              await Promise.resolve();
            }}
            throw new Error('waitUntil condition was not reached');
          }}

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

    def test_detached_ack_lock_and_foreground_full_result_contract(self) -> None:
        result = self._node_eval(
            """
            let releaseDetached;
            const detachedGate = new Promise((resolve) => { releaseDetached = resolve; });
            let detachedStarted = false;
            const lifecycle = makeLifecycle(async (job, payload, context) => {
              await context.setStage(job, protocol.JOB_STAGES.LLM);
              await context.onProgress(`working:${payload.label}`);
              detachedStarted = true;
              await detachedGate;
              const result = { reviewed_plan: { actions: [{ action_id: 'a1' }] } };
              await context.finish(job, result, 'AI plan generated.');
              return result;
            });

            const acknowledged = await lifecycle.startBackgroundJob(
              protocol.JOB_TYPES.GENERATE_AI_PLAN,
              { label: 'detached' },
            );
            await waitUntil(() => detachedStarted);
            const storedDuringRun = await jobStore.get();
            const collision = await lifecycle.startBackgroundJob(
              protocol.JOB_TYPES.REVISE_AI_PLAN,
              {},
            );
            releaseDetached();
            await waitUntil(async () => (await jobStore.get()).status === protocol.JOB_STATUSES.SUCCEEDED);
            await waitUntil(() => lifecycle.getRunningJobId() === '');
            const detachedStored = await jobStore.get();

            now += 1000;
            const foregroundLifecycle = makeLifecycle(async (job, _payload, context) => {
              const report = { succeeded: [{ actionId: 'a2' }], failures: [] };
              await context.finish(job, report, 'Execution complete.');
              return report;
            });
            const foreground = await foregroundLifecycle.runForeground(
              protocol.JOB_TYPES.APPLY_REVIEWED_PLAN,
              { plan: { actions: [] } },
            );
            const foregroundStored = await jobStore.get();
            console.log(JSON.stringify({
              acknowledged,
              storedDuringRun,
              collision,
              detachedStored,
              foreground,
              foregroundStored,
              alarmEvents,
              offscreenEvents,
            }));
            """
        )
        acknowledged = result["acknowledged"]["job"]
        self.assertEqual(acknowledged["type"], "generate-ai-plan")
        self.assertEqual(acknowledged["status"], "running")
        self.assertEqual(acknowledged["owner_run_id"], "sw-current")
        self.assertEqual(result["storedDuringRun"]["stage"], "llm")
        self.assertEqual(result["storedDuringRun"]["progress"], "working:detached")
        self.assertEqual(
            result["collision"],
            {"error": "Background job already running in this service worker."},
        )
        self.assertEqual(result["detachedStored"]["status"], "succeeded")
        self.assertNotIn("result", result["detachedStored"])
        self.assertEqual(
            result["detachedStored"]["result_summary"],
            {"type": "plan", "action_count": 1},
        )
        self.assertEqual(result["foreground"]["status"], "succeeded")
        self.assertEqual(
            result["foreground"]["result"],
            {"succeeded": [{"actionId": "a2"}], "failures": []},
        )
        self.assertNotIn("result", result["foregroundStored"])
        self.assertEqual(
            result["foregroundStored"]["result_summary"],
            {"type": "report", "succeeded_count": 1, "failure_count": 0},
        )
        self.assertIn("close", result["offscreenEvents"])

    def test_cancel_aborts_inflight_job_and_persists_cancellation(self) -> None:
        result = self._node_eval(
            """
            let handlerStarted = false;
            let observedAbort = null;
            const lifecycle = makeLifecycle(async (job, _payload, context) => {
              handlerStarted = true;
              await new Promise((resolve, reject) => {
                context.controller.signal.addEventListener('abort', () => {
                  observedAbort = {
                    aborted: context.controller.signal.aborted,
                    name: BookmarkAdvisor.Background.JobLifecycle.createAbortError('Cancelled by user.').name,
                    code: BookmarkAdvisor.Background.JobLifecycle.createAbortError('Cancelled by user.').code,
                  };
                  reject(BookmarkAdvisor.Background.JobLifecycle.createAbortError('Cancelled by user.'));
                }, { once: true });
              });
            });
            const acknowledged = await lifecycle.start(
              protocol.JOB_TYPES.GENERATE_AI_PLAN,
              {},
            );
            await waitUntil(() => handlerStarted);
            const cancelResult = await lifecycle.cancelActiveJob();
            await waitUntil(async () => (await jobStore.get()).status === protocol.JOB_STATUSES.FAILED);
            await waitUntil(() => lifecycle.getRunningJobId() === '');
            const stored = await jobStore.get();
            console.log(JSON.stringify({
              acknowledged,
              cancelResult,
              observedAbort,
              stored,
              progressSidecar: await storage.get(protocol.STORAGE_KEYS.PROGRESS),
              offscreenEvents,
              abortLike: BookmarkAdvisor.Background.JobLifecycle.isAbortLikeError(
                new Error('request was aborted'),
              ),
            }));
            """
        )
        self.assertEqual(result["cancelResult"], {"cancelled": True})
        self.assertEqual(
            result["observedAbort"],
            {"aborted": True, "name": "AbortError", "code": 20},
        )
        self.assertEqual(result["stored"]["status"], "failed")
        self.assertEqual(result["stored"]["error"], "Cancelled by user.")
        self.assertTrue(result["stored"]["cancellation_requested_at"])
        self.assertIsNone(result["progressSidecar"])
        self.assertIn("cancel", result["offscreenEvents"])
        self.assertIn("close", result["offscreenEvents"])
        self.assertTrue(result["abortLike"])

    def test_startup_recovers_checkpoint_then_persisted_offscreen_result(self) -> None:
        result = self._node_eval(
            """
            await storage.set(protocol.STORAGE_KEYS.EXECUTION_CHECKPOINT, {
              executionId: 'exec-1', done: 2, totalActions: 4,
              succeeded: [{ actionId: 'a1', executed_at: '2026-07-10T07:30:00.000Z' }],
              failures: [{ actionId: 'a2', error: 'failed before restart' }],
            });
            await jobStore.save({
              id: 'job-recover', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: protocol.JOB_STATUSES.RUNNING, stage: protocol.JOB_STAGES.LLM,
              owner_run_id: 'sw-dead', progress: 'Calling LLM...',
              started_at: '2026-07-10T07:59:30.000Z',
              updated_at: '2026-07-10T07:59:30.000Z',
            });
            await storage.set(protocol.STORAGE_KEYS.OFFSCREEN_RESULT, {
              jobId: 'job-recover', ok: true,
              result: { reviewed_plan: { actions: [{ action_id: 'from-persisted' }] } },
            });
            const lifecycle = makeLifecycle(async () => {
              throw new Error('startup recovery must not execute handlers');
            });
            const recovered = await lifecycle.cleanupStaleActiveJobOnStartup();
            const stored = await jobStore.get();
            const secondCleanup = await lifecycle.cleanupStaleActiveJobOnStartup();
            console.log(JSON.stringify({
              recovered,
              stored,
              secondCleanup,
              checkpoint: await storage.get(protocol.STORAGE_KEYS.EXECUTION_CHECKPOINT),
              persisted: (await storage.get(protocol.STORAGE_KEYS.OFFSCREEN_RESULT)) ?? null,
              savedPlans,
              savedReports,
            }));
            """
        )
        self.assertEqual(result["stored"]["status"], "succeeded")
        self.assertEqual(result["stored"]["progress"], "Restored from offscreen after SW restart.")
        self.assertEqual(
            result["stored"]["result_summary"],
            {"type": "plan", "action_count": 1},
        )
        self.assertIsNone(result["checkpoint"])
        self.assertIsNone(result["persisted"])
        self.assertEqual(result["savedPlans"][0]["actions"][0]["action_id"], "from-persisted")
        self.assertEqual(result["savedReports"][0]["partial"], True)
        self.assertEqual(result["savedReports"][0]["executed_at"], "2026-07-10T07:30:00.000Z")
        self.assertEqual(result["savedReports"][0]["partial_reason"], "Service worker interrupted during execution.")
        self.assertIsNone(result["secondCleanup"])

    def test_startup_verifies_fresh_llm_and_fails_interrupted_or_stale_jobs(self) -> None:
        result = self._node_eval(
            """
            const noOpHandler = async () => null;
            await jobStore.save({
              id: 'job-matching', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: 'running', stage: 'llm', owner_run_id: 'sw-old',
              started_at: '2026-07-10T07:59:30.000Z', updated_at: '2026-07-10T07:59:30.000Z',
            });
            const matchingLifecycle = makeLifecycle(noOpHandler, {
              offscreenClient: {
                ping: async () => ({ ok: true, busy: true, jobId: 'job-matching' }),
              },
            });
            const matching = await matchingLifecycle.cleanupOnStartup();

            await jobStore.save({
              id: 'job-mismatch', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: 'running', stage: 'llm', owner_run_id: 'sw-old',
              started_at: '2026-07-10T07:59:30.000Z', updated_at: '2026-07-10T07:59:30.000Z',
            });
            const mismatchLifecycle = makeLifecycle(noOpHandler, {
              offscreenClient: {
                ping: async () => ({ ok: true, busy: true, jobId: 'other-job' }),
              },
            });
            const mismatch = await mismatchLifecycle.cleanupOnStartup();

            await jobStore.save({
              id: 'job-fresh-export', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: 'running', stage: 'export', owner_run_id: 'sw-old',
              started_at: '2026-07-10T07:59:30.000Z', updated_at: '2026-07-10T07:59:30.000Z',
            });
            const interruptedLifecycle = makeLifecycle(noOpHandler);
            const interrupted = await interruptedLifecycle.cleanupOnStartup();

            await jobStore.save({
              id: 'job-stale', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: 'running', stage: 'llm', owner_run_id: 'sw-old',
              started_at: '2026-07-10T06:00:00.000Z', updated_at: '2026-07-10T06:00:00.000Z',
            });
            const staleLifecycle = makeLifecycle(noOpHandler);
            const stale = await staleLifecycle.cleanupOnStartup();
            console.log(JSON.stringify({ matching, mismatch, interrupted, stale }));
            """
        )
        self.assertEqual(result["matching"]["status"], "running")
        self.assertEqual(result["matching"]["id"], "job-matching")
        self.assertEqual(result["mismatch"]["status"], "failed")
        self.assertIn("another job (other-job)", result["mismatch"]["error"])
        self.assertEqual(result["interrupted"]["status"], "failed")
        self.assertEqual(
            result["interrupted"]["error"],
            "Service worker restarted. Background job was interrupted.",
        )
        self.assertEqual(result["stale"]["status"], "failed")
        self.assertEqual(result["stale"]["error"], "Background job timed out before completion.")

    def test_late_result_prefers_persisted_payload_and_popup_rehydrates_it(self) -> None:
        result = self._node_eval(
            """
            await jobStore.save({
              id: 'job-late', type: protocol.JOB_TYPES.REVISE_AI_PLAN,
              status: 'running', stage: 'llm', owner_run_id: 'sw-dead',
              started_at: '2026-07-10T07:59:30.000Z', updated_at: '2026-07-10T07:59:30.000Z',
            });
            await storage.set(protocol.STORAGE_KEYS.OFFSCREEN_RESULT, {
              jobId: 'job-late', ok: true,
              result: { reviewed_plan: { actions: [{ action_id: 'persisted-wins' }] } },
            });
            const lifecycle = makeLifecycle(async () => null);
            const consumed = await lifecycle.consumeOffscreenCompletionMessage({
              type: protocol.MESSAGE_TYPES.OFFSCREEN_RESULT,
              jobId: 'job-late',
              result: { reviewed_plan: { actions: [{ action_id: 'message-loses' }] } },
            });
            const popupJob = await lifecycle.getActiveJobForPopup();
            const unrelated = await lifecycle.consumeOffscreenCompletionMessage({
              type: protocol.MESSAGE_TYPES.OFFSCREEN_ERROR,
              jobId: 'unrelated', error: 'ignore me',
            });
            console.log(JSON.stringify({
              consumed,
              popupJob,
              unrelated,
              persisted: (await storage.get(protocol.STORAGE_KEYS.OFFSCREEN_RESULT)) ?? null,
              savedPlans,
            }));
            """
        )
        self.assertEqual(result["consumed"]["status"], "succeeded")
        self.assertEqual(
            result["savedPlans"][0]["actions"][0]["action_id"],
            "persisted-wins",
        )
        self.assertEqual(
            result["popupJob"]["result"]["reviewed_plan"]["actions"][0]["action_id"],
            "persisted-wins",
        )
        self.assertIsNone(result["persisted"])
        self.assertIsNone(result["unrelated"])

    def test_mutation_wait_and_heartbeat_boundaries(self) -> None:
        result = self._node_eval(
            """
            const lifecycle = makeLifecycle(async () => null);
            let nestedStart;
            const mutationResult = await lifecycle.runDirectMutatingOperation('undo-last-execution', async () => {
              nestedStart = await lifecycle.start(protocol.JOB_TYPES.GENERATE_AI_PLAN, {});
              return 'undone';
            });
            const lockAfterMutation = lifecycle.getRunningJobId();

            await jobStore.save({
              id: 'job-wait', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: 'running', owner_run_id: 'sw-current',
              started_at: new Date(now).toISOString(), updated_at: new Date(now).toISOString(),
            });
            const timeout = await lifecycle.waitForBackgroundJobCompletion('job-wait', 10, 25);
            let blockedError = '';
            try {
              await lifecycle.withMutationLock('undo-last-execution', async () => null);
            } catch (error) {
              blockedError = error.message;
            }

            now += 1000;
            const touched = await lifecycle.jobHeartbeatTick(await jobStore.get());
            const touchedAt = touched.updated_at;

            await jobStore.save({
              id: 'job-orphan', type: protocol.JOB_TYPES.GENERATE_AI_PLAN,
              status: 'running', owner_run_id: 'sw-old',
              started_at: new Date(now - jobStore.ACTIVE_JOB_STALE_MS - 1).toISOString(),
              updated_at: new Date(now - jobStore.ACTIVE_JOB_STALE_MS - 1).toISOString(),
            });
            const orphanFailed = await lifecycle.heartbeatTick(await jobStore.get());
            const ignoredAlarm = await lifecycle.handleAlarm({ name: 'other-alarm' });
            const terminalAlarm = await lifecycle.handleAlarm({ name: lifecycle.heartbeatAlarmName });

            await storage.remove(protocol.STORAGE_KEYS.ACTIVE_JOB);
            const lost = await lifecycle.wait('missing-job', 10, 25);
            console.log(JSON.stringify({
              mutationResult,
              nestedStart,
              lockAfterMutation,
              timeout,
              blockedError,
              touchedAt,
              orphanFailed,
              ignoredAlarm,
              terminalAlarm,
              lost,
              alarmEvents,
            }));
            """
        )
        self.assertEqual(result["mutationResult"], "undone")
        self.assertEqual(
            result["nestedStart"],
            {"error": "Background job already running in this service worker."},
        )
        self.assertEqual(result["lockAfterMutation"], "")
        self.assertEqual(result["timeout"]["status"], "failed")
        self.assertEqual(result["timeout"]["error"], "Timed out waiting for background job completion.")
        self.assertEqual(
            result["blockedError"],
            "Background job already running: generate-ai-plan",
        )
        self.assertEqual(result["touchedAt"], "2026-07-10T08:00:01.030Z")
        self.assertEqual(result["orphanFailed"]["status"], "failed")
        self.assertIn("became stale", result["orphanFailed"]["error"])
        self.assertFalse(result["ignoredAlarm"])
        self.assertTrue(result["terminalAlarm"])
        self.assertEqual(result["lost"], {"status": "failed", "error": "Job lost from storage."})


if __name__ == "__main__":
    unittest.main()
