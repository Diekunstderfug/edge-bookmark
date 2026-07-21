/* OpenAI-compatible endpoint 的共享纯函数。 */

(function attachAiEndpoint(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});

  const DEFAULT_API_BASE_URL = "https://api.openai.com/v1";
  const DEFAULT_API_STYLE = "auto";
  const DEFAULT_REQUEST_TIMEOUT_MS = 180000;
  const MAX_REQUEST_TIMEOUT_MS = 300000;
  const API_STYLES = Object.freeze(["auto", "responses", "chat_completions", "completions"]);

  function nonNegativeInteger(value, fallback) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) {
      return fallback;
    }
    return Math.floor(numberValue);
  }

  function normalizeBaseUrl(value, options) {
    const settings = options || {};
    const provided = String(value || "").trim();
    if (!provided && settings.allowEmpty) {
      return "";
    }
    const raw = provided || String(settings.defaultValue || DEFAULT_API_BASE_URL).trim();
    let parsed;
    try {
      parsed = new URL(raw);
    } catch (_error) {
      throw new Error("API base URL must be a valid https:// URL.");
    }
    if (parsed.protocol !== "https:") {
      throw new Error("API base URL must use https://.");
    }
    parsed.hash = "";
    parsed.search = "";
    parsed.pathname = parsed.pathname.replace(/\/+$/, "");
    return parsed.toString().replace(/\/+$/, "");
  }

  function endpointKind(apiBaseUrl) {
    let parsed;
    try {
      parsed = new URL(normalizeBaseUrl(apiBaseUrl));
    } catch (_error) {
      return "";
    }
    const pathname = parsed.pathname.replace(/\/+$/, "");
    if (pathname.endsWith("/chat/completions")) return "chat_completions";
    if (pathname.endsWith("/responses")) return "responses";
    if (pathname.endsWith("/completions")) return "completions";
    return "";
  }

  function endpointUrl(apiBaseUrl, endpointPath) {
    const normalized = normalizeBaseUrl(apiBaseUrl);
    if (endpointKind(normalized)) {
      return normalized;
    }
    return `${normalized}/${String(endpointPath || "").replace(/^\/+/, "")}`;
  }

  function normalizeStyle(value) {
    const style = String(value || "").trim();
    return API_STYLES.includes(style) ? style : DEFAULT_API_STYLE;
  }

  function buildRequestAttempts(apiStyle, apiBaseUrl) {
    const exactEndpoint = endpointKind(apiBaseUrl);
    if (exactEndpoint === "responses") return ["responses_json_schema"];
    if (exactEndpoint === "chat_completions") {
      return ["chat_plain_json", "chat_json_object", "chat_json_schema"];
    }
    if (exactEndpoint === "completions") return ["completions_plain_json"];

    const style = normalizeStyle(apiStyle);
    if (style === "responses") return ["responses_json_schema"];
    if (style === "chat_completions") {
      return ["chat_plain_json", "chat_json_object", "chat_json_schema"];
    }
    if (style === "completions") return ["completions_plain_json"];
    return [
      "chat_json_object",
      "chat_json_schema",
      "chat_plain_json",
      "completions_plain_json",
      "responses_json_schema",
    ];
  }

  function clampRequestTimeout(value, fallback) {
    return Math.min(
      nonNegativeInteger(value, fallback || DEFAULT_REQUEST_TIMEOUT_MS),
      MAX_REQUEST_TIMEOUT_MS,
    );
  }

  function requestAttemptCount(apiStyle, apiBaseUrl) {
    return buildRequestAttempts(apiStyle, apiBaseUrl).length;
  }

  function extractOrigin(apiBaseUrl) {
    const normalized = normalizeBaseUrl(apiBaseUrl, { allowEmpty: true, defaultValue: "" });
    if (!normalized) return "";
    return new URL(normalized).origin + "/*";
  }

  root.AIEndpoint = Object.freeze({
    API_STYLES,
    DEFAULT_API_BASE_URL,
    DEFAULT_API_STYLE,
    DEFAULT_REQUEST_TIMEOUT_MS,
    MAX_REQUEST_TIMEOUT_MS,
    buildRequestAttempts,
    clampRequestTimeout,
    endpointKind,
    endpointUrl,
    extractOrigin,
    normalizeBaseUrl,
    normalizeStyle,
    requestAttemptCount,
  });
})(globalThis);
