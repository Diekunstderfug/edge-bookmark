"""Independent tests for provider response extraction and JSON decoding."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionAiResponseCodecTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'ai' / 'response_codec.js'))});
          (() => {{
            {body}
          }})();
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

    def test_extract_attempt_text_supports_responses_chat_and_completions_shapes(self) -> None:
        result = self._node_eval(
            """
            const codec = BookmarkAdvisor.AI.ResponseCodec;
            console.log(JSON.stringify({
              responseTopLevel: codec.extractAttemptText(
                'responses_json_schema', { output_text: '{"source":"top"}' },
              ),
              responseNested: codec.extractAttemptText(
                'responses_json_schema', {
                  output: [{ content: [{ type: 'output_text', text: '{"source":"nested"}' }] }],
                },
              ),
              chatString: codec.extractAttemptText(
                'chat_json_schema', {
                  choices: [{ message: { content: '{"source":"chat"}' } }],
                },
              ),
              chatParts: codec.extractAttemptText(
                'chat_plain_json', {
                  choices: [{ message: { content: [{ text: '{"a":' }, { text: '1}' }] } }],
                },
              ),
              completion: codec.extractAttemptText(
                'completions_plain_json', { choices: [{ text: '{"source":"completion"}' }] },
              ),
            }));
            """
        )
        self.assertEqual(result["responseTopLevel"], '{"source":"top"}')
        self.assertEqual(result["responseNested"], '{"source":"nested"}')
        self.assertEqual(result["chatString"], '{"source":"chat"}')
        self.assertEqual(result["chatParts"], '{"a":1}')
        self.assertEqual(result["completion"], '{"source":"completion"}')

    def test_missing_provider_text_preserves_specific_error_messages(self) -> None:
        result = self._node_eval(
            """
            const codec = BookmarkAdvisor.AI.ResponseCodec;
            function capture(callback) {
              try { callback(); return ''; } catch (error) { return error.message; }
            }
            console.log(JSON.stringify({
              responses: capture(() => codec.extractResponsesText({ output: [] })),
              chat: capture(() => codec.extractChatCompletionText({ choices: [] })),
              completions: capture(() => codec.extractCompletionsText({ choices: [] })),
            }));
            """
        )
        self.assertEqual(result["responses"], "OpenAI response did not include output text.")
        self.assertEqual(result["chat"], "OpenAI chat completion did not include message content.")
        self.assertEqual(result["completions"], "OpenAI completion did not include text content.")

    def test_parse_draft_plan_handles_double_fences_and_balanced_nested_json(self) -> None:
        result = self._node_eval(
            """
            const codec = BookmarkAdvisor.AI.ResponseCodec;
            const payload = {
              summary: { overview: 'nested {braces} and an escaped quote: "ok"' },
              activations: [{
                op: 'move_bookmark', node_id: '10', target: '/收藏夹栏/AI',
                duplicate_of_id: '', confidence: 0.9, reason: 'nested object',
                evidence: { note: 'literal } then {' },
              }],
            };
            const doubleFenced = '```json\\n```JSON\\n' + JSON.stringify(payload) + '\\n```\\n```';
            const wrapped = 'Provider preface {not-json}\\n' + JSON.stringify(payload) + '\\nProvider suffix';
            const safelyWrapped = 'Provider preface\\n' + JSON.stringify(payload) + '\\nProvider suffix';
            let firstObjectError = '';
            try { codec.parseDraftPlanText(wrapped); } catch (error) { firstObjectError = error.message; }
            console.log(JSON.stringify({
              direct: codec.parseDraftPlanText(JSON.stringify(payload)),
              fenced: codec.parseDraftPlanText(doubleFenced),
              wrapped: codec.parseDraftPlanText(safelyWrapped),
              firstBalanced: codec.extractBalancedJsonObject(
                'before ' + JSON.stringify(payload) + ' after {"second":true}',
              ),
              stripped: codec.stripJsonFences(doubleFenced),
              firstObjectError,
            }));
            """
        )
        self.assertEqual(result["direct"]["summary"]["overview"], 'nested {braces} and an escaped quote: "ok"')
        self.assertEqual(result["fenced"], result["direct"])
        self.assertEqual(result["wrapped"], result["direct"])
        self.assertEqual(json.loads(result["firstBalanced"]), result["direct"])
        self.assertTrue(result["stripped"].startswith("{"))
        self.assertTrue(result["stripped"].endswith("}"))
        self.assertTrue(result["firstObjectError"])

    def test_parse_errors_and_maximum_text_boundary_fail_closed(self) -> None:
        result = self._node_eval(
            """
            const codec = BookmarkAdvisor.AI.ResponseCodec;
            function capture(text) {
              try {
                return { parsed: codec.parseDraftPlanText(text), error: '' };
              } catch (error) {
                return { parsed: null, error: error.message, name: error.name };
              }
            }
            console.log(JSON.stringify({
              noObject: capture('plain provider prose'),
              invalidObject: capture('prefix { definitely-not-json } suffix'),
              tooLate: capture('x'.repeat(codec.MAX_TEXT_LENGTH) + '{"late":true}'),
              missingClose: capture('prefix {"summary":{"overview":"x"}'),
              maxLength: codec.MAX_TEXT_LENGTH,
            }));
            """
        )
        self.assertEqual(
            result["noObject"]["error"],
            "Provider returned text that did not contain a JSON object.",
        )
        self.assertEqual(result["invalidObject"]["name"], "SyntaxError")
        self.assertEqual(
            result["tooLate"]["error"],
            "Provider returned text that did not contain a JSON object.",
        )
        self.assertEqual(result["missingClose"]["name"], "SyntaxError")
        self.assertEqual(result["maxLength"], 500000)


if __name__ == "__main__":
    unittest.main()
