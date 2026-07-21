/* ActiveJob 的持久化、结果摘要、恢复与状态转换。 */

(function attachJobStore(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  const ACTIVE_JOB_STALE_MS = 30 * 60 * 1000;
  const STARTUP_JOB_STALE_MS = 60 * 1000;

  function create(dependencies) {
    const options = dependencies || {};
    const storage = options.storage;
    const protocol = options.protocol;
    const clock = options.clock;

    if (!storage || typeof storage.get !== "function" || typeof storage.set !== "function") {
      throw new Error("JobStore requires a storage adapter with get/set methods.");
    }
    if (!protocol || !protocol.STORAGE_KEYS || !protocol.JOB_STATUSES) {
      throw new Error("JobStore requires the shared message protocol.");
    }
    if (
      clock !== undefined &&
      typeof clock !== "function" &&
      (!clock || typeof clock.now !== "function")
    ) {
      throw new Error("JobStore clock must be a function or expose now().");
    }

    const storageKeys = protocol.STORAGE_KEYS;
    const statuses = protocol.JOB_STATUSES;

    function nowMs() {
      if (typeof clock === "function") return Number(clock());
      if (clock && typeof clock.now === "function") return Number(clock.now());
      return Date.now();
    }

    function nowTimestamp() {
      return new Date(nowMs()).toISOString();
    }

    function toStoredJob(job) {
      if (!job) return job;
      const { result: _fullResult, ...storedJob } = job;
      return storedJob;
    }

    function get() {
      return storage.get(storageKeys.ACTIVE_JOB);
    }

    async function save(job) {
      const storedJob = toStoredJob(job);
      await storage.set(storageKeys.ACTIVE_JOB, storedJob);
      return storedJob;
    }

    async function currentRunningJob(job) {
      const current = await get();
      if (
        !current ||
        !job ||
        current.id !== job.id ||
        current.status !== statuses.RUNNING
      ) {
        return { current: current || null, canTransition: false };
      }
      return { current, canTransition: true };
    }

    async function setStage(job, stage) {
      const state = await currentRunningJob(job);
      if (!state.canTransition) return state.current;
      const timestamp = nowTimestamp();
      return save({
        ...state.current,
        stage,
        stage_started_at: timestamp,
        updated_at: timestamp,
      });
    }

    async function progress(job, message) {
      const state = await currentRunningJob(job);
      if (!state.canTransition) return state.current;
      const updatedAt = nowMs();
      const updated = {
        ...state.current,
        status: statuses.RUNNING,
        progress: message,
        updated_at: new Date(updatedAt).toISOString(),
      };
      const storedJob = toStoredJob(updated);
      await Promise.all([
        storage.set(storageKeys.ACTIVE_JOB, storedJob),
        storage.set(storageKeys.PROGRESS, { message, updated_at: updatedAt }),
      ]);
      return storedJob;
    }

    function summarizeResult(result) {
      if (!result) return null;
      if (result.reviewed_plan) {
        return {
          type: "plan",
          action_count: (result.reviewed_plan.actions || []).length,
        };
      }
      if (Array.isArray(result.succeeded) || Array.isArray(result.failures)) {
        return {
          type: "report",
          succeeded_count: (result.succeeded || []).length,
          failure_count: (result.failures || []).length,
        };
      }
      return null;
    }

    async function succeed(job, result, message) {
      const state = await currentRunningJob(job);
      if (!state.canTransition) return state.current;
      const timestamp = nowTimestamp();
      return save({
        ...state.current,
        status: statuses.SUCCEEDED,
        progress: message,
        result_summary: summarizeResult(result),
        updated_at: timestamp,
        finished_at: timestamp,
      });
    }

    async function fail(job, message) {
      const state = await currentRunningJob(job);
      if (!state.canTransition) return state.current;
      const timestamp = nowTimestamp();
      const cancellationRequestedAt = message === "Cancelled by user."
        ? job.cancellation_requested_at ||
          state.current.cancellation_requested_at ||
          timestamp
        : job.cancellation_requested_at ||
          state.current.cancellation_requested_at ||
          "";
      return save({
        ...state.current,
        status: statuses.FAILED,
        ...(cancellationRequestedAt
          ? { cancellation_requested_at: cancellationRequestedAt }
          : {}),
        progress: message,
        error: message,
        updated_at: timestamp,
        finished_at: timestamp,
      });
    }

    async function rehydrate(job) {
      const current = job === undefined ? await get() : job;
      if (!current || current.status !== statuses.SUCCEEDED || current.result) {
        return current;
      }
      if (current.result_summary && current.result_summary.type === "plan") {
        const lastPlanData = await storage.get(storageKeys.LAST_PLAN);
        if (lastPlanData && lastPlanData.plan) {
          return { ...current, result: { reviewed_plan: lastPlanData.plan } };
        }
      } else if (current.result_summary && current.result_summary.type === "report") {
        const lastReport = await storage.get(storageKeys.LAST_REPORT);
        if (lastReport) {
          return { ...current, result: lastReport };
        }
      }
      return current;
    }

    function runningTimestamp(job) {
      if (!job || job.status !== statuses.RUNNING) return NaN;
      return Date.parse(job.updated_at || job.started_at || "");
    }

    function hasValidRunningTimestamp(job) {
      return Number.isFinite(runningTimestamp(job));
    }

    function isStaleRunning(job) {
      if (!job || job.status !== statuses.RUNNING) return false;
      const updatedAt = runningTimestamp(job);
      return !Number.isFinite(updatedAt) || nowMs() - updatedAt > ACTIVE_JOB_STALE_MS;
    }

    function isStartupStaleRunning(job) {
      if (!job || job.status !== statuses.RUNNING) return false;
      const effectiveAt = runningTimestamp(job);
      return !Number.isFinite(effectiveAt) || nowMs() - effectiveAt > STARTUP_JOB_STALE_MS;
    }

    function isFreshRunning(job) {
      return !!job && job.status === statuses.RUNNING && !isStaleRunning(job);
    }

    return Object.freeze({
      ACTIVE_JOB_STALE_MS,
      STARTUP_JOB_STALE_MS,
      fail,
      get,
      hasValidRunningTimestamp,
      isFreshRunning,
      isStaleRunning,
      isStartupStaleRunning,
      progress,
      rehydrate,
      save,
      setStage,
      succeed,
      summarizeResult,
    });
  }

  background.JobStore = Object.freeze({
    ACTIVE_JOB_STALE_MS,
    STARTUP_JOB_STALE_MS,
    create,
  });
})(globalThis);
