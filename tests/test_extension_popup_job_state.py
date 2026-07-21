"""Unit tests for popup ActiveJob monitoring."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionPopupJobStateTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          require({json.dumps(str(EXTENSION / 'popup' / 'job_state.js'))});
          (async () => {{ {body} }})().catch((error) => {{
            console.error(error && error.stack ? error.stack : String(error));
            process.exit(1);
          }});
        """
        completed = subprocess.run(
            ["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_observe_starts_once_and_terminal_record_stops_monitor(self) -> None:
        result = self._node_eval(
            """
            const records = [];
            const intervals = [];
            const cleared = [];
            const running = {
              id: 'j1', status: 'running', updated_at: '2026-01-01T00:00:00.000Z',
            };
            const monitor = BookmarkAdvisor.Popup.JobState.create({
              protocol: BookmarkAdvisor.Protocol,
              storage: { get: async () => running },
              now: () => Date.parse('2026-01-01T00:00:01.000Z'),
              timers: {
                setInterval: (callback, milliseconds) => { intervals.push({ callback, milliseconds }); return 7; },
                clearInterval: (id) => cleared.push(id),
              },
              onRecord: (job) => records.push(job),
            });
            monitor.observe(running);
            monitor.observe(running);
            monitor.handleStorageChange({ bookmarkAdvisorActiveJob: {
              newValue: { id: 'j1', status: 'succeeded' },
            } }, 'local');
            monitor.observe({ id: 'j1', status: 'succeeded' });
            console.log(JSON.stringify({
              intervals: intervals.map((item) => item.milliseconds), cleared, records,
              running: monitor.isRunning(), active: monitor.getActive(),
            }));
            """
        )
        self.assertEqual(result["intervals"], [20_000])
        self.assertEqual(result["cleared"], [7])
        self.assertEqual(result["records"], [{"id": "j1", "status": "succeeded"}])
        self.assertFalse(result["running"])

    def test_check_synthesizes_recoverable_failure_for_missing_or_old_timestamp(self) -> None:
        result = self._node_eval(
            """
            let stored = { id: 'old', status: 'running', updated_at: 'invalid' };
            const records = [];
            const monitor = BookmarkAdvisor.Popup.JobState.create({
              protocol: BookmarkAdvisor.Protocol,
              storage: { get: async () => stored },
              now: () => Date.parse('2026-07-10T08:00:00.000Z'),
              timers: { setInterval: () => 1, clearInterval: () => {} },
              staleMessage: () => 'worker lost',
              onRecord: (job) => records.push(job),
            });
            monitor.observe(stored);
            const invalid = await monitor.check();
            stored = {
              id: 'fresh', status: 'running', updated_at: '2026-07-10T07:59:59.000Z',
            };
            monitor.observe(stored);
            const fresh = await monitor.check();
            console.log(JSON.stringify({ invalid, fresh, records }));
            """
        )
        self.assertEqual(result["invalid"]["status"], "failed")
        self.assertTrue(result["invalid"]["recoverable"])
        self.assertEqual(result["invalid"]["error"], "worker lost")
        self.assertEqual(result["invalid"]["finished_at"], "2026-07-10T08:00:00.000Z")
        self.assertEqual(result["fresh"]["status"], "running")
        self.assertEqual(len(result["records"]), 1)

    def test_non_local_and_missing_changes_are_ignored(self) -> None:
        result = self._node_eval(
            """
            const records = [];
            const monitor = BookmarkAdvisor.Popup.JobState.create({
              protocol: BookmarkAdvisor.Protocol,
              storage: { get: async () => null },
              timers: { setInterval: () => 1, clearInterval: () => {} },
              onRecord: (job) => records.push(job),
            });
            const sync = monitor.handleStorageChange({}, 'sync');
            const local = monitor.handleStorageChange({}, 'local');
            console.log(JSON.stringify({ sync, local, records }));
            """
        )
        self.assertIsNone(result["sync"])
        self.assertIsNone(result["local"])
        self.assertEqual(result["records"], [])


if __name__ == "__main__":
    unittest.main()
