/* global EXECUTABLE_ACTIONS, EXECUTION_ORDER, EXECUTABLE_STATUSES, normalizePath, pathWithinScope */

(function attachBookmarkAdvisorAI(globalScope) {
  const DEFAULT_API_BASE_URL = "https://api.openai.com/v1";
  const DEFAULT_MODEL = "gpt-5.4-mini";
  const DEFAULT_API_STYLE = "auto";
  const DEFAULT_MAX_ACTIONS = 40;
  const DEFAULT_APPROVE_THRESHOLD = 0.85;
  const BATCH_PLANNING_BOOKMARK_THRESHOLD = 50;
  const BATCH_PLANNING_SIZE = 50;
  const BATCH_PLANNING_CONCURRENCY = 3;
  const MAX_EXTENSION_FETCH_TIMEOUT_MS = 300000;
  const DEFAULT_REQUEST_TIMEOUT_MS = 180000;
  const DEFAULT_MAX_RETRIES = 1;

  const SUPPORTED_AI_ACTIONS = [
    "rename_folder",
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
    "delete_empty_folder",
    "keep_for_review",
  ];

  // ── Fast rules: loaded from packaged JSON, cached after first load ──
  var _fastRulesCache = null;

  // ── Shared logging utility ──
  function debugLog(message, level) {
    var logLevel = level || "log";
    var prefix = "[BookmarkAdvisor]";
    if (logLevel === "error") {
      console.error(prefix, message);
    } else if (logLevel === "warn") {
      console.warn(prefix, message);
    } else {
      console.log(prefix, message);
    }
  }

  var _FALLBACK_RULES = {
    defaults: { protect_root_loose_bookmarks: true, allow_new_folders_in_advise: true },
    protected_paths: ["/收藏夹栏", "/其他收藏夹", "/移动收藏夹", "/工作区"],
    category_hints: {},
    folder_relocations: [],
    bookmark_relocations: [],
  };

  function _cachedFastRules() {
    return _fastRulesCache || _FALLBACK_RULES;
  }

  async function loadFastRules() {
    if (_fastRulesCache) {
      return _fastRulesCache;
    }
    try {
      var rulesUrl = chrome.runtime.getURL("fast_rules.json");
      var response = await fetch(rulesUrl);
      if (!response.ok) {
        return _FALLBACK_RULES;
      }
      var data = await response.json();
      _fastRulesCache = {
        defaults: data.defaults || _FALLBACK_RULES.defaults,
        protected_paths: Array.isArray(data.protected_paths) ? data.protected_paths : _FALLBACK_RULES.protected_paths,
        category_hints: data.category_hints || {},
        folder_relocations: Array.isArray(data.folder_relocations) ? data.folder_relocations : [],
        bookmark_relocations: Array.isArray(data.bookmark_relocations) ? data.bookmark_relocations : [],
      };
      return _fastRulesCache;
    } catch (_error) {
      return _FALLBACK_RULES;
    }
  }

  // ═══════════════════════════════════════════════════════════════
  //  1. Public API
  // ═══════════════════════════════════════════════════════════════

  async function generateReviewedPlan(options) {
    if (options.signal && options.signal.aborted) {
      throw createAbortError("The operation was aborted.");
    }
    await loadFastRules();
    const apiKey = String(options.apiKey || "").trim();
    if (!apiKey) {
      throw new Error("OpenAI API key is required for HTTPS planning.");
    }

    const snapshot = options.snapshot || {};
    const apiBaseUrl = normalizeApiBaseUrl(options.apiBaseUrl || options.baseUrl || DEFAULT_API_BASE_URL);
    const apiStyle = normalizeApiStyle(options.apiStyle || DEFAULT_API_STYLE);
    const model = String(options.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL;
    const maxActions = Math.min(nonNegativeInteger(options.maxActions, DEFAULT_MAX_ACTIONS), 12);
    const autoApproveThreshold = finiteNumber(
      options.autoApproveThreshold,
      DEFAULT_APPROVE_THRESHOLD,
    );
    const requestTimeoutMs = requestTimeoutMsWithinMv3Lifetime(options.requestTimeoutMs);
    const maxRetries = options.maxRetries;
    const focusPath = String(options.focusPath || "").trim();
    const userInstruction = String(options.userInstruction || "").trim();
    const onProgress = typeof options.onProgress === "function" ? options.onProgress : function () {};
    const signal = options.signal;
    const planningSnapshot = buildPlanningSnapshot(snapshot, focusPath);
    const preferences = options.preferences || {};
    const activationPayload = await requestDraftPlanMaybeBatched({
      apiKey,
      apiBaseUrl,
      apiStyle,
      model,
      maxActions,
      requestTimeoutMs,
      maxRetries,
      snapshot: planningSnapshot,
      focusPath,
      userInstruction,
      preferences,
      onProgress,
      signal,
    });
    // eslint-disable-next-line no-console
    console.log(`[BookmarkAdvisor][offscreen] requestDraftPlan returned, activations=${(activationPayload.activations || []).length}`);

    await onProgress("Compiling activations...");
    let draft;
    try {
      const t0 = performance.now();
      draft = compileActivationPlan(activationPayload, planningSnapshot);
      debugLog(`compileActivationPlan done, actions=${draft.actions.length}, ` + Math.round(performance.now() - t0) + "ms", "log");
    } catch (err) {
      debugLog(`compileActivationPlan FAILED: ` + err, "error");
      throw err;
    }

    await onProgress(`Finalizing plan (${draft.actions.length} actions)...`);
    let reviewedPlan;
    try {
      const t0 = performance.now();
      reviewedPlan = finalizeDraftPlan({
        draft,
        snapshot: planningSnapshot,
        model,
        autoApproveThreshold,
      });
      debugLog(`finalizeDraftPlan done, ` + Math.round(performance.now() - t0) + "ms", "log");
    } catch (err) {
      debugLog(`finalizeDraftPlan FAILED: ` + err, "error");
      throw err;
    }

    await onProgress("Plan ready.");
    debugLog(`generateReviewedPlan complete, returning result`, "log");
    return {
      reviewed_plan: reviewedPlan,
      draft_summary: activationPayload.summary || {},
      planning_mode: "https_openai_compatible",
      api_style: apiStyle,
      api_base_url: apiBaseUrl,
      model,
      focus_path: focusPath,
    };
  }

  async function reviseReviewedPlan(options) {
    if (options.signal && options.signal.aborted) {
      throw createAbortError("The operation was aborted.");
    }
    await loadFastRules();
    const apiKey = String(options.apiKey || "").trim();
    if (!apiKey) {
      throw new Error("OpenAI API key is required for HTTPS planning.");
    }
    if (!options.existingPlan || !Array.isArray(options.existingPlan.actions)) {
      throw new Error("A reviewed plan is required before revision.");
    }

    const snapshot = options.snapshot || {};
    const apiBaseUrl = normalizeApiBaseUrl(options.apiBaseUrl || options.baseUrl || DEFAULT_API_BASE_URL);
    const apiStyle = normalizeApiStyle(options.apiStyle || DEFAULT_API_STYLE);
    const model = String(options.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL;
    const maxActions = nonNegativeInteger(options.maxActions, DEFAULT_MAX_ACTIONS);
    const autoApproveThreshold = finiteNumber(
      options.autoApproveThreshold,
      DEFAULT_APPROVE_THRESHOLD,
    );
    const requestTimeoutMs = requestTimeoutMsWithinMv3Lifetime(options.requestTimeoutMs);
    const maxRetries = options.maxRetries;
    const focusPath = String(options.focusPath || "").trim();
    const userInstruction = String(options.userInstruction || "").trim();
    if (!userInstruction) {
      throw new Error("Describe how to revise the loaded plan before calling the LLM.");
    }
    const onProgress = typeof options.onProgress === "function" ? options.onProgress : function () {};
    const signal = options.signal;
    const planningSnapshot = buildPlanningSnapshot(snapshot, focusPath);
    const preferences = options.preferences || {};
    const activationPayload = await requestRevisionPlan({
      apiKey,
      apiBaseUrl,
      apiStyle,
      model,
      maxActions,
      requestTimeoutMs,
      maxRetries,
      snapshot: planningSnapshot,
      existingPlan: options.existingPlan,
      userInstruction,
      preferences,
      onProgress,
      signal,
    });
    // eslint-disable-next-line no-console
    console.log(`[BookmarkAdvisor][offscreen] requestRevisionPlan returned, activations=${(activationPayload.activations || []).length}`);

    await onProgress("Compiling revision changes...");
    let draft;
    try {
      const t0 = performance.now();
      const deltaDraft = compileActivationPlan(activationPayload, planningSnapshot);
      draft = mergeRevisionDraft(options.existingPlan, deltaDraft);
      debugLog(`mergeRevisionDraft done, changed=${deltaDraft.actions.length}, total=${draft.actions.length}, ` + Math.round(performance.now() - t0) + "ms", "log");
    } catch (err) {
      debugLog(`compileActivationPlan FAILED: ` + err, "error");
      throw err;
    }

    await onProgress(`Finalizing plan (${draft.actions.length} actions)...`);
    let reviewedPlan;
    try {
      const t0 = performance.now();
      reviewedPlan = finalizeDraftPlan({
        draft,
        snapshot: planningSnapshot,
        model,
        autoApproveThreshold,
      });
      debugLog(`finalizeDraftPlan done, ` + Math.round(performance.now() - t0) + "ms", "log");
    } catch (err) {
      debugLog(`finalizeDraftPlan FAILED: ` + err, "error");
      throw err;
    }
    await onProgress("Plan ready.");
    debugLog(`reviseReviewedPlan complete, returning result`, "log");
    reviewedPlan.summary = {
      ...reviewedPlan.summary,
      overview: String((activationPayload.summary || {}).overview || "Revised in the Edge extension via HTTPS."),
      revision_instruction: userInstruction,
    };
    return {
      reviewed_plan: reviewedPlan,
      draft_summary: activationPayload.summary || {},
      planning_mode: "extension_https_revision",
      api_style: apiStyle,
      api_base_url: apiBaseUrl,
      model,
      focus_path: focusPath,
    };
  }

  async function requestDraftPlanMaybeBatched(options) {
    const parts = splitPlanningSnapshot(options.snapshot, BATCH_PLANNING_BOOKMARK_THRESHOLD, BATCH_PLANNING_SIZE);
    if (parts.length <= 1) {
      return requestDraftPlan(options);
    }
    await options.onProgress(`Large folder detected: ${options.snapshot.bookmarks.length} bookmarks, split into ${parts.length} cached prompt parts.`);
    const payloads = await mapWithConcurrency(parts, BATCH_PLANNING_CONCURRENCY, async (part, index) => {
      const partNumber = index + 1;
      await options.onProgress(`Planning part ${partNumber}/${parts.length} (${part.bookmarks.length} bookmarks)...`);
      return requestDraftPlan({
        ...options,
        maxActions: BATCH_PLANNING_SIZE,
        snapshot: part,
        batchInfo: {
          partNumber,
          totalParts: parts.length,
          partBookmarkCount: part.bookmarks.length,
        },
      });
    });
    const merged = mergeActivationPayloads(payloads);
    await options.onProgress(`Merged ${merged.activations.length} deduplicated activations from ${parts.length} parts.`);
    return merged;
  }

  async function requestDraftPlan({ apiKey, apiBaseUrl, apiStyle, model, maxActions, requestTimeoutMs, maxRetries, snapshot, focusPath, userInstruction, preferences, onProgress, signal, batchInfo }) {
    const systemText = buildSystemPrompt(maxActions, preferences);
    const userText = buildUserPrompt(snapshot, focusPath, userInstruction, preferences, batchInfo);
    const totalChars = systemText.length + userText.length;
    const approxTokens = Math.round(totalChars / 4);
    await onProgress(`Prompt size: ~${approxTokens} tokens (${totalChars} chars)`);
    const schema = activationResponseSchema();
    return requestLintedActivationPlan({
      apiKey,
      apiBaseUrl,
      apiStyle,
      model,
      requestTimeoutMs,
      maxRetries,
      schema,
      systemText,
      userText,
      snapshot,
      onProgress,
      signal,
      progressLabel: "planning",
    });
  }

  async function requestRevisionPlan({ apiKey, apiBaseUrl, apiStyle, model, maxActions, requestTimeoutMs, maxRetries, snapshot, existingPlan, userInstruction, preferences, onProgress, signal }) {
    const systemText = buildSystemPrompt(maxActions, preferences);
    const userText = buildRevisionUserPrompt(existingPlan, snapshot, userInstruction, preferences, maxActions);
    const totalChars = systemText.length + userText.length;
    const approxTokens = Math.round(totalChars / 4);
    await onProgress(`Prompt size: ~${approxTokens} tokens (${totalChars} chars)`);
    const schema = activationResponseSchema();
    return requestLintedActivationPlan({
      apiKey,
      apiBaseUrl,
      apiStyle,
      model,
      requestTimeoutMs,
      maxRetries,
      schema,
      systemText,
      userText,
      snapshot,
      onProgress,
      signal,
      progressLabel: "plan revision",
    });
  }

  async function requestLintedActivationPlan({ apiKey, apiBaseUrl, apiStyle, model, requestTimeoutMs, maxRetries, schema, systemText, userText, snapshot, onProgress, signal, progressLabel }) {
    const maxAttempts = Math.max(1, (Number.isFinite(maxRetries) ? maxRetries : DEFAULT_MAX_RETRIES) + 1);
    let retryFeedback = "";
    const errors = [];

    for (let lintAttempt = 1; lintAttempt <= maxAttempts; lintAttempt++) {
      for (const attempt of buildRequestAttempts(apiStyle, apiBaseUrl)) {
        try {
          await onProgress(`Calling LLM endpoint (${attemptLabel(attempt)}) for ${progressLabel}, pass ${lintAttempt}/${maxAttempts}...`);
          const payload = await requestCompatibleAttempt({
            attempt,
            apiBaseUrl,
            apiKey,
            model,
            requestTimeoutMs,
            schema,
            systemText,
            userText: userText + retryFeedback,
            signal,
            onProgress,
          });
          const rawText = extractAttemptText(attempt, payload);
          await onProgress(`Parsing response (${rawText.length} chars)...`);
          const activationPayload = parseDraftPlanText(rawText);
          await onProgress(`Linting ${(activationPayload.activations || []).length} activations...`);
          const lintErrors = lintActivationPayload(activationPayload, snapshot);
          if (lintErrors.length === 0) {
            await onProgress("Lint passed.");
            return activationPayload;
          }
          if (lintAttempt === maxAttempts && lintErrorsAreOnlyReferenceErrors(lintErrors)) {
            const prunedPayload = pruneInvalidActivationReferences(activationPayload, snapshot);
            const prunedLintErrors = lintActivationPayload(prunedPayload.payload, snapshot);
            if (prunedPayload.dropped > 0 && prunedLintErrors.length === 0) {
              await onProgress(`Dropped ${prunedPayload.dropped} activation(s) with unknown bookmark/folder ids after retry.`);
              return prunedPayload.payload;
            }
          }
          errors.push(`activation lint pass ${lintAttempt}: ${lintErrors.join("; ")}`);
          retryFeedback = buildActivationRetryFeedback(lintErrors);
          await onProgress(`Lint failed (${lintErrors.length} issue(s)). Retrying...`);
          break;
        } catch (error) {
          if (error && error.name === "AbortError") {
            throw error;
          }
          const errMsg = error.message || String(error);
          errors.push(`${attempt}: ${errMsg}`);
          if (errMsg.includes("JSON") || errMsg.includes("json") || errMsg.includes("parse") || errMsg.includes("lint")) {
            await onProgress(`Parse/lint error (${attemptLabel(attempt)}): ${errMsg.slice(0, 200)}`);
          } else {
            await onProgress(`LLM attempt failed (${attemptLabel(attempt)}). Trying fallback...`);
          }
        }
      }
    }

    throw new Error(`OpenAI-compatible HTTPS ${progressLabel} failed after ${maxAttempts} attempt(s). ${errors.join(" | ")}`);
  }

  function buildActivationRetryFeedback(lintErrors) {
    return [
      "",
      "",
      "Your previous activation JSON failed local validation.",
      "Return corrected JSON only, using the same activation schema.",
      "Use exact node_id values copied from the B/F rows in the prompt. Do not use URLs, titles, domains, indexes, or invented ids.",
      "Validation errors:",
      ...lintErrors.slice(0, 20).map((error) => `- ${error}`),
    ].join("\n");
  }

  function attemptLabel(attempt) {
    if (attempt === "responses_json_schema") {
      return "Responses JSON schema";
    }
    if (attempt === "chat_json_schema") {
      return "Chat JSON schema";
    }
    if (attempt === "chat_json_object") {
      return "Chat JSON object";
    }
    if (attempt === "completions_plain_json") {
      return "Completions plain JSON";
    }
    return "Chat plain JSON";
  }

  async function requestCompatibleAttempt({ attempt, apiBaseUrl, apiKey, model, requestTimeoutMs, schema, systemText, userText, signal, onProgress }) {
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
      return postCompatible(endpointUrl(apiBaseUrl, "responses"), apiKey, requestTimeoutMs, payload, signal, onProgress);
    }

    if (attempt === "completions_plain_json") {
      return postCompatible(endpointUrl(apiBaseUrl, "completions"), apiKey, requestTimeoutMs, {
        model,
        prompt: `${systemText}\nReturn a single JSON object and no Markdown fences.\n\n${userText}`,
        max_tokens: 16384,
        temperature: 0,
      }, signal, onProgress);
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
    return postCompatible(endpointUrl(apiBaseUrl, "chat/completions"), apiKey, requestTimeoutMs, withOpenAiPromptCacheFields(apiBaseUrl, model, chatPayload), signal, onProgress);
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
      return new URL(normalizeApiBaseUrl(apiBaseUrl)).hostname === "api.openai.com";
    } catch (_error) {
      return false;
    }
  }

  function supportsOpenAiExtendedPromptCache(model) {
    const name = String(model || "").toLowerCase();
    return name.startsWith("gpt-5.5") || name.startsWith("gpt-5.4") || name.startsWith("gpt-5.2") || name.startsWith("gpt-5.1") || name.startsWith("gpt-5") || name.startsWith("gpt-4.1");
  }

  function buildRequestAttempts(apiStyle, apiBaseUrl) {
    const exactEndpoint = coreEndpointKind(apiBaseUrl);
    if (exactEndpoint === "responses") {
      return ["responses_json_schema"];
    }
    if (exactEndpoint === "chat_completions") {
      return ["chat_plain_json", "chat_json_object", "chat_json_schema"];
    }
    if (exactEndpoint === "completions") {
      return ["completions_plain_json"];
    }
    if (apiStyle === "responses") {
      return ["responses_json_schema"];
    }
    if (apiStyle === "chat_completions") {
      return ["chat_plain_json", "chat_json_object", "chat_json_schema"];
    }
    if (apiStyle === "completions") {
      return ["completions_plain_json"];
    }
    // auto: 先尝试 chat JSON 约束；不支持 response_format 的兼容端点再退回 plain chat
    return ["chat_json_object", "chat_json_schema", "chat_plain_json", "completions_plain_json", "responses_json_schema"];
  }

  function buildChatMessages(systemText, userText, _schema, attempt) {
    const messages = [{ role: "system", content: systemText }];
    if (attempt === "chat_plain_json" || attempt === "chat_json_object") {
      messages[0] = {
        role: "system",
        content: `${systemText}\nReturn a single JSON object and no Markdown fences. Top-level fields: summary (object with overview string), activations (array of objects with op, node_id, target, duplicate_of_id, confidence, reason).`,
      };
    }
    messages.push({ role: "user", content: userText });
    return messages;
  }

  function createAbortError(message) {
    const error = new Error(message || "The operation was aborted.");
    error.name = "AbortError";
    error.code = 20;
    return error;
  }

  // ═══════════════════════════════════════════════════════════════
  //  3. API Client
  // ═══════════════════════════════════════════════════════════════

  async function postCompatible(url, apiKey, timeoutMs, body, externalSignal, onProgress) {
    const effectiveTimeout = timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS;
    const controller = new AbortController();
    let timedOut = false;
    let externalAborted = false;
    const onExternalAbort = function () {
      externalAborted = true;
      controller.abort();
    };
    if (externalSignal) {
      if (externalSignal.aborted) {
        throw createAbortError("The operation was aborted.");
      }
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
    const timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, effectiveTimeout);

    // MV3 Service Worker 在 await fetch 期间可能被 Chrome 终止。
    // 通过定期触发 onProgress 产生 JavaScript 事件，延长 SW 存活时间。
    let fetchKeepAliveId = null;
    if (typeof onProgress === "function") {
      let elapsed = 0;
      fetchKeepAliveId = setInterval(() => {
        elapsed += 1;
        void onProgress(`Waiting for LLM response... (${elapsed}s)`);
      }, 1000);
    }

    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (error) {
      clearTimeout(timeoutId);
      if (fetchKeepAliveId !== null) clearInterval(fetchKeepAliveId);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", onExternalAbort);
      }
      if (timedOut || (error && error.name === "AbortError" && !externalAborted && !externalSignal?.aborted)) {
        throw new Error(`Request timed out after ${Math.round(effectiveTimeout / 1000)}s: ${url}`);
      }
      if (externalAborted || externalSignal?.aborted) {
        throw createAbortError("The operation was aborted.");
      }
      throw error;
    }
    if (fetchKeepAliveId !== null) clearInterval(fetchKeepAliveId);

    let textKeepAliveId = null;
    if (typeof onProgress === "function") {
      let elapsed = 0;
      textKeepAliveId = setInterval(() => {
        elapsed += 1;
        void onProgress(`Reading LLM response body... (${elapsed}s)`);
      }, 1000);
    }

    let text;
    let bodyTimedOut = false;
    let bodyTimeoutId;
    try {
      text = await Promise.race([
        response.text(),
        new Promise((_, reject) => {
          bodyTimeoutId = setTimeout(() => {
            bodyTimedOut = true;
            reject(new Error(`Response body timed out after ${Math.round(effectiveTimeout / 1000)}s`));
          }, effectiveTimeout);
        }),
      ]);
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(bodyTimeoutId);
      if (textKeepAliveId !== null) clearInterval(textKeepAliveId);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", onExternalAbort);
      }
      if (timedOut || bodyTimedOut) {
        throw new Error(`Request timed out after ${Math.round(effectiveTimeout / 1000)}s: ${url}`);
      }
      if (externalAborted || externalSignal?.aborted) {
        throw createAbortError("The operation was aborted.");
      }
      throw error;
    }
    clearTimeout(timeoutId);
    clearTimeout(bodyTimeoutId);
    if (textKeepAliveId !== null) clearInterval(textKeepAliveId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }

    // 如果 body 特别大，JSON.parse 也可能慢。先记录大小。
    const bodySize = text ? text.length : 0;
    if (typeof onProgress === "function" && bodySize > 0) {
      void onProgress(`Response body received: ${bodySize} chars`);
    }

    let payload = null;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch (_error) {
      payload = { raw: text };
    }
    if (!response.ok) {
      const message = payload && payload.error && payload.error.message
        ? payload.error.message
        : text;
      throw new Error(`${response.status} ${message}`);
    }
    return payload;
  }

  function buildPlanningSnapshot(snapshot, focusPath) {
    const folders = (snapshot.folders || []).map(normalizeFolder);
    const bookmarks = (snapshot.bookmarks || [])
      .map(normalizeBookmark)
      .filter((bookmark) => !focusPath || pathWithinScope(bookmark.folder_path, focusPath))
      .map((bookmark) => ({
        ...bookmark,
        review_status: urlRequiresReview(bookmark.url) ? "fast_reviewed" : "skipped_internal",
        review_method: urlRequiresReview(bookmark.url)
          ? "extension_fast_title_domain"
          : "system_skip",
        page_title: bookmark.title,
        one_line_summary: bookmark.domain
          ? `${bookmark.title} (${bookmark.domain})`
          : bookmark.title,
        review_confidence: urlRequiresReview(bookmark.url) ? 0.35 : 1.0,
      }));

    return {
      snapshot_version: "2",
      source: snapshot.source || "edge-extension",
      source_path: snapshot.source_path || "edge-bookmarks-api",
      created_at: snapshot.created_at || new Date().toISOString(),
      focus_path: focusPath,
      folders: folders.filter((folder) => !focusPath || pathWithinScope(folder.path, focusPath) || focusPath.startsWith(`${folder.path}/`)),
      bookmarks,
    };
  }

  function splitPlanningSnapshot(snapshot, threshold, size) {
    const bookmarks = snapshot.bookmarks || [];
    if (bookmarks.length <= threshold) {
      return [snapshot];
    }
    const parts = [];
    for (let index = 0; index < bookmarks.length; index += size) {
      parts.push({
        ...snapshot,
        bookmarks: bookmarks.slice(index, index + size),
      });
    }
    return parts;
  }

  async function mapWithConcurrency(items, concurrency, mapper) {
    const results = new Array(items.length);
    let nextIndex = 0;
    const workers = new Array(Math.min(concurrency, items.length)).fill(null).map(async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        results[index] = await mapper(items[index], index);
      }
    });
    await Promise.all(workers);
    return results;
  }

  function mergeActivationPayloads(payloads) {
    const summaryParts = [];
    const activationByKey = new Map();
    const nodeScopedKeyByNode = new Map();

    for (const payload of payloads || []) {
      const overview = payload && payload.summary ? payload.summary.overview : "";
      if (overview) {
        summaryParts.push(String(overview));
      }
      for (const activation of (payload && payload.activations) || []) {
        const key = activationDedupeKey(activation);
        const existing = activationByKey.get(key);
        if (existing && !activationShouldReplace(existing, activation)) {
          continue;
        }
        if (isBookmarkScopedActivation(activation)) {
          const nodeKey = String(activation.node_id || "");
          const previousKey = nodeScopedKeyByNode.get(nodeKey);
          const previous = previousKey ? activationByKey.get(previousKey) : null;
          if (previous && previousKey !== key && !activationShouldReplace(previous, activation)) {
            continue;
          }
          if (previousKey && previousKey !== key) {
            activationByKey.delete(previousKey);
          }
          nodeScopedKeyByNode.set(nodeKey, key);
        }
        activationByKey.set(key, activation);
      }
    }

    return {
      summary: {
        overview: summaryParts.length ? summaryParts.join("; ") : "Generated in cached parts.",
      },
      activations: Array.from(activationByKey.values()),
    };
  }

  function activationDedupeKey(activation) {
    return [
      String(activation.op || ""),
      String(activation.node_id || ""),
      String(activation.target || ""),
      String(activation.duplicate_of_id || ""),
    ].join("::");
  }

  function isBookmarkScopedActivation(activation) {
    return ["move_bookmark", "remove_duplicate", "keep_for_review"].includes(String(activation.op || "")) && !!activation.node_id;
  }

  function activationShouldReplace(existing, candidate) {
    const existingConfidence = finiteNumber(existing.confidence, 0);
    const candidateConfidence = finiteNumber(candidate.confidence, 0);
    if (candidateConfidence !== existingConfidence) {
      return candidateConfidence > existingConfidence;
    }
    return existing.op === "keep_for_review" && candidate.op !== "keep_for_review";
  }

  function finalizeDraftPlan({ draft, snapshot, model, autoApproveThreshold }) {
    const t0 = performance.now();
    const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
    const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.path, folder]));
    const actions = [];
    const seen = new Set();

    for (const action of draft.actions || []) {
      const normalized = normalizeAction(action);
      if (!SUPPORTED_AI_ACTIONS.includes(normalized.action_type)) {
        continue;
      }
      const guarded = applyActionGuardrails(normalized, bookmarkIndex);
      addAction(actions, seen, guarded);
    }

    for (const action of forcedRuleActions(snapshot, folderIndex)) {
      addAction(actions, seen, action);
    }

    const finalized = actions.map((action) => {
      if (!EXECUTABLE_ACTIONS.has(action.action_type)) {
        return { ...action, status: "blocked" };
      }
      if (action.status === "approved" || action.status === "edited") {
        return action;
      }
      if (action.confidence >= autoApproveThreshold) {
        return {
          ...action,
          status: "approved",
          details: {
            ...action.details,
            finalize_reason: "auto-approved",
          },
        };
      }
      return {
        ...action,
        status: "blocked",
        details: {
          ...action.details,
          finalize_reason: "below-threshold",
        },
      };
    });

    const elapsed = Math.round(performance.now() - t0);
    debugLog(`finalizeDraftPlan: ${finalized.length} actions, ${elapsed}ms`, "log");

    return {
      plan_version: "2",
      plan_kind: "reviewed",
      source: "bookmark-advisor-extension",
      created_at: new Date().toISOString(),
      source_snapshot: snapshot.source_path || "edge-bookmarks-api",
      rules_source: "extension-embedded-fast-rules",
      model,
      summary: {
        overview: String((draft.summary || {}).overview || "Generated in the Edge extension via HTTPS."),
        planning_mode: "extension_https_fast",
        review_method: "extension_fast_title_domain",
        total_actions: finalized.length,
        approved_actions: finalized.filter((action) => ["approved", "edited"].includes(action.status)).length,
        blocked_actions: finalized.filter((action) => action.status === "blocked" || action.status === "proposed").length,
      },
      actions: finalized,
    };
  }

  // ═══════════════════════════════════════════════════════════════
  //  4. Compiler & Finalizer
  // ═══════════════════════════════════════════════════════════════

  function compileActivationPlan(activationPayload, snapshot) {
    const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
    const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.id, folder]));
    const actions = [];

    for (const activation of activationPayload.activations || []) {
      actions.push(compileActivation(activation, bookmarkIndex, folderIndex));
    }

    // summary 允许缺失或非对象（如字符串），编译阶段强制为对象
    const rawSummary = activationPayload.summary;
    const safeSummary = (rawSummary && typeof rawSummary === "object" && !Array.isArray(rawSummary)) ? rawSummary : {};
    return {
      summary: safeSummary,
      actions,
    };
  }

  function mergeRevisionDraft(existingPlan, deltaDraft) {
    const retained = [];
    const replacementKeys = new Set((deltaDraft.actions || []).map(revisionActionScopeKey).filter(Boolean));
    for (const action of existingPlan.actions || []) {
      const normalized = normalizeAction(action);
      const key = revisionActionScopeKey(normalized);
      if (key && replacementKeys.has(key)) {
        continue;
      }
      retained.push(normalized);
    }
    return {
      summary: {
        ...(existingPlan.summary || {}),
        ...(deltaDraft.summary || {}),
      },
      actions: retained.concat(deltaDraft.actions || []),
    };
  }

  function revisionActionScopeKey(action) {
    const type = String(action.action_type || "");
    if (["move_bookmark", "remove_duplicate", "keep_for_review"].includes(type)) {
      const id = action.bookmark_locator && action.bookmark_locator.id;
      return id ? `bookmark:${id}` : "";
    }
    if (["move_folder", "rename_folder", "delete_empty_folder"].includes(type)) {
      const folder = action.folder_locator || {};
      const idOrPath = folder.id || folder.path;
      return idOrPath ? `folder:${idOrPath}` : "";
    }
    if (type === "create_folder") {
      return action.target_path ? `create_folder:${action.target_path}` : "";
    }
    return "";
  }

  function lintActivationPayload(activationPayload, snapshot) {
    const errors = [];
    if (!activationPayload || typeof activationPayload !== "object") {
      return ["Response must be a JSON object."];
    }
    // summary 和 activations 格式问题由 compile 阶段自动修复，lint 不阻断
    if (!Array.isArray(activationPayload.activations)) {
      errors.push("activations must be an array.");
      return errors;
    }

    const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
    const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.id, folder]));
    const focusPath = String(snapshot.focus_path || "");

    activationPayload.activations.forEach((activation, index) => {
      const path = `activations[${index}]`;
      if (!activation || typeof activation !== "object") {
        errors.push(`${path} must be an object.`);
        return;
      }
      const op = String(activation.op || "");
      const nodeId = String(activation.node_id || "");
      const target = String(activation.target || "");
      if (!SUPPORTED_AI_ACTIONS.includes(op)) {
        errors.push(`${path}.op must be one of ${SUPPORTED_AI_ACTIONS.join(", ")}.`);
        return; // 未知 op 直接跳过后续检查
      }

      // 只检查会打断执行逻辑的严重错误；格式问题（confidence 缺失、reason 空等）由 compile 阶段修复
      if (op === "keep_for_review") {
        if (nodeId && !bookmarkIndex.has(nodeId) && !folderIndex.has(nodeId)) {
          errors.push(`${path}.node_id must reference an existing bookmark or folder id.`);
        }
      } else if (op === "create_folder") {
        if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
        if (!pathWithinScope(target, focusPath)) errors.push(`${path}.target must stay within the focused folder.`);
      } else if (op === "move_bookmark") {
        const bookmark = bookmarkIndex.get(nodeId);
        if (!bookmark) errors.push(`${path}.node_id must reference an existing bookmark id.`);
        if (bookmark && !pathWithinScope(bookmark.folder_path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
      } else if (op === "move_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
        if (folder && !pathWithinScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
        if (folder && (target === folder.path || target.startsWith(`${folder.path}/`))) {
          errors.push(`${path}.target must not be the same folder or its descendant.`);
        }
      } else if (op === "rename_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
        if (folder && !pathWithinScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
      } else if (op === "remove_duplicate") {
        const bookmark = bookmarkIndex.get(nodeId);
        const duplicateOf = bookmarkIndex.get(String(activation.duplicate_of_id || ""));
        if (!bookmark) errors.push(`${path}.node_id must reference an existing bookmark id.`);
        if (bookmark && !pathWithinScope(bookmark.folder_path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!duplicateOf) errors.push(`${path}.duplicate_of_id must reference an existing bookmark id.`);
        // duplicate URL 不匹配不阻断，由 compile 阶段转为 keep_for_review
      } else if (op === "delete_empty_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
        if (folder && !pathWithinScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
      }
    });

    return errors;
  }

  function pruneInvalidActivationReferences(activationPayload, snapshot) {
    if (!activationPayload || !Array.isArray(activationPayload.activations)) {
      return { payload: activationPayload, dropped: 0 };
    }
    const bookmarkIds = new Set((snapshot.bookmarks || []).map((bookmark) => String(bookmark.id || "")));
    const folderIds = new Set((snapshot.folders || []).map((folder) => String(folder.id || "")));
    const kept = [];
    let dropped = 0;
    for (const activation of activationPayload.activations) {
      if (!activation || typeof activation !== "object") {
        kept.push(activation);
        continue;
      }
      if (activationHasUnknownReferences(activation, bookmarkIds, folderIds)) {
        dropped += 1;
        continue;
      }
      kept.push(activation);
    }
    return {
      payload: {
        ...activationPayload,
        activations: kept,
      },
      dropped,
    };
  }

  function lintErrorsAreOnlyReferenceErrors(lintErrors) {
    return lintErrors.length > 0 && lintErrors.every((error) => String(error || "").includes("must reference an existing"));
  }

  function activationHasUnknownReferences(activation, bookmarkIds, folderIds) {
    const op = String(activation.op || "");
    const nodeId = String(activation.node_id || "");
    if (op === "move_bookmark" || op === "remove_duplicate") {
      if (!bookmarkIds.has(nodeId)) {
        return true;
      }
      if (op === "remove_duplicate" && !bookmarkIds.has(String(activation.duplicate_of_id || ""))) {
        return true;
      }
      return false;
    }
    if (op === "move_folder" || op === "rename_folder" || op === "delete_empty_folder") {
      return !folderIds.has(nodeId);
    }
    if (op === "keep_for_review") {
      return !!nodeId && !bookmarkIds.has(nodeId) && !folderIds.has(nodeId);
    }
    return false;
  }

  function compileActivation(activation, bookmarkIndex, folderIndex) {
    const op = String(activation.op || "keep_for_review");
    const reason = sanitizeForPrompt(activation.reason || "Needs review.") || "Needs review.";
    const confidence = finiteNumber(activation.confidence, 0);
    const nodeId = String(activation.node_id || "");
    const target = String(activation.target || "");

    if (op === "move_bookmark") {
      const bookmark = bookmarkIndex.get(nodeId);
      if (!bookmark || !isAbsolutePath(target)) {
        return reviewActivation(activation, reason, confidence, "Move bookmark activation could not be resolved locally.");
      }
      return baseCompiledAction(activation, reason, confidence, {
        action_type: "move_bookmark",
        bookmark_locator: bookmarkLocator(bookmark),
        from_path: bookmark.folder_path,
        to_path: target,
      });
    }

    if (op === "move_folder") {
      const folder = folderIndex.get(nodeId);
      if (!folder || !isAbsolutePath(target) || target === folder.path || target.startsWith(`${folder.path}/`)) {
        return reviewActivation(activation, reason, confidence, "Move folder activation could not be resolved safely.");
      }
      return baseCompiledAction(activation, reason, confidence, {
        action_type: "move_folder",
        folder_locator: folderLocator(folder),
        from_path: folder.path,
        to_path: target,
      });
    }

    if (op === "rename_folder") {
      const folder = folderIndex.get(nodeId);
      const newTitle = sanitizeForPrompt(target);
      if (!folder || !newTitle) {
        return reviewActivation(activation, reason, confidence, "Rename folder activation could not be resolved locally.");
      }
      return baseCompiledAction(activation, reason, confidence, {
        action_type: "rename_folder",
        folder_locator: folderLocator(folder),
        from_path: folder.path,
        to_name: newTitle,
      });
    }

    if (op === "create_folder") {
      if (!isAbsolutePath(target)) {
        return reviewActivation(activation, reason, confidence, "Create folder activation did not include an absolute folder path.");
      }
      return baseCompiledAction(activation, reason, confidence, {
        action_type: "create_folder",
        target_path: target,
      });
    }

    if (op === "remove_duplicate") {
      const bookmark = bookmarkIndex.get(nodeId);
      const duplicateOf = bookmarkIndex.get(String(activation.duplicate_of_id || ""));
      if (!bookmark || !duplicateOf || bookmark.normalized_url !== duplicateOf.normalized_url) {
        return reviewActivation(activation, reason, confidence, "Duplicate removal activation could not be verified locally.");
      }
      return baseCompiledAction(activation, reason, confidence, {
        action_type: "remove_duplicate",
        bookmark_locator: bookmarkLocator(bookmark),
        from_path: bookmark.folder_path,
      });
    }

    if (op === "delete_empty_folder") {
      const folder = folderIndex.get(nodeId);
      if (!folder) {
        return reviewActivation(activation, reason, confidence, "Delete empty folder activation could not be resolved locally.");
      }
      return baseCompiledAction(activation, reason, confidence, {
        action_type: "delete_empty_folder",
        folder_locator: folderLocator(folder),
        from_path: folder.path,
      });
    }

    return reviewActivation(activation, reason, confidence, "LLM marked this item for review.");
  }

  function baseCompiledAction(activation, reason, confidence, fields) {
    return Object.assign({
      action_id: "",
      status: "proposed",
      reason,
      confidence,
      bookmark_locator: {},
      folder_locator: {},
      from_path: "",
      to_path: "",
      target_path: "",
      to_name: "",
      details: activationDetails(activation, reason, "compiled-activation"),
    }, fields);
  }

  function reviewActivation(activation, reason, confidence, reviewReason) {
    return baseCompiledAction(activation, `${reason} [${reviewReason}]`, confidence, {
      action_type: "keep_for_review",
      details: activationDetails(activation, reviewReason, "activation-review-required"),
    });
  }

  function activationDetails(activation, summary, guardrail) {
    return {
      evidence: {
        review_status: "derived",
        review_method: "extension-activation",
        summary: sanitizeForPrompt(summary || activation.reason || ""),
        rule_override: "",
      },
      guardrail,
      rule_override: "",
    };
  }

  function folderLocator(folder) {
    return {
      id: folder.id,
      name: folder.name,
      path: folder.path,
    };
  }

  function isAbsolutePath(path) {
    return typeof path === "string" && path.startsWith("/") && path.length > 1;
  }

  function applyActionGuardrails(action, bookmarkIndex) {
    if (action.action_type !== "move_bookmark") {
      return action;
    }

    const bookmark = bookmarkIndex.get(action.bookmark_locator.id);
    if (!bookmark) {
      return blockForReview(action, "Bookmark locator could not be verified in the current snapshot.");
    }
    if (_cachedFastRules().protected_paths.includes(bookmark.folder_path)) {
      return blockForReview(action, "Blocked by protected root loose-bookmark rule.");
    }
    return action;
  }

  function blockForReview(action, reason) {
    return {
      ...action,
      action_type: "keep_for_review",
      status: "blocked",
      to_path: "",
      target_path: "",
      reason: `${action.reason} [${reason}]`,
      details: {
        ...action.details,
        guardrail: "extension-review-required",
      },
    };
  }

  function addAction(actions, seen, action) {
    const key = [
      action.action_type,
      action.bookmark_locator.id || action.folder_locator.id || action.folder_locator.path,
      action.to_path || action.target_path || action.to_name || "",
    ].join("::");
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    actions.push(action);
  }

  function forcedRuleActions(snapshot, folderIndex) {
    var rules = _cachedFastRules();
    var actions = [];
    var focusPath = String(snapshot.focus_path || "");
    for (var i = 0; i < rules.folder_relocations.length; i++) {
      var rule = rules.folder_relocations[i];
      var folder = folderIndex.get(rule.from);
      if (!folder || !pathWithinScope(folder.path, focusPath)) {
        continue;
      }
      actions.push(normalizeAction({
        action_type: "move_folder",
        status: "approved",
        reason: rule.reason,
        confidence: 0.99,
        folder_locator: { id: folder.id, name: folder.name, path: folder.path },
        from_path: folder.path,
        to_path: rule.to,
        details: {
          evidence: {
            review_status: "derived",
            review_method: "forced-rule",
            summary: rule.reason,
            rule_override: "forced-folder-relocation",
          },
          guardrail: "forced-folder-relocation",
          rule_override: "forced-folder-relocation",
        },
      }));
    }

    for (var j = 0; j < rules.bookmark_relocations.length; j++) {
      var bkRule = rules.bookmark_relocations[j];
      for (const bookmark of snapshot.bookmarks || []) {
        if (!pathWithinScope(bookmark.folder_path, focusPath) || !bookmarkMatchesRule(bookmark, bkRule)) {
          continue;
        }
        actions.push(normalizeAction({
          action_type: "move_bookmark",
          status: "approved",
          reason: bkRule.reason,
          confidence: 0.98,
          bookmark_locator: bookmarkLocator(bookmark),
          from_path: bookmark.folder_path,
          to_path: bkRule.to,
          details: {
            evidence: {
              review_status: bookmark.review_status || "reviewed",
              review_method: "forced-rule",
              summary: bkRule.reason,
              rule_override: "forced-bookmark-relocation",
            },
            guardrail: "forced-bookmark-relocation",
            rule_override: "forced-bookmark-relocation",
          },
        }));
      }
    }
    return actions;
  }

  function bookmarkMatchesRule(bookmark, rule) {
    const match = rule.match || {};
    if (match.folder_path && bookmark.folder_path !== match.folder_path) {
      return false;
    }
    if (match.title_contains && !bookmark.title.toLowerCase().includes(match.title_contains.toLowerCase())) {
      return false;
    }
    if (match.title_equals && bookmark.title !== match.title_equals) {
      return false;
    }
    if (match.url_contains && !bookmark.url.toLowerCase().includes(match.url_contains.toLowerCase())) {
      return false;
    }
    return true;
  }

  // ═══════════════════════════════════════════════════════════════
  //  2. Prompt Builder
  // ═══════════════════════════════════════════════════════════════

  function buildSystemPrompt(maxActions, preferences) {
    var prefs = preferences || {};
    var lines = [
      "You are an expert bookmark organizer.",
      "Return JSON only. Return a single JSON object only. No markdown fences. No explanations outside the JSON.",
      "Focus on semantic organization, not cosmetic renaming.",
      "Prefer moving bookmarks into semantically appropriate existing folders.",
      "Only propose create_folder when a genuinely new category is justified.",
      `Propose at most ${maxActions} high-value actions.`,
      "Use keep_for_review for ambiguous, risky, or low-confidence items.",
      "Only bookmarks with review_status=reviewed may be auto-classified; unresolved bookmarks must stay in keep_for_review.",
      "Choosing any action other than keep_for_review means you recommend executing it.",
      "Confidence is a number from 0.0 to 1.0. Set confidence=0.95 for obvious moves, 0.5 for uncertain ones.",
      "When title and domain evidence is insufficient, use keep_for_review instead of guessing.",
      "The browser extension will lint and post-process your output before execution.",
      "When you can classify confidently from title, domain, and folder_path, decide immediately. Keep reasons under 15 words. Do not deliberate — a quick correct classification is better than slow overthinking.",
      "For bookmarks where title and domain alone are ambiguous, use web search/grounding only if your API runtime actually provides it. Batch all uncertain URLs into one search pass; if no search tool is available, keep them for review instead of inferring page content.",
      "",
      "Required JSON structure:",
      '{"summary":{"overview":"brief plan description"},"activations":[{"op":"move_bookmark","node_id":"bookmark-id","target":"/folder/path","duplicate_of_id":"","confidence":0.92,"reason":"why this move makes sense"},{"op":"create_folder","node_id":"","target":"/new/folder/path","duplicate_of_id":"","confidence":0.88,"reason":"new category needed"},{"op":"delete_empty_folder","node_id":"folder-id","target":"","duplicate_of_id":"","confidence":0.9,"reason":"folder is empty and no longer needed"},{"op":"keep_for_review","node_id":"bookmark-id","target":"","duplicate_of_id":"","confidence":0.3,"reason":"unclear purpose from title alone"}]}',
      "Rules: node_id is the bookmark/folder id from the snapshot. target is the absolute destination path except delete_empty_folder and keep_for_review. duplicate_of_id is only used for remove_duplicate and must be empty for other ops. confidence must always be a number (0.0-1.0).",
    ];

    if (prefs.protectRootLooseBookmarks === "yes") {
      lines.push("Loose bookmarks directly under protected root paths must stay in place. Do not move them.");
    } else {
      lines.push("Loose bookmarks under protected root paths may be reorganized into appropriate subfolders.");
    }

    if (prefs.sortOrder === "alpha-asc") {
      lines.push("Within each destination folder, arrange bookmarks in alphabetical order by title (A to Z).");
    } else if (prefs.sortOrder === "alpha-desc") {
      lines.push("Within each destination folder, arrange bookmarks in reverse alphabetical order by title (Z to A).");
    }

    if (prefs.planningStyle === "conservative") {
      lines.push("Be very conservative: only move bookmarks you are highly confident about. When in doubt, use keep_for_review.");
      lines.push("Avoid creating new folders unless absolutely necessary.");
    } else if (prefs.planningStyle === "aggressive") {
      lines.push("Be thorough: try to organize every bookmark into a meaningful category. Create new folders when no existing folder fits.");
      lines.push("Minimize keep_for_review — only use it for truly ambiguous items.");
    }

    return lines.join(" ");
  }

  function buildUserPrompt(snapshot, focusPath, userInstruction, preferences, batchInfo) {
    var rules = _cachedFastRules();
    var prefs = preferences || {};
    var protectRoot = prefs.protectRootLooseBookmarks !== "no";
    var rulesSummary = {
      protect_root_loose_bookmarks: protectRoot,
      protected_paths: rules.protected_paths,
      forced_folder_relocations: rules.folder_relocations,
      forced_bookmark_relocations: rules.bookmark_relocations,
      fast_mode_warning: "URL review evidence is limited to current bookmark title, URL, domain, and folder path.",
    };
    const prompt = [
      "Given this Edge bookmark snapshot and these guardrails, propose lightweight activation rows for a semantic reorganization plan.",
      "The snapshot was collected from chrome.bookmarks and enriched in fast mode with title/domain evidence only.",
      "For bookmarks you can classify confidently from title, domain, and folder path: classify immediately, do not overthink.",
      "For bookmarks where the title or domain is ambiguous: if your API runtime provides web search or grounding, visit all uncertain URLs in one batch pass, then classify based on the page content. Do NOT look up URLs one by one.",
      "If search/grounding is unavailable, or if a bookmark remains unclear after searching, use keep_for_review and explain why.",
      "For move_bookmark or remove_duplicate, set node_id to the bookmark id from the snapshot.",
      "For move_folder or rename_folder, set node_id to the folder id from the snapshot.",
      "Copy node_id exactly from B/F rows. Never use URLs, titles, domains, folder paths, numeric positions, or invented ids as node_id.",
      "For delete_empty_folder, set node_id to a folder id only when the snapshot shows 0 bookmarks and 0 subfolders for that folder.",
      "For move_bookmark or move_folder, set target to the absolute destination folder path.",
      "For rename_folder, set target to the new folder title.",
      "For create_folder, set target to the absolute folder path to create.",
      "For remove_duplicate, set duplicate_of_id to the id of the original bookmark.",
      "Do not invent bookmarks or folders that are not implied by the snapshot.",
    ];
    if (focusPath) {
      prompt.push(`Focus on bookmarks currently under ${focusPath}. Do not propose unrelated changes outside that focus folder.`);
    }
    const instructionPrefix = userInstruction ? `User instruction: ${userInstruction}\n\n` : "";
    const batchText = batchInfo && batchInfo.totalParts > 1
      ? [
        `Part: ${batchInfo.partNumber}/${batchInfo.totalParts}. This part contains ${batchInfo.partBookmarkCount} bookmarks.`,
        `Only return activations for node_ids present in this part. Return up to ${batchInfo.partBookmarkCount} activation rows for this part.`,
        "The extension will merge and deduplicate all parts after every part returns.",
        "",
      ].join("\n")
      : "";
    return `${instructionPrefix}${prompt.join("\n")}\n\nRules:\n${JSON.stringify(rulesSummary)}\n\n${encodeSnapshotFolders(snapshot)}\n\n${batchText}${encodeSnapshotBookmarks(snapshot, true)}`;
  }

  function buildRevisionUserPrompt(existingPlan, snapshot, userInstruction, preferences, maxActions) {
    var rules = _cachedFastRules();
    var prefs = preferences || {};
    var protectRoot = prefs.protectRootLooseBookmarks !== "no";
    var rulesSummary = {
      protect_root_loose_bookmarks: protectRoot,
      protected_paths: rules.protected_paths,
      forced_folder_relocations: rules.folder_relocations,
      forced_bookmark_relocations: rules.bookmark_relocations,
      fast_mode_warning: "URL review evidence is limited to current bookmark title, URL, domain, and folder path.",
    };
    return [
      "Revise the current reviewed bookmark plan according to the user instruction.",
      "Return only changed activation rows: additions, replacements, or rows that should become keep_for_review.",
      "Do not repeat unchanged activations from the existing plan. The extension will preserve unchanged rows locally.",
      "To replace an existing bookmark or folder action, return one activation for the same node_id with the new target/op.",
      "To stop executing an existing bookmark or folder action, return keep_for_review for the same node_id with a brief reason.",
      `Return at most ${maxActions} changed activation rows unless the instruction explicitly requires more.`,
      "Do not invent bookmarks or folders that are not implied by the current snapshot.",
      "For move_bookmark or remove_duplicate, set node_id to the bookmark id from the snapshot.",
      "For move_folder or rename_folder, set node_id to the folder id from the snapshot.",
      "For delete_empty_folder, set node_id to a folder id only when the snapshot shows 0 bookmarks and 0 subfolders for that folder.",
      "For move_bookmark or move_folder, set target to the absolute destination folder path.",
      "For rename_folder, set target to the new folder title.",
      "For create_folder, set target to the absolute folder path to create.",
      `User revision instruction: ${sanitizeForPrompt(userInstruction)}`,
      "",
      encodePlan(existingPlan),
      "",
      "Rules:",
      JSON.stringify(rulesSummary),
      "",
      encodeSnapshot(snapshot, false),
    ].join("\n");
  }

  function _pipeSafe(text) {
    return String(text || "").replace(/\|/g, "¦");
  }

  function _compactTitle(title) {
    var cleaned = sanitizeForPrompt(title);
    return cleaned.length > 80 ? cleaned.slice(0, 80) : cleaned;
  }

  function encodeSnapshot(snapshot, includeStatus) {
    return [encodeSnapshotFolders(snapshot), encodeSnapshotBookmarks(snapshot, includeStatus)].filter(Boolean).join("\n");
  }

  function encodeSnapshotFolders(snapshot) {
    var lines = [];
    if (snapshot.focus_path) {
      lines.push("Focus:" + snapshot.focus_path);
    }
    var folders = snapshot.folders || [];
    for (var fi = 0; fi < folders.length; fi++) {
      var f = folders[fi];
      lines.push("F " + f.id + "|" + _pipeSafe(f.path) + "|" + (f.bookmark_count || 0) + "|" + (f.subfolder_count || 0));
    }
    return lines.join("\n");
  }

  function encodeSnapshotBookmarks(snapshot, includeStatus) {
    var lines = [];
    var bookmarks = snapshot.bookmarks || [];
    for (var bi = 0; bi < bookmarks.length; bi++) {
      var b = bookmarks[bi];
      var title = _pipeSafe(_compactTitle(b.title));
      // 跳过内部 URL 的 domain（localhost、file 等）以节省 tokens
      var domain = _pipeSafe(b.domain || "");
      var fp = _pipeSafe(b.folder_path || "");
      var status = includeStatus ? ((b.review_status === "fast_reviewed") ? "F" : "R") : "";
      var parts = ["B", b.id, title, domain, fp];
      if (includeStatus) parts.push(status);
      lines.push(parts.join(" "));
    }
    return lines.join("\n");
  }

  function encodePlan(plan) {
    var actions = plan.actions || [];
    var lines = [];
    for (var i = 0; i < actions.length; i++) {
      var a = actions[i];
      var t = String(a.action_type || "");
      var nodeId = "";
      var target = "";
      if (t === "move_bookmark" || t === "remove_duplicate") {
        nodeId = (a.bookmark_locator || {}).id || "";
      } else if (t === "move_folder" || t === "rename_folder") {
        nodeId = (a.folder_locator || {}).id || "";
      }
      if (t === "move_bookmark" || t === "move_folder") {
        target = String(a.to_path || "");
      } else if (t === "rename_folder") {
        target = String(a.to_name || "");
      } else if (t === "create_folder") {
        target = String(a.target_path || "");
      }
      lines.push(
        "A " +
        (a.action_id || "") + "|" +
        t + "|" +
        (a.status || "") + "|" +
        nodeId + "|" +
        _pipeSafe(target) + "|" +
        finiteNumber(a.confidence, 0) + "|" +
        _pipeSafe(sanitizeForPrompt(a.reason || ""))
      );
    }
    return lines.join("\n");
  }

  // ═══════════════════════════════════════════════════════════════
  //  5. Schema & Lint
  // ═══════════════════════════════════════════════════════════════

  function activationResponseSchema() {
    return {
      type: "object",
      properties: {
        summary: {
          type: "object",
          properties: {
            overview: { type: "string" },
          },
          required: ["overview"],
        },
        activations: {
          type: "array",
          items: {
            type: "object",
            properties: {
              op: { type: "string", enum: SUPPORTED_AI_ACTIONS },
              node_id: { type: "string" },
              target: { type: "string" },
              duplicate_of_id: { type: "string" },
              confidence: { type: "number" },
              reason: { type: "string" },
            },
          },
        },
      },
      required: ["summary", "activations"],
    };
  }

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
    const MAX_TEXT_LENGTH = 500000; // 约 500KB，超过则截断
    let raw = String(text || "").trim();
    if (raw.length > MAX_TEXT_LENGTH) {
      raw = raw.slice(0, MAX_TEXT_LENGTH);
    }
    const cleaned = stripJsonFences(raw);
    // 快速失败：如果没有 JSON 对象标记，直接报错
    if (!cleaned.includes("{") || !cleaned.includes("}")) {
      throw new Error("Provider returned text that did not contain a JSON object.");
    }
    try {
      return JSON.parse(cleaned);
    } catch (_error) {
      // 提取第一个 {...} 块
      const match = cleaned.match(/\{[\s\S]*?\}/);
      if (match) {
        try {
          return JSON.parse(match[0]);
        } catch (_e2) {
          // 继续尝试外层提取
        }
      }
      const start = cleaned.indexOf("{");
      const end = cleaned.lastIndexOf("}");
      if (start >= 0 && end > start) {
        return JSON.parse(cleaned.slice(start, end + 1));
      }
      throw new Error("Provider returned text that was not valid JSON.");
    }
  }

  function stripJsonFences(text) {
    return text
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/i, "")
      .trim();
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

  function normalizeApiBaseUrl(value) {
    const raw = String(value || DEFAULT_API_BASE_URL).trim();
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

  function endpointUrl(apiBaseUrl, endpointPath) {
    const normalized = normalizeApiBaseUrl(apiBaseUrl);
    if (coreEndpointKind(normalized)) {
      return normalized;
    }
    return `${normalized}/${endpointPath.replace(/^\/+/, "")}`;
  }

  function coreEndpointKind(apiBaseUrl) {
    let parsed;
    try {
      parsed = new URL(normalizeApiBaseUrl(apiBaseUrl));
    } catch (_error) {
      return "";
    }
    const pathname = parsed.pathname.replace(/\/+$/, "");
    if (pathname.endsWith("/chat/completions")) {
      return "chat_completions";
    }
    if (pathname.endsWith("/responses")) {
      return "responses";
    }
    if (pathname.endsWith("/completions")) {
      return "completions";
    }
    return "";
  }

  // ═══════════════════════════════════════════════════════════════
  //  6. Utilities
  // ═══════════════════════════════════════════════════════════════

  function normalizeApiStyle(value) {
    const style = String(value || "").trim();
    return ["auto", "responses", "chat_completions", "completions"].includes(style) ? style : DEFAULT_API_STYLE;
  }

  function normalizeAction(action) {
    const bookmark = action.bookmark_locator || {};
    const folder = action.folder_locator || {};
    const details = action.details || {};
    const evidence = details.evidence || {};
    return {
      action_id: String(action.action_id || ""),
      action_type: String(action.action_type || ""),
      status: String(action.status || "proposed"),
      reason: String(action.reason || ""),
      confidence: finiteNumber(action.confidence, 0),
      bookmark_locator: {
        id: String(bookmark.id || ""),
        title: String(bookmark.title || ""),
        url: String(bookmark.url || ""),
        normalized_url: String(bookmark.normalized_url || ""),
        folder_path: String(bookmark.folder_path || ""),
      },
      folder_locator: {
        id: String(folder.id || ""),
        name: String(folder.name || ""),
        path: String(folder.path || ""),
      },
      from_path: String(action.from_path || bookmark.folder_path || folder.path || ""),
      to_path: String(action.to_path || ""),
      target_path: String(action.target_path || ""),
      to_name: String(action.to_name || ""),
      details: {
        evidence: {
          review_status: String(evidence.review_status || "derived"),
          review_method: String(evidence.review_method || "extension-fast"),
          summary: String(evidence.summary || action.reason || ""),
          rule_override: String(evidence.rule_override || ""),
        },
        guardrail: String(details.guardrail || ""),
        rule_override: String(details.rule_override || ""),
      },
    };
  }

  function normalizeFolder(folder) {
    return {
      id: String(folder.id || ""),
      name: String(folder.name || ""),
      path: String(folder.path || ""),
      parent_path: folder.parent_path || null,
      root_key: String(folder.root_key || ""),
      depth: nonNegativeInteger(folder.depth, 0),
      bookmark_count: nonNegativeInteger(folder.bookmark_count, 0),
      subfolder_count: nonNegativeInteger(folder.subfolder_count, 0),
    };
  }

  function normalizeBookmark(bookmark) {
    return {
      id: String(bookmark.id || ""),
      title: String(bookmark.title || ""),
      url: String(bookmark.url || ""),
      normalized_url: String(bookmark.normalized_url || bookmark.url || ""),
      domain: String(bookmark.domain || ""),
      folder_id: String(bookmark.folder_id || ""),
      folder_path: String(bookmark.folder_path || ""),
      top_level_folder: bookmark.top_level_folder || "",
      root_key: String(bookmark.root_key || ""),
      path: String(bookmark.path || ""),
      depth: nonNegativeInteger(bookmark.depth, 0),
    };
  }

  function bookmarkLocator(bookmark) {
    return {
      id: bookmark.id,
      title: bookmark.title,
      url: bookmark.url,
      normalized_url: bookmark.normalized_url,
      folder_path: bookmark.folder_path,
    };
  }

  var IPV4_RE = /^\d{1,3}(\.\d{1,3}){3}$/;

  function urlRequiresReview(url) {
    try {
      const parsed = new URL(url);
      const scheme = parsed.protocol.replace(":", "").toLowerCase();
      const hostname = parsed.hostname.toLowerCase();
      if (["file", "edge", "chrome", "about", "javascript", "data"].includes(scheme)) {
        return false;
      }
      if (!hostname || hostname === "localhost" || hostname.endsWith(".local")) {
        return false;
      }
      // 跳过裸 IPv4 地址（含内网和公网），与 Python 侧 ipaddress.ip_address() 对齐
      if (IPV4_RE.test(hostname)) {
        return false;
      }
      // 跳过 IPv6 地址（含 ::1, fe80::1 等链路本地地址）
      if (hostname.includes(":")) {
        return false;
      }
      return hostname.includes(".");
    } catch (_error) {
      return false;
    }
  }

  function sanitizeForPrompt(text) {
    if (!text) return "";
    var cleaned = String(text)
      .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "")
      .replace(/[\r\n\t]/g, " ")
      .replace(/ {2,}/g, " ")
      .trim();
    return cleaned.length > 500 ? cleaned.slice(0, 500) : cleaned;
  }

  function nonNegativeInteger(value, fallback) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) {
      return fallback;
    }
    return Math.floor(numberValue);
  }

  function finiteNumber(value, fallback) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
  }

  function requestTimeoutMsWithinMv3Lifetime(value) {
    return Math.min(
      nonNegativeInteger(value, DEFAULT_REQUEST_TIMEOUT_MS),
      MAX_EXTENSION_FETCH_TIMEOUT_MS,
    );
  }

  globalScope.BookmarkAdvisorAI = {
    generateReviewedPlan,
    reviseReviewedPlan,
    loadFastRules,
    _endpointUrl: endpointUrl,
    _buildRequestAttempts: buildRequestAttempts,
    _buildRevisionUserPrompt: buildRevisionUserPrompt,
    _activationResponseSchema: activationResponseSchema,
    _compileActivationPlan: compileActivationPlan,
    _lintActivationPayload: lintActivationPayload,
    _requestTimeoutMsWithinMv3Lifetime: requestTimeoutMsWithinMv3Lifetime,
  };
})(globalThis);
