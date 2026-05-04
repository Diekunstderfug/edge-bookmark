importScripts("ai_planner.js");
importScripts("storage_helpers.js");

/* global ACTIVE_JOB_STORAGE_NAME, UNDO_LOG_STORAGE_NAME, BookmarkAdvisorAI, chromeStorageGet, chromeStorageSet, saveLastPlan, saveLastReport, pathWithinScope */

const EXECUTION_ORDER = [
  "rename_folder",
  "create_folder",
  "move_folder",
  "move_bookmark",
  "remove_duplicate",
];
const EXECUTABLE_STATUSES = new Set(["approved", "edited"]);
const ACTIVE_JOB_STALE_MS = 30 * 60 * 1000;
const STARTUP_JOB_STALE_MS = 60 * 1000;
const QUARANTINE_FOLDER_PATH = "/收藏夹栏/_Quarantine";
const UNDO_MOVE = "move";
const UNDO_RENAME = "rename";
const UNDO_DELETE_FOLDER = "delete_folder";
let runningJobId = "";
let _jobHeartbeatIntervalId = null;
let _jobAbortController = null;
let _startupCleanupStarted = false;

function createJobAbortController() {
  abortJobAbortController();
  _jobAbortController = new AbortController();
  return _jobAbortController;
}

function abortJobAbortController() {
  if (_jobAbortController && !_jobAbortController.signal.aborted) {
    _jobAbortController.abort();
  }
  return _jobAbortController;
}

function clearJobAbortController(controller = _jobAbortController) {
  if (_jobAbortController && controller === _jobAbortController) {
    _jobAbortController = null;
  }
}

function clearRunningJobState(jobId, controller) {
  if (runningJobId === jobId) {
    runningJobId = "";
  }
  clearJobAbortController(controller);
}

async function cleanupStaleActiveJobOnStartup() {
  if (_startupCleanupStarted) {
    return;
  }
  _startupCleanupStarted = true;
  try {
    const activeJob = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
    if (!isStartupStaleRunningJob(activeJob)) {
      return;
    }
    await failJob(activeJob, "Service worker restarted. Background job was interrupted.");
  } catch (_error) {
    // 启动清理失败不应影响服务工作线程加载。
  }
}

