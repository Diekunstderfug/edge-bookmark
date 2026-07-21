"""Independent tests for the ActiveJob persistence module."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionJobStoreTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'job_store.js'))});
          const protocol = BookmarkAdvisor.Protocol;
          const state = new Map();
          const writes = [];
          const storage = {{
            async get(key) {{
              const value = state.get(key);
              return value === undefined ? undefined : structuredClone(value);
            }},
            async set(key, value) {{
              const cloned = value === undefined ? undefined : structuredClone(value);
              state.set(key, cloned);
              writes.push([key, cloned]);
            }},
          }};
          let now = Date.parse('2026-07-10T08:00:00.000Z');
          const jobStore = BookmarkAdvisor.Background.JobStore.create({{
            storage,
            protocol,
            clock: () => now,
          }});
          const activeKey = protocol.STORAGE_KEYS.ACTIVE_JOB;
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

    def test_save_persists_all_existing_fields_but_never_the_full_result(self) -> None:
        result = self._node_eval(
            """
            const saved = await jobStore.save({
              id: 'job-1',
              type: 'generate-ai-plan',
              status: protocol.JOB_STATUSES.SUCCEEDED,
              stage: 'save',
              owner_run_id: 'sw-1',
              custom_field: { keep: true },
              result_summary: { type: 'plan', action_count: 2 },
              result: { reviewed_plan: { actions: [{}, {}] } },
            });
            const loaded = await jobStore.get();
            console.log(JSON.stringify({ saved, loaded }));
            """
        )
        for job in (result["saved"], result["loaded"]):
            self.assertNotIn("result", job)
            self.assertEqual(job["result_summary"], {"type": "plan", "action_count": 2})
            self.assertEqual(job["custom_field"], {"keep": True})
            self.assertEqual(job["owner_run_id"], "sw-1")

    def test_stage_and_progress_merge_the_latest_stored_job_fields(self) -> None:
        result = self._node_eval(
            """
            await jobStore.save({
              id: 'job-1', type: 'generate-ai-plan', status: 'running',
              progress: 'newer stored progress', owner_run_id: 'sw-current',
              custom_field: 'keep-me', started_at: '2026-07-10T07:00:00.000Z',
            });
            const staleReference = {
              id: 'job-1', type: 'generate-ai-plan', status: 'running',
              progress: 'stale progress', owner_run_id: 'sw-old',
            };
            const staged = await jobStore.setStage(staleReference, 'llm');
            now += 5000;
            const progressed = await jobStore.progress(staleReference, 'Calling LLM...');
            console.log(JSON.stringify({
              staged,
              progressed,
              progressSidecar: state.get(protocol.STORAGE_KEYS.PROGRESS),
            }));
            """
        )
        self.assertEqual(result["staged"]["stage"], "llm")
        self.assertEqual(result["staged"]["stage_started_at"], "2026-07-10T08:00:00.000Z")
        self.assertEqual(result["progressed"]["updated_at"], "2026-07-10T08:00:05.000Z")
        self.assertEqual(result["progressed"]["progress"], "Calling LLM...")
        self.assertEqual(result["progressed"]["owner_run_id"], "sw-current")
        self.assertEqual(result["progressed"]["custom_field"], "keep-me")
        self.assertEqual(
            result["progressSidecar"],
            {"message": "Calling LLM...", "updated_at": 1783670405000},
        )

    def test_succeed_summarizes_and_rehydrates_without_persisting_full_result(self) -> None:
        result = self._node_eval(
            """
            await jobStore.save({
              id: 'job-1', type: 'generate-ai-plan', status: 'running',
              stage: 'save', progress: 'stored progress', owner_run_id: 'sw-current',
              custom_field: 'keep-me', started_at: '2026-07-10T07:00:00.000Z',
            });
            const staleReference = {
              id: 'job-1', status: 'running', stage: 'export', owner_run_id: 'sw-old',
            };
            const fullResult = {
              reviewed_plan: { plan_version: '2', actions: [{ action_id: 'a1' }, { action_id: 'a2' }] },
            };
            const succeeded = await jobStore.succeed(staleReference, fullResult, 'AI plan complete.');
            const writesBeforeLateProgress = writes.length;
            now += 5000;
            const afterLateProgress = await jobStore.progress(staleReference, 'late progress');
            const writesAfterLateProgress = writes.length;
            await storage.set(protocol.STORAGE_KEYS.LAST_PLAN, {
              plan: fullResult.reviewed_plan, saved_at: '2026-07-10T08:00:00.000Z',
            });
            const hydrated = await jobStore.rehydrate();
            const persisted = state.get(activeKey);
            console.log(JSON.stringify({
              succeeded,
              afterLateProgress,
              writesBeforeLateProgress,
              writesAfterLateProgress,
              hydrated,
              persisted,
            }));
            """
        )
        succeeded = cast(dict[str, object], result["succeeded"])
        self.assertEqual(succeeded["status"], "succeeded")
        self.assertEqual(succeeded["stage"], "save")
        self.assertEqual(succeeded["owner_run_id"], "sw-current")
        self.assertEqual(succeeded["custom_field"], "keep-me")
        self.assertEqual(succeeded["progress"], "AI plan complete.")
        self.assertEqual(succeeded["updated_at"], "2026-07-10T08:00:00.000Z")
        self.assertEqual(succeeded["finished_at"], "2026-07-10T08:00:00.000Z")
        self.assertEqual(succeeded["result_summary"], {"type": "plan", "action_count": 2})
        self.assertEqual(result["afterLateProgress"], succeeded)
        self.assertEqual(result["writesBeforeLateProgress"], result["writesAfterLateProgress"])
        self.assertNotIn("result", result["persisted"])
        self.assertEqual(
            result["hydrated"]["result"]["reviewed_plan"]["actions"],
            [{"action_id": "a1"}, {"action_id": "a2"}],
        )

    def test_report_rehydration_and_failure_transitions_keep_current_fields(self) -> None:
        result = self._node_eval(
            """
            const report = {
              succeeded: [{ actionId: 'a1' }],
              failures: [{ actionId: 'a2', error: 'failed' }],
            };
            const reportSummary = jobStore.summarizeResult(report);
            await jobStore.save({
              id: 'report-job', type: 'apply-reviewed-plan', status: 'succeeded',
              result_summary: reportSummary,
            });
            await storage.set(protocol.STORAGE_KEYS.LAST_REPORT, report);
            const hydratedReport = await jobStore.rehydrate();

            await jobStore.save({
              id: 'failed-job', type: 'generate-ai-plan', status: 'running',
              stage: 'llm', owner_run_id: 'sw-current', custom_field: 'keep-me',
              started_at: '2026-07-10T07:00:00.000Z',
            });
            const failed = await jobStore.fail(
              { id: 'failed-job', status: 'running', owner_run_id: 'sw-old' },
              'Cancelled by user.',
            );
            now += 5000;
            const afterLateFailure = await jobStore.fail(
              { id: 'failed-job', status: 'running' },
              'late failure',
            );
            console.log(JSON.stringify({ reportSummary, hydratedReport, failed, afterLateFailure }));
            """
        )
        self.assertEqual(
            result["reportSummary"],
            {"type": "report", "succeeded_count": 1, "failure_count": 1},
        )
        self.assertEqual(
            result["hydratedReport"]["result"],
            {
                "succeeded": [{"actionId": "a1"}],
                "failures": [{"actionId": "a2", "error": "failed"}],
            },
        )
        failed = result["failed"]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["stage"], "llm")
        self.assertEqual(failed["owner_run_id"], "sw-current")
        self.assertEqual(failed["custom_field"], "keep-me")
        self.assertEqual(failed["progress"], "Cancelled by user.")
        self.assertEqual(failed["error"], "Cancelled by user.")
        self.assertEqual(failed["cancellation_requested_at"], "2026-07-10T08:00:00.000Z")
        self.assertEqual(result["afterLateFailure"], failed)

    def test_staleness_uses_updated_at_then_started_at_and_matches_existing_thresholds(self) -> None:
        result = self._node_eval(
            """
            const isoAgo = (milliseconds) => new Date(now - milliseconds).toISOString();
            const fresh = { status: 'running', updated_at: isoAgo(60 * 1000) };
            const startupStale = { status: 'running', updated_at: isoAgo(60 * 1000 + 1) };
            const activeStale = { status: 'running', updated_at: isoAgo(30 * 60 * 1000 + 1) };
            const startedFallback = { status: 'running', started_at: isoAgo(1000) };
            const invalid = { status: 'running', updated_at: 'not-a-date' };
            const terminal = { status: 'failed', updated_at: 'not-a-date' };
            console.log(JSON.stringify({
              thresholds: [jobStore.STARTUP_JOB_STALE_MS, jobStore.ACTIVE_JOB_STALE_MS],
              fresh: [
                jobStore.isFreshRunning(fresh),
                jobStore.isStartupStaleRunning(fresh),
                jobStore.isStaleRunning(fresh),
              ],
              startupStale: [
                jobStore.isStartupStaleRunning(startupStale),
                jobStore.isStaleRunning(startupStale),
              ],
              activeStale: jobStore.isStaleRunning(activeStale),
              fallbackValid: jobStore.hasValidRunningTimestamp(startedFallback),
              invalid: [
                jobStore.hasValidRunningTimestamp(invalid),
                jobStore.isStartupStaleRunning(invalid),
                jobStore.isStaleRunning(invalid),
              ],
              terminal: [
                jobStore.hasValidRunningTimestamp(terminal),
                jobStore.isStartupStaleRunning(terminal),
                jobStore.isStaleRunning(terminal),
              ],
            }));
            """
        )
        self.assertEqual(result["thresholds"], [60_000, 1_800_000])
        self.assertEqual(result["fresh"], [True, False, False])
        self.assertEqual(result["startupStale"], [True, False])
        self.assertTrue(result["activeStale"])
        self.assertTrue(result["fallbackValid"])
        self.assertEqual(result["invalid"], [False, True, True])
        self.assertEqual(result["terminal"], [False, False, False])


if __name__ == "__main__":
    unittest.main()
