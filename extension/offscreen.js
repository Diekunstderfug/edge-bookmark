/* Offscreen Document for Bookmark Advisor
 *
 * 负责执行所有 LLM API 调用（fetch），运行在独立的 renderer 进程中，
 * 不受 MV3 Service Worker 30 秒 idle 超时限制。
 *
 * 通信协议：
 *   SW -> offscreen: { type: "offscreen-llm", mode: "generate"|"revise", payload: {...} }
 *   offscreen -> SW: { type: "offscreen-progress", jobId, message }
 *   offscreen -> SW: { type: "offscreen-result", jobId, result }
 *   offscreen -> SW: { type: "offscreen-error", jobId, error }
 */

(function (globalScope) {
  let _currentJobId = null;
  let _abortController = null;

  const OFFSCREEN_RESULT_STORAGE = "bookmarkAdvisorOffscreenResult";

  // 向 Service Worker 发送消息（等待完成，确保大对象序列化不静默失败）
  async function sendToSw(type, jobId, data) {
    try {
      await chrome.runtime.sendMessage({ type, jobId, ...data });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error(`[BookmarkAdvisor][offscreen] sendToSw(${type}) failed:`, err?.message || err);
      throw err;
    }
  }

  // 将结果持久化到 storage，防止 SW 终止导致消息丢失
  // 限制：chrome.storage.local 单条约 8MB，超大结果跳过 persist 直接发消息
  async function persistOffscreenResult(jobId, data) {
    try {
      const payload = {
        jobId,
        ...data,
        timestamp: Date.now(),
      };
      const size = JSON.stringify(payload).length;
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] persistOffscreenResult size=${size} chars`);
      if (size > 7 * 1024 * 1024) {
        // eslint-disable-next-line no-console
        console.warn(`[BookmarkAdvisor][offscreen] result too large (${Math.round(size / 1024 / 1024)}MB), skipping storage persist`);
        return;
      }
      // storage 写入加 5 秒超时，防止卡住
      await Promise.race([
        chrome.storage.local.set({ [OFFSCREEN_RESULT_STORAGE]: payload }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("storage persist timeout")), 5000)),
      ]);
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] persistOffscreenResult done`);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn(`[BookmarkAdvisor][offscreen] persistOffscreenResult failed (non-fatal):`, err?.message || err);
    }
  }

  async function clearOffscreenResult() {
    try {
      await chrome.storage.local.remove(OFFSCREEN_RESULT_STORAGE);
    } catch (_e) {}
  }

  // 包装 onProgress：同时更新本地状态并通过消息通知 SW
  function makeProgressCallback(jobId) {
    return function (message) {
      if (_currentJobId !== jobId) {
        return;
      }
      void sendToSw("offscreen-progress", jobId, { message }).catch(() => {});
    };
  }

  function createAbortError(message) {
    const error = new Error(message || "The operation was aborted.");
    error.name = "AbortError";
    return error;
  }

  async function handleGenerate(jobId, payload) {
    // eslint-disable-next-line no-console
    console.log(`[BookmarkAdvisor][offscreen] handleGenerate start, jobId=${jobId}`);
    const onProgress = makeProgressCallback(jobId);
    _abortController = new AbortController();
    try {
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] calling generateReviewedPlan...`);
      const result = await globalScope.BookmarkAdvisorAI.generateReviewedPlan({
        ...payload,
        onProgress,
        signal: _abortController.signal,
      });
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] generateReviewedPlan returned, persisting result...`);
      await persistOffscreenResult(jobId, { ok: true, result });
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] result persisted, sending offscreen-result to SW...`);
      await sendToSw("offscreen-result", jobId, { result });
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] offscreen-result sent to SW`);
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error(`[BookmarkAdvisor][offscreen] handleGenerate error:`, error);
      const errorPayload = {
        error: error.message || String(error),
        abortLike: error.name === "AbortError" || /aborted|cancelled by user/i.test(error.message || ""),
      };
      await persistOffscreenResult(jobId, { ok: false, ...errorPayload });
      await sendToSw("offscreen-error", jobId, errorPayload);
    } finally {
      _currentJobId = null;
      _abortController = null;
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] handleGenerate cleanup done`);
    }
  }

  async function handleRevise(jobId, payload) {
    // eslint-disable-next-line no-console
    console.log(`[BookmarkAdvisor][offscreen] handleRevise start, jobId=${jobId}`);
    const onProgress = makeProgressCallback(jobId);
    _abortController = new AbortController();
    try {
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] calling reviseReviewedPlan...`);
      const result = await globalScope.BookmarkAdvisorAI.reviseReviewedPlan({
        ...payload.options,
        existingPlan: payload.plan,
        onProgress,
        signal: _abortController.signal,
      });
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] reviseReviewedPlan returned, persisting result...`);
      await persistOffscreenResult(jobId, { ok: true, result });
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] result persisted, sending offscreen-result to SW...`);
      await sendToSw("offscreen-result", jobId, { result });
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] offscreen-result sent to SW`);
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error(`[BookmarkAdvisor][offscreen] handleRevise error:`, error);
      const errorPayload = {
        error: error.message || String(error),
        abortLike: error.name === "AbortError" || /aborted|cancelled by user/i.test(error.message || ""),
      };
      await persistOffscreenResult(jobId, { ok: false, ...errorPayload });
      await sendToSw("offscreen-error", jobId, errorPayload);
    } finally {
      _currentJobId = null;
      _abortController = null;
      // eslint-disable-next-line no-console
      console.log(`[BookmarkAdvisor][offscreen] handleRevise cleanup done`);
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !message.type) {
      sendResponse({ ok: false, error: "Missing message type" });
      return false;
    }

    if (message.type === "offscreen-llm") {
      if (_currentJobId) {
        sendResponse({ ok: false, error: `Offscreen busy with job ${_currentJobId}` });
        return false;
      }
      const jobId = message.jobId;
      if (!jobId) {
        sendResponse({ ok: false, error: "Missing jobId" });
        return false;
      }
      _currentJobId = jobId;
      sendResponse({ ok: true });

      if (message.mode === "generate") {
        void handleGenerate(jobId, message.payload);
      } else if (message.mode === "revise") {
        void handleRevise(jobId, message.payload);
      } else {
        void sendToSw("offscreen-error", jobId, { error: `Unknown mode: ${message.mode}` }).catch(() => {});
        _currentJobId = null;
      }
      return false;
    }

    if (message.type === "offscreen-cancel") {
      if (_abortController && !_abortController.signal.aborted) {
        _abortController.abort();
      }
      sendResponse({ ok: true });
      return false;
    }

    if (message.type === "offscreen-ping") {
      sendResponse({ ok: true, busy: !!_currentJobId, jobId: _currentJobId });
      return false;
    }

    return false;
  });

  // 页面加载完成后向 SW 报告就绪
  void sendToSw("offscreen-ready", null, {}).catch(() => {});
})(globalThis);
