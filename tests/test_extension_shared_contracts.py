"""Shared extension protocol, schema, and endpoint contract tests."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionSharedContractsTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          const protocolPath = {json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))};
          const schemaPath = {json.dumps(str(EXTENSION / 'shared' / 'plan_schema.js'))};
          const endpointPath = {json.dumps(str(EXTENSION / 'shared' / 'ai_endpoint.js'))};
          const actionConstantsPath = {json.dumps(str(EXTENSION / 'action_constants.js'))};
          const planLintPath = {json.dumps(str(EXTENSION / 'plan_lint.js'))};
          const aiPlannerPath = {json.dumps(str(EXTENSION / 'ai_planner.js'))};
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

    def test_message_job_stage_and_storage_values_are_stable(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                """
                require(protocolPath);
                const protocol = globalThis.BookmarkAdvisor.Protocol;
                console.log(JSON.stringify({
                  messages: protocol.MESSAGE_TYPES,
                  jobs: protocol.JOB_TYPES,
                  stages: protocol.JOB_STAGES,
                  statuses: protocol.JOB_STATUSES,
                  storage: protocol.STORAGE_KEYS,
                  supported: [
                    protocol.isSupportedJobType('generate-ai-plan'),
                    protocol.isSupportedJobType('revise-ai-plan'),
                    protocol.isSupportedJobType('apply-reviewed-plan'),
                    protocol.isSupportedJobType('unknown'),
                  ],
                }));
                """
            ),
        )
        self.assertEqual(
            result["jobs"],
            {
                "GENERATE_AI_PLAN": "generate-ai-plan",
                "REVISE_AI_PLAN": "revise-ai-plan",
                "APPLY_REVIEWED_PLAN": "apply-reviewed-plan",
            },
        )
        self.assertEqual(result["stages"], {"EXPORT": "export", "LLM": "llm", "SAVE": "save"})
        self.assertEqual(
            result["statuses"],
            {"RUNNING": "running", "SUCCEEDED": "succeeded", "FAILED": "failed"},
        )
        self.assertEqual(result["supported"], [True, True, True, False])

        messages = cast(dict[str, str], result["messages"])
        self.assertEqual(
            set(messages.values()),
            {
                "start-background-job",
                "generate-ai-plan",
                "revise-ai-plan",
                "apply-reviewed-plan",
                "get-active-job",
                "cancel-active-job",
                "export-snapshot",
                "list-folders",
                "undo-last-execution",
                "offscreen-llm",
                "offscreen-cancel",
                "offscreen-ping",
                "offscreen-ready",
                "offscreen-keepalive",
                "offscreen-progress",
                "offscreen-result",
                "offscreen-error",
            },
        )

        storage = cast(dict[str, str], result["storage"])
        self.assertEqual(
            set(storage.values()),
            {
                "bookmarkAdvisorLastPlan",
                "bookmarkAdvisorLastReport",
                "bookmarkAdvisorActiveJob",
                "bookmarkAdvisorUndoLog",
                "bookmarkAdvisorOffscreenResult",
                "bookmarkAdvisorExecCheckpoint",
                "bookmarkAdvisorProgress",
                "bookmarkAdvisorOpenAIKey",
                "bookmarkAdvisorOpenAIKeyDraft",
                "bookmarkAdvisorLlmSettings",
                "bookmarkAdvisorPopupDraft",
                "bookmarkAdvisorPreferences",
            },
        )

    def test_plan_schema_keeps_action_order_and_status_semantics(self) -> None:
        result = self._node_eval(
            """
            require(schemaPath);
            const schema = globalThis.BookmarkAdvisor.PlanSchema;
            const agreedReview = {
              action_type: 'keep_for_review',
              status: 'approved',
              details: { review_agreed: true },
            };
            console.log(JSON.stringify({
              order: schema.EXECUTION_ORDER,
              knownStatuses: schema.KNOWN_ACTION_STATUSES,
              v1Default: schema.resolveActionStatus({ plan_version: '1' }, {}),
              v2Default: schema.resolveActionStatus({ plan_version: '2' }, {}),
              approvedMove: schema.isExecutableAction({ action_type: 'move_bookmark', status: 'approved' }),
              proposedMove: schema.isExecutableAction({ action_type: 'move_bookmark', status: 'proposed' }),
              agreedReview: schema.isExecutableAction(agreedReview),
              unagreedReview: schema.isExecutableAction({ ...agreedReview, details: {} }),
              unknownKnown: schema.isKnownActionType('made_up_action'),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "order": [
                    "rename_folder",
                    "delete_empty_folder",
                    "create_folder",
                    "move_folder",
                    "move_bookmark",
                    "remove_duplicate",
                    "keep_for_review",
                ],
                "knownStatuses": ["approved", "edited", "proposed", "blocked", "rejected"],
                "v1Default": "approved",
                "v2Default": "proposed",
                "approvedMove": True,
                "proposedMove": False,
                "agreedReview": True,
                "unagreedReview": False,
                "unknownKnown": False,
            },
        )

    def test_plan_schema_centralizes_action_shape_rules(self) -> None:
        result = self._node_eval(
            """
            require(schemaPath);
            const schema = globalThis.BookmarkAdvisor.PlanSchema;
            const cases = [
              ['rename_folder', { folder_locator: { id: '1' }, to_name: 'New' }],
              ['create_folder', { target_path: '/收藏夹栏/New' }],
              ['move_folder', { folder_locator: { path: '/收藏夹栏/A' }, to_path: '/收藏夹栏/B' }],
              ['move_bookmark', { bookmark_locator: { id: '2' }, to_path: '/收藏夹栏/B' }],
              ['remove_duplicate', { bookmark_locator: { id: '2' } }],
              ['delete_empty_folder', { folder_locator: { id: '3' } }],
              ['keep_for_review', {}],
            ];
            console.log(JSON.stringify({
              validCounts: cases.map(([type, action]) => schema.validateActionShape(type, action, '$.action').length),
              missingBookmark: schema.validateActionShape('move_bookmark', { to_path: '/收藏夹栏/B' }, '$.action'),
              missingTarget: schema.validateActionShape('create_folder', {}, '$.action'),
            }));
            """
        )
        self.assertEqual(result["validCounts"], [0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result["missingBookmark"][0]["path"], "$.action")
        self.assertIn("bookmark", result["missingBookmark"][0]["message"].lower())
        self.assertEqual(result["missingTarget"][0]["path"], "$.action.target_path")

    def test_ai_endpoint_contract_matches_existing_fallback_order(self) -> None:
        result = self._node_eval(
            """
            require(endpointPath);
            const endpoint = globalThis.BookmarkAdvisor.AIEndpoint;
            console.log(JSON.stringify({
              normalized: endpoint.normalizeBaseUrl('https://api.openai.com/v1/?q=ignored#fragment'),
              chatUrl: endpoint.endpointUrl('https://api.openai.com/v1', 'chat/completions'),
              exactKind: endpoint.endpointKind('https://example.com/v1/chat/completions'),
              exactAttempts: endpoint.buildRequestAttempts('auto', 'https://example.com/v1/completions'),
              autoAttempts: endpoint.buildRequestAttempts('auto', 'https://example.com/v1'),
              invalidStyle: endpoint.normalizeStyle('made-up'),
              cappedTimeout: endpoint.clampRequestTimeout(999999999),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "normalized": "https://api.openai.com/v1",
                "chatUrl": "https://api.openai.com/v1/chat/completions",
                "exactKind": "chat_completions",
                "exactAttempts": ["completions_plain_json"],
                "autoAttempts": [
                    "chat_json_object",
                    "chat_json_schema",
                    "chat_plain_json",
                    "completions_plain_json",
                    "responses_json_schema",
                ],
                "invalidStyle": "auto",
                "cappedTimeout": 300000,
            },
        )

    def test_plan_consumers_share_one_action_and_status_classification(self) -> None:
        result = self._node_eval(
            """
            globalThis.self = globalThis;
            globalThis.chrome = { runtime: { getURL: (path) => path } };
            require(schemaPath);
            require(actionConstantsPath);
            require(planLintPath);
            require(aiPlannerPath);
            const schema = globalThis.BookmarkAdvisor.PlanSchema;
            const statuses = schema.KNOWN_ACTION_STATUSES;
            const actionTemplates = {
              rename_folder: { folder_locator: { id: 'f1' }, to_name: 'Renamed' },
              delete_empty_folder: { folder_locator: { id: 'f1' } },
              create_folder: { target_path: '/收藏夹栏/New' },
              move_folder: { folder_locator: { id: 'f1' }, to_path: '/收藏夹栏/Target' },
              move_bookmark: { bookmark_locator: { id: 'b1' }, to_path: '/收藏夹栏/Target' },
              remove_duplicate: { bookmark_locator: { id: 'b1' } },
              keep_for_review: {},
            };
            const matrix = [];
            for (const actionType of schema.EXECUTION_ORDER) {
              for (const status of statuses) {
                for (const reviewAgreed of actionType === 'keep_for_review' ? [false, true] : [false]) {
                  const action = {
                    action_type: actionType,
                    status,
                    reason: 'contract test',
                    confidence: 0.9,
                    details: { review_agreed: reviewAgreed },
                    ...actionTemplates[actionType],
                  };
                  const lint = globalThis.BookmarkPlanLint.lintPlan({ plan_version: '2', actions: [action] });
                  matrix.push({
                    actionType,
                    status,
                    reviewAgreed,
                    schemaExecutable: schema.isExecutableAction(action),
                    lintExecutable: lint.executableActions.length === 1,
                    warnings: lint.warnings.length,
                  });
                }
              }
            }
            const v1 = { action_type: 'move_bookmark', reason: 'v1', confidence: 0.9,
              bookmark_locator: { id: 'b1' }, to_path: '/收藏夹栏/Target' };
            const v2 = { ...v1 };
            const v1Lint = globalThis.BookmarkPlanLint.lintPlan({ plan_version: '1', actions: [v1] });
            const v2Lint = globalThis.BookmarkPlanLint.lintPlan({ plan_version: '2', actions: [v2] });
            const activationOps = globalThis.BookmarkAdvisorAI._activationResponseSchema()
              .properties.activations.items.properties.op.enum.slice().sort();
            console.log(JSON.stringify({
              matrix,
              v1Executable: v1Lint.executableActions.length,
              v2Executable: v2Lint.executableActions.length,
              activationOps,
              schemaOps: schema.EXECUTION_ORDER.slice().sort(),
            }));
            """
        )
        for row in result["matrix"]:
            expected = row["status"] in {"approved", "edited"}
            if row["actionType"] == "keep_for_review":
                expected = expected and row["reviewAgreed"]
            self.assertEqual(row["schemaExecutable"], expected, row)
            self.assertEqual(row["lintExecutable"], expected, row)
            self.assertEqual(row["warnings"], 0, row)
        self.assertEqual(result["v1Executable"], 1)
        self.assertEqual(result["v2Executable"], 0)
        self.assertEqual(result["activationOps"], result["schemaOps"])


if __name__ == "__main__":
    unittest.main()
