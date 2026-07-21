importScripts(
  "shared/message_protocol.js",
  "shared/plan_schema.js",
  "shared/ai_endpoint.js",
  "shared/path_utils.js",
  "shared/storage.js",
  "action_constants.js",
  "storage_helpers.js",
  "background/bookmark_api.js",
  "background/snapshot_export.js",
  "background/bookmark_tree.js",
  "background/execution_policy.js",
  "background/undo_log.js",
  "background/action_handlers.js",
  "background/plan_executor.js",
  "background/job_store.js",
  "background/offscreen_client.js",
  "background/job_handlers.js",
  "background/job_lifecycle.js",
  "background/message_router.js",
  "ai/fast_rules.js",
  "ai/snapshot_model.js",
  "ai/batching.js",
  "ai/prompt_codec.js",
  "ai/response_codec.js",
  "ai/provider_client.js",
  "ai/plan_compiler.js",
  "ai_planner.js",
);

/* global BookmarkAdvisor, chromeStorageGet, saveLastPlan, saveLastReport */

const PROTOCOL = BookmarkAdvisor.Protocol;
const BACKGROUND = BookmarkAdvisor.Background;
const STORAGE = BookmarkAdvisor.Storage;

const BOOKMARK_API = BACKGROUND.BookmarkApi;
const BOOKMARK_UTILS = BACKGROUND.BookmarkUtils;
const SNAPSHOT_EXPORT = BACKGROUND.SnapshotExport;
const EXECUTION_POLICY = BACKGROUND.ExecutionPolicy;
const BOOKMARK_TREE = BACKGROUND.BookmarkTree.create({
  api: BOOKMARK_API,
  normalizeUrl: BOOKMARK_UTILS.normalizeUrl,
});
const UNDO_LOG = BACKGROUND.UndoLog.create({
  storage: STORAGE,
  bookmarkApi: BOOKMARK_API,
  bookmarkTree: BOOKMARK_TREE,
});
const ACTION_HANDLERS = BACKGROUND.ActionHandlers.create({
  bookmarkApi: BOOKMARK_API,
  bookmarkTree: BOOKMARK_TREE,
  executionPolicy: EXECUTION_POLICY,
  undoLog: UNDO_LOG,
});
const PLAN_EXECUTOR = BACKGROUND.PlanExecutor.create({
  planSchema: BookmarkAdvisor.PlanSchema,
  executionPolicy: EXECUTION_POLICY,
  actionHandlers: ACTION_HANDLERS,
  bookmarkApi: BOOKMARK_API,
  bookmarkTree: BOOKMARK_TREE,
  checkpointStore: {
    save: (checkpoint) => STORAGE.set(PROTOCOL.STORAGE_KEYS.EXECUTION_CHECKPOINT, checkpoint),
    clear: () => STORAGE.set(PROTOCOL.STORAGE_KEYS.EXECUTION_CHECKPOINT, null),
  },
  saveReport: saveLastReport,
  locatorLabel,
});

const JOB_STORE = BACKGROUND.JobStore.create({
  storage: STORAGE,
  protocol: PROTOCOL,
});
const OFFSCREEN_CLIENT = BACKGROUND.OffscreenClient.create({
  chrome,
  protocol: PROTOCOL,
  storage: STORAGE,
  aiFacade: globalThis.BookmarkAdvisorAI,
  aiEndpoint: BookmarkAdvisor.AIEndpoint,
  activeJobStaleMs: JOB_STORE.ACTIVE_JOB_STALE_MS,
});
const JOB_HANDLERS = BACKGROUND.JobHandlers.create({
  protocol: PROTOCOL,
  snapshotExport: SNAPSHOT_EXPORT,
  runLlm: runLlmTransport,
  executePlan: executePlanForJob,
  saveLastPlan,
  log: swLog,
});

/**
 * ActiveJob 持久化结构：
 * { id, type, status, stage?, progress, owner_run_id, started_at, updated_at,
 *   stage_started_at?, finished_at?, error?, cancellation_requested_at?, result_summary? }
 * 完整 result 不落入 ActiveJob；popup 读取时由 JobStore 从 last plan/report 补全。
 */
const SERVICE_WORKER_RUN_ID = `sw-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const JOB_LIFECYCLE = BACKGROUND.JobLifecycle.create({
  protocol: PROTOCOL,
  jobStore: JOB_STORE,
  jobHandlers: JOB_HANDLERS,
  offscreenClient: OFFSCREEN_CLIENT,
  storage: STORAGE,
  alarms: chrome.alarms,
  saveLastPlan,
  saveLastReport,
  runId: SERVICE_WORKER_RUN_ID,
  log: swLog,
});
const MESSAGE_ROUTER = BACKGROUND.MessageRouter.create({
  protocol: PROTOCOL,
  lifecycle: JOB_LIFECYCLE,
  snapshotExport: SNAPSHOT_EXPORT,
  undoLastExecution: () => UNDO_LOG.undoLastExecution(),
  handleLateOffscreenCompletion: JOB_LIFECYCLE.consumeCompletionMessage,
  loadLastPlan: () => chromeStorageGet(globalThis.LAST_PLAN_STORAGE_NAME),
  logger: reportProgress,
});

chrome.runtime.onMessage.addListener(MESSAGE_ROUTER);
chrome.alarms.onAlarm.addListener((alarm) => {
  void JOB_LIFECYCLE.handleAlarm(alarm).catch(() => {});
});
void JOB_LIFECYCLE.cleanupOnStartup();

function runLlmTransport(job, mode, payload, controller) {
  return OFFSCREEN_CLIENT.run(job, mode, payload, {
    controller,
    onProgress: (message) => JOB_STORE.progress(job, message),
  });
}

function executePlanForJob(plan, focusPath, onProgress, jobContext) {
  return PLAN_EXECUTOR.execute(plan, {
    focusPath,
    onProgress,
    shouldCancel: () => JOB_LIFECYCLE.isCancellationRequested(jobContext && jobContext.id),
  });
}

function locatorLabel(action) {
  const bookmark = action.bookmark_locator || {};
  const folder = action.folder_locator || {};
  return bookmark.title || bookmark.id || action.bookmark_id ||
    folder.path || folder.id || action.folder_id || "";
}

function reportProgress(message) {
  return STORAGE.set(PROTOCOL.STORAGE_KEYS.PROGRESS, {
    message,
    updated_at: Date.now(),
  });
}

function swLog(...args) {
  if (typeof process === "undefined") {
    // eslint-disable-next-line no-console
    console.log(...args);
  }
}

// 保留现有 Node 回归测试与外部诊断所用的窄兼容面。
if (typeof process !== "undefined") {
  globalThis.__bookmarkAdvisorTestHooks = {
    hasOffscreenDocument: OFFSCREEN_CLIENT.hasDocument,
    supportsOffscreenProtocol: OFFSCREEN_CLIENT.supports,
    setJobStage: JOB_LIFECYCLE.setStage,
    jobProgress: JOB_LIFECYCLE.progress,
    jobHeartbeatTick: JOB_LIFECYCLE.heartbeatTick,
    finishJob: JOB_LIFECYCLE.finish,
    failJob: JOB_LIFECYCLE.fail,
  };
}

globalThis.BookmarkAdvisorSW = {
  _offscreenHardTimeoutMs: OFFSCREEN_CLIENT.hardTimeoutMs,
  _ACTIVE_JOB_STALE_MS: JOB_STORE.ACTIVE_JOB_STALE_MS,
  _evictOrphanOffscreenJob: OFFSCREEN_CLIENT.evictOrphan,
};