function isAbortLikeError(error) {
  if (!error) {
    return false;
  }
  if (error.name === "AbortError") {
    return true;
  }
  const message = error.message || String(error);
  return /aborted|cancelled by user/i.test(message);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message) {
    return undefined;
  }

  if (message.type === "apply-reviewed-plan") {
    runDirectMutatingOperation("apply-reviewed-plan", () => executeReviewedPlan(message.plan, message.focusPath || "", reportProgress))
      .then((result) => sendResponse(result))
      .catch((error) => {
        reportProgress(`Execution failed: ${error.message || String(error)}`);
        sendResponse({
          succeeded: [],
          failures: [{ actionType: "plan", error: error.message || String(error) }],
          executed_at: new Date().toISOString(),
        });
      });
    return true;
  }

  if (message.type === "export-snapshot") {
    exportCurrentSnapshot()
      .then((result) => sendResponse(result))
      .catch((error) => {
        sendResponse({ error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "generate-ai-plan") {
    runDirectMutatingOperation("generate-ai-plan", () => generateAiReviewedPlan(message.options || {}, reportProgress))
      .then((result) => sendResponse(result))
      .catch((error) => {
        reportProgress(`AI planning failed: ${error.message || String(error)}`);
        sendResponse({ error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "revise-ai-plan") {
    runDirectMutatingOperation("revise-ai-plan", () => reviseAiReviewedPlan(message.plan, message.options || {}, reportProgress))
      .then((result) => sendResponse(result))
      .catch((error) => {
        reportProgress(`AI plan revision failed: ${error.message || String(error)}`);
        sendResponse({ error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "start-background-job") {
    startBackgroundJob(message.job_type, message.payload || {})
      .then((response) => sendResponse(response))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  if (message.type === "get-active-job") {
    getActiveJobForPopup()
      .then((job) => sendResponse({ job: job || null }))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  if (message.type === "list-folders") {
    listFolders()
      .then((folders) => sendResponse({ folders }))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  if (message.type === "undo-last-execution") {
    undoLastExecution()
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  if (message.type === "cancel-active-job") {
    cancelActiveJob()
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  return undefined;
});

async function startBackgroundJob(jobType, payload) {
  if (!["generate-ai-plan", "revise-ai-plan", "apply-reviewed-plan"].includes(jobType)) {
    return { error: `Unsupported background job type: ${jobType}` };
  }
  if (runningJobId) {
    return { error: "Background job already running in this service worker." };
  }
  runningJobId = "starting";
  let existingJob;
  try {
    existingJob = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  } catch (error) {
    runningJobId = "";
    throw error;
  }
  if (isFreshRunningJob(existingJob)) {
    runningJobId = "";
    return { error: `Background job already running: ${existingJob.type}` };
  }
  if (isStaleRunningJob(existingJob)) {
    try {
      await failJob(existingJob, "Background job timed out before completion.");
    } catch (error) {
      runningJobId = "";
      throw error;
    }
  }
  const jobAbortController = createJobAbortController();
  const job = {
    id: `job-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    type: jobType,
    status: "running",
    progress: "Starting background job...",
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  runningJobId = job.id;
  void saveActiveJob(job).then(() => runBackgroundJob(job, payload, jobAbortController)).catch((error) => {
    void failJob(job, error.message || String(error));
    clearRunningJobState(job.id, jobAbortController);
  });
  return { job };
}

async function runDirectMutatingOperation(jobType, callback) {
  if (runningJobId) {
    throw new Error(`Background job already running: ${jobType}`);
  }
  runningJobId = `direct-${jobType}-${Date.now()}`;
  try {
    const existingJob = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
    if (isFreshRunningJob(existingJob)) {
      throw new Error(`Background job already running: ${existingJob.type}`);
    }
    return await callback();
  } finally {
    if (runningJobId.startsWith(`direct-${jobType}-`)) {
      runningJobId = "";
    }
  }
}

async function getActiveJobForPopup() {
  const job = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  if (isStaleRunningJob(job)) {
    const failed = await failJob(job, "Background job timed out before completion.");
    return failed;
  }
  return job || null;
}

function isFreshRunningJob(job) {
  return !!job && job.status === "running" && !isStaleRunningJob(job);
}

function isStartupStaleRunningJob(job) {
  if (!job || job.status !== "running") {
    return false;
  }
  const effectiveAt = Date.parse(job.updated_at || job.started_at || "");
  if (!Number.isFinite(effectiveAt)) {
    return true;
  }
  const now = Date.now();
  return now - effectiveAt > STARTUP_JOB_STALE_MS;
}

function isStaleRunningJob(job) {
  if (!job || job.status !== "running") {
    return false;
  }
  const updatedAt = Date.parse(job.updated_at || job.started_at || "");
  return !Number.isFinite(updatedAt) || Date.now() - updatedAt > ACTIVE_JOB_STALE_MS;
}

async function failJob(job, message) {
  stopJobHeartbeat();
  const current = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  if (!current || current.id !== job.id) {
    return current || null;
  }
  if (current.status !== "running") {
    return current;
  }
  const cancellationRequestedAt = message === "Cancelled by user."
    ? job.cancellation_requested_at || current.cancellation_requested_at || new Date().toISOString()
    : job.cancellation_requested_at || current.cancellation_requested_at || "";
  const failed = {
    ...job,
    status: "failed",
    ...(cancellationRequestedAt ? { cancellation_requested_at: cancellationRequestedAt } : {}),
    progress: message,
    error: message,
    updated_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  };
  await saveActiveJob(failed);
  return failed;
}

async function cancelActiveJob() {
  abortJobAbortController();
  stopJobHeartbeat();
  const activeJob = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  if (activeJob && activeJob.status === "running") {
    await failJob({ ...activeJob, cancellation_requested_at: new Date().toISOString() }, "Cancelled by user.");
  }
  await Promise.all([
    chromeStorageSet("bookmarkAdvisorProgress", null).catch(() => {}),
  ]);
  return { cancelled: true };
}

async function runBackgroundJob(job, payload, jobAbortController) {
  startJobHeartbeat(job);
  try {
    const onProgress = (message) => jobProgress(job, message);
    if (job.type === "generate-ai-plan") {
      const result = await generateAiReviewedPlan({ ...(payload.options || {}), signal: jobAbortController.signal }, onProgress);
      await finishJob(job, result, "AI plan generated.");
      return;
    }
    if (job.type === "revise-ai-plan") {
      const result = await reviseAiReviewedPlan(payload.plan, { ...(payload.options || {}), signal: jobAbortController.signal }, onProgress);
      await finishJob(job, result, "AI plan revision complete.");
      return;
    }
    if (job.type === "apply-reviewed-plan") {
      const result = await executeReviewedPlan(payload.plan, payload.focusPath || "", onProgress, { id: job.id });
      await finishJob(job, result, "Execution complete.");
    }
  } catch (error) {
    if (isAbortLikeError(error)) {
      await failJob(job, "Cancelled by user.");
      return;
    }
    throw error;
  } finally {
    stopJobHeartbeat();
    clearRunningJobState(job.id, jobAbortController);
  }
}

async function finishJob(job, result, progress) {
  stopJobHeartbeat();
  const current = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  if (!current || current.id !== job.id) {
    return current || null;
  }
  if (current.status !== "running") {
    return current;
  }
  await saveActiveJob({
    ...job,
    status: "succeeded",
    progress,
    result,
    updated_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  });
}

function saveActiveJob(job) {
  return chromeStorageSet(globalThis.ACTIVE_JOB_STORAGE_NAME, job);
}

function startJobHeartbeat(job, intervalMs = 25000) {
  stopJobHeartbeat();
  if (!job || !job.id) {
    return;
  }
  _jobHeartbeatIntervalId = setInterval(() => {
    void jobHeartbeatTick(job).catch(() => {
      stopJobHeartbeat();
    });
  }, intervalMs);
}

function stopJobHeartbeat() {
  if (_jobHeartbeatIntervalId !== null) {
    clearInterval(_jobHeartbeatIntervalId);
    _jobHeartbeatIntervalId = null;
  }
}

async function jobHeartbeatTick(job) {
  const current = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  if (!current || current.id !== job.id || current.status !== "running") {
    stopJobHeartbeat();
    return;
  }
  await saveActiveJob({
    ...current,
    updated_at: new Date().toISOString(),
  });
}

function jobProgress(job, message) {
  return chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME).then((current) => {
    if (!current || current.id !== job.id || current.status !== "running") {
      return;
    }
    const updated = {
      ...job,
      status: "running",
      progress: message,
      updated_at: new Date().toISOString(),
    };
    return Promise.all([
      saveActiveJob(updated),
      chromeStorageSet("bookmarkAdvisorProgress", { message, updated_at: Date.now() }),
    ]);
  });
}

async function generateAiReviewedPlan(options, onProgress = reportProgress) {
  await onProgress("Exporting current bookmarks...");
  const snapshot = await exportCurrentSnapshot();
  await onProgress("Calling LLM endpoint...");
  const result = await BookmarkAdvisorAI.generateReviewedPlan({
    ...options,
    onProgress,
    snapshot,
  });
  await saveLastPlan(result.reviewed_plan);
  await onProgress("AI plan generated and saved for popup restore.");
  return result;
}

async function reviseAiReviewedPlan(plan, options, onProgress = reportProgress) {
  if (!plan || typeof plan !== "object" || !Array.isArray(plan.actions)) {
    throw new Error("Load a reviewed plan before asking the LLM to revise it.");
  }
  await onProgress("Exporting current bookmarks...");
  const snapshot = await exportCurrentSnapshot();
  await onProgress("Calling LLM endpoint to revise current plan...");
  const result = await BookmarkAdvisorAI.reviseReviewedPlan({
    ...options,
    existingPlan: plan,
    onProgress,
    snapshot,
  });
  await saveLastPlan(result.reviewed_plan);
  await onProgress("AI plan revision saved for popup restore.");
  return result;
}

async function executeReviewedPlan(plan, focusPath, onProgress = reportProgress, jobContext = null) {
  validateExecutablePlan(plan);

  const executionId = `exec-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const grouped = new Map(EXECUTION_ORDER.map((actionType) => [actionType, []]));
  for (const action of plan.actions) {
    if (
      !EXECUTABLE_ACTIONS().has(action.action_type) ||
      !EXECUTABLE_STATUSES.has(resolveActionStatus(plan, action))
    ) {
      continue;
    }
    grouped.get(action.action_type).push(action);
  }

  const succeeded = [];
  const failures = [];
  const executedAt = new Date().toISOString();
  const totalActions = EXECUTION_ORDER.reduce(
    (sum, actionType) => sum + grouped.get(actionType).length, 0,
  );

  await assertJobNotCancelled(jobContext);
  await onProgress("Starting plan execution...");

  for (const actionType of EXECUTION_ORDER) {
    for (const action of grouped.get(actionType)) {
      await assertJobNotCancelled(jobContext);
      try {
        await applyAction(action, focusPath, executionId);
        succeeded.push({
          actionId: action.action_id || "",
          actionType,
          target: action.to_path || action.target_path || locatorLabel(action),
          result: "succeeded",
          executed_at: executedAt,
        });
      } catch (error) {
        failures.push({
          actionId: action.action_id || "",
          actionType,
          target: action.to_path || action.target_path || locatorLabel(action),
          error: error.message || String(error),
          executed_at: executedAt,
        });
      }
      await onProgress(`Executing action ${succeeded.length + failures.length}/${totalActions}...`);
      await assertJobNotCancelled(jobContext);
    }
  }

  const report = {
    plan_version: plan.plan_version || "2",
    plan_kind: plan.plan_kind || "reviewed",
    executed_at: executedAt,
    succeeded,
    failures,
  };
  await saveLastReport(report);
  await onProgress("Execution report saved for popup restore.");
  return report;
}

function createCancelledByUserError() {
  const error = new Error("Cancelled by user.");
  error.name = "AbortError";
  return error;
}

async function assertJobNotCancelled(jobContext) {
  if (!jobContext || !jobContext.id) {
    return;
  }
  if (await isJobCancellationRequested(jobContext.id)) {
    throw createCancelledByUserError();
  }
}

async function isJobCancellationRequested(jobId) {
  if (!jobId) {
    return false;
  }
  const current = await chromeStorageGet(globalThis.ACTIVE_JOB_STORAGE_NAME);
  if (!current || current.id !== jobId) {
    return true;
  }
  if (current.cancellation_requested_at) {
    return true;
  }
  return current.status !== "running";
}

void cleanupStaleActiveJobOnStartup();

async function exportCurrentSnapshot() {
  assertBookmarkApiAvailable();
  const tree = await bookmarkCall("getTree");
  const folders = [];
  const bookmarks = [];
  const root = tree[0];
  walkTree(root, "", folders, bookmarks);
  return {
    snapshot_version: "1",
    source: "edge-extension",
    source_path: "edge-bookmarks-api",
    created_at: new Date().toISOString(),
    folders,
    bookmarks,
  };
}

async function listFolders() {
  const snapshot = await exportCurrentSnapshot();
  return (snapshot.folders || [])
    .slice()
    .sort((a, b) => a.path.localeCompare(b.path, "zh-Hans-CN"));
}

function walkTree(node, parentPath, folders, bookmarks) {
  const isFolder = !node.url;
  const path = node.title ? `${parentPath}/${node.title}` : parentPath;

  if (isFolder && node.id !== "0") {
    const childFolders = (node.children || []).filter((child) => !child.url).length;
    const childBookmarks = (node.children || []).filter((child) => !!child.url).length;
    folders.push({
      id: node.id,
      name: node.title || "",
      path,
      parent_path: parentPath || null,
      root_key: parentPath ? "" : node.title || "",
      depth: parentPath ? path.split("/").filter(Boolean).length - 1 : 0,
      bookmark_count: childBookmarks,
      subfolder_count: childFolders,
      folder_type: node.folderType || "",
      syncing: typeof node.syncing === "boolean" ? node.syncing : null,
    });
  }

  for (const child of node.children || []) {
    if (child.url) {
      bookmarks.push({
        id: child.id,
        title: child.title || "",
        url: child.url || "",
        normalized_url: normalizeUrl(child.url || ""),
        domain: extractDomain(child.url || ""),
        folder_id: node.id,
        folder_path: path,
        top_level_folder: path.split("/").filter(Boolean)[1] || "",
        root_key: path.split("/").filter(Boolean)[0] || "",
        path: `${path}/${child.title || ""}`,
        depth: path.split("/").filter(Boolean).length,
      });
    } else {
      walkTree(child, path, folders, bookmarks);
    }
  }
}

function validateExecutablePlan(plan) {
  if (!plan || typeof plan !== "object" || !Array.isArray(plan.actions)) {
    throw new Error("Plan must contain an actions array.");
  }
  for (const action of plan.actions) {
    if (!action.action_type) {
      throw new Error("Action missing action_type");
    }
    if (action.action_type === "keep_for_review") {
      continue;
    }
    if (!EXECUTABLE_ACTIONS().has(action.action_type)) {
      throw new Error(`Unknown action_type: ${action.action_type}`);
    }
  }
}

function checkActionPolicy(action, focusPath) {
  if (!focusPath) {
    return { allowed: true };
  }
  const type = action.action_type;

  switch (type) {
    case "create_folder": {
      const targetPath = action.target_path || "";
      if (!pathWithinScope(targetPath, focusPath)) {
        return { allowed: false, reason: `create_folder target ${targetPath} is outside focus scope ${focusPath}` };
      }
      return { allowed: true };
    }
    case "move_bookmark":
    case "move_folder": {
      const fromPath = action.from_path || "";
      const toPath = action.to_path || "";
      if (!pathWithinScope(fromPath, focusPath)) {
        return { allowed: false, reason: `${type} source ${fromPath} is outside focus scope ${focusPath}` };
      }
      if (!pathWithinScope(toPath, focusPath)) {
        return { allowed: false, reason: `${type} destination ${toPath} is outside focus scope ${focusPath}` };
      }
      return { allowed: true };
    }
    case "rename_folder": {
      const fromPath = action.from_path || "";
      if (!pathWithinScope(fromPath, focusPath)) {
        return { allowed: false, reason: `rename_folder path ${fromPath} is outside focus scope ${focusPath}` };
      }
      return { allowed: true };
    }
    case "remove_duplicate":
      return { allowed: true };
    default:
      return { allowed: false, reason: `Unknown action_type: ${type}` };
  }
}

async function recordUndo(executionId, action, before, undoType) {
  const entry = {
    undo_id: `undo-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    execution_id: executionId,
    action_id: action.action_id || "",
    action_type: action.action_type,
    before,
    undo_action: undoType === UNDO_DELETE_FOLDER
      ? { type: UNDO_DELETE_FOLDER, id: before.id }
      : undoType === UNDO_RENAME
        ? { type: UNDO_RENAME, id: before.id, title: before.title }
        : { type: UNDO_MOVE, id: before.id, parentId: before.parentId },
    timestamp: new Date().toISOString(),
  };
  const log = (await chromeStorageGet(UNDO_LOG_STORAGE_NAME)) || [];
  log.push(entry);
  const execIds = [...new Set(log.map((e) => e.execution_id))];
  if (execIds.length > 20) {
    const staleIds = new Set(execIds.slice(0, execIds.length - 20));
    const trimmed = log.filter((e) => !staleIds.has(e.execution_id));
    await chromeStorageSet(UNDO_LOG_STORAGE_NAME, trimmed);
  } else {
    await chromeStorageSet(UNDO_LOG_STORAGE_NAME, log);
  }
}

async function undoLastExecution() {
  const log = (await chromeStorageGet(UNDO_LOG_STORAGE_NAME)) || [];
  if (log.length === 0) {
    return { undone: false, reason: "No undo log entries found." };
  }

  const lastExecutionId = log[log.length - 1].execution_id;
  const entries = [];
  const remaining = [];
  for (const e of log) {
    (e.execution_id === lastExecutionId ? entries : remaining).push(e);
  }

  const undone = [];
  const undoFailures = [];

  for (const entry of entries.slice().reverse()) {
    try {
      const ua = entry.undo_action;
      if (ua.type === UNDO_MOVE) {
        await bookmarkCall("move", ua.id, { parentId: ua.parentId });
      } else if (ua.type === UNDO_RENAME) {
        await bookmarkCall("update", ua.id, { title: ua.title });
      } else if (ua.type === UNDO_DELETE_FOLDER) {
        await bookmarkCall("remove", ua.id);
      }
      undone.push(entry.undo_id);
    } catch (error) {
      undoFailures.push({
        undo_id: entry.undo_id,
        error: error.message || String(error),
      });
    }
  }

  await chromeStorageSet(UNDO_LOG_STORAGE_NAME, remaining);
  return {
    undone: true,
    execution_id: lastExecutionId,
    count: undone.length,
    failures: undoFailures,
    hasMore: remaining.length > 0,
  };
}

async function applyAction(action, focusPath, executionId) {
  const policy = checkActionPolicy(action, focusPath);
  if (!policy.allowed) {
    throw new Error(`Policy blocked: ${policy.reason}`);
  }

  switch (action.action_type) {
    case "create_folder": {
      if (!action.target_path) {
        throw new Error("create_folder requires target_path");
      }
      const createdId = await ensureFolderPath(action.target_path);
      if (executionId) {
        await recordUndo(executionId, action, { id: createdId, title: action.target_path.split("/").pop() }, UNDO_DELETE_FOLDER);
      }
      return;
    }
    case "rename_folder": {
      if (!action.to_name) {
        throw new Error("rename_folder requires to_name");
      }
      const folderId = await resolveFolderId(action);
      if (!folderId) {
        throw new Error("Could not resolve folder by locator");
      }
      const [folderNode] = await bookmarkCall("get", folderId);
      if (executionId) {
        await recordUndo(executionId, action, { id: folderId, title: folderNode.title }, UNDO_RENAME);
      }
      await bookmarkCall("update", folderId, { title: action.to_name });
      return;
    }
    case "move_folder": {
      if (!action.to_path) {
        throw new Error("move_folder requires to_path");
      }
      const srcFolderId = await resolveFolderId(action);
      if (!srcFolderId) {
        throw new Error("Could not resolve folder by locator");
      }
      const fromPath = expectedFolderPath(action);
      if (fromPath && (action.to_path === fromPath || action.to_path.startsWith(`${fromPath}/`))) {
        throw new Error("move_folder destination must not be the source folder or its descendant");
      }
      const [srcNode] = await bookmarkCall("get", srcFolderId);
      const destFolderId = await ensureFolderPath(action.to_path);
      if (executionId) {
        await recordUndo(executionId, action, { id: srcFolderId, parentId: srcNode.parentId, title: srcNode.title }, UNDO_MOVE);
      }
      await bookmarkCall("move", srcFolderId, { parentId: destFolderId });
      return;
    }
    case "move_bookmark": {
      if (!action.to_path) {
        throw new Error("move_bookmark requires to_path");
      }
      const bookmarkId = await resolveBookmarkId(action);
      if (!bookmarkId) {
        throw new Error("Could not resolve bookmark by locator");
      }
      const [node] = await bookmarkCall("get", bookmarkId);
      const destinationFolderId = await ensureFolderPath(action.to_path);
      if (executionId) {
        await recordUndo(executionId, action, { id: bookmarkId, parentId: node.parentId, title: node.title, url: node.url || null }, UNDO_MOVE);
      }
      await bookmarkCall("move", bookmarkId, { parentId: destinationFolderId });
      return;
    }
    case "remove_duplicate": {
      const dupBookmarkId = await resolveBookmarkId(action);
      if (!dupBookmarkId) {
        throw new Error("Could not resolve bookmark by locator");
      }
      const [dupNode] = await bookmarkCall("get", dupBookmarkId);
      const quarantineFolderId = await ensureFolderPath(QUARANTINE_FOLDER_PATH);
      if (executionId) {
        await recordUndo(executionId, action, { id: dupBookmarkId, parentId: dupNode.parentId, title: dupNode.title, url: dupNode.url || null }, UNDO_MOVE);
      }
      await bookmarkCall("move", dupBookmarkId, { parentId: quarantineFolderId });
      return;
    }
    default:
      throw new Error(`Unsupported action_type: ${action.action_type}`);
  }
}

async function resolveFolderId(action) {
  const locator = action.folder_locator || {};
  const candidateId = locator.id || action.folder_id || "";
  if (candidateId) {
    let nodes = null;
    try {
      nodes = await bookmarkCall("get", candidateId);
    } catch (_error) {
      nodes = null;
    }
    if (nodes && nodes[0]) {
      if (!nodes[0].url && await folderNodeMatchesLocator(nodes[0], action)) {
        return candidateId;
      }
      throw new Error("Folder locator id did not match the current folder metadata");
    }
  }

  const tree = await bookmarkCall("getTree");
  const path = locator.path || action.from_path || "";
  if (!path) {
    return "";
  }
  return resolvePathToFolderId(tree[0], path);
}

async function resolveBookmarkId(action) {
  const locator = action.bookmark_locator || {};
  const candidateId = locator.id || action.bookmark_id || "";
  if (candidateId) {
    let nodes = null;
    try {
      nodes = await bookmarkCall("get", candidateId);
    } catch (_error) {
      nodes = null;
    }
    if (nodes && nodes[0]) {
      if (nodes[0].url && await bookmarkNodeMatchesLocator(nodes[0], action)) {
        return candidateId;
      }
      throw new Error("Bookmark locator id did not match the current bookmark metadata");
    }
  }

  const searchUrl = locator.url || "";
  if (searchUrl) {
    const matches = await bookmarkSearch({ url: searchUrl });
    for (const node of matches) {
      if ((locator.title ? node.title === locator.title : true) &&
          (locator.folder_path ? await nodeParentPath(node.parentId) === locator.folder_path : true)) {
        return node.id;
      }
    }
  }

  const allMatches = await bookmarkSearch({ title: locator.title || "" });
  for (const node of allMatches) {
    if (!node.url) {
      continue;
    }
    const normalizedNodeUrl = normalizeUrl(node.url || "");
    if (
      (locator.normalized_url ? normalizedNodeUrl === locator.normalized_url : true) &&
      (locator.folder_path ? await nodeParentPath(node.parentId) === locator.folder_path : true)
    ) {
      return node.id;
    }
  }
  return "";
}

async function bookmarkNodeMatchesLocator(node, action) {
  const locator = action.bookmark_locator || {};
  if (locator.title && node.title !== locator.title) {
    return false;
  }
  if (locator.url && node.url !== locator.url) {
    return false;
  }
  if (locator.normalized_url && normalizeUrl(node.url || "") !== locator.normalized_url) {
    return false;
  }
  if (locator.folder_path && await nodeParentPath(node.parentId) !== locator.folder_path) {
    return false;
  }
  return true;
}

async function folderNodeMatchesLocator(node, action) {
  const locator = action.folder_locator || {};
  if (locator.name && node.title !== locator.name) {
    return false;
  }
  const expectedPath = expectedFolderPath(action);
  if (expectedPath) {
    const parentPath = await nodeParentPath(node.parentId);
    const actualPath = `${parentPath}/${node.title || ""}`.replace(/\/+/g, "/");
    return actualPath === expectedPath;
  }
  return true;
}

function expectedFolderPath(action) {
  const locator = action.folder_locator || {};
  return locator.path || action.from_path || "";
}

async function nodeParentPath(parentId) {
  if (!parentId) {
    return "";
  }
  const chain = [];
  let currentId = parentId;
  while (currentId && currentId !== "0") {
    const nodes = await bookmarkCall("get", currentId);
    if (!nodes || !nodes[0]) {
      break;
    }
    const node = nodes[0];
    chain.unshift(node.title || "");
    currentId = node.parentId;
  }
  return `/${chain.filter(Boolean).join("/")}`;
}

async function ensureFolderPath(folderPath) {
  const parts = folderPath.split("/").filter(Boolean);
  if (parts.length === 0) {
    throw new Error("folder path must not be empty");
  }

  const tree = await bookmarkCall("getTree");
  const root = tree[0];
  let current = (root.children || []).find((node) => node.title === parts[0]);
  if (!current) {
    throw new Error(`Could not resolve root folder: ${parts[0]}`);
  }

  for (const part of parts.slice(1)) {
    let next = (current.children || []).find(
      (node) => !node.url && node.title === part,
    );
    if (!next) {
      const refreshedChildren = await bookmarkCall("getChildren", current.id);
      next = (refreshedChildren || []).find(
        (node) => !node.url && node.title === part,
      );
    }
    if (!next) {
      next = await bookmarkCall("create", {
        parentId: current.id,
        title: part,
      });
    }
    current = next;
  }

  return current.id;
}

function resolvePathToFolderId(root, folderPath) {
  const parts = folderPath.split("/").filter(Boolean);
  let current = (root.children || []).find((node) => node.title === parts[0]);
  if (!current) {
    return "";
  }
  for (const part of parts.slice(1)) {
    current = (current.children || []).find((node) => !node.url && node.title === part);
    if (!current) {
      return "";
    }
  }
  return current.id;
}

function bookmarkCall(method, ...args) {
  assertBookmarkApiAvailable();
  return new Promise((resolve, reject) => {
    chrome.bookmarks[method](...args, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(result);
    });
  });
}

function assertBookmarkApiAvailable() {
  if (!chrome.bookmarks || typeof chrome.bookmarks.getTree !== "function") {
    throw new Error("Bookmark permission is unavailable. Enable the extension's Bookmarks permission, then reload the extension.");
  }
}

function bookmarkSearch(query) {
  return new Promise((resolve, reject) => {
    chrome.bookmarks.search(query, (results) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(results || []);
    });
  });
}

function EXECUTABLE_ACTIONS() {
  return new Set(EXECUTION_ORDER);
}

function locatorLabel(action) {
  const bookmark = action.bookmark_locator || {};
  const folder = action.folder_locator || {};
  return bookmark.title || bookmark.id || action.bookmark_id || folder.path || folder.id || action.folder_id || "";
}

/** Parity with Python bookmark_advisor.utils.normalize_url — same steps, same order. */
function normalizeUrl(url) {
  if (!url) return "";
  try {
    var parsed = new URL(url);
    var scheme = parsed.protocol.slice(0, -1);
    var host = parsed.host;
    var path = decodeURIComponent(parsed.pathname);
    if (
      (parsed.protocol === "http:" && (parsed.port === "80" || parsed.port === "")) ||
      (parsed.protocol === "https:" && (parsed.port === "443" || parsed.port === ""))
    ) {
      host = parsed.hostname;
    }
    if (path.length > 1) {
      path = path.replace(/\/+$/, "") || "/";
    }
    var kept = [];
    for (var entry of parsed.searchParams.entries()) {
      var key = entry[0], value = entry[1];
      var lowered = key.toLowerCase();
      if (
        lowered === "spm" ||
        lowered === "ref" ||
        lowered === "fbclid" ||
        lowered === "gclid" ||
        lowered === "_" ||
        lowered.startsWith("utm_")
      ) {
        continue;
      }
      if (value === "") {
        continue;
      }
      kept.push([key, value]);
    }
    kept.sort(function (a, b) {
      if (a[0] < b[0]) return -1;
      if (a[0] > b[0]) return 1;
      if (a[1] < b[1]) return -1;
      if (a[1] > b[1]) return 1;
      return 0;
    });
    var query = kept
      .map(function (pair) { return encodeURIComponent(pair[0]) + "=" + encodeURIComponent(pair[1]); })
      .join("&");
    return scheme + "://" + host + path + (query ? "?" + query : "");
  } catch (_error) {
    return url || "";
  }
}

function extractDomain(url) {
  try {
    return new URL(url).host.toLowerCase();
  } catch (_error) {
    return "";
  }
}

function resolveActionStatus(plan, action) {
  if (action.status) {
    return action.status;
  }
  return plan.plan_version === "1" ? "approved" : "proposed";
}

function reportProgress(message) {
  return chromeStorageSet("bookmarkAdvisorProgress", { message, updated_at: Date.now() });
}
