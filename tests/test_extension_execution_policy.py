"""Background execution policy module tests."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionExecutionPolicyTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'plan_schema.js'))});
          require({json.dumps(str(EXTENSION / 'shared' / 'path_utils.js'))});
          require({json.dumps(str(EXTENSION / 'background' / 'execution_policy.js'))});
          const policy = globalThis.BookmarkAdvisor.Background.ExecutionPolicy;
          {body}
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

    def test_plan_validation_and_v1_status_semantics_match_service_worker(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                """
                const errors = [];
                for (const plan of [null, {}, { actions: [{}] }, { actions: [{ action_type: 'made_up' }] }]) {
                  try {
                    policy.validateExecutablePlan(plan);
                    errors.push('');
                  } catch (error) {
                    errors.push(error.message);
                  }
                }
                const agreedReview = {
                  action_type: 'keep_for_review',
                  details: { review_agreed: true },
                };
                console.log(JSON.stringify({
                  errors,
                  v1Move: policy.isExecutablePlanAction(
                    { plan_version: '1' },
                    { action_type: 'move_bookmark' },
                  ),
                  v2Move: policy.isExecutablePlanAction(
                    { plan_version: '2' },
                    { action_type: 'move_bookmark' },
                  ),
                  v1AgreedReview: policy.isExecutablePlanAction(
                    { plan_version: '1' },
                    agreedReview,
                  ),
                  v1UnagreedReview: policy.isExecutablePlanAction(
                    { plan_version: '1' },
                    { action_type: 'keep_for_review', details: {} },
                  ),
                }));
                """
            ),
        )
        self.assertEqual(
            result["errors"],
            [
                "Plan must contain an actions array.",
                "Plan must contain an actions array.",
                "Action missing action_type",
                "Unknown action_type: made_up",
            ],
        )
        self.assertTrue(result["v1Move"])
        self.assertFalse(result["v2Move"])
        self.assertTrue(result["v1AgreedReview"])
        self.assertFalse(result["v1UnagreedReview"])

    def test_focus_policy_covers_all_action_path_shapes(self) -> None:
        result = cast(
            list[dict[str, object]],
            self._node_eval(
                """
                const focus = '/收藏夹栏/Work';
                const actions = [
                  { action_type: 'create_folder', target_path: '/收藏夹栏/Other/New' },
                  { action_type: 'move_bookmark', from_path: '/收藏夹栏/Other', to_path: focus },
                  { action_type: 'move_folder', from_path: focus + '/A', to_path: '/收藏夹栏/Other' },
                  { action_type: 'rename_folder', from_path: '/收藏夹栏/Other/A' },
                  { action_type: 'remove_duplicate', bookmark_locator: { folder_path: '/收藏夹栏/Other' } },
                  { action_type: 'delete_empty_folder', folder_locator: { path: '/收藏夹栏/Other/Empty' } },
                  { action_type: 'keep_for_review' },
                  { action_type: 'made_up' },
                ];
                console.log(JSON.stringify(actions.map((action) => policy.checkActionPolicy(action, focus))));
                """
            ),
        )
        self.assertEqual([item["allowed"] for item in result], [False] * 6 + [True, False])
        self.assertIn("target", cast(str, result[0]["reason"]))
        self.assertIn("source", cast(str, result[1]["reason"]))
        self.assertIn("destination", cast(str, result[2]["reason"]))
        self.assertIn("Unknown action_type", cast(str, result[-1]["reason"]))

    def test_actual_source_path_assertion_remains_a_separate_execution_guard(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                """
                const focus = '/收藏夹栏/Work';
                const action = {
                  action_type: 'move_bookmark',
                  from_path: '/收藏夹栏/Work/Planned',
                  to_path: '/收藏夹栏/Work/Target',
                };
                const preflight = policy.checkActionPolicy(action, focus);
                let actualError = '';
                try {
                  policy.assertPathWithinFocus(
                    '/收藏夹栏/Personal/Actual',
                    focus,
                    'move_bookmark source',
                  );
                } catch (error) {
                  actualError = error.message;
                }
                console.log(JSON.stringify({ preflight, actualError }));
                """
            ),
        )
        self.assertEqual(result["preflight"], {"allowed": True})
        self.assertEqual(
            result["actualError"],
            "move_bookmark source /收藏夹栏/Personal/Actual is outside focus scope /收藏夹栏/Work",
        )

    def test_quarantine_path_decisions_are_locale_independent_and_pure(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                """
                const englishIndex = new Map([
                  ['/Favorites bar', { id: '1' }],
                  ['/Favorites bar/Work', { id: '2' }],
                ]);
                const chineseTree = [{
                  id: '0',
                  children: [
                    { id: '1', title: '收藏夹栏', children: [] },
                    { id: '2', title: 'A bookmark', url: 'https://example.com' },
                  ],
                }];
                console.log(JSON.stringify({
                  focus: policy.knownQuarantinePath('/Favorites bar/Work/', englishIndex),
                  index: policy.knownQuarantinePath('', englishIndex),
                  tree: policy.quarantinePathFromBookmarkTree(chineseTree),
                  root: policy.quarantinePathUnder('/'),
                  missingIndex: policy.knownQuarantinePath('', new Map()),
                }));
                """
            ),
        )
        self.assertEqual(
            result,
            {
                "focus": "/Favorites bar/Work/_Quarantine",
                "index": "/Favorites bar/_Quarantine",
                "tree": "/收藏夹栏/_Quarantine",
                "root": "/_Quarantine",
                "missingIndex": "",
            },
        )

    def test_quarantine_tree_requires_a_folder_root(self) -> None:
        result = self._node_eval(
            """
            let message = '';
            try {
              policy.quarantinePathFromBookmarkTree([{ id: '0', children: [] }]);
            } catch (error) {
              message = error.message;
            }
            console.log(JSON.stringify({ message }));
            """
        )
        self.assertEqual(
            result["message"],
            "Could not find a bookmark root folder for quarantine.",
        )


if __name__ == "__main__":
    unittest.main()
