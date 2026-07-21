/* Bookmark Advisor 跨运行环境消息与持久化协议。 */

(function attachMessageProtocol(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});

  const MESSAGE_TYPES = Object.freeze({
    START_BACKGROUND_JOB: "start-background-job",
    GENERATE_AI_PLAN: "generate-ai-plan",
    REVISE_AI_PLAN: "revise-ai-plan",
    APPLY_REVIEWED_PLAN: "apply-reviewed-plan",
    GET_ACTIVE_JOB: "get-active-job",
    CANCEL_ACTIVE_JOB: "cancel-active-job",
    EXPORT_SNAPSHOT: "export-snapshot",
    LIST_FOLDERS: "list-folders",
    UNDO_LAST_EXECUTION: "undo-last-execution",
    OFFSCREEN_LLM: "offscreen-llm",
    OFFSCREEN_CANCEL: "offscreen-cancel",
    OFFSCREEN_PING: "offscreen-ping",
    OFFSCREEN_READY: "offscreen-ready",
    OFFSCREEN_KEEPALIVE: "offscreen-keepalive",
    OFFSCREEN_PROGRESS: "offscreen-progress",
    OFFSCREEN_RESULT: "offscreen-result",
    OFFSCREEN_ERROR: "offscreen-error",
  });

  const JOB_TYPES = Object.freeze({
    GENERATE_AI_PLAN: MESSAGE_TYPES.GENERATE_AI_PLAN,
    REVISE_AI_PLAN: MESSAGE_TYPES.REVISE_AI_PLAN,
    APPLY_REVIEWED_PLAN: MESSAGE_TYPES.APPLY_REVIEWED_PLAN,
  });

  const JOB_STAGES = Object.freeze({
    EXPORT: "export",
    LLM: "llm",
    SAVE: "save",
  });

  const JOB_STATUSES = Object.freeze({
    RUNNING: "running",
    SUCCEEDED: "succeeded",
    FAILED: "failed",
  });

  const STORAGE_KEYS = Object.freeze({
    LAST_PLAN: "bookmarkAdvisorLastPlan",
    LAST_REPORT: "bookmarkAdvisorLastReport",
    ACTIVE_JOB: "bookmarkAdvisorActiveJob",
    UNDO_LOG: "bookmarkAdvisorUndoLog",
    OFFSCREEN_RESULT: "bookmarkAdvisorOffscreenResult",
    EXECUTION_CHECKPOINT: "bookmarkAdvisorExecCheckpoint",
    PROGRESS: "bookmarkAdvisorProgress",
    ENCRYPTED_API_KEY: "bookmarkAdvisorOpenAIKey",
    ENCRYPTED_API_KEY_DRAFT: "bookmarkAdvisorOpenAIKeyDraft",
    LLM_SETTINGS: "bookmarkAdvisorLlmSettings",
    POPUP_DRAFT: "bookmarkAdvisorPopupDraft",
    PREFERENCES: "bookmarkAdvisorPreferences",
  });

  const supportedJobTypes = new Set(Object.values(JOB_TYPES));

  function isSupportedJobType(jobType) {
    return supportedJobTypes.has(String(jobType || ""));
  }

  root.Protocol = Object.freeze({
    MESSAGE_TYPES,
    JOB_TYPES,
    JOB_STAGES,
    JOB_STATUSES,
    STORAGE_KEYS,
    isSupportedJobType,
  });
})(globalThis);
