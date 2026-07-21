/* Popup 与 Service Worker 的纯 runtime 通信客户端。 */

(function attachPopupRuntimeClient(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const popup = root.Popup || (root.Popup = {});

  if (!root.Protocol && typeof require === "function") {
    require("../shared/message_protocol.js");
  }

  const DEFAULT_TIMEOUT_MS = 240000;
  const START_JOB_TIMEOUT_MS = 10000;
  const GET_ACTIVE_JOB_TIMEOUT_MS = 5000;
  const LIST_FOLDERS_TIMEOUT_MS = 10000;
  const TIMEOUT_MESSAGE = "Extension background task timed out. Reload the extension and check that Bookmark permission is enabled.";

  function create(dependencies) {
    const options = dependencies || {};
    const chromeApi = options.chrome || globalScope.chrome;
    const protocol = options.protocol || root.Protocol;
    const timers = options.timers || globalScope;
    const defaultTimeoutMs = options.timeoutMs === undefined
      ? DEFAULT_TIMEOUT_MS
      : options.timeoutMs;

    if (!chromeApi || !chromeApi.runtime || typeof chromeApi.runtime.sendMessage !== "function") {
      throw new Error("RuntimeClient requires chrome.runtime.sendMessage().");
    }
    if (!protocol || !protocol.MESSAGE_TYPES) {
      throw new Error("RuntimeClient requires the shared message protocol.");
    }
    if (!timers || typeof timers.setTimeout !== "function" || typeof timers.clearTimeout !== "function") {
      throw new Error("RuntimeClient requires setTimeout/clearTimeout.");
    }

    const messages = protocol.MESSAGE_TYPES;

    function send(payload, timeoutOverride) {
      const effectiveTimeout = timeoutOverride === undefined ? defaultTimeoutMs : timeoutOverride;
      return new Promise((resolve, reject) => {
        let settled = false;
        const timeoutId = timers.setTimeout(() => {
          if (settled) return;
          settled = true;
          reject(new Error(TIMEOUT_MESSAGE));
        }, effectiveTimeout);

        function resolveOnce(response) {
          if (settled) return;
          settled = true;
          timers.clearTimeout(timeoutId);
          resolve(response);
        }

        function rejectOnce(error) {
          if (settled) return;
          settled = true;
          timers.clearTimeout(timeoutId);
          reject(error);
        }

        function callback(response) {
          const runtimeError = chromeApi.runtime.lastError;
          if (settled) return;
          if (runtimeError) {
            rejectOnce(new Error(runtimeError.message));
            return;
          }
          resolveOnce(response);
        }

        let returned;
        try {
          returned = chromeApi.runtime.sendMessage(payload, callback);
        } catch (error) {
          rejectOnce(error);
          return;
        }

        if (returned && typeof returned.then === "function") {
          returned.then(resolveOnce, rejectOnce);
        }
      });
    }

    async function startJob(jobType, payload) {
      const response = await send({
        type: messages.START_BACKGROUND_JOB,
        job_type: jobType,
        payload,
      }, START_JOB_TIMEOUT_MS);
      if (response && response.error) {
        throw new Error(response.error);
      }
      if (!response || !response.job) {
        throw new Error("Background executor did not return a job record.");
      }
      return response;
    }

    function getActiveJob() {
      return send({ type: messages.GET_ACTIVE_JOB }, GET_ACTIVE_JOB_TIMEOUT_MS);
    }

    function cancel() {
      return send({ type: messages.CANCEL_ACTIVE_JOB });
    }

    function exportSnapshot() {
      return send({ type: messages.EXPORT_SNAPSHOT });
    }

    function listFolders() {
      return send({ type: messages.LIST_FOLDERS }, LIST_FOLDERS_TIMEOUT_MS);
    }

    function undo() {
      return send({ type: messages.UNDO_LAST_EXECUTION });
    }

    return Object.freeze({
      cancel,
      exportSnapshot,
      getActiveJob,
      listFolders,
      send,
      startJob,
      undo,
    });
  }

  popup.RuntimeClient = Object.freeze({
    create,
    DEFAULT_TIMEOUT_MS,
    GET_ACTIVE_JOB_TIMEOUT_MS,
    LIST_FOLDERS_TIMEOUT_MS,
    START_JOB_TIMEOUT_MS,
    TIMEOUT_MESSAGE,
  });
})(globalThis);
