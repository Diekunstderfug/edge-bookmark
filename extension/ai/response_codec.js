/* OpenAI-compatible provider 响应文本提取与 JSON 解码。 */

(function attachResponseCodec(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const ai = root.AI || (root.AI = {});
  const MAX_TEXT_LENGTH = 500000;

  function extractAttemptText(attempt, payload) {
    if (attempt === "responses_json_schema") {
      return extractResponsesText(payload);
    }
    if (attempt === "completions_plain_json") {
      return extractCompletionsText(payload);
    }
    return extractChatCompletionText(payload);
  }

  function parseDraftPlanText(text) {
    let raw = String(text || "").trim();
    if (raw.length > MAX_TEXT_LENGTH) {
      raw = raw.slice(0, MAX_TEXT_LENGTH);
    }
    const cleaned = stripJsonFences(raw);
    if (!cleaned.includes("{") || !cleaned.includes("}")) {
      throw new Error("Provider returned text that did not contain a JSON object.");
    }
    try {
      return JSON.parse(cleaned);
    } catch (_error) {
      const extracted = extractBalancedJsonObject(cleaned);
      if (extracted) {
        return JSON.parse(extracted);
      }
      throw new Error("Provider returned text that was not valid JSON.");
    }
  }

  // 提取第一个平衡 {...}；忽略嵌套对象以及 JSON 字符串内的括号。
  function extractBalancedJsonObject(text) {
    const start = text.indexOf("{");
    if (start < 0) return null;
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < text.length; index += 1) {
      const character = text[index];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
      if (character === '"') {
        inString = !inString;
        continue;
      }
      if (inString) continue;
      if (character === "{") {
        depth += 1;
      } else if (character === "}") {
        depth -= 1;
        if (depth === 0) {
          return text.slice(start, index + 1);
        }
      }
    }

    const end = text.lastIndexOf("}");
    if (end > start) {
      return text.slice(start, end + 1);
    }
    return null;
  }

  function stripJsonFences(text) {
    let output = text;
    for (let index = 0; index < 4; index += 1) {
      const next = output
        .replace(/^\s*```(?:json|JSON)?\s*/i, "")
        .replace(/\s*```\s*$/i, "")
        .trim();
      if (next === output) break;
      output = next;
    }
    return output;
  }

  function extractResponsesText(payload) {
    if (payload.output_text) {
      return String(payload.output_text);
    }
    for (const item of payload.output || []) {
      for (const content of item.content || []) {
        if (content.text) {
          return String(content.text);
        }
      }
    }
    throw new Error("OpenAI response did not include output text.");
  }

  function extractChatCompletionText(payload) {
    const content = payload.choices && payload.choices[0] && payload.choices[0].message
      ? payload.choices[0].message.content
      : "";
    if (typeof content === "string" && content.trim()) {
      return content;
    }
    if (Array.isArray(content)) {
      return content.map((item) => item.text || "").join("");
    }
    throw new Error("OpenAI chat completion did not include message content.");
  }

  function extractCompletionsText(payload) {
    const text = payload.choices && payload.choices[0]
      ? payload.choices[0].text
      : "";
    if (typeof text === "string" && text.trim()) {
      return text;
    }
    throw new Error("OpenAI completion did not include text content.");
  }

  ai.ResponseCodec = Object.freeze({
    MAX_TEXT_LENGTH,
    extractAttemptText,
    extractBalancedJsonObject,
    extractChatCompletionText,
    extractCompletionsText,
    extractResponsesText,
    parseDraftPlanText,
    stripJsonFences,
  });
})(globalThis);
