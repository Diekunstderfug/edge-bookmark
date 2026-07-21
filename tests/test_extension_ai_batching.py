"""Unit tests for AI planning batch orchestration helpers."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "extension" / "ai" / "batching.js"


class ExtensionAiBatchingTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(MODULE))});
          const batching = BookmarkAdvisor.AI.Batching;
          (async () => {{ {body} }})().catch((error) => {{
            console.error(error && error.stack ? error.stack : String(error));
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

    def test_split_preserves_small_snapshot_and_chunks_large_bookmark_list(self) -> None:
        result = self._node_eval(
            """
            const small = { marker: 'same', bookmarks: [{ id: 1 }, { id: 2 }] };
            const large = { marker: 'copied', bookmarks: [1, 2, 3, 4, 5].map((id) => ({ id })) };
            const smallParts = batching.splitPlanningSnapshot(small, 2, 2);
            const largeParts = batching.splitPlanningSnapshot(large, 2, 2);
            console.log(JSON.stringify({
              sameReference: smallParts[0] === small,
              ids: largeParts.map((part) => part.bookmarks.map((item) => item.id)),
              markers: largeParts.map((part) => part.marker),
            }));
            """
        )
        self.assertTrue(result["sameReference"])
        self.assertEqual(result["ids"], [[1, 2], [3, 4], [5]])
        self.assertEqual(result["markers"], ["copied", "copied", "copied"])

    def test_concurrency_is_bounded_and_results_keep_input_order(self) -> None:
        result = self._node_eval(
            """
            let active = 0;
            let maximum = 0;
            const releases = [];
            const gate = () => new Promise((resolve) => releases.push(resolve));
            const promise = batching.mapWithConcurrency([0, 1, 2, 3], 2, async (value) => {
              active += 1;
              maximum = Math.max(maximum, active);
              await gate();
              active -= 1;
              return value * 10;
            });
            while (releases.length < 2) await Promise.resolve();
            releases.shift()();
            while (releases.length < 2) await Promise.resolve();
            releases.shift()();
            while (releases.length < 2) await Promise.resolve();
            releases.shift()();
            releases.shift()();
            console.log(JSON.stringify({ maximum, results: await promise }));
            """
        )
        self.assertEqual(result, {"maximum": 2, "results": [0, 10, 20, 30]})

    def test_merge_deduplicates_by_confidence_and_prefers_action_over_review_on_tie(self) -> None:
        result = self._node_eval(
            """
            const merged = batching.mergeActivationPayloads([
              { summary: { overview: 'part one' }, activations: [
                { op: 'keep_for_review', node_id: 'b1', target: '', confidence: 0.8 },
                { op: 'create_folder', node_id: '', target: '/A', confidence: 0.5 },
              ] },
              { summary: { overview: 'part two' }, activations: [
                { op: 'move_bookmark', node_id: 'b1', target: '/A', confidence: 0.8 },
                { op: 'create_folder', node_id: '', target: '/A', confidence: 0.9 },
                { op: 'move_bookmark', node_id: 'b2', target: '/B', confidence: 'bad' },
              ] },
              { activations: [
                { op: 'move_bookmark', node_id: 'b2', target: '/C', confidence: 0.1 },
              ] },
            ]);
            console.log(JSON.stringify(merged));
            """
        )
        self.assertEqual(result["summary"]["overview"], "part one; part two")
        actions = result["activations"]
        self.assertEqual([item["op"] for item in actions], ["create_folder", "move_bookmark", "move_bookmark"])
        self.assertEqual(actions[0]["confidence"], 0.9)
        self.assertEqual(actions[1]["node_id"], "b1")
        self.assertEqual(actions[2]["target"], "/C")


if __name__ == "__main__":
    unittest.main()
