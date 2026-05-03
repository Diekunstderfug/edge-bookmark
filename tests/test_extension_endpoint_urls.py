"""Extension OpenAI-compatible endpoint URL behavior tests."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import cast


_REPO_ROOT = Path(__file__).resolve().parent.parent
_AI_PLANNER = _REPO_ROOT / "extension" / "ai_planner.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS endpoint tests")
class ExtensionEndpointUrlTest(unittest.TestCase):
    def _node_eval(self, expression: str) -> object:
        script = (
            f"require({json.dumps(str(_AI_PLANNER))});\n"
            f"const result = {expression};\n"
            "console.log(JSON.stringify(result));\n"
        )
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=15,
        )
        return cast(object, json.loads(completed.stdout))

    def _node_script(self, body: str) -> object:
        script = f"require({json.dumps(str(_AI_PLANNER))});\n{body}\n"
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=15,
        )
        return cast(object, json.loads(completed.stdout))

    def test_base_url_appends_responses_endpoint(self):
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._endpointUrl('https://api.example.com/v1', 'responses')"),
            "https://api.example.com/v1/responses",
        )

    def test_exact_responses_endpoint_is_preserved(self):
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._endpointUrl('https://api.example.com/custom/responses', 'chat/completions')"),
            "https://api.example.com/custom/responses",
        )

    def test_exact_chat_completions_endpoint_is_preserved(self):
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._endpointUrl('https://api.example.com/openai/deployments/x/chat/completions', 'responses')"),
            "https://api.example.com/openai/deployments/x/chat/completions",
        )

    def test_exact_completions_endpoint_is_preserved(self):
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._endpointUrl('https://api.example.com/v1/completions', 'chat/completions')"),
            "https://api.example.com/v1/completions",
        )

    def test_exact_completions_endpoint_uses_only_completions_attempt(self):
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._buildRequestAttempts('auto', 'https://api.example.com/v1/completions')"),
            ["completions_plain_json"],
        )

    def test_request_timeout_is_capped_for_mv3_service_worker_fetch_lifetime(self):
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._requestTimeoutMsWithinMv3Lifetime(120000)"),
            120000,
        )
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._requestTimeoutMsWithinMv3Lifetime(300000)"),
            300000,
        )
        self.assertEqual(
            self._node_eval("BookmarkAdvisorAI._requestTimeoutMsWithinMv3Lifetime(600000)"),
            300000,
        )

    def test_revision_prompt_includes_existing_plan_and_instruction(self):
        expression = """
        BookmarkAdvisorAI._buildRevisionUserPrompt(
          {
            plan_version: '2',
            plan_kind: 'reviewed',
            summary: { overview: 'old plan' },
            actions: [{
              action_id: 'a-0001',
              action_type: 'move_bookmark',
              status: 'approved',
              reason: 'old reason',
              confidence: 0.91,
              bookmark_locator: { id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com', folder_path: '/收藏夹栏' },
              folder_locator: {},
              from_path: '/收藏夹栏',
              to_path: '/收藏夹栏/AI',
              target_path: '',
              to_name: ''
            }]
          },
          {
            created_at: 'now',
            folders: [],
            bookmarks: [{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com', folder_path: '/收藏夹栏' }]
          },
          'Keep AI tools separate'
        )
        """
        prompt = self._node_eval(expression)
        self.assertIsInstance(prompt, str)
        prompt_text = cast(str, prompt)
        self.assertIn("Revise the current reviewed bookmark plan", prompt_text)
        self.assertIn("Keep AI tools separate", prompt_text)
        self.assertIn("old reason", prompt_text)
        self.assertIn("Bookmarks (id|title|domain|folder_path):", prompt_text)

    def test_llm_schema_uses_lightweight_activations_not_full_actions(self):
        schema = self._node_eval("BookmarkAdvisorAI._activationResponseSchema()")
        self.assertIsInstance(schema, dict)
        schema_dict = cast(dict[str, object], schema)
        properties = cast(dict[str, object], schema_dict["properties"])
        self.assertIn("activations", properties)
        self.assertNotIn("actions", properties)

    def test_activation_compiler_materializes_move_bookmark_action(self):
        expression = """
        BookmarkAdvisorAI._compileActivationPlan(
          {
            summary: { overview: 'activation plan' },
            activations: [{
              op: 'move_bookmark',
              node_id: '10',
              target: '/收藏夹栏/AI',
              duplicate_of_id: '',
              confidence: 0.92,
              reason: 'belongs with AI tools'
            }]
          },
          {
            folders: [],
            bookmarks: [{
              id: '10',
              title: 'Example',
              url: 'https://example.com',
              normalized_url: 'https://example.com',
              folder_path: '/收藏夹栏'
            }]
          }
        )
        """
        draft = self._node_eval(expression)
        self.assertIsInstance(draft, dict)
        draft_dict = cast(dict[str, object], draft)
        actions = cast(list[dict[str, object]], draft_dict["actions"])
        self.assertEqual(actions[0]["action_type"], "move_bookmark")
        self.assertEqual(actions[0]["to_path"], "/收藏夹栏/AI")
        locator = cast(dict[str, object], actions[0]["bookmark_locator"])
        self.assertEqual(locator["id"], "10")

    def test_activation_lint_accepts_compilable_move_bookmark(self):
        expression = """
        BookmarkAdvisorAI._lintActivationPayload(
          {
            summary: { overview: 'activation plan' },
            activations: [{
              op: 'move_bookmark',
              node_id: '10',
              target: '/收藏夹栏/AI',
              duplicate_of_id: '',
              confidence: 0.92,
              reason: 'belongs with AI tools'
            }]
          },
          {
            folders: [],
            bookmarks: [{
              id: '10',
              title: 'Example',
              url: 'https://example.com',
              normalized_url: 'https://example.com',
              folder_path: '/收藏夹栏'
            }]
          }
        )
        """
        self.assertEqual(self._node_eval(expression), [])

    def test_activation_lint_rejects_unresolvable_bookmark(self):
        expression = """
        BookmarkAdvisorAI._lintActivationPayload(
          {
            summary: { overview: 'bad activation plan' },
            activations: [{
              op: 'move_bookmark',
              node_id: 'missing',
              target: '/收藏夹栏/AI',
              duplicate_of_id: '',
              confidence: 0.92,
              reason: 'belongs with AI tools'
            }]
          },
          { folders: [], bookmarks: [] }
        )
        """
        errors = self._node_eval(expression)
        self.assertIsInstance(errors, list)
        error_text = "\n".join(cast(list[str], errors))
        self.assertIn("existing bookmark id", error_text)

    def test_low_confidence_extension_actions_finalize_as_blocked(self):
        body = """
        global.fetch = async function (_url, _options) {
          const payload = {
            summary: { overview: 'low confidence' },
            activations: [{
              op: 'move_bookmark',
              node_id: '10',
              target: '/收藏夹栏/AI',
              duplicate_of_id: '',
              confidence: 0.2,
              reason: 'maybe AI'
            }]
          };
          return {
            ok: true,
            text: async () => JSON.stringify({ choices: [{ text: JSON.stringify(payload) }] })
          };
        };
        BookmarkAdvisorAI.generateReviewedPlan({
          apiKey: 'test-key',
          apiBaseUrl: 'https://api.example.com/v1/completions',
          apiStyle: 'completions',
          model: 'test-model',
          snapshot: {
            created_at: 'now',
            folders: [],
            bookmarks: [{
              id: '10',
              title: 'Example',
              url: 'https://example.com',
              normalized_url: 'https://example.com',
              folder_path: '/收藏夹栏/Loose'
            }]
          }
        }).then((result) => {
          console.log(JSON.stringify({
            status: result.reviewed_plan.actions[0].status,
            blocked: result.reviewed_plan.summary.blocked_actions
          }));
        }).catch((error) => {
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(body))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"], 1)

    def test_activation_lint_rejects_focus_path_escape(self):
        expression = """
        BookmarkAdvisorAI._lintActivationPayload(
          {
            summary: { overview: 'outside focus' },
            activations: [{
              op: 'move_folder',
              node_id: '20',
              target: '/收藏夹栏/Inside/Target',
              duplicate_of_id: '',
              confidence: 0.92,
              reason: 'move outside folder'
            }]
          },
          {
            focus_path: '/收藏夹栏/Inside',
            folders: [{ id: '20', path: '/收藏夹栏/Outside', name: 'Outside' }],
            bookmarks: []
          }
        )
        """
        errors = self._node_eval(expression)
        error_text = "\n".join(cast(list[str], errors))
        self.assertIn("focused folder", error_text)

    def test_generate_plan_retries_invalid_activation_with_lint_feedback(self):
        body = """
        const calls = [];
        const invalidPayload = {
          summary: { overview: 'first try' },
          activations: [{
            op: 'move_bookmark',
            node_id: 'missing',
            target: '/收藏夹栏/AI',
            duplicate_of_id: '',
            confidence: 0.91,
            reason: 'move it'
          }]
        };
        const validPayload = {
          summary: { overview: 'second try' },
          activations: [{
            op: 'move_bookmark',
            node_id: '10',
            target: '/收藏夹栏/AI',
            duplicate_of_id: '',
            confidence: 0.91,
            reason: 'move it'
          }]
        };
        global.fetch = async function (_url, options) {
          const requestBody = JSON.parse(options.body);
          calls.push(requestBody.prompt);
          const payload = calls.length === 1 ? invalidPayload : validPayload;
          return {
            ok: true,
            text: async () => JSON.stringify({ choices: [{ text: JSON.stringify(payload) }] })
          };
        };
        BookmarkAdvisorAI.generateReviewedPlan({
          apiKey: 'test-key',
          apiBaseUrl: 'https://api.example.com/v1/completions',
          apiStyle: 'completions',
          model: 'test-model',
          maxActions: 5,
          snapshot: {
            created_at: 'now',
            folders: [],
            bookmarks: [{
              id: '10',
              title: 'Example',
              url: 'https://example.com',
              normalized_url: 'https://example.com',
              folder_path: '/收藏夹栏/Loose'
            }]
          }
        }).then((result) => {
          console.log(JSON.stringify({
            callCount: calls.length,
            feedbackIncluded: calls[1].includes('Validation errors') && calls[1].includes('existing bookmark id'),
            actionType: result.reviewed_plan.actions[0].action_type,
            toPath: result.reviewed_plan.actions[0].to_path
          }));
        }).catch((error) => {
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        });
        """
        result = self._node_script(body)
        self.assertEqual(result, {
            "callCount": 2,
            "feedbackIncluded": True,
            "actionType": "move_bookmark",
            "toPath": "/收藏夹栏/AI",
        })

    def test_generate_plan_stops_after_three_activation_lint_failures(self):
        body = """
        const calls = [];
        const invalidPayload = {
          summary: { overview: 'still bad' },
          activations: [{
            op: 'move_bookmark',
            node_id: 'missing',
            target: '/收藏夹栏/AI',
            duplicate_of_id: '',
            confidence: 0.91,
            reason: 'move it'
          }]
        };
        global.fetch = async function (_url, options) {
          const requestBody = JSON.parse(options.body);
          calls.push(requestBody.prompt);
          return {
            ok: true,
            text: async () => JSON.stringify({ choices: [{ text: JSON.stringify(invalidPayload) }] })
          };
        };
        BookmarkAdvisorAI.generateReviewedPlan({
          apiKey: 'test-key',
          apiBaseUrl: 'https://api.example.com/v1/completions',
          apiStyle: 'completions',
          model: 'test-model',
          maxRetries: 2,
          snapshot: {
            created_at: 'now',
            folders: [],
            bookmarks: [{
              id: '10',
              title: 'Example',
              url: 'https://example.com',
              normalized_url: 'https://example.com',
              folder_path: '/收藏夹栏/Loose'
            }]
          }
        }).then(() => {
          console.error('expected lint failure');
          process.exit(1);
        }).catch((error) => {
          console.log(JSON.stringify({
            callCount: calls.length,
            feedbackIncludedOnLastTry: calls[2].includes('Validation errors'),
            message: error.message
          }));
        });
        """
        result = cast(dict[str, object], self._node_script(body))
        self.assertEqual(result["callCount"], 3)
        self.assertEqual(result["feedbackIncludedOnLastTry"], True)
        self.assertIn("failed after 3 attempt", cast(str, result["message"]))

    def test_focus_snapshot_does_not_include_prefix_sibling_folder_bookmarks(self):
        body = """
        let prompt = '';
        global.fetch = async function (_url, options) {
          const requestBody = JSON.parse(options.body);
          prompt = requestBody.prompt;
          return {
            ok: true,
            text: async () => JSON.stringify({ choices: [{ text: JSON.stringify({ summary: { overview: 'none' }, activations: [] }) }] })
          };
        };
        BookmarkAdvisorAI.generateReviewedPlan({
          apiKey: 'test-key',
          apiBaseUrl: 'https://api.example.com/v1/completions',
          apiStyle: 'completions',
          model: 'test-model',
          focusPath: '/收藏夹栏/AI',
          snapshot: {
            created_at: 'now',
            folders: [
              { id: '1', name: '收藏夹栏', path: '/收藏夹栏' },
              { id: '2', name: 'AI', path: '/收藏夹栏/AI' },
              { id: '3', name: 'AIX', path: '/收藏夹栏/AIX' }
            ],
            bookmarks: [
              { id: '10', title: 'Inside', url: 'https://inside.example', normalized_url: 'https://inside.example', folder_path: '/收藏夹栏/AI' },
              { id: '11', title: 'Sibling', url: 'https://sibling.example', normalized_url: 'https://sibling.example', folder_path: '/收藏夹栏/AIX' }
            ]
          }
        }).then(() => {
          console.log(JSON.stringify({
            hasInside: prompt.includes('Inside'),
            hasSibling: prompt.includes('Sibling')
          }));
        }).catch((error) => {
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(body))
        self.assertEqual(result, {"hasInside": True, "hasSibling": False})


if __name__ == "__main__":
    _ = unittest.main()
