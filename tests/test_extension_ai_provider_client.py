"""Independent tests for the extracted OpenAI-compatible provider client."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionAiProviderClientTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'ai' / 'provider_client.js'))});
          (async () => {{
            {body}
          }})().catch((error) => {{
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
            timeout=15,
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_build_request_attempts_delegates_endpoint_style_contract(self) -> None:
        result = self._node_eval(
            """
            const client = BookmarkAdvisor.AI.ProviderClient.create({
              fetch: async () => { throw new Error('unused'); },
            });
            console.log(JSON.stringify({
              exactResponses: client.buildRequestAttempts(
                'auto', 'https://api.example.com/custom/responses',
              ),
              exactChat: client.buildRequestAttempts(
                'auto', 'https://api.example.com/v1/chat/completions',
              ),
              exactCompletions: client.buildRequestAttempts(
                'auto', 'https://api.example.com/v1/completions',
              ),
              automatic: client.buildRequestAttempts(
                'auto', 'https://api.example.com/v1',
              ),
            }));
            """
        )
        self.assertEqual(result["exactResponses"], ["responses_json_schema"])
        self.assertEqual(
            result["exactChat"],
            ["chat_plain_json", "chat_json_object", "chat_json_schema"],
        )
        self.assertEqual(result["exactCompletions"], ["completions_plain_json"])
        self.assertEqual(
            result["automatic"],
            [
                "chat_json_object",
                "chat_json_schema",
                "chat_plain_json",
                "completions_plain_json",
                "responses_json_schema",
            ],
        )

    def test_request_attempts_preserve_urls_headers_bodies_and_prompt_cache_fields(self) -> None:
        result = self._node_eval(
            """
            const calls = [];
            const client = BookmarkAdvisor.AI.ProviderClient.create({
              fetch: async (url, options) => {
                calls.push({
                  url,
                  method: options.method,
                  headers: options.headers,
                  body: JSON.parse(options.body),
                  hasSignal: !!options.signal,
                });
                return {
                  ok: true,
                  status: 200,
                  headers: { get: () => null },
                  text: async () => JSON.stringify({ accepted: true }),
                };
              },
            });
            const schema = {
              type: 'object', additionalProperties: false, properties: {}, required: [],
            };
            const common = {
              apiKey: 'secret', requestTimeoutMs: 2000,
              schema, systemText: 'SYSTEM', userText: 'USER',
            };
            await client.requestCompatibleAttempt({
              ...common,
              attempt: 'responses_json_schema',
              apiBaseUrl: 'https://api.openai.com/v1',
              model: 'gpt-5.4-mini',
            });
            await client.requestCompatibleAttempt({
              ...common,
              attempt: 'chat_json_object',
              apiBaseUrl: 'https://api.openai.com/v1',
              model: 'gpt-4o-mini',
            });
            await client.requestCompatibleAttempt({
              ...common,
              attempt: 'chat_json_schema',
              apiBaseUrl: 'https://api.example.com/v1',
              model: 'provider-model',
            });
            await client.requestCompatibleAttempt({
              ...common,
              attempt: 'completions_plain_json',
              apiBaseUrl: 'https://api.example.com/v1',
              model: 'legacy-model',
            });
            console.log(JSON.stringify(calls));
            """
        )
        self.assertEqual(
            [call["url"] for call in result],
            [
                "https://api.openai.com/v1/responses",
                "https://api.openai.com/v1/chat/completions",
                "https://api.example.com/v1/chat/completions",
                "https://api.example.com/v1/completions",
            ],
        )
        for call in result:
            self.assertEqual(call["method"], "POST")
            self.assertEqual(
                call["headers"],
                {"Authorization": "Bearer secret", "Content-Type": "application/json"},
            )
            self.assertTrue(call["hasSignal"])

        responses = result[0]["body"]
        self.assertEqual(responses["input"][0]["content"], [{"type": "input_text", "text": "SYSTEM"}])
        self.assertEqual(responses["text"]["format"]["schema"], {
            "type": "object", "additionalProperties": False, "properties": {}, "required": [],
        })
        self.assertEqual(responses["prompt_cache_key"], "edge-bookmark-planner-v1")
        self.assertEqual(responses["prompt_cache_retention"], "24h")

        chat_object = result[1]["body"]
        self.assertEqual(chat_object["response_format"], {"type": "json_object"})
        self.assertIn("Return a single JSON object", chat_object["messages"][0]["content"])
        self.assertEqual(chat_object["prompt_cache_key"], "edge-bookmark-planner-v1")
        self.assertNotIn("prompt_cache_retention", chat_object)

        chat_schema = result[2]["body"]
        self.assertEqual(chat_schema["messages"][0]["content"], "SYSTEM")
        self.assertEqual(chat_schema["response_format"]["json_schema"]["schema"], responses["text"]["format"]["schema"])
        self.assertNotIn("prompt_cache_key", chat_schema)

        completions = result[3]["body"]
        self.assertEqual(
            completions["prompt"],
            "SYSTEM\nReturn a single JSON object and no Markdown fences.\n\nUSER",
        )
        self.assertEqual(completions["max_tokens"], 16384)
        self.assertEqual(completions["temperature"], 0)
        self.assertNotIn("prompt_cache_key", completions)

    def test_post_compatible_keeps_raw_success_and_http_error_retry_semantics(self) -> None:
        result = self._node_eval(
            """
            const responses = [
              {
                ok: true, status: 200, headers: {},
                text: async () => 'provider returned non-json text',
              },
              {
                ok: false, status: 401, headers: { 'Retry-After': '7' },
                text: async () => JSON.stringify({ error: { message: 'Invalid API key' } }),
              },
              {
                ok: false, status: 429,
                headers: { get: (name) => name === 'retry-after' ? '2.5' : null },
                text: async () => JSON.stringify({ error: { message: 'Slow down' } }),
              },
            ];
            const progress = [];
            const client = BookmarkAdvisor.AI.ProviderClient.create({
              fetch: async () => responses.shift(),
              now: () => Date.parse('2026-07-10T00:00:00Z'),
            });
            const raw = await client.postCompatible(
              'https://api.example.com/v1/test', 'key', 2000, { hello: 'world' }, null,
              (message) => progress.push(message),
            );
            async function capture() {
              try {
                await client.postCompatible(
                  'https://api.example.com/v1/test', 'key', 2000, {}, null,
                );
                return null;
              } catch (error) {
                return {
                  message: error.message,
                  status: error.httpStatus,
                  retryable: error.retryable,
                  retryAfter: error.retryAfter,
                  retryAfterMs: error.retryAfterMs,
                };
              }
            }
            const unauthorized = await capture();
            const rateLimited = await capture();
            console.log(JSON.stringify({
              raw, progress, unauthorized, rateLimited,
              dateRetryAfterMs: client.parseRetryAfterMs('Fri, 10 Jul 2026 00:00:03 GMT'),
              invalidRetryAfter: client.parseRetryAfterMs('later'),
              classifications: [400, 408, 429, 500, 599, 600].map(
                (status) => [status, client.classifyHttpError(status)],
              ),
            }));
            """
        )
        self.assertEqual(result["raw"], {"raw": "provider returned non-json text"})
        self.assertEqual(
            result["progress"],
            ["Response body received: 31 chars"],
        )
        self.assertEqual(
            result["unauthorized"],
            {
                "message": "401 Invalid API key",
                "status": 401,
                "retryable": False,
                "retryAfter": "7",
                "retryAfterMs": 7000,
            },
        )
        self.assertEqual(
            result["rateLimited"],
            {
                "message": "429 Slow down",
                "status": 429,
                "retryable": True,
                "retryAfter": "2.5",
                "retryAfterMs": 2500,
            },
        )
        self.assertEqual(result["dateRetryAfterMs"], 3000)
        self.assertIsNone(result["invalidRetryAfter"])
        self.assertEqual(
            result["classifications"],
            [[400, False], [408, True], [429, True], [500, True], [599, True], [600, False]],
        )

    def test_request_timeout_aborts_fetch_and_cleans_injected_timer(self) -> None:
        result = self._node_eval(
            """
            const timeouts = new Map();
            const cleared = [];
            let nextId = 1;
            let internalSignal = null;
            const timers = {
              setTimeout(callback, milliseconds) {
                const id = nextId++;
                timeouts.set(id, { callback, milliseconds });
                return id;
              },
              clearTimeout(id) { cleared.push(id); timeouts.delete(id); },
              setInterval() { return nextId++; },
              clearInterval() {},
            };
            const client = BookmarkAdvisor.AI.ProviderClient.create({
              timers,
              fetch: async (_url, options) => {
                internalSignal = options.signal;
                return new Promise((resolve, reject) => {
                  options.signal.addEventListener('abort', () => {
                    const error = new Error('aborted by timer');
                    error.name = 'AbortError';
                    reject(error);
                  }, { once: true });
                });
              },
            });
            const pending = client.postCompatible(
              'https://api.example.com/v1/test', 'key', 2000, {}, null,
            );
            while (!internalSignal || timeouts.size === 0) await Promise.resolve();
            const timeout = [...timeouts.values()][0];
            timeout.callback();
            let error = null;
            try { await pending; } catch (caught) {
              error = { name: caught.name, message: caught.message };
            }
            console.log(JSON.stringify({
              error,
              timeoutMs: timeout.milliseconds,
              internalAborted: internalSignal.aborted,
              remainingTimers: timeouts.size,
              cleared,
            }));
            """
        )
        self.assertEqual(
            result["error"],
            {
                "name": "Error",
                "message": "Request timed out after 2s: https://api.example.com/v1/test",
            },
        )
        self.assertEqual(result["timeoutMs"], 2000)
        self.assertTrue(result["internalAborted"])
        self.assertEqual(result["remainingTimers"], 0)
        self.assertEqual(result["cleared"], [1])

    def test_external_abort_keeps_abort_error_identity_and_skips_preaborted_fetch(self) -> None:
        result = self._node_eval(
            """
            let fetchCount = 0;
            let internalSignal = null;
            const client = BookmarkAdvisor.AI.ProviderClient.create({
              fetch: async (_url, options) => {
                fetchCount += 1;
                internalSignal = options.signal;
                return new Promise((resolve, reject) => {
                  options.signal.addEventListener('abort', () => {
                    const error = new Error('internal abort');
                    error.name = 'AbortError';
                    reject(error);
                  }, { once: true });
                });
              },
            });
            const external = new AbortController();
            const pending = client.postCompatible(
              'https://api.example.com/v1/test', 'key', 2000, {}, external.signal,
            );
            while (!internalSignal) await Promise.resolve();
            external.abort();
            let activeAbort = null;
            try { await pending; } catch (error) {
              activeAbort = { name: error.name, code: error.code, message: error.message };
            }

            const preAborted = new AbortController();
            preAborted.abort();
            let preAbort = null;
            try {
              await client.postCompatible(
                'https://api.example.com/v1/test', 'key', 2000, {}, preAborted.signal,
              );
            } catch (error) {
              preAbort = { name: error.name, code: error.code, message: error.message };
            }
            console.log(JSON.stringify({
              activeAbort, preAbort, fetchCount, internalAborted: internalSignal.aborted,
            }));
            """
        )
        expected = {"name": "AbortError", "code": 20, "message": "The operation was aborted."}
        self.assertEqual(result["activeAbort"], expected)
        self.assertEqual(result["preAbort"], expected)
        self.assertEqual(result["fetchCount"], 1)
        self.assertTrue(result["internalAborted"])

    def test_response_body_timeout_uses_same_public_timeout_error(self) -> None:
        result = self._node_eval(
            """
            const timeouts = new Map();
            const cleared = [];
            let nextId = 1;
            const timers = {
              setTimeout(callback, milliseconds) {
                const id = nextId++;
                timeouts.set(id, { id, callback, milliseconds });
                return id;
              },
              clearTimeout(id) { cleared.push(id); timeouts.delete(id); },
              setInterval() { return nextId++; },
              clearInterval() {},
            };
            const client = BookmarkAdvisor.AI.ProviderClient.create({
              timers,
              fetch: async () => ({
                ok: true, status: 200, headers: {},
                text: async () => new Promise(() => {}),
              }),
            });
            const pending = client.postCompatible(
              'https://api.example.com/v1/body', 'key', 3000, {}, null,
            );
            while (timeouts.size < 2) await Promise.resolve();
            const bodyTimer = [...timeouts.values()][1];
            bodyTimer.callback();
            let error = '';
            try { await pending; } catch (caught) { error = caught.message; }
            console.log(JSON.stringify({
              error,
              bodyTimeoutMs: bodyTimer.milliseconds,
              remainingTimers: timeouts.size,
              cleared: cleared.sort((a, b) => a - b),
            }));
            """
        )
        self.assertEqual(
            result["error"],
            "Request timed out after 3s: https://api.example.com/v1/body",
        )
        self.assertEqual(result["bodyTimeoutMs"], 3000)
        self.assertEqual(result["remainingTimers"], 0)
        self.assertEqual(result["cleared"], [1, 2])


if __name__ == "__main__":
    unittest.main()
