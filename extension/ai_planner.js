/* OpenAI-compatible 书签计划 facade：配置归一化、请求编排与模块组装。 */

(function attachBookmarkAdvisorAI(globalScope) {
  if (typeof require === "function") {
    const root = globalScope.BookmarkAdvisor || {};
    if (!root.PlanSchema) require("./shared/plan_schema.js");
    if (!root.AIEndpoint) require("./shared/ai_endpoint.js");
    if (!root.PathUtils) require("./shared/path_utils.js");
    const ai = (globalScope.BookmarkAdvisor && globalScope.BookmarkAdvisor.AI) || {};
    if (!ai.FastRules) require("./ai/fast_rules.js");
    if (!ai.SnapshotModel) require("./ai/snapshot_model.js");
    if (!ai.Batching) require("./ai/batching.js");
    if (!ai.PromptCodec) require("./ai/prompt_codec.js");
    if (!ai.ResponseCodec) require("./ai/response_codec.js");
    if (!ai.ProviderClient) require("./ai/provider_client.js");
    if (!ai.PlanCompiler) require("./ai/plan_compiler.js");
  }

  const shared = globalScope.BookmarkAdvisor || {};
  const planSchema = shared.PlanSchema;
  const aiEndpoint = shared.AIEndpoint;
  const pathUtils = shared.PathUtils;
  const aiModules = shared.AI || {};
  if (!planSchema || !aiEndpoint || !pathUtils ||
      !aiModules.FastRules || !aiModules.SnapshotModel || !aiModules.Batching ||
      !aiModules.PromptCodec || !aiModules.ResponseCodec || !aiModules.ProviderClient ||
      !aiModules.PlanCompiler) {
    throw new Error("Shared and AI foundation modules must load before ai_planner.js");
  }

  const DEFAULT_API_BASE_URL = aiEndpoint.DEFAULT_API_BASE_URL;
  const DEFAULT_MODEL = "gpt-5.4-mini";
  const DEFAULT_API_STYLE = aiEndpoint.DEFAULT_API_STYLE;
  const DEFAULT_MAX_ACTIONS = 40;
  const MAX_ACTIONS_LIMIT = 80;
  const DEFAULT_APPROVE_THRESHOLD = 0.85;
  const DEFAULT_MAX_RETRIES = 1;
  const BATCH_PLANNING_BOOKMARK_THRESHOLD = 50;
  const BATCH_PLANNING_SIZE = 50;
  const BATCH_PLANNING_CONCURRENCY = 3;

  const dynamicChrome = {};
  Object.defineProperty(dynamicChrome, "runtime", {
    get: function () {
      return globalScope.chrome && globalScope.chrome.runtime;
    },
  });
  const fastRules = aiModules.FastRules.create({
    chrome: dynamicChrome,
    fetch: function (...args) { return globalScope.fetch(...args); },
    log: debugLog,
  });
  const snapshotModel = aiModules.SnapshotModel;
  const batching = aiModules.Batching;
  const promptCodec = aiModules.PromptCodec.create({
    getFastRules: () => fastRules.get(),
    supportedActions: planSchema.AI_ACTIVATION_ACTION_TYPES,
    finiteNumber,
  });
  const responseCodec = aiModules.ResponseCodec;
  const providerClient = aiModules.ProviderClient.create({
    aiEndpoint,
    fetch: function (...args) { return globalScope.fetch(...args); },
    log: function (level, error) {
      debugLog(error && error.message ? error.message : String(error), level);
    },
  });
  const planCompiler = aiModules.PlanCompiler.create({
    planSchema,
    pathUtils,
    snapshotModel,
    fastRules,
    log: debugLog,
  });

  async function generateReviewedPlan(options) {
    if (options.signal && options.signal.aborted) {
      throw createAbortError("The operation was aborted.");
    }
    await fastRules.load();
    const apiKey = String(options.apiKey || "").trim();
    if (!apiKey) {
      throw new Error("OpenAI API key is required for HTTPS planning.");
    }

    const snapshot = options.snapshot || {};
    const apiBaseUrl = normalizeApiBaseUrl(
      options.apiBaseUrl || options.baseUrl || DEFAULT_API_BASE_URL,
    );
    const apiStyle = normalizeApiStyle(options.apiStyle || DEFAULT_API_STYLE);
    const model = String(options.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL;
    const maxActions = boundedMaxActions(options.maxActions);
    const autoApproveThreshold = finiteNumber(
      options.autoApproveThreshold,
      DEFAULT_APPROVE_THRESHOLD,
    );
    const requestTimeoutMs = requestTimeoutMsWithinMv3Lifetime(options.requestTimeoutMs);
    const maxRetries = options.maxRetries;
    const focusPath = String(options.focusPath || "").trim();
    const userInstruction = String(options.userInstruction || "").trim();
    const onProgress = typeof options.onProgress === "function"
      ? options.onProgress
      : function () {};
    const planningSnapshot = snapshotModel.buildPlanningSnapshot(snapshot, focusPath);
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
      preferences: options.preferences || {},
      onProgress,
      signal: options.signal,
    });
    // eslint-disable-next-line no-console
    console.log(
      `[BookmarkAdvisor][offscreen] requestDraftPlan returned, activations=` +
      `${(activationPayload.activations || []).length}`,
    );

    await onProgress("Compiling activations...");
    let draft;
    try {
      const startedAt = performance.now();
      draft = planCompiler.compileActivationPlan(activationPayload, planningSnapshot);
      debugLog(
        `compileActivationPlan done, actions=${draft.actions.length}, ` +
        `${Math.round(performance.now() - startedAt)}ms`,
        "log",
      );
    } catch (error) {
      debugLog(`compileActivationPlan FAILED: ${error}`, "error");
      throw error;
    }

    await onProgress(`Finalizing plan (${draft.actions.length} actions)...`);
    let reviewedPlan;
    try {
      const startedAt = performance.now();
      reviewedPlan = planCompiler.finalizeDraftPlan({
        draft,
        snapshot: planningSnapshot,
        model,
        autoApproveThreshold,
      });
      debugLog(
        `finalizeDraftPlan done, ${Math.round(performance.now() - startedAt)}ms`,
        "log",
      );
    } catch (error) {
      debugLog(`finalizeDraftPlan FAILED: ${error}`, "error");
      throw error;
    }

    await onProgress("Plan ready.");
    debugLog("generateReviewedPlan complete, returning result", "log");
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
    await fastRules.load();
    const apiKey = String(options.apiKey || "").trim();
    if (!apiKey) {
      throw new Error("OpenAI API key is required for HTTPS planning.");
    }
    if (!options.existingPlan || !Array.isArray(options.existingPlan.actions)) {
      throw new Error("A reviewed plan is required before revision.");
    }

    const snapshot = options.snapshot || {};
    const apiBaseUrl = normalizeApiBaseUrl(
      options.apiBaseUrl || options.baseUrl || DEFAULT_API_BASE_URL,
    );
    const apiStyle = normalizeApiStyle(options.apiStyle || DEFAULT_API_STYLE);
    const model = String(options.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL;
    const maxActions = boundedMaxActions(options.maxActions);
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
    const onProgress = typeof options.onProgress === "function"
      ? options.onProgress
      : function () {};
    const planningSnapshot = snapshotModel.buildPlanningSnapshot(snapshot, focusPath);
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
      preferences: options.preferences || {},
      onProgress,
      signal: options.signal,
    });
    // eslint-disable-next-line no-console
    console.log(
      `[BookmarkAdvisor][offscreen] requestRevisionPlan returned, activations=` +
      `${(activationPayload.activations || []).length}`,
    );

    await onProgress("Compiling revision changes...");
    let draft;
    try {
      const startedAt = performance.now();
      const deltaDraft = planCompiler.compileActivationPlan(activationPayload, planningSnapshot);
      draft = planCompiler.mergeRevisionDraft(options.existingPlan, deltaDraft);
      debugLog(
        `mergeRevisionDraft done, changed=${deltaDraft.actions.length}, ` +
        `total=${draft.actions.length}, ${Math.round(performance.now() - startedAt)}ms`,
        "log",
      );
    } catch (error) {
      debugLog(`compileActivationPlan FAILED: ${error}`, "error");
      throw error;
    }

    await onProgress(`Finalizing plan (${draft.actions.length} actions)...`);
    let reviewedPlan;
    try {
      const startedAt = performance.now();
      reviewedPlan = planCompiler.finalizeDraftPlan({
        draft,
        snapshot: planningSnapshot,
        model,
        autoApproveThreshold,
      });
      debugLog(
        `finalizeDraftPlan done, ${Math.round(performance.now() - startedAt)}ms`,
        "log",
      );
    } catch (error) {
      debugLog(`finalizeDraftPlan FAILED: ${error}`, "error");
      throw error;
    }

    await onProgress("Plan ready.");
    debugLog("reviseReviewedPlan complete, returning result", "log");
    reviewedPlan.summary = {
      ...reviewedPlan.summary,
      overview: String(
        (activationPayload.summary || {}).overview ||
        "Revised in the Edge extension via HTTPS.",
      ),
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
    const parts = batching.splitPlanningSnapshot(
      options.snapshot,
      BATCH_PLANNING_BOOKMARK_THRESHOLD,
      BATCH_PLANNING_SIZE,
    );
    if (parts.length <= 1) {
      return requestDraftPlan(options);
    }
    await options.onProgress(
      `Large folder detected: ${options.snapshot.bookmarks.length} bookmarks, ` +
      `split into ${parts.length} cached prompt parts.`,
    );
    const payloads = await batching.mapWithConcurrency(
      parts,
      BATCH_PLANNING_CONCURRENCY,
      async (part, index) => {
        const partNumber = index + 1;
        await options.onProgress(
          `Planning part ${partNumber}/${parts.length} (${part.bookmarks.length} bookmarks)...`,
        );
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
      },
    );
    const merged = batching.mergeActivationPayloads(payloads);
    await options.onProgress(
      `Merged ${merged.activations.length} deduplicated activations from ${parts.length} parts.`,
    );
    return merged;
  }

  async function requestDraftPlan(options) {
    const systemText = promptCodec.buildSystemPrompt(options.maxActions, options.preferences);
    const userText = promptCodec.buildUserPrompt(
      options.snapshot,
      options.focusPath,
      options.userInstruction,
      options.preferences,
      options.batchInfo,
    );
    return requestPromptPlan({
      ...options,
      systemText,
      userText,
      progressLabel: "planning",
    });
  }

  async function requestRevisionPlan(options) {
    const systemText = promptCodec.buildSystemPrompt(options.maxActions, options.preferences);
    const userText = promptCodec.buildRevisionUserPrompt(
      options.existingPlan,
      options.snapshot,
      options.userInstruction,
      options.preferences,
      options.maxActions,
    );
    return requestPromptPlan({
      ...options,
      systemText,
      userText,
      progressLabel: "plan revision",
    });
  }

  async function requestPromptPlan(options) {
    const totalChars = options.systemText.length + options.userText.length;
    const approxTokens = Math.round(totalChars / 4);
    await options.onProgress(`Prompt size: ~${approxTokens} tokens (${totalChars} chars)`);
    return requestLintedActivationPlan({
      ...options,
      schema: promptCodec.activationResponseSchema(),
    });
  }

  async function requestLintedActivationPlan(options) {
    const maxAttempts = Math.max(
      1,
      (Number.isFinite(options.maxRetries) ? options.maxRetries : DEFAULT_MAX_RETRIES) + 1,
    );
    let retryFeedback = "";
    const errors = [];

    for (let lintAttempt = 1; lintAttempt <= maxAttempts; lintAttempt += 1) {
      const attempts = providerClient.buildRequestAttempts(options.apiStyle, options.apiBaseUrl);
      for (const attempt of attempts) {
        try {
          await options.onProgress(
            `Calling LLM endpoint (${attemptLabel(attempt)}) for ${options.progressLabel}, ` +
            `pass ${lintAttempt}/${maxAttempts}...`,
          );
          const payload = await providerClient.requestCompatibleAttempt({
            attempt,
            apiBaseUrl: options.apiBaseUrl,
            apiKey: options.apiKey,
            model: options.model,
            requestTimeoutMs: options.requestTimeoutMs,
            schema: options.schema,
            systemText: options.systemText,
            userText: options.userText + retryFeedback,
            signal: options.signal,
            onProgress: options.onProgress,
          });
          const rawText = responseCodec.extractAttemptText(attempt, payload);
          await options.onProgress(`Parsing response (${rawText.length} chars)...`);
          const activationPayload = responseCodec.parseDraftPlanText(rawText);
          await options.onProgress(
            `Linting ${(activationPayload.activations || []).length} activations...`,
          );
          const lintErrors = planCompiler.lintActivationPayload(
            activationPayload,
            options.snapshot,
          );
          if (lintErrors.length === 0) {
            await options.onProgress("Lint passed.");
            return activationPayload;
          }
          if (
            lintAttempt === maxAttempts &&
            planCompiler.lintErrorsAreOnlyReferenceErrors(lintErrors)
          ) {
            const pruned = planCompiler.pruneInvalidActivationReferences(
              activationPayload,
              options.snapshot,
            );
            const remainingErrors = planCompiler.lintActivationPayload(
              pruned.payload,
              options.snapshot,
            );
            if (pruned.dropped > 0 && remainingErrors.length === 0) {
              await options.onProgress(
                `Dropped ${pruned.dropped} activation(s) with unknown bookmark/folder ids after retry.`,
              );
              return pruned.payload;
            }
          }
          errors.push(`activation lint pass ${lintAttempt}: ${lintErrors.join("; ")}`);
          retryFeedback = buildActivationRetryFeedback(lintErrors);
          await options.onProgress(`Lint failed (${lintErrors.length} issue(s)). Retrying...`);
          break;
        } catch (error) {
          if (error && error.name === "AbortError") {
            throw error;
          }
          const message = error && error.message ? error.message : String(error);
          errors.push(`${attempt}: ${message}`);
          if (error.retryable === false) {
            throw new Error(
              `LLM request failed with non-retryable error ` +
              `(${error.httpStatus || "?"}): ${message}.`,
            );
          }
          if (
            message.includes("JSON") || message.includes("json") ||
            message.includes("parse") || message.includes("lint")
          ) {
            await options.onProgress(
              `Parse/lint error (${attemptLabel(attempt)}): ${message.slice(0, 200)}`,
            );
          } else {
            await options.onProgress(
              `LLM attempt failed (${attemptLabel(attempt)}). Trying fallback...`,
            );
          }
        }
      }
    }

    throw new Error(
      `OpenAI-compatible HTTPS ${options.progressLabel} failed after ` +
      `${maxAttempts} attempt(s). ${errors.join(" | ")}`,
    );
  }

  function buildActivationRetryFeedback(lintErrors) {
    return [
      "",
      "",
      "Your previous activation JSON failed local validation.",
      "Return corrected JSON only, using the same activation schema.",
      "Use exact node_id values copied from the B/F rows in the prompt. " +
        "Do not use URLs, titles, domains, indexes, or invented ids.",
      "Validation errors:",
      ...lintErrors.slice(0, 20).map((error) => `- ${error}`),
    ].join("\n");
  }

  function attemptLabel(attempt) {
    if (attempt === "responses_json_schema") return "Responses JSON schema";
    if (attempt === "chat_json_schema") return "Chat JSON schema";
    if (attempt === "chat_json_object") return "Chat JSON object";
    if (attempt === "completions_plain_json") return "Completions plain JSON";
    return "Chat plain JSON";
  }

  function normalizeApiBaseUrl(value) {
    return aiEndpoint.normalizeBaseUrl(value || DEFAULT_API_BASE_URL);
  }

  function endpointUrl(apiBaseUrl, endpointPath) {
    return aiEndpoint.endpointUrl(apiBaseUrl, endpointPath);
  }

  function normalizeApiStyle(value) {
    return aiEndpoint.normalizeStyle(value);
  }

  function requestTimeoutMsWithinMv3Lifetime(value) {
    return aiEndpoint.clampRequestTimeout(value, aiEndpoint.DEFAULT_REQUEST_TIMEOUT_MS);
  }

  function boundedMaxActions(value) {
    return Math.min(nonNegativeInteger(value, DEFAULT_MAX_ACTIONS), MAX_ACTIONS_LIMIT);
  }

  function nonNegativeInteger(value, fallback) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) return fallback;
    return Math.floor(numberValue);
  }

  function finiteNumber(value, fallback) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
  }

  function createAbortError(message) {
    const error = new Error(message || "The operation was aborted.");
    error.name = "AbortError";
    error.code = 20;
    return error;
  }

  function debugLog(message, level) {
    const logLevel = level || "log";
    const prefix = "[BookmarkAdvisor]";
    if (logLevel === "error") {
      console.error(prefix, message);
    } else if (logLevel === "warn") {
      console.warn(prefix, message);
    } else {
      console.log(prefix, message);
    }
  }

  globalScope.BookmarkAdvisorAI = {
    generateReviewedPlan,
    reviseReviewedPlan,
    loadFastRules: () => fastRules.load(),
    _endpointUrl: endpointUrl,
    _buildRequestAttempts: providerClient.buildRequestAttempts,
    _buildRevisionUserPrompt: promptCodec.buildRevisionUserPrompt,
    _activationResponseSchema: promptCodec.activationResponseSchema,
    _compileActivationPlan: planCompiler.compileActivationPlan,
    _lintActivationPayload: planCompiler.lintActivationPayload,
    _requestTimeoutMsWithinMv3Lifetime: requestTimeoutMsWithinMv3Lifetime,
  };
})(globalThis);
