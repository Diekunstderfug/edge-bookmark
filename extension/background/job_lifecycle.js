/* 后台任务生命周期：互斥、运行、恢复、取消与 heartbeat。 */

(function attachJobLifecycle(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  if (!root.Protocol && typeof require === "function") {
    require("../shared/message_protocol.js");
  }

  const DEFAULT_HEARTBEAT_ALARM = "bookmarkAdvisorJobKeepalive";
  const DEFAULT_POLL_INTERVAL_MS = 250;
  const DEFAULT_WAIT_DEADLINE_MS = 300000;

  function create(dependencies) {
    const options = dependencies || {};
    const protocol = options.protocol || root.Protocol;
    const jobStore = options.jobStore;
    const jobHandlers = options.jobHandlers;
    const offscreenClient = options.offscreenClient;
    const storage = options.storage;
    const alarms = options.alarms;
    const saveLastPlan = options.saveLastPlan;
    const saveLastReport = options.saveLastReport;
    const clock = options.clock || {};
    const log = typeof options.log === "function" ? options.log : function () {};
    const makeAbortController = options.makeAbortController || (() => new AbortController());
    const random = typeof options.random === "function" ? options.random : Math.random;

    validateDependencies({
      protocol,
      jobStore,
      jobHandlers,
      offscreenClient,
      storage,
      alarms,
      saveLastPlan,
      saveLastReport,
    });

    const statuses = protocol.JOB_STATUSES;
    const jobTypes = protocol.JOB_TYPES;
    const jobStages = protocol.JOB_STAGES;
    const storageKeys = protocol.STORAGE_KEYS;
    const heartbeatAlarmName = String(options.heartbeatAlarmName || DEFAULT_HEARTBEAT_ALARM);
    const runId = String(options.runId || createRunId(nowMs(), random));
    const jobIdFactory = typeof options.jobIdFactory === "function"
      ? options.jobIdFactory
      : (milliseconds) => `job-${milliseconds}-${random().toString(16).slice(2)}`;

    let runningJobId = "";
    let jobAbortController = null;
    let startupCleanupStarted = false;

    function nowMs() {
      if (typeof clock === "function") return Number(clock());
      if (clock && typeof clock.now === "function") return Number(clock.now());
      return Date.now();
    }

    function nowTimestamp() {
      return new Date(nowMs()).toISOString();
    }

    function sleep(milliseconds) {
      if (clock && typeof clock.sleep === "function") {
        return clock.sleep(milliseconds);
      }
      return new Promise((resolve) => setTimeout(resolve, milliseconds));
    }

    function createJobAbortController() {
      abortCurrent();
      jobAbortController = makeAbortController();
      return jobAbortController;
    }

    function abortCurrent() {
      if (jobAbortController && !jobAbortController.signal.aborted) {
        jobAbortController.abort();
      }
      return jobAbortController;
    }

    function clearAbortController(controller = jobAbortController) {
      if (jobAbortController && controller === jobAbortController) {
        jobAbortController = null;
      }
    }

    function clearRunningJobState(jobId, controller) {
      if (runningJobId === jobId) {
        runningJobId = "";
      }
      clearAbortController(controller);
    }

    function getRunningJobId() {
      return runningJobId;
    }

    async function setStage(job, stage) {
      const updated = await jobStore.setStage(job, stage);
      if (updated && job && updated.id === job.id && updated.stage === stage) {
        job.stage = updated.stage;
        job.stage_started_at = updated.stage_started_at;
      }
      return updated;
    }

    function progress(job, message) {
      return jobStore.progress(job, message);
    }

    async function finish(job, result, message) {
      stopHeartbeat();
      const current = await jobStore.get();
      if (!current || !job || current.id !== job.id) {
        return current || null;
      }
      if (current.status !== statuses.RUNNING) {
        return current;
      }
      const finished = await jobStore.succeed(job, result, message);
      await offscreenClient.clearPersistedResult(job.id);
      return finished;
    }

    async function fail(job, message) {
      stopHeartbeat();
      const current = await jobStore.get();
      if (!current || !job || current.id !== job.id) {
        return current || null;
      }
      if (current.status !== statuses.RUNNING) {
        return current;
      }
      const failed = await jobStore.fail(job, message);
      await offscreenClient.clearPersistedResult(job.id);
      return failed;
    }

    async function reserve(jobType) {
      if (!protocol.isSupportedJobType(jobType)) {
        return { error: `Unsupported background job type: ${jobType}` };
      }
      if (runningJobId) {
        return { error: "Background job already running in this service worker." };
      }

      runningJobId = "starting";
      let existingJob;
      try {
        existingJob = await jobStore.get();
      } catch (error) {
        runningJobId = "";
        throw error;
      }

      if (jobStore.isFreshRunning(existingJob)) {
        runningJobId = "";
        return { error: `Background job already running: ${existingJob.type}` };
      }
      if (jobStore.isStaleRunning(existingJob)) {
        try {
          await fail(existingJob, "Background job timed out before completion.");
        } catch (error) {
          runningJobId = "";
          throw error;
        }
      }

      const controller = createJobAbortController();
      const timestamp = nowTimestamp();
      const job = {
        id: jobIdFactory(nowMs()),
        type: jobType,
        status: statuses.RUNNING,
        progress: "Starting background job...",
        owner_run_id: runId,
        started_at: timestamp,
        updated_at: nowTimestamp(),
      };
      runningJobId = job.id;
      return { job, jobAbortController: controller };
    }

    async function start(jobType, payload) {
      const reserved = await reserve(jobType);
      if (reserved.error) {
        return { error: reserved.error };
      }
      void runDetached(reserved.job, payload, reserved.jobAbortController);
      return { job: reserved.job };
    }

    async function runForeground(jobType, payload) {
      const reserved = await reserve(jobType);
      if (reserved.error) {
        throw new Error(reserved.error);
      }
      return runReservedForeground(reserved.job, payload, reserved.jobAbortController);
    }

    function runApplyReviewedPlanForeground(payload) {
      return runForeground(jobTypes.APPLY_REVIEWED_PLAN, payload);
    }

    async function runReservedForeground(job, payload, controller) {
      await jobStore.save(job);
      let fullResult = null;
      try {
        fullResult = await runJob(job, payload, controller);
      } catch (error) {
        await fail(job, errorMessage(error));
      }
      const savedJob = (await jobStore.get()) || job;
      if (fullResult && savedJob.status === statuses.SUCCEEDED) {
        savedJob.result = fullResult;
      }
      return savedJob;
    }

    async function runDetached(job, payload, controller) {
      try {
        await jobStore.save(job);
        await runJob(job, payload, controller);
      } catch (error) {
        await fail(job, errorMessage(error));
        clearRunningJobState(job.id, controller);
      }
    }

    async function runJob(job, payload, controller) {
      startHeartbeat(job);
      try {
        return await jobHandlers.run(job, payload, {
          controller,
          ensureOffscreen: offscreenClient.ensureDocument,
          finish,
          onProgress: (message) => progress(job, message),
          setStage,
        });
      } catch (error) {
        if (isAbortLikeError(error)) {
          await fail(job, "Cancelled by user.");
          return null;
        }
        throw error;
      } finally {
        stopHeartbeat();
        clearRunningJobState(job.id, controller);
        void Promise.resolve()
          .then(() => offscreenClient.closeDocument())
          .catch(() => {});
      }
    }

    async function wait(jobId, pollIntervalMs = DEFAULT_POLL_INTERVAL_MS, deadlineMs = DEFAULT_WAIT_DEADLINE_MS) {
      const deadline = nowMs() + deadlineMs;
      while (nowMs() < deadline) {
        const job = await jobStore.get();
        if (!job || job.id !== jobId) {
          return job || { status: statuses.FAILED, error: "Job lost from storage." };
        }
        if (job.status !== statuses.RUNNING) {
          return job;
        }
        await sleep(pollIntervalMs);
      }
      return { status: statuses.FAILED, error: "Timed out waiting for background job completion." };
    }

    async function withMutationLock(operationType, callback) {
      if (runningJobId) {
        throw new Error(`Background job already running: ${operationType}`);
      }
      const lockId = `direct-${operationType}-${nowMs()}`;
      runningJobId = lockId;
      try {
        const existingJob = await jobStore.get();
        if (jobStore.isFreshRunning(existingJob)) {
          throw new Error(`Background job already running: ${existingJob.type}`);
        }
        return await callback();
      } finally {
        if (runningJobId === lockId) {
          runningJobId = "";
        }
      }
    }

    async function getActiveForPopup() {
      const recovered = await recoverPersistedResult("Restored from offscreen after popup wake.");
      if (recovered) {
        return jobStore.rehydrate(recovered);
      }
      const job = await jobStore.get();
      if (jobStore.isStaleRunning(job)) {
        return fail(job, "Background job timed out before completion.");
      }
      if (job && job.status === statuses.RUNNING && (job.stage || "") === jobStages.LLM) {
        const verified = await verifyOffscreenLlmJob(job);
        return verified.job;
      }
      return jobStore.rehydrate(job);
    }

    async function cancel() {
      abortCurrent();
      stopHeartbeat();
      const activeJob = await jobStore.get();
      if (activeJob && activeJob.status === statuses.RUNNING) {
        await fail({ ...activeJob, cancellation_requested_at: nowTimestamp() }, "Cancelled by user.");
      }
      await Promise.all([
        Promise.resolve().then(() => offscreenClient.cancel()).catch(() => {}),
        Promise.resolve().then(() => offscreenClient.closeDocument()).catch(() => {}),
        storage.set(storageKeys.PROGRESS, null).catch(() => {}),
      ]);
      return { cancelled: true };
    }

    async function cleanupOnStartup() {
      if (startupCleanupStarted) {
        return null;
      }
      startupCleanupStarted = true;
      try {
        await recoverExecutionCheckpoint();

        const recovered = await recoverPersistedResult("Restored from offscreen after SW restart.");
        if (recovered) {
          return recovered;
        }

        const activeJob = await jobStore.get();
        if (!activeJob || activeJob.status !== statuses.RUNNING) {
          return activeJob || null;
        }

        const stage = activeJob.stage || "";
        const isFreshAtStartup = !jobStore.isStartupStaleRunning(activeJob);
        if (activeJob.owner_run_id === runId) {
          return activeJob;
        }
        if (stage === jobStages.LLM && isFreshAtStartup) {
          const verified = await verifyOffscreenLlmJob(activeJob);
          return verified.job;
        }
        if (isFreshAtStartup) {
          return fail(activeJob, "Service worker restarted. Background job was interrupted.");
        }
        if (jobStore.isStaleRunning(activeJob) && jobStore.hasValidRunningTimestamp(activeJob)) {
          return fail(activeJob, "Background job timed out before completion.");
        }
        if (jobStore.isStartupStaleRunning(activeJob)) {
          return fail(activeJob, "Service worker restarted. Background job was interrupted.");
        }
        return activeJob;
      } catch (error) {
        log("[BookmarkAdvisor][SW] startup cleanup failed:", error && error.stack ? error.stack : error);
        return null;
      }
    }

    async function recoverExecutionCheckpoint() {
      const checkpoint = await storage.get(storageKeys.EXECUTION_CHECKPOINT);
      if (!checkpoint || !checkpoint.executionId || !(checkpoint.done > 0)) {
        return null;
      }
      const partialReport = {
        plan_version: "2",
        plan_kind: "reviewed",
        executed_at: checkpoint.succeeded && checkpoint.succeeded[0]
          ? checkpoint.succeeded[0].executed_at
          : nowTimestamp(),
        succeeded: checkpoint.succeeded || [],
        failures: checkpoint.failures || [],
        partial: true,
        partial_reason: "Service worker interrupted during execution.",
      };
      await saveLastReport(partialReport);
      await storage.set(storageKeys.EXECUTION_CHECKPOINT, null);
      log(
        `[BookmarkAdvisor][SW] recovered execution checkpoint: ${checkpoint.done}/${checkpoint.totalActions} actions`,
      );
      return partialReport;
    }

    async function verifyOffscreenLlmJob(job) {
      if (!job || job.status !== statuses.RUNNING || (job.stage || "") !== jobStages.LLM) {
        return { verified: true, job };
      }
      try {
        const response = await offscreenClient.ping();
        if (!response || response.ok !== true) {
          const failed = await fail(job, response && response.error
            ? response.error
            : "Offscreen document did not respond.");
          return { verified: false, job: failed };
        }
        if (response.busy && response.jobId === job.id) {
          return { verified: true, job };
        }
        const message = response.busy
          ? `Offscreen document is busy with another job${response.jobId ? ` (${response.jobId})` : ""}.`
          : "Offscreen document is no longer running this job.";
        const failed = await fail(job, message);
        return { verified: false, job: failed };
      } catch (error) {
        const failed = await fail(job, errorMessage(error));
        return { verified: false, job: failed };
      }
    }

    async function recoverPersistedResult(message) {
      const persisted = await offscreenClient.loadPersistedResult();
      if (!persisted || !persisted.jobId) {
        return null;
      }
      return consumeResultPayload(persisted, message, { removeStoredResult: true });
    }

    async function consumeCompletionMessage(message) {
      if (!message || !message.jobId || runningJobId === message.jobId) {
        return null;
      }
      const persisted = await offscreenClient.loadPersistedResult(message.jobId);
      if (persisted) {
        return consumeResultPayload(persisted, "Restored from late offscreen completion.", {
          removeStoredResult: true,
        });
      }
      const payload = message.type === protocol.MESSAGE_TYPES.OFFSCREEN_RESULT
        ? { jobId: message.jobId, ok: true, result: message.result }
        : {
            jobId: message.jobId,
            ok: false,
            error: message.error || "Offscreen task failed.",
            abortLike: !!message.abortLike,
          };
      return consumeResultPayload(payload, "Restored from late offscreen completion.", {
        removeStoredResult: false,
      });
    }

    async function consumeResultPayload(offscreenResult, message, consumeOptions = {}) {
      const activeJob = await jobStore.get();
      if (!activeJob || !offscreenResult || activeJob.id !== offscreenResult.jobId) {
        return null;
      }
      if (activeJob.status !== statuses.RUNNING) {
        if (consumeOptions.removeStoredResult) {
          await offscreenClient.clearPersistedResult(offscreenResult.jobId);
        }
        return null;
      }
      if (offscreenResult.ok && offscreenResult.result) {
        if (
          activeJob.type === jobTypes.GENERATE_AI_PLAN ||
          activeJob.type === jobTypes.REVISE_AI_PLAN
        ) {
          await saveLastPlan(offscreenResult.result.reviewed_plan);
        }
        await finish(activeJob, offscreenResult.result, message);
      } else {
        await fail(activeJob, offscreenResult.error || "Offscreen task failed.");
      }
      if (consumeOptions.removeStoredResult) {
        await offscreenClient.clearPersistedResult(offscreenResult.jobId);
      }
      return jobStore.get();
    }

    function startHeartbeat(job) {
      stopHeartbeat();
      if (!job || !job.id) {
        return false;
      }
      void alarms.create(heartbeatAlarmName, { periodInMinutes: 0.5 });
      return true;
    }

    function stopHeartbeat() {
      void alarms.clear(heartbeatAlarmName);
    }

    async function heartbeatTick(job) {
      const current = await jobStore.get();
      if (!current || !job || current.id !== job.id || current.status !== statuses.RUNNING) {
        stopHeartbeat();
        return current || null;
      }
      if (current.owner_run_id !== runId) {
        if (jobStore.isStaleRunning(current)) {
          log(`[BookmarkAdvisor][SW] orphan job=${current.id} exceeded stale threshold during alarm tick; failing.`);
          return fail(
            current,
            "Background job became stale (service worker restarted or stopped responding).",
          );
        }
        return current;
      }
      return jobStore.save({ ...current, updated_at: nowTimestamp() });
    }

    async function handleAlarm(alarm) {
      if (!alarm || alarm.name !== heartbeatAlarmName) {
        return false;
      }
      const current = await jobStore.get();
      if (!current || current.status !== statuses.RUNNING) {
        stopHeartbeat();
        return true;
      }
      await heartbeatTick(current);
      return true;
    }

    async function isCancellationRequested(jobId) {
      if (!jobId) return false;
      const current = await jobStore.get();
      if (!current || current.id !== jobId) return true;
      if (current.cancellation_requested_at) return true;
      return current.status !== statuses.RUNNING;
    }

    return Object.freeze({
      abortCurrent,
      cancel,
      cancelActiveJob: cancel,
      cleanupOnStartup,
      cleanupStaleActiveJobOnStartup: cleanupOnStartup,
      consumeCompletionMessage,
      consumeOffscreenCompletionMessage: consumeCompletionMessage,
      consumeResultPayload,
      fail,
      finish,
      getActiveForPopup,
      getActiveJobForPopup: getActiveForPopup,
      getRunningJobId,
      handleAlarm,
      heartbeatAlarmName,
      heartbeatTick,
      isCancellationRequested,
      jobHeartbeatTick: heartbeatTick,
      progress,
      recoverExecutionCheckpoint,
      recoverPersistedResult,
      reserve,
      reserveBackgroundJob: reserve,
      runDetached,
      runDetachedBackgroundJob: runDetached,
      runApplyReviewedPlanForeground,
      runForeground,
      runForegroundBackgroundJob: runReservedForeground,
      runId,
      runJob,
      setStage,
      start,
      startBackgroundJob: start,
      startHeartbeat,
      stopHeartbeat,
      verifyOffscreenLlmJob,
      wait,
      waitForBackgroundJobCompletion: wait,
      withMutationLock,
      runDirectMutatingOperation: withMutationLock,
    });
  }

  function validateDependencies(options) {
    const protocol = options.protocol;
    if (!protocol || !protocol.JOB_TYPES || !protocol.JOB_STAGES ||
        !protocol.JOB_STATUSES || !protocol.STORAGE_KEYS ||
        typeof protocol.isSupportedJobType !== "function") {
      throw new Error("JobLifecycle requires the shared message protocol.");
    }
    requireMethods(options.jobStore, "JobLifecycle jobStore", [
      "fail",
      "get",
      "hasValidRunningTimestamp",
      "isFreshRunning",
      "isStaleRunning",
      "isStartupStaleRunning",
      "progress",
      "rehydrate",
      "save",
      "setStage",
      "succeed",
    ]);
    requireMethods(options.jobHandlers, "JobLifecycle jobHandlers", ["run"]);
    requireMethods(options.offscreenClient, "JobLifecycle offscreenClient", [
      "cancel",
      "clearPersistedResult",
      "closeDocument",
      "ensureDocument",
      "loadPersistedResult",
      "ping",
    ]);
    requireMethods(options.storage, "JobLifecycle storage", ["get", "set"]);
    requireMethods(options.alarms, "JobLifecycle alarms", ["clear", "create"]);
    if (typeof options.saveLastPlan !== "function" || typeof options.saveLastReport !== "function") {
      throw new Error("JobLifecycle requires plan and report persistence callbacks.");
    }
  }

  function requireMethods(value, label, methods) {
    if (!value || methods.some((method) => typeof value[method] !== "function")) {
      throw new Error(`${label} requires ${methods.join("/")} methods.`);
    }
  }

  function createRunId(milliseconds, random) {
    return `sw-${milliseconds}-${random().toString(16).slice(2)}`;
  }

  function createAbortError(message) {
    const error = new Error(message || "The operation was aborted.");
    error.name = "AbortError";
    error.code = 20;
    return error;
  }

  function isAbortLikeError(error) {
    if (!error) return false;
    if (error.name === "AbortError") return true;
    return /aborted|cancelled by user/i.test(errorMessage(error));
  }

  function errorMessage(error) {
    return error && error.message ? error.message : String(error);
  }

  background.JobLifecycle = Object.freeze({
    DEFAULT_HEARTBEAT_ALARM,
    create,
    createAbortError,
    isAbortLikeError,
  });
})(globalThis);
