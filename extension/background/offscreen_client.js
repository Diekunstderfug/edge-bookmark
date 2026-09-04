/* MV3 offscreen document 生命周期与 LLM transport。 */

(function attachOffscreenClient(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  if (!root.Protocol && typeof require === "function") {
    require("../shared/message_protocol.js");
  }
  if (!root.Storage && typeof require === "function") {
    require("../shared/storage.js");
  }
  if (!root.AIEndpoint && typeof require === "function") {
    require("../shared/ai_endpoint.js");
  }

  const DEFAULT_ACTIVE_JOB_STALE_MS = 30 * 60 * 1000;
  const DEFAULT_MAX_RETRIES = 1;
  const MAX_LINT_RETRIES = 3;
  const DEFAULT_DEADLINE_GRACE_MS = 60 * 1000;
  const DEFAULT_STALE_SAFETY_MARGIN_MS = 60 * 1000;
  const DEFAULT_ORPHAN_SETTLE_MS = 50;

  function create(dependencies) {
    const options = dependencies || {};
    const chromeApi = options.chrome || globalScope.chrome;
    const protocol = options.protocol || root.Protocol;
    const storage = options.storage || root.Storage;
    const aiFacade = options.aiFacade || globalScope.BookmarkAdvisorAI;
    const aiEndpoint = options.aiEndpoint || root.AIEndpoint || {};
    const clock = options.clock || {};
    const timerApi = options.timers || clock;

    if (!chromeApi || !chromeApi.runtime) {
      throw new Error("OffscreenClient requires chrome.runtime.");
    }
    if (!protocol || !protocol.MESSAGE_TYPES || !protocol.STORAGE_KEYS) {
      throw new Error("OffscreenClient requires the shared message protocol.");
    }
    if (!storage || typeof storage.get !== "function" || typeof storage.remove !== "function") {
      throw new Error("OffscreenClient requires storage.get/remove.");
    }

    const setTimer = bindTimer(timerApi, "setTimeout", globalScope);
    const clearTimer = bindTimer(timerApi, "clearTimeout", globalScope);
    const sleep = typeof clock.sleep === "function"
      ? clock.sleep.bind(clock)
      : (milliseconds) => new Promise((resolve) => setTimer(resolve, milliseconds));
    const activeJobStaleMs = Math.max(2, positiveInteger(
      options.activeJobStaleMs,
      DEFAULT_ACTIVE_JOB_STALE_MS,
    ));
    const deadlineGraceMs = nonNegativeInteger(
      options.deadlineGraceMs,
      DEFAULT_DEADLINE_GRACE_MS,
    );
    const staleSafetyMarginMs = nonNegativeInteger(
      options.staleSafetyMarginMs,
      DEFAULT_STALE_SAFETY_MARGIN_MS,
    );
    const orphanSettleMs = nonNegativeInteger(
      options.orphanSettleMs,
      DEFAULT_ORPHAN_SETTLE_MS,
    );
    const defaultRequestTimeoutMs = positiveInteger(
      aiEndpoint.DEFAULT_REQUEST_TIMEOUT_MS,
      180000,
    );
    const maxRequestTimeoutMs = positiveInteger(
      aiEndpoint.MAX_REQUEST_TIMEOUT_MS,
      300000,
    );
    const messages = protocol.MESSAGE_TYPES;
    const resultStorageKey = protocol.STORAGE_KEYS.OFFSCREEN_RESULT;
    const documentPath = String(options.documentPath || "offscreen.html");
    const documentUrl = typeof chromeApi.runtime.getURL === "function"
      ? chromeApi.runtime.getURL(documentPath)
      : documentPath;
    let creatingDocumentPromise = null;

    function supports() {
      return !!(
        chromeApi.runtime && typeof chromeApi.runtime.sendMessage === "function" &&
        chromeApi.offscreen && typeof chromeApi.offscreen.createDocument === "function" &&
        (
          typeof chromeApi.runtime.getContexts === "function" ||
          typeof chromeApi.offscreen.hasDocument === "function"
        )
      );
    }

    async function hasDocument() {
      if (typeof chromeApi.runtime.getContexts === "function") {
        const contexts = await chromeApi.runtime.getContexts({
          contextTypes: ["OFFSCREEN_DOCUMENT"],
          documentUrls: [documentUrl],
        });
        return Array.isArray(contexts) && contexts.length > 0;
      }
      if (chromeApi.offscreen && typeof chromeApi.offscreen.hasDocument === "function") {
        return !!(await chromeApi.offscreen.hasDocument());
      }
      return false;
    }

    async function ensureDocument() {
      if (!supports()) {
        return false;
      }
      if (await hasDocument()) {
        return true;
      }
      if (creatingDocumentPromise) {
        await creatingDocumentPromise;
        return true;
      }

      const creation = Promise.resolve(chromeApi.offscreen.createDocument({
        url: documentPath,
        reasons: ["WORKERS"],
        justification: "Execute long-running LLM API calls that exceed MV3 Service Worker idle timeout.",
      }));
      creatingDocumentPromise = creation;
      try {
        await creation;
        return true;
      } finally {
        if (creatingDocumentPromise === creation) {
          creatingDocumentPromise = null;
        }
      }
    }

    async function closeDocument() {
      if (
        chromeApi.offscreen &&
        typeof chromeApi.offscreen.closeDocument === "function" &&
        await hasDocument()
      ) {
        await chromeApi.offscreen.closeDocument();
        return true;
      }
      return false;
    }

    function hardTimeoutMs(mode, payload) {
      const llmOptions = mode === "revise" && payload && payload.options
        ? payload.options
        : (payload || {});
      const requestTimeoutMs = clampNumber(
        nonNegativeInteger(llmOptions.requestTimeoutMs, defaultRequestTimeoutMs),
        1,
        maxRequestTimeoutMs,
      );
      const lintRetries = clampNumber(
        nonNegativeInteger(llmOptions.maxRetries, DEFAULT_MAX_RETRIES),
        0,
        MAX_LINT_RETRIES,
      );
      const lintPasses = lintRetries + 1;
      // 单次 offscreen 运行会走完整个端点回退链（auto 最多 5 个），预算必须乘上该因子，
      // 否则早段端点挂起时硬超时会在任务仍正常工作时提前触发（ee24ac0 修复的回归）。
      const endpointAttempts = typeof aiEndpoint.requestAttemptCount === "function"
        ? Math.max(1, aiEndpoint.requestAttemptCount(llmOptions.apiStyle, llmOptions.apiBaseUrl))
        : 1;
      const singlePathBudget = 2 * requestTimeoutMs * lintPasses * endpointAttempts + deadlineGraceMs;
      const safetyMargin = Math.max(
        1,
        Math.min(staleSafetyMarginMs, activeJobStaleMs - 1),
      );
      const staleCeiling = activeJobStaleMs - safetyMargin;
      return Math.min(singlePathBudget, staleCeiling);
    }

    // 这里只做 transport：返回结果或抛错，任务 finish/fail 由上层 lifecycle 决定。
    function run(job, mode, payload, runtimeOptions, legacyOnProgress) {
      const runtime = normalizeRuntimeOptions(runtimeOptions, legacyOnProgress);
      if (!supports()) {
        return runDirectly(mode, payload, runtime.signal);
      }
      if (!job || !job.id) {
        return Promise.reject(new Error("Offscreen LLM transport requires job.id."));
      }
      if (
        !chromeApi.runtime.onMessage ||
        typeof chromeApi.runtime.onMessage.addListener !== "function" ||
        typeof chromeApi.runtime.onMessage.removeListener !== "function"
      ) {
        return Promise.reject(new Error("chrome.runtime.onMessage add/removeListener is unavailable."));
      }

      const jobId = job.id;
      const timeoutMs = hardTimeoutMs(mode, payload);

      return new Promise((resolve, reject) => {
        let settled = false;
        let hardTimeoutId = null;

        function cleanup() {
          if (hardTimeoutId !== null) {
            clearTimer(hardTimeoutId);
            hardTimeoutId = null;
          }
          chromeApi.runtime.onMessage.removeListener(onMessage);
          if (runtime.signal) {
            runtime.signal.removeEventListener("abort", onAbort);
          }
        }

        function settleWithResult(result) {
          if (settled) return false;
          settled = true;
          cleanup();
          resolve(result);
          return true;
        }

        function settleWithError(error) {
          if (settled) return false;
          settled = true;
          cleanup();
          reject(error);
          return true;
        }

        function onMessage(message) {
          if (!message || message.jobId !== jobId) return;

          if (message.type === messages.OFFSCREEN_PROGRESS) {
            void Promise.resolve()
              .then(() => runtime.onProgress(message.message))
              .catch(() => {});
            return;
          }
          if (message.type === messages.OFFSCREEN_RESULT) {
            settleWithResult(message.result);
            return;
          }
          if (message.type === messages.OFFSCREEN_ERROR) {
            const error = message.abortLike
              ? createAbortError(message.error)
              : new Error(message.error || "Offscreen task failed.");
            settleWithError(error);
          }
        }

        function onAbort() {
          if (!settleWithError(createAbortError("Cancelled by user."))) return;
          void cancel().catch(() => {});
        }

        chromeApi.runtime.onMessage.addListener(onMessage);
        if (runtime.signal) {
          runtime.signal.addEventListener("abort", onAbort, { once: true });
        }
        hardTimeoutId = setTimer(() => {
          settleWithError(new Error(
            `Offscreen document did not respond within ${Math.round(timeoutMs / 1000)}s. ` +
            "It may have crashed or been closed by the browser.",
          ));
        }, timeoutMs);

        if (runtime.signal && runtime.signal.aborted) {
          onAbort();
          return;
        }

        void startRemoteRun();

        async function startRemoteRun() {
          try {
            await evictOrphan(jobId);
            if (settled) return;
            const response = await chromeApi.runtime.sendMessage({
              type: messages.OFFSCREEN_LLM,
              jobId,
              mode,
              payload,
            });
            if (settled) return;
            if (!response || !response.ok) {
              settleWithError(new Error(response && response.error
                ? response.error
                : "Offscreen rejected the task"));
            }
          } catch (error) {
            settleWithError(error instanceof Error ? error : new Error(String(error)));
          }
        }
      });
    }

    function runDirectly(mode, payload, signal) {
      const restoreConsoleLog = suppressConsoleLogInNode(globalScope);
      if (!aiFacade) {
        restoreConsoleLog();
        return Promise.reject(new Error("AI facade is unavailable for direct LLM fallback."));
      }
      try {
        if (mode === "revise") {
          if (typeof aiFacade.reviseReviewedPlan !== "function") {
            throw new Error("AI facade does not support plan revision.");
          }
          return Promise.resolve(aiFacade.reviseReviewedPlan({
            ...((payload && payload.options) || {}),
            existingPlan: payload && payload.plan,
            signal,
          })).finally(restoreConsoleLog);
        }
        if (typeof aiFacade.generateReviewedPlan !== "function") {
          throw new Error("AI facade does not support plan generation.");
        }
        return Promise.resolve(aiFacade.generateReviewedPlan({
          ...(payload || {}),
          signal,
        })).finally(restoreConsoleLog);
      } catch (error) {
        restoreConsoleLog();
        return Promise.reject(error);
      }
    }

    function ping() {
      if (!chromeApi.runtime || typeof chromeApi.runtime.sendMessage !== "function") {
        return Promise.reject(new Error("Offscreen messaging is unavailable."));
      }
      return chromeApi.runtime.sendMessage({ type: messages.OFFSCREEN_PING });
    }

    function cancel() {
      if (!chromeApi.runtime || typeof chromeApi.runtime.sendMessage !== "function") {
        return Promise.reject(new Error("Offscreen messaging is unavailable."));
      }
      return chromeApi.runtime.sendMessage({ type: messages.OFFSCREEN_CANCEL });
    }

    async function evictOrphan(currentJobId) {
      if (!chromeApi.runtime || typeof chromeApi.runtime.sendMessage !== "function") {
        return false;
      }
      try {
        const response = await ping();
        if (!response || !response.busy || !response.jobId || response.jobId === currentJobId) {
          return false;
        }
        try {
          await cancel();
        } catch (_error) {
          // 驱逐是尽力而为；run 的正式发送仍会给出可见错误。
        }
        await sleep(orphanSettleMs);
        return true;
      } catch (_error) {
        // offscreen 不可达时由随后正式的 OFFSCREEN_LLM 发送决定结果。
        return false;
      }
    }

    async function loadPersistedResult(jobId) {
      const result = await storage.get(resultStorageKey);
      if (!result || !result.jobId) {
        return null;
      }
      if (jobId && result.jobId !== jobId) {
        return null;
      }
      return result;
    }

    async function clearPersistedResult(jobId) {
      const result = await storage.get(resultStorageKey);
      if (!result || (jobId && result.jobId !== jobId)) {
        return false;
      }
      await storage.remove(resultStorageKey);
      return true;
    }

    return Object.freeze({
      cancel,
      clearPersistedResult,
      closeDocument,
      ensureDocument,
      evictOrphan,
      hardTimeoutMs,
      hasDocument,
      loadPersistedResult,
      ping,
      run,
      supports,
    });
  }

  function normalizeRuntimeOptions(runtimeOptions, legacyOnProgress) {
    const looksLikeController = !!(
      runtimeOptions && runtimeOptions.signal &&
      typeof runtimeOptions.abort === "function"
    );
    const runtime = looksLikeController
      ? { controller: runtimeOptions, onProgress: legacyOnProgress }
      : (runtimeOptions || {});
    const signal = runtime.signal || (runtime.controller && runtime.controller.signal) || null;
    return {
      signal,
      onProgress: typeof runtime.onProgress === "function"
        ? runtime.onProgress
        : function () {},
    };
  }

  function createAbortError(message) {
    const error = new Error(message || "The operation was aborted.");
    error.name = "AbortError";
    error.code = 20;
    return error;
  }

  function suppressConsoleLogInNode(scope) {
    if (!scope.process || !scope.console || typeof scope.console.log !== "function") {
      return function () {};
    }
    const originalLog = scope.console.log;
    scope.console.log = function (...args) {
      if (typeof scope.console.error === "function") {
        scope.console.error(...args);
      }
    };
    return function restoreConsoleLog() {
      scope.console.log = originalLog;
    };
  }

  function bindTimer(timerApi, methodName, globalScope) {
    if (timerApi && typeof timerApi[methodName] === "function") {
      return timerApi[methodName].bind(timerApi);
    }
    if (typeof globalScope[methodName] !== "function") {
      throw new Error(`OffscreenClient requires ${methodName}.`);
    }
    return globalScope[methodName].bind(globalScope);
  }

  function nonNegativeInteger(value, fallback) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) {
      return fallback;
    }
    return Math.floor(numeric);
  }

  function positiveInteger(value, fallback) {
    const numeric = nonNegativeInteger(value, fallback);
    return numeric > 0 ? numeric : fallback;
  }

  function clampNumber(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
  }

  background.OffscreenClient = Object.freeze({
    create,
    DEFAULT_ACTIVE_JOB_STALE_MS,
  });
})(globalThis);
