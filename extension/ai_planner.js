(function attachBookmarkAdvisorAI(globalScope) {
  const DEFAULT_API_BASE_URL = "https://api.openai.com/v1";
  const DEFAULT_MODEL = "gpt-4o-mini";
  const DEFAULT_API_STYLE = "auto";
  const DEFAULT_MAX_ACTIONS = 40;
  const DEFAULT_APPROVE_THRESHOLD = 0.85;
  const MAX_EXTENSION_FETCH_TIMEOUT_MS = 300000;
  const DEFAULT_REQUEST_TIMEOUT_MS = 120000;
  const DEFAULT_MAX_RETRIES = 1;

  const SUPPORTED_AI_ACTIONS = [
    "rename_folder",
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
    "keep_for_review",
  ];
  const EXECUTABLE_ACTIONS = new Set([
    "rename_folder",
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
  ]);

  // ── Fast rules: loaded from packaged JSON, cached after first load ──
  var _fastRulesCache = null;

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
    const maxActions = positiveInteger(options.maxActions, DEFAULT_MAX_ACTIONS);
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
    const activationPayload = await requestDraftPlan({
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
    const draft = compileActivationPlan(activationPayload, planningSnapshot);
    const reviewedPlan = finalizeDraftPlan({
      draft,
      snapshot: planningSnapshot,
      model,
      autoApproveThreshold,
    });
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
    const maxActions = positiveInteger(options.maxActions, DEFAULT_MAX_ACTIONS);
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
    const draft = compileActivationPlan(activationPayload, planningSnapshot);
    const reviewedPlan = finalizeDraftPlan({
      draft,
      snapshot: planningSnapshot,
      model,
      autoApproveThreshold,
    });
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

  async function requestDraftPlan({ apiKey, apiBaseUrl, apiStyle, model, maxActions, requestTimeoutMs, maxRetries, snapshot, focusPath, userInstruction, preferences, onProgress, signal }) {
    const systemText = buildSystemPrompt(maxActions, preferences);
    const userText = buildUserPrompt(snapshot, focusPath, userInstruction, preferences);
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
    const userText = buildRevisionUserPrompt(existingPlan, snapshot, userInstruction, preferences);
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
          });
          await onProgress("Parsing and linting activation response...");
          const activationPayload = parseDraftPlanText(extractAttemptText(attempt, payload));
          const lintErrors = lintActivationPayload(activationPayload, snapshot);
          if (lintErrors.length === 0) {
            return activationPayload;
          }
          errors.push(`activation lint pass ${lintAttempt}: ${lintErrors.join("; ")}`);
          retryFeedback = buildActivationRetryFeedback(lintErrors);
          await onProgress(`Activation lint failed (${lintErrors.length} issue(s)). Retrying...`);
          break;
        } catch (error) {
          if (error && error.name === "AbortError") {
            throw error;
          }
          errors.push(`${attempt}: ${error.message || String(error)}`);
          await onProgress(`LLM attempt failed (${attemptLabel(attempt)}). Trying fallback...`);
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

  async function requestCompatibleAttempt({ attempt, apiBaseUrl, apiKey, model, requestTimeoutMs, schema, systemText, userText, signal }) {
    if (attempt === "responses_json_schema") {
      return postCompatible(endpointUrl(apiBaseUrl, "responses"), apiKey, requestTimeoutMs, {
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
      }, signal);
    }

    if (attempt === "completions_plain_json") {
      return postCompatible(endpointUrl(apiBaseUrl, "completions"), apiKey, requestTimeoutMs, {
        model,
        prompt: `${systemText}\nReturn a single JSON object and no Markdown fences.\n\n${userText}`,
        max_tokens: 16384,
        temperature: 0,
      }, signal);
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
    return postCompatible(endpointUrl(apiBaseUrl, "chat/completions"), apiKey, requestTimeoutMs, chatPayload, signal);
  }

  function buildRequestAttempts(apiStyle, apiBaseUrl) {
    const exactEndpoint = coreEndpointKind(apiBaseUrl);
    if (exactEndpoint === "responses") {
      return ["responses_json_schema"];
    }
    if (exactEndpoint === "chat_completions") {
      return ["chat_json_schema", "chat_json_object", "chat_plain_json"];
    }
    if (exactEndpoint === "completions") {
      return ["completions_plain_json"];
    }
    if (apiStyle === "responses") {
      return ["responses_json_schema"];
    }
    if (apiStyle === "chat_completions") {
      return ["chat_json_schema", "chat_json_object", "chat_plain_json"];
    }
    if (apiStyle === "completions") {
      return ["completions_plain_json"];
    }
    return ["responses_json_schema", "chat_json_schema", "chat_json_object", "chat_plain_json", "completions_plain_json"];
  }

  function buildChatMessages(systemText, userText, schema, attempt) {
    const messages = [{ role: "system", content: systemText }];
    if (attempt === "chat_plain_json" || attempt === "chat_json_object") {
      messages[0] = {
        role: "system",
        content: `${systemText}\nReturn a single JSON object and no Markdown fences. It must match this JSON schema:\n${JSON.stringify(schema)}`,
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

  async function postCompatible(url, apiKey, timeoutMs, body, externalSignal) {
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
    let text;
    let bodyTimeoutId;
    try {
      text = await Promise.race([
        response.text(),
        new Promise((_, reject) => {
          bodyTimeoutId = setTimeout(() => reject(new Error(`Response body timed out after ${Math.round(effectiveTimeout / 1000)}s`)), effectiveTimeout);
        }),
      ]);
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(bodyTimeoutId);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", onExternalAbort);
      }
      if (timedOut) {
        throw new Error(`Request timed out after ${Math.round(effectiveTimeout / 1000)}s: ${url}`);
      }
      if (externalAborted || externalSignal?.aborted) {
        throw createAbortError("The operation was aborted.");
      }
      throw error;
    }
    clearTimeout(timeoutId);
    clearTimeout(bodyTimeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
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
      .filter((bookmark) => !focusPath || pathInFocusScope(bookmark.folder_path, focusPath))
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
      folders: folders.filter((folder) => !focusPath || pathInFocusScope(folder.path, focusPath) || focusPath.startsWith(`${folder.path}/`)),
      bookmarks,
    };
  }

  function finalizeDraftPlan({ draft, snapshot, model, autoApproveThreshold }) {
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
    }).map((action, index) => ({ ...action, action_id: `a-${String(index + 1).padStart(4, "0")}` }));

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

  function compileActivationPlan(activationPayload, snapshot) {
    const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
    const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.id, folder]));
    const actions = [];

    for (const activation of activationPayload.activations || []) {
      actions.push(compileActivation(activation, bookmarkIndex, folderIndex));
    }

    return {
      summary: activationPayload.summary || {},
      actions,
    };
  }

  function lintActivationPayload(activationPayload, snapshot) {
    const errors = [];
    if (!activationPayload || typeof activationPayload !== "object") {
      return ["Response must be a JSON object."];
    }
    if (!activationPayload.summary || typeof activationPayload.summary !== "object") {
      errors.push("summary must be an object.");
    }
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
      const confidence = Number(activation.confidence);
      if (!SUPPORTED_AI_ACTIONS.includes(op)) {
        errors.push(`${path}.op must be one of ${SUPPORTED_AI_ACTIONS.join(", ")}.`);
      }
      if (!Number.isFinite(confidence)) {
        errors.push(`${path}.confidence must be a finite number.`);
      }
      if (!sanitizeForPrompt(activation.reason || "")) {
        errors.push(`${path}.reason must be non-empty.`);
      }

      if (op === "move_bookmark") {
        const bookmark = bookmarkIndex.get(nodeId);
        if (!bookmark) errors.push(`${path}.node_id must reference an existing bookmark id.`);
        if (bookmark && !pathInFocusScope(bookmark.folder_path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
      } else if (op === "move_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
        if (folder && !pathInFocusScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
        if (folder && (target === folder.path || target.startsWith(`${folder.path}/`))) {
          errors.push(`${path}.target must not be the same folder or its descendant.`);
        }
      } else if (op === "rename_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
        if (folder && !pathInFocusScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!sanitizeForPrompt(target)) errors.push(`${path}.target must be non-empty (new title).`);
      } else if (op === "create_folder") {
        if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
        if (!pathInFocusScope(target, focusPath)) errors.push(`${path}.target must stay within the focused folder.`);
      } else if (op === "remove_duplicate") {
        const bookmark = bookmarkIndex.get(nodeId);
        const duplicateOf = bookmarkIndex.get(String(activation.duplicate_of_id || ""));
        if (!bookmark) errors.push(`${path}.node_id must reference an existing bookmark id.`);
        if (bookmark && !pathInFocusScope(bookmark.folder_path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        if (!duplicateOf) errors.push(`${path}.duplicate_of_id must reference an existing bookmark id.`);
        if (bookmark && duplicateOf && bookmark.normalized_url !== duplicateOf.normalized_url) {
          errors.push(`${path}.duplicate_of_id must point to a bookmark with the same normalized_url.`);
        }
      } else if (op === "keep_for_review") {
        if (nodeId && !bookmarkIndex.has(nodeId) && !folderIndex.has(nodeId)) errors.push(`${path}.node_id must reference an existing bookmark or folder id.`);
      }
    });

    return errors;
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

  function pathInFocusScope(path, focusPath) {
    if (!focusPath) return true;
    return path === focusPath || path.startsWith(`${focusPath}/`);
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
      if (!folder || !pathInFocusScope(folder.path, focusPath)) {
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
        if (!pathInFocusScope(bookmark.folder_path, focusPath) || !bookmarkMatchesRule(bookmark, bkRule)) {
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

  function buildSystemPrompt(maxActions, preferences) {
    var prefs = preferences || {};
    var lines = [
      "You are an expert bookmark organizer.",
      "Return JSON only.",
      "Focus on semantic organization, not cosmetic renaming.",
      "Prefer moving bookmarks into semantically appropriate existing folders.",
      "Only propose create_folder when a genuinely new category is justified.",
      `Propose at most ${maxActions} high-value actions.`,
      "Use keep_for_review for ambiguous, risky, or low-confidence items.",
      "Choosing any action other than keep_for_review means you recommend executing it — the extension will run it directly.",
      "Confidence reflects how sure you are the action is correct, not whether it needs human review. Only use keep_for_review when you want human review.",
      "When title and domain evidence is insufficient to determine a bookmark's purpose or category, use keep_for_review instead of guessing.",
      "In the reason field for uncertain items, note that web content inspection would help classify the bookmark accurately.",
      "Only bookmarks with review_status=reviewed may be auto-classified; extension fast_reviewed rows are allowed only when title/domain evidence is strong, otherwise keep_for_review.",
      "The browser extension will lint and post-process your output before execution.",
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

  function buildUserPrompt(snapshot, focusPath, userInstruction, preferences) {
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
      "Be conservative: if the title/domain/folder path is not enough to determine what the page is about, emit keep_for_review instead of moving.",
      "If a bookmark's purpose is genuinely unclear from its title and domain alone, keep it for review and mention in the reason that visiting the URL or searching its domain would clarify its category.",
      "For move_bookmark or remove_duplicate, set node_id to the bookmark id from the snapshot.",
      "For move_folder or rename_folder, set node_id to the folder id from the snapshot.",
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
    return `${instructionPrefix}${prompt.join("\n")}\n\nRules:\n${JSON.stringify(rulesSummary)}\n\n${encodeSnapshot(snapshot, true)}`;
  }

  function buildRevisionUserPrompt(existingPlan, snapshot, userInstruction, preferences) {
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
      "Return a complete replacement activation list, not a patch or commentary.",
      "Preserve useful existing intentions that the instruction does not change.",
      "Remove or modify activations that conflict with the instruction.",
      "Do not invent bookmarks or folders that are not implied by the current snapshot.",
      "For move_bookmark or remove_duplicate, set node_id to the bookmark id from the snapshot.",
      "For move_folder or rename_folder, set node_id to the folder id from the snapshot.",
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

  function encodeSnapshot(snapshot, includeStatus) {
    var lines = [];
    if (snapshot.focus_path) {
      lines.push("Focus: " + snapshot.focus_path);
      lines.push("");
    }
    lines.push("Folders (id|path):");
    var folders = snapshot.folders || [];
    for (var fi = 0; fi < folders.length; fi++) {
      var f = folders[fi];
      lines.push(f.id + "|" + _pipeSafe(f.path));
    }
    lines.push("");
    if (includeStatus) {
      lines.push("Bookmarks (id|title|domain|folder_path|status):");
    } else {
      lines.push("Bookmarks (id|title|domain|folder_path):");
    }
    var bookmarks = snapshot.bookmarks || [];
    for (var bi = 0; bi < bookmarks.length; bi++) {
      var b = bookmarks[bi];
      var title = _pipeSafe(sanitizeForPrompt(b.title));
      var domain = _pipeSafe(b.domain || "");
      var fp = _pipeSafe(b.folder_path || "");
      var line = b.id + "|" + title + "|" + domain + "|" + fp;
      if (includeStatus) {
        var status = (b.review_status === "fast_reviewed") ? "F" : "R";
        line += "|" + status;
      }
      lines.push(line);
    }
    return lines.join("\n");
  }

  function encodePlan(plan) {
    var actions = plan.actions || [];
    var lines = ["Plan (action_id|action_type|status|node_id|target|confidence|reason):"];
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

  function activationResponseSchema() {
    return {
      type: "object",
      additionalProperties: false,
      properties: {
        summary: {
          type: "object",
          additionalProperties: false,
          properties: {
            overview: { type: "string" },
          },
          required: ["overview"],
        },
        activations: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            properties: {
              op: { type: "string", enum: SUPPORTED_AI_ACTIONS },
              node_id: { type: "string" },
              target: { type: "string" },
              duplicate_of_id: { type: "string" },
              confidence: { type: "number" },
              reason: { type: "string" },
            },
            required: [
              "op",
              "node_id",
              "target",
              "duplicate_of_id",
              "confidence",
              "reason",
            ],
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
    const cleaned = stripJsonFences(String(text || "").trim());
    try {
      return JSON.parse(cleaned);
    } catch (_error) {
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
      depth: positiveInteger(folder.depth, 0),
      bookmark_count: positiveInteger(folder.bookmark_count, 0),
      subfolder_count: positiveInteger(folder.subfolder_count, 0),
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
      depth: positiveInteger(bookmark.depth, 0),
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

  function positiveInteger(value, fallback) {
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
      positiveInteger(value, DEFAULT_REQUEST_TIMEOUT_MS),
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
