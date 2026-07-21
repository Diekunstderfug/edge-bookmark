/* Popup 侧 ActiveJob 观察与 service-worker 失联检测。 */

(function attachPopupJobState(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const popup = root.Popup || (root.Popup = {});

  const DEFAULT_CHECK_INTERVAL_MS = 20 * 1000;
  const DEFAULT_STALE_THRESHOLD_MS = 180 * 1000;

  function create(dependencies) {
    const options = dependencies || {};
    const protocol = options.protocol || root.Protocol;
    const storage = options.storage || root.Storage;
    const timers = options.timers || globalScope;
    const now = typeof options.now === "function" ? options.now : Date.now;
    const onRecord = typeof options.onRecord === "function" ? options.onRecord : function () {};
    const staleMessage = typeof options.staleMessage === "function"
      ? options.staleMessage
      : () => String(options.staleMessage || "Background task lost connection.");

    if (!protocol || !protocol.JOB_STATUSES || !protocol.STORAGE_KEYS) {
      throw new Error("Popup JobState requires the shared protocol.");
    }
    if (!storage || typeof storage.get !== "function") {
      throw new Error("Popup JobState requires storage.get().");
    }
    if (typeof timers.setInterval !== "function" || typeof timers.clearInterval !== "function") {
      throw new Error("Popup JobState requires interval timers.");
    }

    const activeKey = protocol.STORAGE_KEYS.ACTIVE_JOB;
    const runningStatus = protocol.JOB_STATUSES.RUNNING;
    const failedStatus = protocol.JOB_STATUSES.FAILED;
    const checkIntervalMs = positiveInteger(options.checkIntervalMs, DEFAULT_CHECK_INTERVAL_MS);
    const staleThresholdMs = positiveInteger(options.staleThresholdMs, DEFAULT_STALE_THRESHOLD_MS);
    let activeJob = null;
    let intervalId = null;
    let checkPromise = null;

    function observe(job) {
      activeJob = job || null;
      if (isRunning()) {
        start();
      } else {
        stop();
      }
      return activeJob;
    }

    function getActive() {
      return activeJob;
    }

    function isRunning() {
      return !!activeJob && activeJob.status === runningStatus;
    }

    function handleStorageChange(changes, areaName) {
      if (areaName !== "local") return null;
      const change = changes && changes[activeKey];
      if (!change || !change.newValue) return null;
      onRecord(change.newValue);
      return change.newValue;
    }

    function start() {
      if (intervalId !== null || !isRunning()) {
        return intervalId;
      }
      intervalId = timers.setInterval(() => {
        void check();
      }, checkIntervalMs);
      void check();
      return intervalId;
    }

    function stop() {
      if (intervalId !== null) {
        timers.clearInterval(intervalId);
        intervalId = null;
      }
    }

    function check() {
      if (checkPromise) {
        return checkPromise;
      }
      checkPromise = performCheck().finally(() => {
        checkPromise = null;
      });
      return checkPromise;
    }

    async function performCheck() {
      if (!isRunning()) {
        stop();
        return null;
      }
      let storedJob;
      try {
        storedJob = await storage.get(activeKey);
      } catch (_error) {
        return null;
      }
      if (!isRunning()) {
        stop();
        return null;
      }
      if (!storedJob || storedJob.status !== runningStatus) {
        stop();
        return storedJob || null;
      }
      const timestamps = [storedJob.updated_at, storedJob.started_at]
        .map((value) => Date.parse(value))
        .filter((value) => Number.isFinite(value));
      if (
        timestamps.length > 0 &&
        now() - Math.max(...timestamps) <= staleThresholdMs
      ) {
        return storedJob;
      }

      const timestamp = new Date(now()).toISOString();
      const message = staleMessage();
      const failed = {
        ...storedJob,
        status: failedStatus,
        recoverable: true,
        error: message,
        progress: message,
        updated_at: timestamp,
        finished_at: timestamp,
      };
      onRecord(failed);
      return failed;
    }

    return Object.freeze({
      check,
      getActive,
      handleStorageChange,
      isRunning,
      observe,
      start,
      stop,
    });
  }

  function positiveInteger(value, fallback) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) && numberValue > 0
      ? Math.floor(numberValue)
      : fallback;
  }

  popup.JobState = Object.freeze({
    create,
    DEFAULT_CHECK_INTERVAL_MS,
    DEFAULT_STALE_THRESHOLD_MS,
  });
})(globalThis);
