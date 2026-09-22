/* OpenAI-compatible provider 请求构造与 HTTP transport。 */

(function attachProviderClient(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const ai = root.AI || (root.AI = {});

  if (!root.AIEndpoint && typeof require === "function") {
    require("../shared/ai_endpoint.js");
  }

  function create(dependencies) {
    const options = dependencies || {};
    const aiEndpoint = options.aiEndpoint || options.AIEndpoint || root.AIEndpoint;
    const fetchImpl = options.fetch || globalScope.fetch;
    const timerApi = options.timers || globalScope;
    const AbortControllerImpl = options.AbortController || globalScope.AbortController;
    const now = typeof options.now === "function" ? options.now : () => Date.now();
    const log = normalizeLogger(options.log);

    if (!aiEndpoint || typeof aiEndpoint.endpointUrl !== "function" ||
      typeof aiEndpoint.buildRequestAttempts !== "function") {
      throw new Error("ProviderClient requires shared AIEndpoint helpers.");
    }
    if (typeof fetchImpl !== "function") {
      throw new Error("ProviderClient requires fetch.");
    }
    if (typeof AbortControllerImpl !== "function") {
      throw new Error("ProviderClient requires AbortController.");
    }

    const setTimer = bindTimer(timerApi, "setTimeout", globalScope);
    const clearTimer = bindTimer(timerApi, "clearTimeout", globalScope);
    const setRepeatingTimer = bindTimer(timerApi, "setInterval", globalScope);
    const clearRepeatingTimer = bindTimer(timerApi, "clearInterval", globalScope);
    const defaultApiBaseUrl = aiEndpoint.DEFAULT_API_BASE_URL || "https://api.openai.com/v1";
    const defaultRequestTimeoutMs = aiEndpoint.DEFAULT_REQUEST_TIMEOUT_MS || 180000;

    function buildRequestAttempts(apiStyle, apiBaseUrl) {
      return aiEndpoint.buildRequestAttempts(apiStyle, apiBaseUrl);
    }

    async function requestCompatibleAttempt(request) {
      const {
        attempt,
        apiBaseUrl,
        apiKey,
        model,
        requestTimeoutMs,
        schema,
        systemText,
        userText,
        signal,
        onProgress,
      } = request || {};

      if (attempt === "responses_json_schema") {
        const payload = withOpenAiPromptCacheFields(apiBaseUrl, model, {
          model,
          input: [
            {
              role: "system",
              content: [{ type: "input_text", text: systemText }],
            },
            {
              role: "user",
              content: [{ type: "input_text", text: userText }],
            },
          ],
          text: {
            format: {
              type: "json_schema",
              name: "bookmark_draft_plan",
              strict: true,
              schema,
            },
          },
        });
        return postCompatible(
          aiEndpoint.endpointUrl(apiBaseUrl, "responses"),
          apiKey,
          requestTimeoutMs,
          payload,
          signal,
          onProgress,
        );
      }

      if (attempt === "completions_plain_json") {
        return postCompatible(
          aiEndpoint.endpointUrl(apiBaseUrl, "completions"),
          apiKey,
          requestTimeoutMs,
          {
            model,
            prompt: `${systemText}\nReturn a single JSON object and no Markdown fences.\n\n${userText}`,
            max_tokens: 16384,
            temperature: 0,
          },
          signal,
          onProgress,
        );
      }

      const chatPayload = {
        model,
        messages: buildChatMessages(systemText, userText, schema, attempt),
      };
      if (attempt === "chat_json_schema") {
        chatPayload.response_format = {
          type: "json_schema",
          json_schema: {
            name: "bookmark_draft_plan",
            strict: true,
            schema,
          },
        };
      } else if (attempt === "chat_json_object") {
        chatPayload.response_format = { type: "json_object" };
      }
      return postCompatible(
        aiEndpoint.endpointUrl(apiBaseUrl, "chat/completions"),
        apiKey,
        requestTimeoutMs,
        withOpenAiPromptCacheFields(apiBaseUrl, model, chatPayload),
        signal,
        onProgress,
      );
    }

    async function postCompatible(url, apiKey, timeoutMs, body, externalSignal, onProgress) {
      const effectiveTimeout = timeoutMs || defaultRequestTimeoutMs;
      const controller = new AbortControllerImpl();
      let timedOut = false;
      let bodyTimedOut = false;
      let externalAborted = false;
      let timeoutId = null;
      let bodyTimeoutId = null;
      let fetchKeepAliveId = null;
      let textKeepAliveId = null;
      let externalListenerAttached = false;

      const onExternalAbort = function () {
        externalAborted = true;
        controller.abort();
      };

      if (externalSignal) {
        if (externalSignal.aborted) {
          throw createAbortError("The operation was aborted.");
        }
        externalSignal.addEventListener("abort", onExternalAbort, { once: true });
        externalListenerAttached = true;
      }

      timeoutId = setTimer(() => {
        timedOut = true;
        controller.abort();
      }, effectiveTimeout);

      if (typeof onProgress === "function") {
        let elapsed = 0;
        fetchKeepAliveId = setRepeatingTimer(() => {
          elapsed += 1;
          emitProgress(onProgress, `Waiting for LLM response... (${elapsed}s)`);
        }, 1000);
      }

      let response;
      try {
        response = await fetchImpl(url, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${apiKey}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
      } catch (error) {
        cleanupAll();
        if (timedOut || (
          error && error.name === "AbortError" &&
          !externalAborted && !(externalSignal && externalSignal.aborted)
        )) {
          throw new Error(
            `Request timed out after ${Math.round(effectiveTimeout / 1000)}s: ${url}`,
          );
        }
        if (externalAborted || (externalSignal && externalSignal.aborted)) {
          throw createAbortError("The operation was aborted.");
        }
        throw error;
      }
      clearRepeating("fetch");

      if (typeof onProgress === "function") {
        let elapsed = 0;
        textKeepAliveId = setRepeatingTimer(() => {
          elapsed += 1;
          emitProgress(onProgress, `Reading LLM response body... (${elapsed}s)`);
        }, 1000);
      }

      let text;
      try {
        text = await Promise.race([
          response.text(),
          new Promise((_, reject) => {
            bodyTimeoutId = setTimer(() => {
              bodyTimedOut = true;
              reject(new Error(
                `Response body timed out after ${Math.round(effectiveTimeout / 1000)}s`,
              ));
            }, effectiveTimeout);
          }),
        ]);
      } catch (error) {
        cleanupAll();
        if (timedOut || bodyTimedOut) {
          throw new Error(
            `Request timed out after ${Math.round(effectiveTimeout / 1000)}s: ${url}`,
          );
        }
        if (externalAborted || (externalSignal && externalSignal.aborted)) {
          throw createAbortError("The operation was aborted.");
        }
        throw error;
      }
      cleanupAll();

      const bodySize = text ? text.length : 0;
      if (typeof onProgress === "function" && bodySize > 0) {
        emitProgress(onProgress, `Response body received: ${bodySize} chars`);
      }

      let payload;
      try {
        payload = text ? JSON.parse(text) : {};
      } catch (_error) {
        payload = { raw: text };
      }
      if (!response.ok) {
        const message = payload && payload.error && payload.error.message
          ? payload.error.message
          : text;
        const httpError = new Error(`${response.status} ${message}`);
        httpError.httpStatus = response.status;
        httpError.retryable = classifyHttpError(response.status);
        attachRetryAfterMetadata(httpError, response.headers);
        throw httpError;
      }
      return payload;

      function clearRepeating(phase) {
        if ((phase === "fetch" || !phase) && fetchKeepAliveId !== null) {
          clearRepeatingTimer(fetchKeepAliveId);
          fetchKeepAliveId = null;
        }
        if ((phase === "text" || !phase) && textKeepAliveId !== null) {
          clearRepeatingTimer(textKeepAliveId);
          textKeepAliveId = null;
        }
      }

      function cleanupAll() {
        if (timeoutId !== null) {
          clearTimer(timeoutId);
          timeoutId = null;
        }
        if (bodyTimeoutId !== null) {
          clearTimer(bodyTimeoutId);
          bodyTimeoutId = null;
        }
        clearRepeating();
        if (externalSignal && externalListenerAttached) {
          externalSignal.removeEventListener("abort", onExternalAbort);
          externalListenerAttached = false;
        }
      }
    }

    function withOpenAiPromptCacheFields(apiBaseUrl, model, payload) {
      if (!isOfficialOpenAiApi(apiBaseUrl)) {
        return payload;
      }
      const next = { ...payload, prompt_cache_key: "edge-bookmark-planner-v1" };
      if (supportsOpenAiExtendedPromptCache(model)) {
        next.prompt_cache_retention = "24h";
      }
      return next;
    }

    function isOfficialOpenAiApi(apiBaseUrl) {
      try {
        const normalized = aiEndpoint.normalizeBaseUrl(
          apiBaseUrl || defaultApiBaseUrl,
        );
        return new URL(normalized).hostname === "api.openai.com";
      } catch (_error) {
        return false;
      }
    }

    function supportsOpenAiExtendedPromptCache(model) {
      const name = String(model || "").toLowerCase();
      return name.startsWith("gpt-5.5") ||
        name.startsWith("gpt-5.4") ||
        name.startsWith("gpt-5.2") ||
        name.startsWith("gpt-5.1") ||
        name.startsWith("gpt-5") ||
        name.startsWith("gpt-4.1");
    }

    function buildChatMessages(systemText, userText, _schema, attempt) {
      const messages = [{ role: "system", content: systemText }];
      if (attempt === "chat_plain_json" || attempt === "chat_json_object") {
        messages[0] = {
          role: "system",
          content: `${systemText}\nReturn a single JSON object and no Markdown fences. ` +
            "Top-level fields: summary (object with overview string), activations " +
            "(array of objects with op, node_id, target, duplicate_of_id, confidence, reason).",
        };
      }
      messages.push({ role: "user", content: userText });
      return messages;
    }

    function attachRetryAfterMetadata(error, headers) {
      const retryAfter = readHeader(headers, "retry-after");
      if (!retryAfter) return;
      error.retryAfter = retryAfter;
      const milliseconds = parseRetryAfterMs(retryAfter);
      if (milliseconds !== null) {
        error.retryAfterMs = milliseconds;
      }
    }

    function parseRetryAfterMs(value) {
      const raw = String(value || "").trim();
      if (!raw) return null;
      const seconds = Number(raw);
      if (Number.isFinite(seconds) && seconds >= 0) {
        return Math.max(0, Math.round(seconds * 1000));
      }
      const target = Date.parse(raw);
      if (!Number.isFinite(target)) return null;
      return Math.max(0, target - now());
    }

    function emitProgress(callback, message) {
      try {
        const pending = callback(message);
        if (pending && typeof pending.catch === "function") {
          void pending.catch((error) => log("warn", error));
        }
      } catch (error) {
        log("warn", error);
      }
    }

    return Object.freeze({
      buildChatMessages,
      buildRequestAttempts,
      classifyHttpError,
      parseRetryAfterMs,
      postCompatible,
      requestCompatibleAttempt,
      withOpenAiPromptCacheFields,
    });
  }

  function classifyHttpError(status) {
    // 400/404/405/415/422/501 与 CLI 端 ai_planner.py 的
    // COMPATIBILITY_FALLBACK_STATUS_CODES 对齐:这些状态码通常意味着当前
    // 请求格式或端点不被 provider 支持,应回退到 auto 链的下一个格式,
    // 而不是以 non-retryable 错误立即中止(501 由下方 5xx 分支覆盖)。
    if (
      status === 400 || status === 404 || status === 405 ||
      status === 415 || status === 422
    ) {
      return true;
    }
    if (status === 408 || status === 429) return true;
    if (status >= 500 && status <= 599) return true;
    return false;
  }

  function createAbortError(message) {
    const error = new Error(message || "The operation was aborted.");
    error.name = "AbortError";
    error.code = 20;
    return error;
  }

  function readHeader(headers, name) {
    if (!headers) return "";
    if (typeof headers.get === "function") {
      return String(headers.get(name) || "");
    }
    const wanted = String(name || "").toLowerCase();
    for (const key of Object.keys(headers)) {
      if (key.toLowerCase() === wanted) {
        return String(headers[key] || "");
      }
    }
    return "";
  }

  function bindTimer(timerApi, methodName, globalScope) {
    if (timerApi && typeof timerApi[methodName] === "function") {
      return timerApi[methodName].bind(timerApi);
    }
    if (typeof globalScope[methodName] !== "function") {
      throw new Error(`ProviderClient requires ${methodName}.`);
    }
    return globalScope[methodName].bind(globalScope);
  }

  function normalizeLogger(logger) {
    if (typeof logger === "function") {
      return logger;
    }
    if (logger && typeof logger.warn === "function") {
      return (_level, error) => logger.warn(error);
    }
    return function () { };
  }

  ai.ProviderClient = Object.freeze({ create });
})(globalThis);
