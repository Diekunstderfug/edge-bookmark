if (
  (!globalThis.BookmarkAdvisor || !globalThis.BookmarkAdvisor.AIEndpoint) &&
  typeof require === "function"
) {
  require("./shared/ai_endpoint.js");
}
if (typeof require === "function") {
  const popupModules = globalThis.BookmarkAdvisor.Popup || {};
  if (!popupModules.RuntimeClient) require("./popup/runtime_client.js");
  if (!popupModules.JobState) require("./popup/job_state.js");
  if (!popupModules.Secrets) require("./popup/secrets.js");
  if (!popupModules.SettingsStore) require("./popup/settings_store.js");
  if (!popupModules.I18n) require("./popup/i18n.js");
  if (!popupModules.PlanView) require("./popup/plan_view.js");
}

const POPUP_PROTOCOL = globalThis.BookmarkAdvisor.Protocol;
const POPUP_ENDPOINT = globalThis.BookmarkAdvisor.AIEndpoint;
const POPUP_MESSAGES = POPUP_PROTOCOL.MESSAGE_TYPES;
const POPUP_JOB_TYPES = POPUP_PROTOCOL.JOB_TYPES;
const POPUP_JOB_STATUSES = POPUP_PROTOCOL.JOB_STATUSES;
const POPUP_RUNTIME_CLIENT = globalThis.BookmarkAdvisor.Popup.RuntimeClient.create({
  chrome,
  protocol: POPUP_PROTOCOL,
});
const POPUP_SECRETS = globalThis.BookmarkAdvisor.Popup.Secrets.create({
  chrome,
  crypto: globalThis.crypto,
  protocol: POPUP_PROTOCOL,
});
const POPUP_SETTINGS_STORE = globalThis.BookmarkAdvisor.Popup.SettingsStore.create({
  chrome,
  protocol: POPUP_PROTOCOL,
  aiEndpoint: POPUP_ENDPOINT,
});
const POPUP_I18N = globalThis.BookmarkAdvisor.Popup.I18n.create({
  document,
});

let loadedPlan = null;
let loadedSummary = null;
let lastExecutionReport = null;
const pendingReviseNotes = new Map();

function t(key) {
  return POPUP_I18N.t(key);
}

function applyLanguage(lang) {
  POPUP_I18N.applyLanguage(lang);
}

const ENCRYPTED_KEY_STORAGE_NAME = POPUP_PROTOCOL.STORAGE_KEYS.ENCRYPTED_API_KEY;
const ENCRYPTED_KEY_DRAFT_STORAGE_NAME = POPUP_PROTOCOL.STORAGE_KEYS.ENCRYPTED_API_KEY_DRAFT;
const LLM_SETTINGS_STORAGE_NAME = POPUP_PROTOCOL.STORAGE_KEYS.LLM_SETTINGS;
const UI_DRAFT_STORAGE_NAME = POPUP_PROTOCOL.STORAGE_KEYS.POPUP_DRAFT;
const PREFERENCES_STORAGE_NAME = POPUP_PROTOCOL.STORAGE_KEYS.PREFERENCES;
const PROGRESS_STORAGE_NAME = POPUP_PROTOCOL.STORAGE_KEYS.PROGRESS;
const RUNTIME_MESSAGE_TIMEOUT_MS = 240000;
const JOB_STALENESS_CHECK_INTERVAL_MS = 20000;
const JOB_STALENESS_THRESHOLD_MS = 180000;
const DEFAULT_LLM_SETTINGS = POPUP_SETTINGS_STORE.DEFAULT_LLM_SETTINGS;
const DEFAULT_PREFERENCES = POPUP_SETTINGS_STORE.DEFAULT_PREFERENCES;
const DEFAULT_UI_DRAFT = POPUP_SETTINGS_STORE.DEFAULT_UI_DRAFT;
const ACTIVE_TAB_ALIASES = POPUP_SETTINGS_STORE.ACTIVE_TAB_ALIASES;
const ACTIVE_TABS = POPUP_SETTINGS_STORE.ACTIVE_TABS;
const REVIEW_CATEGORY_KEY = "__review__";
const REJECTED_CATEGORY_KEY = "__rejected__";
const POPUP_PLAN_VIEW = globalThis.BookmarkAdvisor.Popup.PlanView.create({
  isExecutableAction,
  rejectedCategoryKey: REJECTED_CATEGORY_KEY,
  reportOnlyActions: REPORT_ONLY_ACTIONS,
  reviewCategoryKey: REVIEW_CATEGORY_KEY,
  t,
});
const {
  actionDisplayStatus,
  actionReviewAgreed,
  actionTitle,
  actionTypeLabel,
  categoryKeyForAction,
  confidenceClass,
  groupActionsByCategory,
  lastSegment,
  shouldShowQuickAgreeAction,
  sortCategories,
} = POPUP_PLAN_VIEW;

function normalizeActiveTabName(name) {
  return POPUP_SETTINGS_STORE.normalizeActiveTabName(name);
}

const fileInput = document.getElementById("plan-file");
const apiKeyInput = document.getElementById("api-key");
const apiBaseUrlInput = document.getElementById("api-base-url");
const apiStyleInput = document.getElementById("api-style");
const endpointPreviewEl = document.getElementById("endpoint-preview");
const keyStorageStatusEl = document.getElementById("key-storage-status");
const modelInput = document.getElementById("model");
const requestTimeoutInput = document.getElementById("request-timeout");
const maxRetriesInput = document.getElementById("max-retries");
const maxActionsInput = document.getElementById("max-actions");
const focusPathInput = document.getElementById("focus-path");
const userInstructionInput = document.getElementById("user-instruction");
const statusEl = document.getElementById("status");
const statsEl = document.getElementById("stats");
const totalCountEl = document.getElementById("total-count");
const executableCountEl = document.getElementById("executable-count");
const reviewCountEl = document.getElementById("review-count");
const errorCountEl = document.getElementById("error-count");
const warningCountEl = document.getElementById("warning-count");
const rejectedCountEl = document.getElementById("rejected-count");
const previewListEl = document.getElementById("preview-list");
const executeButton = document.getElementById("execute-btn");
const exportSnapshotButton = document.getElementById("export-snapshot-btn");
const generateAiButton = document.getElementById("generate-ai-btn");
const reviseAiButton = document.getElementById("revise-ai-btn");
const saveCredentialsButton = document.getElementById("save-credentials-btn");
const forgetKeyButton = document.getElementById("forget-key-btn");
const downloadReportButton = document.getElementById("download-report-btn");
const undoButton = document.getElementById("undo-btn");
const cancelJobButton = document.getElementById("cancel-job-btn");
const continueButton = document.getElementById("continue-btn");
const spinnerEl = document.getElementById("spinner");
const organizeTabButton = document.getElementById("organize-tab-btn");
const aiServiceTabButton = document.getElementById("ai-service-tab-btn");
const strategyTabButton = document.getElementById("strategy-tab-btn");
const diagnosticsTabButton = document.getElementById("diagnostics-tab-btn");
const organizeTab = document.getElementById("organize-tab");
const aiServiceTab = document.getElementById("ai-service-tab");
const strategyTab = document.getElementById("strategy-tab");
const diagnosticsTab = document.getElementById("diagnostics-tab");
const prefProtectRoot = document.getElementById("pref-protect-root");
const prefSortOrder = document.getElementById("pref-sort-order");
const prefPlanningStyle = document.getElementById("pref-planning-style");
const prefLang = document.getElementById("pref-lang");
let restoringInputs = false;
let cacheWriteInFlight = false;
let cacheWriteQueued = false;
let activeBackgroundJob = null;
let currentActiveTab = DEFAULT_UI_DRAFT.activeTab;
let _stalenessCheckIntervalId = null;
let _pendingFocusPath = "";
const POPUP_JOB_STATE = globalThis.BookmarkAdvisor.Popup.JobState.create({
  protocol: POPUP_PROTOCOL,
  storage: globalThis.BookmarkAdvisor.Storage,
  staleMessage: () => t("error_sw_terminated"),
  onRecord: handleJobRecord,
});

function showSpinner() { spinnerEl.hidden = false; }
function hideSpinner() { spinnerEl.hidden = true; }
function updateStatus(message, className) {
  statusEl.textContent = message;
  statusEl.className = className || "";
}

initializeTabs();
initializeSavedSettings();

fileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files || [];
  if (!file) {
    return;
  }

  try {
    const text = await file.text();
    const plan = BookmarkPlanLint.parsePlanText(text);
    loadPlan(plan);
    saveLastPlan(plan);
  } catch (error) {
    loadedPlan = null;
    loadedSummary = null;
    lastExecutionReport = null;
    downloadReportButton.disabled = true;
    renderError(error instanceof Error ? error.message : String(error));
    executeButton.disabled = true;
    reviseAiButton.disabled = true;
    chromeStorageRemove(LAST_PLAN_STORAGE_NAME);
  }
});

saveCredentialsButton.addEventListener("click", async () => {
  let settings;
  try {
    settings = readLlmSettingsFromInputs();
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
    return;
  }
  if (!settings.apiBaseUrl) {
    updateKeyStorageStatus(t("key_enter_api_url"), "error");
    return;
  }
  if (!settings.model) {
    updateKeyStorageStatus(t("key_enter_model"), "error");
    return;
  }

  saveCredentialsButton.disabled = true;
  try {
    const hostGranted = await ensureHostPermission(settings.apiBaseUrl);
    if (!hostGranted) {
      updateKeyStorageStatus(t("key_host_denied"), "error");
      return;
    }
    await saveLlmSettings(settings);
    // 非官方端点警告:密钥会被发往任意用户配置的 HTTPS 主机,仅在非 api.openai.com 时提示
    let endpointWarning = "";
    try {
      const hostname = new URL(normalizeHttpsBaseUrl(settings.apiBaseUrl)).hostname;
      if (hostname && hostname !== "api.openai.com") {
        endpointWarning = " " + t("key_third_party_endpoint").replace("{host}", hostname);
      }
    } catch (_urlError) {
      // URL 已在 readLlmSettingsFromInputs 校验过,这里不会失败;静默忽略
    }
    if (apiKeyInput.value.trim()) {
      await saveEncryptedApiKey(apiKeyInput.value.trim());
      await clearEncryptedApiKeyDraft();
      requestInputCacheWrite();
      updateKeyStorageStatus(t("key_saved_with_key") + endpointWarning, endpointWarning ? "warning" : "ok");
    } else {
      const savedKey = await chromeStorageGet(ENCRYPTED_KEY_STORAGE_NAME);
      const baseMsg = savedKey ? t("key_saved_existing_key") : t("key_saved_need_key");
      updateKeyStorageStatus(
        baseMsg + endpointWarning,
        savedKey && !endpointWarning ? "ok" : "warning",
      );
    }
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    saveCredentialsButton.disabled = false;
  }
});

forgetKeyButton.addEventListener("click", async () => {
  forgetKeyButton.disabled = true;
  try {
    await chromeStorageRemove(ENCRYPTED_KEY_STORAGE_NAME);
    await clearEncryptedApiKeyDraft();
    apiKeyInput.value = "";
    requestInputCacheWrite();
    updateKeyStorageStatus(t("key_removed"), "warning");
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    forgetKeyButton.disabled = false;
  }
});

generateAiButton.addEventListener("click", async () => {
  let settings;
  try {
    settings = readLlmSettingsFromInputs();
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
    showTab("ai-service", { persist: true });
    return;
  }
  if (!settings.apiBaseUrl) {
    renderError(t("error_need_api_base_url"));
    showTab("ai-service", { persist: true });
    return;
  }
  if (!settings.model) {
    renderError(t("error_need_model"));
    showTab("ai-service", { persist: true });
    return;
  }

  let apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    try {
      apiKey = await loadEncryptedApiKey();
      updateKeyStorageStatus(t("key_loaded"), "ok");
    } catch (_savedKeyError) {
      try {
        apiKey = await loadEncryptedApiKeyDraft();
        apiKeyInput.value = apiKey;
        updateKeyStorageStatus(t("key_draft_restored"), "warning");
      } catch (_draftKeyError) {
        updateKeyStorageStatus(t("key_no_key"), "error");
      }
    }
  }
  if (!apiKey) {
    renderError(t("error_need_api_key"));
    showTab("ai-service", { persist: true });
    return;
  }

  generateAiButton.disabled = true;
  reviseAiButton.disabled = true;
  executeButton.disabled = true;
  updateStatus(t("status_checking_permission"), "");
  showSpinner();

  function onStorageChange(changes, areaName) {
    if (areaName !== "local") return;
    const progress = changes[PROGRESS_STORAGE_NAME];
    if (progress && progress.newValue) {
      updateStatus(progress.newValue.message || t("status_job_running"), "");
    }
  }
  chrome.storage.onChanged.addListener(onStorageChange);

  try {
    const hostGranted = await ensureHostPermission(settings.apiBaseUrl);
    if (!hostGranted) {
      throw new Error(t("key_host_denied"));
    }
    updateStatus(t("status_exporting_bookmarks"), "");
    await saveLlmSettings(settings);
    const response = await startBackgroundJobAndRender(POPUP_JOB_TYPES.GENERATE_AI_PLAN, {
      options: {
        apiKey,
        apiBaseUrl: settings.apiBaseUrl,
        apiStyle: settings.apiStyle,
        model: settings.model,
        maxActions: maxActionsInput.value,
        requestTimeoutMs: (parseInt(requestTimeoutInput.value, 10) || 180) * 1000,
        maxRetries: parseInt(maxRetriesInput.value, 10),
        focusPath: focusPathInput.value,
        userInstruction: userInstructionInput.value.trim(),
        preferences: readPreferences(),
      },
    });
    if (response && response.error) {
      throw new Error(response.error);
    }
    updateStatus(t("status_planning_background"), "");
  } catch (error) {
    hideSpinner();
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    chrome.storage.onChanged.removeListener(onStorageChange);
    if (!isActiveJobRunning()) {
      generateAiButton.disabled = false;
      reviseAiButton.disabled = !loadedPlan;
      hideSpinner();
    }
  }
});

reviseAiButton.addEventListener("click", async () => {
  if (!loadedPlan) {
    renderError(t("error_need_loaded_plan"));
    return;
  }
  const globalInstruction = userInstructionInput.value.trim();
  const perActionNotes = [];
  for (const [key, note] of pendingReviseNotes) {
    perActionNotes.push(`- [${key}]: ${note}`);
  }
  const rejectedNotes = [];
  for (const action of loadedPlan.actions || []) {
    if (String(action.status || "").trim() === "rejected") {
      const title = actionTitle(action);
      const reason = action.details && action.details.rejection_reason
        ? ` (reason: ${action.details.rejection_reason})`
        : "";
      rejectedNotes.push(`- "${title}"${reason}`);
    }
  }
  const parts = [];
  if (globalInstruction) parts.push(globalInstruction);
  if (perActionNotes.length > 0) {
    parts.push("Per-action revision notes:\n" + perActionNotes.join("\n"));
  }
  if (rejectedNotes.length > 0) {
    parts.push("The user rejected these actions — do not propose them again:\n" + rejectedNotes.join("\n"));
  }
  const userInstruction = parts.join("\n\n");
  if (!userInstruction) {
    renderError(t("error_need_revision_instruction"));
    return;
  }

  let settings;
  try {
    settings = readLlmSettingsFromInputs();
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
    showTab("ai-service", { persist: true });
    return;
  }

  let apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    try {
      apiKey = await loadEncryptedApiKey();
      updateKeyStorageStatus(t("key_loaded"), "ok");
    } catch (_savedKeyError) {
      try {
        apiKey = await loadEncryptedApiKeyDraft();
        apiKeyInput.value = apiKey;
        updateKeyStorageStatus(t("key_draft_restored"), "warning");
      } catch (_draftKeyError) {
        updateKeyStorageStatus(t("key_no_key"), "error");
      }
    }
  }
  if (!apiKey) {
    renderError(t("error_need_api_key"));
    showTab("ai-service", { persist: true });
    return;
  }

  generateAiButton.disabled = true;
  reviseAiButton.disabled = true;
  executeButton.disabled = true;
  updateStatus(t("status_checking_permission"), "");
  showSpinner();

  function onStorageChange(changes, areaName) {
    if (areaName !== "local") return;
    const progress = changes[PROGRESS_STORAGE_NAME];
    if (progress && progress.newValue) {
      updateStatus(progress.newValue.message || t("status_job_running"), "");
    }
  }
  chrome.storage.onChanged.addListener(onStorageChange);

  try {
    const hostGranted = await ensureHostPermission(settings.apiBaseUrl);
    if (!hostGranted) {
      throw new Error(t("key_host_denied"));
    }
    updateStatus(t("status_revising_exporting"), "");
    await saveLlmSettings(settings);
    const response = await startBackgroundJobAndRender(POPUP_JOB_TYPES.REVISE_AI_PLAN, {
      plan: loadedPlan,
      options: {
        apiKey,
        apiBaseUrl: settings.apiBaseUrl,
        apiStyle: settings.apiStyle,
        model: settings.model,
        maxActions: maxActionsInput.value,
        requestTimeoutMs: (parseInt(requestTimeoutInput.value, 10) || 180) * 1000,
        maxRetries: parseInt(maxRetriesInput.value, 10),
        focusPath: focusPathInput.value,
        userInstruction,
        preferences: readPreferences(),
      },
    });
    if (response && response.error) {
      throw new Error(response.error);
    }
    updateStatus(t("status_revision_background"), "");
    pendingReviseNotes.clear();
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    chrome.storage.onChanged.removeListener(onStorageChange);
    if (!isActiveJobRunning()) {
      generateAiButton.disabled = false;
      reviseAiButton.disabled = !loadedPlan;
      hideSpinner();
    }
  }
});

executeButton.addEventListener("click", async () => {
  if (!loadedPlan || !loadedSummary || !loadedSummary.ok) {
    return;
  }
  executeButton.disabled = true;
  reviseAiButton.disabled = true;
  updateStatus(t("status_executing_plan"), "");
  showSpinner();

  function onStorageChange(changes, areaName) {
    if (areaName !== "local") return;
    const progress = changes[PROGRESS_STORAGE_NAME];
    if (progress && progress.newValue) {
      updateStatus(progress.newValue.message || t("status_job_running"), "");
    }
  }
  chrome.storage.onChanged.addListener(onStorageChange);

  try {
    await startBackgroundJobAndRender(POPUP_JOB_TYPES.APPLY_REVIEWED_PLAN, {
      plan: loadedPlan,
      focusPath: document.getElementById("focus-path").value,
    });
    updateStatus(t("status_execution_background"), "");
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    chrome.storage.onChanged.removeListener(onStorageChange);
    if (!isActiveJobRunning()) {
      executeButton.disabled = false;
      reviseAiButton.disabled = !loadedPlan;
      hideSpinner();
    }
  }
});

undoButton.addEventListener("click", async () => {
  undoButton.disabled = true;
  updateStatus(t("status_undoing"), "");
  showSpinner();
  try {
    const response = await sendRuntimeMessage({ type: POPUP_MESSAGES.UNDO_LAST_EXECUTION });
    if (response && response.error) {
      throw new Error(response.error);
    }
    if (response && response.undone) {
      updateStatus(t("status_undone").replace("{count}", response.count), "ok");
      undoButton.disabled = !response.hasMore;
    } else {
      updateStatus(response.reason || t("status_nothing_to_undo"), "");
    }
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    hideSpinner();
  }
});

cancelJobButton.addEventListener("click", async () => {
  cancelJobButton.hidden = true;
  updateStatus(t("status_cancelling"), "");
  try {
    await sendRuntimeMessage({ type: POPUP_MESSAGES.CANCEL_ACTIVE_JOB });
  } catch (_error) {
    // Let persisted job state settle through storage changes.
  }
});

continueButton.addEventListener("click", () => {
  continueButton.hidden = true;
  generateAiButton.click();
});

exportSnapshotButton.addEventListener("click", async () => {
  exportSnapshotButton.disabled = true;
  updateStatus(t("status_exporting_snapshot"), "");
  showSpinner();
  try {
    const response = await sendRuntimeMessage({
      type: POPUP_MESSAGES.EXPORT_SNAPSHOT,
    });
    if (response && response.error) {
      throw new Error(response.error);
    }
    downloadJson(response, buildFilename("snapshot"));
    updateStatus(t("status_snapshot_exported"), "ok");
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    exportSnapshotButton.disabled = false;
    hideSpinner();
  }
});

downloadReportButton.addEventListener("click", () => {
  if (!lastExecutionReport) {
    return;
  }
  downloadJson(lastExecutionReport, buildFilename("execution-report"));
});

function initializeTabs() {
  organizeTabButton.addEventListener("click", () => showTab("organize", { persist: true }));
  aiServiceTabButton.addEventListener("click", () => showTab("ai-service", { persist: true }));
  strategyTabButton.addEventListener("click", () => showTab("strategy", { persist: true }));
  diagnosticsTabButton.addEventListener("click", () => showTab("diagnostics", { persist: true }));
}

async function initializeSavedSettings() {
  try {
    restoringInputs = true;
    const prefs = await loadPreferences();
    applyLanguage(prefs.lang || "zh");
    const settings = await loadLlmSettings();
    applyLlmSettings(settings);
    applyUiDraft(await loadUiDraft());
    applyPreferences(prefs);
    await restoreEncryptedDraftApiKey();
    await refreshSavedKeyStatus();
    updateEndpointPreview();
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    restoringInputs = false;
    attachInputCacheHandlers();
    attachPreferenceHandlers();
    requestInputCacheWrite();
  }

  try {
    const savedPlanRecord = await chromeStorageGet(LAST_PLAN_STORAGE_NAME);
    if (savedPlanRecord && savedPlanRecord.plan) {
      loadPlan(savedPlanRecord.plan);
      updateStatus(t("status_restored_plan"), "ok");
    }
    const savedReport = await chromeStorageGet(LAST_REPORT_STORAGE_NAME);
    if (savedReport) {
      lastExecutionReport = savedReport;
      downloadReportButton.disabled = false;
    }
    const activeJobResponse = await sendRuntimeMessage({ type: POPUP_MESSAGES.GET_ACTIVE_JOB }, 5000);
    if (activeJobResponse && activeJobResponse.job) {
      handleJobRecord(activeJobResponse.job);
    }
  } catch (_error) {
    // plan restoration is best-effort
  }

  loadFolderList();
  chrome.storage.onChanged.addListener(handleBackgroundJobStorageChange);
}

function attachInputCacheHandlers() {
  // 非 API key 字段:input/change 时写 UI 草稿快照(轻量,有合并)。
  const fields = [
    apiBaseUrlInput,
    apiStyleInput,
    modelInput,
    requestTimeoutInput,
    focusPathInput,
    maxActionsInput,
    maxRetriesInput,
    userInstructionInput,
  ];
  for (const field of fields) {
    field.addEventListener("input", () => {
      if (field === apiBaseUrlInput) {
        updateEndpointPreview();
      }
      requestInputCacheWrite();
    });
    field.addEventListener("change", () => {
      if (field === apiBaseUrlInput) {
        updateEndpointPreview();
      }
      requestInputCacheWrite();
    });
  }
  // API key:不在每次按键时加密落盘(避免每个按键都做一次 AES-GCM 加密 + storage 写入,
  // 也避免"粘贴后未点保存就关闭 popup,key 已落盘"的语义混淆)。仅在失焦/隐藏时持久化。
  apiKeyInput.addEventListener("blur", () => {
    void persistApiKeyDraftIfChanged();
  });
  window.addEventListener("pagehide", () => {
    stopJobStalenessCheck();
    persistUiDraftSnapshotNow();
    void autoSaveLlmSettingsIfChanged();
    void persistApiKeyDraftIfChanged();
    requestInputCacheWrite();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      stopJobStalenessCheck();
      persistUiDraftSnapshotNow();
      void autoSaveLlmSettingsIfChanged();
      void persistApiKeyDraftIfChanged();
      requestInputCacheWrite();
    }
  });
  window.addEventListener("blur", () => {
    persistUiDraftSnapshotNow();
    void autoSaveLlmSettingsIfChanged();
    void persistApiKeyDraftIfChanged();
    requestInputCacheWrite();
  });
}

async function autoSaveLlmSettingsIfChanged() {
  if (restoringInputs) return;
  try {
    const current = readLlmSettingsFromInputs();
    if (!current.apiBaseUrl && !current.model) return;
    const saved = await loadLlmSettings();
    if (current.apiBaseUrl !== saved.apiBaseUrl ||
        current.apiStyle !== saved.apiStyle ||
        current.model !== saved.model ||
        current.requestTimeout !== saved.requestTimeout) {
      await saveLlmSettings(current);
    }
  } catch (_error) {
    // URL 不合法等异常静默忽略
  }
}

function requestInputCacheWrite() {
  if (restoringInputs) {
    return;
  }
  cacheWriteQueued = true;
  void drainInputCacheWrites();
}

async function drainInputCacheWrites() {
  if (cacheWriteInFlight) {
    return;
  }
  cacheWriteInFlight = true;
  try {
    while (cacheWriteQueued) {
      cacheWriteQueued = false;
      await persistInputCache();
    }
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    cacheWriteInFlight = false;
  }
}

async function persistInputCache() {
  // UI 草稿快照(非密钥字段)在按键时合并写入。API key 草稿不在此处持久化 ——
  // 见 persistApiKeyDraftIfChanged(仅失焦/隐藏时加密落盘)。
  await POPUP_SETTINGS_STORE.saveUiDraft(buildUiDraftSnapshot());
}

async function persistApiKeyDraftIfChanged() {
  if (restoringInputs) return;
  const apiKeyDraft = apiKeyInput.value.trim();
  if (apiKeyDraft) {
    await saveEncryptedApiKeyDraft(apiKeyDraft);
  } else {
    await clearEncryptedApiKeyDraft();
  }
}

function buildUiDraftSnapshot() {
  return {
    version: 3,
    activeTab: currentActiveTab,
    apiBaseUrl: apiBaseUrlInput.value,
    apiStyle: apiStyleInput.value,
    model: modelInput.value,
    requestTimeout: requestTimeoutInput.value,
    focusPath: focusPathInput.value,
    maxActions: maxActionsInput.value,
    maxRetries: maxRetriesInput.value,
    userInstruction: userInstructionInput.value,
    updated_at: new Date().toISOString(),
  };
}

function persistUiDraftSnapshotNow() {
  if (restoringInputs) {
    return;
  }
  void POPUP_SETTINGS_STORE.saveUiDraft(buildUiDraftSnapshot()).catch((error) => {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  });
}

function showTab(name, options = {}) {
  const activeName = normalizeActiveTabName(name);
  currentActiveTab = activeName;
  const tabPairs = [
    ["organize", organizeTab, organizeTabButton],
    ["ai-service", aiServiceTab, aiServiceTabButton],
    ["strategy", strategyTab, strategyTabButton],
    ["diagnostics", diagnosticsTab, diagnosticsTabButton],
  ];
  for (const [tabName, panel, button] of tabPairs) {
    const selected = tabName === activeName;
    panel.hidden = !selected;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
  }
  if (options.persist) {
    persistUiDraftSnapshotNow();
    requestInputCacheWrite();
  }
}

async function loadFolderList() {
  try {
    const response = await sendRuntimeMessage({ type: POPUP_MESSAGES.LIST_FOLDERS }, 10000);
    if (response && response.folders) {
      populateFolderDropdown(response.folders);
    }
  } catch (_error) {
    // folder list is best-effort; text input fallback still works
  }
}

function populateFolderDropdown(folders) {
  const current = focusPathInput.value || _pendingFocusPath;
  focusPathInput.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = t("opt_all_bookmarks");
  focusPathInput.appendChild(allOption);
  for (const folder of folders) {
    const option = document.createElement("option");
    option.value = folder.path;
    const indent = "\u00A0\u00A0".repeat(Math.min(folder.depth || 0, 6));
    option.textContent = indent + folder.path;
    focusPathInput.appendChild(option);
  }
  if (current && !folders.some((f) => f.path === current)) {
    const option = document.createElement("option");
    option.value = current;
    option.textContent = current;
    focusPathInput.appendChild(option);
  }
  if (current) {
    focusPathInput.value = current;
    _pendingFocusPath = "";
  }
}

async function loadPreferences() {
  return POPUP_SETTINGS_STORE.loadPreferences();
}

function applyPreferences(prefs) {
  prefProtectRoot.value = prefs.protectRootLooseBookmarks || DEFAULT_PREFERENCES.protectRootLooseBookmarks;
  prefSortOrder.value = prefs.sortOrder || DEFAULT_PREFERENCES.sortOrder;
  prefPlanningStyle.value = prefs.planningStyle || DEFAULT_PREFERENCES.planningStyle;
  prefLang.value = prefs.lang || DEFAULT_PREFERENCES.lang;
}

function readPreferences() {
  return {
    protectRootLooseBookmarks: prefProtectRoot.value,
    sortOrder: prefSortOrder.value,
    planningStyle: prefPlanningStyle.value,
    lang: prefLang.value,
  };
}

function attachPreferenceHandlers() {
  prefProtectRoot.addEventListener("change", () => persistPreferencesNow());
  prefSortOrder.addEventListener("change", () => persistPreferencesNow());
  prefPlanningStyle.addEventListener("change", () => persistPreferencesNow());
  prefLang.addEventListener("change", () => {
    applyLanguage(prefLang.value);
    persistPreferencesNow();
  });
}

async function persistPreferencesNow() {
  if (restoringInputs) return;
  try {
    await POPUP_SETTINGS_STORE.savePreferences(readPreferences());
  } catch (_error) {
    // preferences persistence is best-effort
  }
}

async function preferencesStorageGet() {
  if (chrome.storage && chrome.storage.sync && typeof chrome.storage.sync.get === "function") {
    try {
      return await chromeStorageGetFromArea(chrome.storage.sync, PREFERENCES_STORAGE_NAME);
    } catch (error) {
      if (!(error instanceof Error) || !/chrome\.storage\.sync|sync/i.test(error.message || "")) {
        throw error;
      }
    }
  }
  return chromeStorageGet(PREFERENCES_STORAGE_NAME);
}

async function preferencesStorageSet(value) {
  if (chrome.storage && chrome.storage.sync && typeof chrome.storage.sync.set === "function") {
    try {
      await chromeStorageSetFromArea(chrome.storage.sync, PREFERENCES_STORAGE_NAME, value);
      return;
    } catch (error) {
      if (!(error instanceof Error) || !/chrome\.storage\.sync|sync/i.test(error.message || "")) {
        throw error;
      }
    }
  }
  await chromeStorageSet(PREFERENCES_STORAGE_NAME, value);
}

function renderSummary(summary) {
  if (summary.errors.length > 0) {
    statusEl.className = "error";
    statusEl.textContent = t("lint_failed").replace("{n}", summary.errors.length);
  } else if (summary.warnings.length > 0) {
    statusEl.className = "warning";
    statusEl.textContent = t("lint_warnings").replace("{n}", summary.warnings.length);
  } else {
    statusEl.className = "ok";
    statusEl.textContent = t("lint_ok");
  }

  const rejectedCount = summary.reviewActions.filter(
    (a) => String(a.status || "").trim() === "rejected"
  ).length;
  const nonRejectedReviewCount = summary.reviewActions.length - rejectedCount;

  statsEl.hidden = false;
  totalCountEl.textContent = String(summary.totalActions);
  executableCountEl.textContent = String(summary.executableActions.length);
  reviewCountEl.textContent = String(nonRejectedReviewCount);
  errorCountEl.textContent = String(summary.errors.length);
  warningCountEl.textContent = String(summary.warnings.length);
  rejectedCountEl.textContent = String(rejectedCount);

  previewListEl.innerHTML = "";
  if (!summary.ok) {
    const diagnostics = [
      ...summary.errors.map(BookmarkPlanLint.formatDiagnostic),
      ...summary.warnings.map(BookmarkPlanLint.formatDiagnostic),
    ];
    for (const item of diagnostics) {
      const li = document.createElement("li");
      li.textContent = item;
      previewListEl.appendChild(li);
    }
    return;
  }

  const allActions = [...summary.executableActions, ...summary.reviewActions];
  if (allActions.length === 0) {
    return;
  }

  const categories = groupActionsByCategory(allActions);
  const sortedCategories = sortCategories(categories);

  const container = document.createElement("div");
  container.className = "category-list";

  for (const cat of sortedCategories) {
    container.appendChild(buildCategoryElement(cat));
  }

  previewListEl.appendChild(container);
}

function loadPlan(plan) {
  const summary = BookmarkPlanLint.lintPlan(plan);
  loadedPlan = plan;
  loadedSummary = summary;
  lastExecutionReport = null;
  downloadReportButton.disabled = true;
  continueButton.hidden = true;
  renderSummary(summary);
  executeButton.disabled = !summary.ok || summary.executableActions.length === 0;
  reviseAiButton.disabled = false;
}

function approveAction(action) {
  if (String(action.action_type || "") === "keep_for_review") {
    action.status = "approved";
    action.details = {
      ...(action.details || {}),
      review_agreed: true,
    };
    saveLastPlan(loadedPlan);
    loadPlan(loadedPlan);
    return;
  }
  action.status = "approved";
  saveLastPlan(loadedPlan);
  loadPlan(loadedPlan);
}

function rejectAction(action) {
  action.status = "rejected";
  saveLastPlan(loadedPlan);
  loadPlan(loadedPlan);
}

function unrejectAction(action) {
  action.status = "proposed";
  if (action.details) {
    delete action.details.rejection_reason;
  }
  saveLastPlan(loadedPlan);
  loadPlan(loadedPlan);
}

function buildCategoryElement(category) {
  const isReviewCategory = category.key === REVIEW_CATEGORY_KEY;
  const isRejectedCategory = category.key === REJECTED_CATEGORY_KEY;
  let displayName, subtitle;
  if (isRejectedCategory) {
    displayName = t("cat_rejected");
    subtitle = t("cat_rejected_hint");
  } else if (isReviewCategory) {
    displayName = t("cat_review");
    subtitle = t("cat_review_hint");
  } else {
    displayName = lastSegment(category.path);
    subtitle = category.path;
  }
  const actionCount = category.actions.length;

  const group = document.createElement("div");
  group.className = "category-group";

  const header = document.createElement("div");
  header.className = "category-header";
  header.setAttribute("role", "button");
  header.setAttribute("tabindex", "0");
  header.setAttribute("aria-expanded", "false");

  const nameSpan = document.createElement("span");
  nameSpan.className = "category-name";

  const chevron = document.createElement("span");
  chevron.className = "chevron";
  chevron.textContent = "\u25B6";

  const nameText = document.createElement("span");
  nameText.textContent = displayName;

  const pathHint = document.createElement("span");
  pathHint.className = "category-path";
  pathHint.textContent = subtitle;

  nameSpan.appendChild(chevron);
  nameSpan.appendChild(nameText);
  nameSpan.appendChild(pathHint);

  const badge = document.createElement("span");
  badge.className = "count-badge";
  badge.textContent = String(actionCount);

  header.appendChild(nameSpan);
  header.appendChild(badge);

  const details = document.createElement("div");
  details.className = "category-details";
  details.id = `cat-details-${category.key.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

  header.setAttribute("aria-controls", details.id);

  for (const action of category.actions) {
    details.appendChild(buildActionItem(action, isReviewCategory));
  }

  header.addEventListener("click", () => {
    const expanded = details.classList.toggle("open");
    header.classList.toggle("expanded", expanded);
    header.setAttribute("aria-expanded", String(expanded));
  });

  header.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      header.click();
    }
  });

  if (actionCount <= 3) {
    details.classList.add("open");
    header.classList.add("expanded");
    header.setAttribute("aria-expanded", "true");
  }

  group.appendChild(header);
  group.appendChild(details);
  return group;
}

function buildActionItem(action, isReviewCategory = false) {
  const type = String(action.action_type || "");
  const title = actionTitle(action);
  const reason = String(action.reason || "");
  const confidence = Number(action.confidence);
  const fromPath = String(action.from_path || "");
  const toPath = String(action.to_path || action.target_path || action.to_name || "");
  const needsReview = actionDisplayStatus(action) !== "executable";

  const displayStatus = actionDisplayStatus(action);
  const isRejected = displayStatus === "rejected";

  const item = document.createElement("div");
  item.className = "action-item" + (isRejected ? " rejected" : "");

  const titleEl = document.createElement("div");
  titleEl.className = "action-title";
  titleEl.textContent = title;

  const metaEl = document.createElement("div");
  metaEl.className = "action-meta";

  const typeLabel = document.createElement("span");
  typeLabel.className = "action-type-label" + (needsReview ? " review" : "");
  typeLabel.textContent = actionTypeLabel(type);

  const confDot = document.createElement("span");
  confDot.className = "confidence-dot " + confidenceClass(confidence);
  confDot.setAttribute("aria-label", `confidence: ${confidence.toFixed(2)}`);
  confDot.title = `confidence: ${confidence.toFixed(2)}`;

  metaEl.appendChild(typeLabel);
  metaEl.appendChild(confDot);

  if (fromPath && toPath && fromPath !== toPath) {
    const moveHint = document.createElement("span");
    const shortFrom = lastSegment(fromPath);
    const shortTo = lastSegment(toPath);
    moveHint.textContent = `${shortFrom} \u2192 ${shortTo}`;
    metaEl.appendChild(moveHint);
  }

  const controls = document.createElement("div");
  controls.className = "action-controls";

  if (shouldShowQuickAgreeAction(action, isReviewCategory)) {
    const isAgreed = actionReviewAgreed(action);
    const agreeBtn = document.createElement("button");
    agreeBtn.type = "button";
    agreeBtn.className = "action-agree";
    agreeBtn.textContent = t("btn_action_agree");
    agreeBtn.disabled = isAgreed;
    agreeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      approveAction(action);
    });
    controls.appendChild(agreeBtn);
  }

  if (!isRejected) {
    const rejectBtn = document.createElement("button");
    rejectBtn.type = "button";
    rejectBtn.className = "action-reject";
    rejectBtn.textContent = t("btn_action_reject");
    rejectBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      rejectAction(action);
    });
    controls.appendChild(rejectBtn);
  } else {
    const unrejectBtn = document.createElement("button");
    unrejectBtn.type = "button";
    unrejectBtn.className = "action-unreject";
    unrejectBtn.textContent = t("btn_action_unreject");
    unrejectBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      unrejectAction(action);
    });
    controls.appendChild(unrejectBtn);
  }

  if (controls.children.length > 0) {
    metaEl.appendChild(controls);
  }

  const reasonEl = document.createElement("div");
  reasonEl.className = "action-reason";
  reasonEl.textContent = reason;

  item.appendChild(titleEl);
  item.appendChild(metaEl);
  if (reason) {
    item.appendChild(reasonEl);
  }

  const actionKey = action.action_id || `${type}-${title}`;
  const savedNote = pendingReviseNotes.get(actionKey) || "";

  const reviseInput = document.createElement("input");
  reviseInput.type = "text";
  reviseInput.className = "action-revise-input";
  reviseInput.placeholder = t("placeholder_action_revise");
  if (savedNote) {
    reviseInput.value = savedNote;
    reviseInput.classList.add("open", "has-note");
  }
  reviseInput.addEventListener("click", (e) => e.stopPropagation());
  reviseInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const text = reviseInput.value.trim();
      if (text) {
        pendingReviseNotes.set(actionKey, text);
        reviseInput.classList.add("has-note");
      } else {
        pendingReviseNotes.delete(actionKey);
        reviseInput.classList.remove("has-note");
      }
      reviseInput.blur();
    }
  });
  reviseInput.addEventListener("blur", () => {
    const text = reviseInput.value.trim();
    if (text) {
      pendingReviseNotes.set(actionKey, text);
      reviseInput.classList.add("has-note");
    } else {
      pendingReviseNotes.delete(actionKey);
      reviseInput.classList.remove("has-note");
    }
  });

  if (isRejected) {
    const rejectionInput = document.createElement("input");
    rejectionInput.type = "text";
    rejectionInput.className = "action-rejection-input";
    rejectionInput.placeholder = t("placeholder_rejection_reason");
    rejectionInput.value = (action.details && action.details.rejection_reason) || "";
    if (rejectionInput.value) {
      rejectionInput.classList.add("has-note");
    }
    rejectionInput.addEventListener("click", (e) => e.stopPropagation());
    rejectionInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const text = rejectionInput.value.trim();
        action.details = {
          ...(action.details || {}),
          rejection_reason: text || "",
        };
        if (text) {
          rejectionInput.classList.add("has-note");
        } else {
          rejectionInput.classList.remove("has-note");
        }
        saveLastPlan(loadedPlan);
        rejectionInput.blur();
      }
    });
    rejectionInput.addEventListener("blur", () => {
      const text = rejectionInput.value.trim();
      action.details = {
        ...(action.details || {}),
        rejection_reason: text || "",
      };
      if (text) {
        rejectionInput.classList.add("has-note");
      } else {
        rejectionInput.classList.remove("has-note");
      }
      saveLastPlan(loadedPlan);
    });
    item.appendChild(rejectionInput);
  }

  item.addEventListener("click", () => {
    if (isRejected) return;
    const wasHidden = !reviseInput.classList.contains("open");
    reviseInput.classList.toggle("open");
    if (wasHidden) reviseInput.focus();
  });

  item.style.cursor = "pointer";
  item.appendChild(reviseInput);
  return item;
}

function renderExecutionResult(report) {
  const failures = report.failures || [];
  const succeeded = report.succeeded || [];
  lastExecutionReport = report;
  downloadReportButton.disabled = false;
  undoButton.disabled = succeeded.length === 0;
  saveLastReport(report);
  statusEl.className = failures.length === 0 ? "ok" : "error";
  statusEl.textContent =
    failures.length === 0
      ? t("execution_applied").replace("{n}", succeeded.length)
      : t("execution_failures").replace("{n}", failures.length);

  const hasRemaining = loadedPlan && (loadedPlan.actions || []).some(
    (a) => actionDisplayStatus(a) === "pending" || actionDisplayStatus(a) === "review",
  );
  continueButton.hidden = !hasRemaining;

  previewListEl.innerHTML = "";
  const list = document.createElement("ul");
  const items = [
    `${t("execution_succeeded")} ${succeeded.length}`,
    `${t("execution_failed")} ${failures.length}`,
    ...succeeded.filter((s) => s.target).map((s) => `${s.actionId || s.actionType}: ${s.target}`),
    ...failures.map((failure) => `${failure.actionId || failure.actionType}: ${failure.error}`),
  ];
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
  previewListEl.appendChild(list);
}

function renderError(message) {
  statusEl.className = "error";
  statusEl.textContent = message;
  statsEl.hidden = true;
  previewListEl.innerHTML = "";
  reviseAiButton.disabled = !loadedPlan;
}

function sendRuntimeMessage(payload, timeoutMs = RUNTIME_MESSAGE_TIMEOUT_MS) {
  return POPUP_RUNTIME_CLIENT.send(payload, timeoutMs);
}

async function startBackgroundJobAndRender(jobType, payload) {
  const response = await POPUP_RUNTIME_CLIENT.startJob(jobType, payload);
  handleJobRecord(response.job);
  return response;
}

function handleBackgroundJobStorageChange(changes, areaName) {
  return POPUP_JOB_STATE.handleStorageChange(changes, areaName);
}

function handleJobRecord(job) {
  activeBackgroundJob = job || null;
  POPUP_JOB_STATE.observe(job);
  if (!job) {
    stopJobStalenessCheck();
    return;
  }
  if (job.status === POPUP_JOB_STATUSES.RUNNING) {
    startJobStalenessCheck();
    generateAiButton.disabled = true;
    reviseAiButton.disabled = true;
    executeButton.disabled = true;
    cancelJobButton.hidden = false;
    showSpinner();
    let statusText = job.progress || t("status_job_running");
    if (job.stage) {
      const stageLabel = {
        export: t("stage_export"),
        llm: t("stage_llm"),
        save: t("stage_save"),
        finalize: t("stage_finalize"),
      }[job.stage] || job.stage;
      statusText = `[${stageLabel}] ${statusText}`;
    }
    updateStatus(statusText, "");
    return;
  }
  if (job.status === POPUP_JOB_STATUSES.SUCCEEDED) {
    stopJobStalenessCheck();
    hideSpinner();
    cancelJobButton.hidden = true;
    generateAiButton.disabled = false;
    reviseAiButton.disabled = !loadedPlan;
    const result = job.result || {};
    if (result.reviewed_plan) {
      loadPlan(result.reviewed_plan);
      updateStatus(job.progress || t("status_plan_saved"), "ok");
      return;
    }
    if (Array.isArray(result.succeeded) || Array.isArray(result.failures)) {
      renderExecutionResult(result);
      return;
    }
    updateStatus(job.progress || t("status_background_completed"), "ok");
    return;
  }
  if (job.status === POPUP_JOB_STATUSES.FAILED) {
    stopJobStalenessCheck();
    hideSpinner();
    const cancelledByUser = isCancelledJobMessage(job.error) || isCancelledJobMessage(job.progress);
    cancelJobButton.hidden = cancelledByUser ? true : !job.recoverable;
    generateAiButton.disabled = false;
    reviseAiButton.disabled = !loadedPlan;
    executeButton.disabled = !loadedSummary || !loadedSummary.ok || loadedSummary.executableActions.length === 0;
    renderError(cancelledByUser ? t("error_cancelled_by_user") : job.error || job.progress || "Background job failed.");
  }
}

function isCancelledJobMessage(message) {
  return typeof message === "string" && /cancelled/i.test(message);
}

function isActiveJobRunning() {
  return POPUP_JOB_STATE.isRunning();
}

function startJobStalenessCheck() {
  return POPUP_JOB_STATE.start();
}

function stopJobStalenessCheck() {
  return POPUP_JOB_STATE.stop();
}

async function checkJobStaleness() {
  return POPUP_JOB_STATE.check();
}

function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildFilename(prefix) {
  const now = new Date();
  const stamp = now.toISOString().replaceAll(":", "-").replace(/\.\d+Z$/, "Z");
  return `${prefix}_${stamp}.json`;
}

async function refreshSavedKeyStatus() {
  try {
    const record = await chromeStorageGet(ENCRYPTED_KEY_STORAGE_NAME);
    const draftRecord = await chromeStorageGet(ENCRYPTED_KEY_DRAFT_STORAGE_NAME);
    if (record) {
      if (record.version === 1) {
        updateKeyStorageStatus(t("key_old_migration"), "warning");
      } else {
        updateKeyStorageStatus(t("key_saved"), "ok");
      }
    } else if (draftRecord) {
      updateKeyStorageStatus(t("key_draft_available"), "warning");
    } else {
      updateKeyStorageStatus(t("key_none"), "");
    }
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  }
}

async function loadLlmSettings() {
  return POPUP_SETTINGS_STORE.loadLlmSettings();
}

async function loadUiDraft() {
  return POPUP_SETTINGS_STORE.loadUiDraft();
}

function applyUiDraft(draft) {
  if (draft.apiBaseUrl) {
    apiBaseUrlInput.value = draft.apiBaseUrl;
  }
  if (draft.apiStyle) {
    apiStyleInput.value = normalizeApiStyle(draft.apiStyle);
  }
  if (draft.model) {
    modelInput.value = draft.model;
  }
  requestTimeoutInput.value = draft.requestTimeout || DEFAULT_LLM_SETTINGS.requestTimeout;
  _pendingFocusPath = draft.focusPath || DEFAULT_UI_DRAFT.focusPath;
  maxActionsInput.value = draft.maxActions || DEFAULT_UI_DRAFT.maxActions;
  maxRetriesInput.value = draft.maxRetries ?? DEFAULT_UI_DRAFT.maxRetries;
  if (draft.userInstruction) {
    userInstructionInput.value = draft.userInstruction;
  }
  showTab(normalizeActiveTabName(draft.activeTab));
}

async function restoreEncryptedDraftApiKey() {
  try {
    const apiKey = await loadEncryptedApiKeyDraft();
    apiKeyInput.value = apiKey;
  } catch (_error) {
    try {
      apiKeyInput.value = await loadEncryptedApiKey();
    } catch (_savedKeyError) {
      apiKeyInput.value = "";
    }
  }
}

async function saveLlmSettings(settings) {
  await POPUP_SETTINGS_STORE.saveLlmSettings(settings);
}

function applyLlmSettings(settings) {
  apiBaseUrlInput.value = settings.apiBaseUrl;
  apiStyleInput.value = settings.apiStyle;
  modelInput.value = settings.model;
  requestTimeoutInput.value = settings.requestTimeout || DEFAULT_LLM_SETTINGS.requestTimeout;
}

function readLlmSettingsFromInputs() {
  return normalizeLlmSettings({
    apiBaseUrl: apiBaseUrlInput.value,
    apiStyle: apiStyleInput.value,
    model: modelInput.value,
    requestTimeout: requestTimeoutInput.value,
  });
}

function normalizeLlmSettings(settings) {
  return POPUP_SETTINGS_STORE.normalizeLlmSettings(settings);
}

function normalizeHttpsBaseUrl(value) {
  return POPUP_SETTINGS_STORE.normalizeHttpsBaseUrl(value);
}

function extractOrigin(apiBaseUrl) {
  return POPUP_SETTINGS_STORE.extractOrigin(apiBaseUrl);
}

async function checkHostPermission(origin) {
  return POPUP_SETTINGS_STORE.checkHostPermission(origin);
}

async function requestHostPermission(origin) {
  return POPUP_SETTINGS_STORE.requestHostPermission(origin);
}

async function ensureHostPermission(apiBaseUrl) {
  return POPUP_SETTINGS_STORE.ensureHostPermission(apiBaseUrl);
}

function normalizeApiStyle(value) {
  return POPUP_SETTINGS_STORE.normalizeApiStyle(value);
}

function updateEndpointPreview() {
  try {
    const baseUrl = normalizeHttpsBaseUrl(apiBaseUrlInput.value || DEFAULT_LLM_SETTINGS.apiBaseUrl);
    endpointPreviewEl.className = "hint";
    const exactEndpoint = coreEndpointKind(baseUrl);
    const apiStyle = normalizeApiStyle(apiStyleInput.value);
    if (exactEndpoint) {
      endpointPreviewEl.textContent = `Will call exact ${exactEndpoint} endpoint: ${baseUrl}.`;
    } else if (apiStyle === "responses") {
      endpointPreviewEl.textContent = `Will call ${baseUrl}/responses.`;
    } else if (apiStyle === "chat_completions") {
      endpointPreviewEl.textContent = `Will call ${baseUrl}/chat/completions.`;
    } else if (apiStyle === "completions") {
      endpointPreviewEl.textContent = `Will call ${baseUrl}/completions.`;
    } else {
      endpointPreviewEl.textContent = `Will try ${baseUrl}/chat/completions, then ${baseUrl}/completions, then ${baseUrl}/responses.`;
    }
  } catch (error) {
    endpointPreviewEl.className = "hint error";
    endpointPreviewEl.textContent = error instanceof Error ? error.message : String(error);
  }
}

function coreEndpointKind(apiBaseUrl) {
  const kind = POPUP_ENDPOINT.endpointKind(apiBaseUrl);
  return kind === "chat_completions" ? "chat/completions" : kind;
}

async function saveEncryptedApiKey(apiKey) {
  await POPUP_SECRETS.saveActiveKey(apiKey);
}

async function loadEncryptedApiKey() {
  try {
    return await POPUP_SECRETS.loadActiveKey();
  } catch (error) {
    throw localizeSecretError(error);
  }
}

async function saveEncryptedApiKeyDraft(apiKey) {
  await POPUP_SECRETS.saveDraft(apiKey);
}

async function loadEncryptedApiKeyDraft() {
  try {
    return await POPUP_SECRETS.loadDraft();
  } catch (error) {
    throw localizeSecretError(error);
  }
}

async function clearEncryptedApiKeyDraft() {
  await POPUP_SECRETS.clearDraft();
}

function draftStorageArea() {
  return POPUP_SECRETS.draftStorageArea();
}

function localizeSecretError(error) {
  const message = error instanceof Error ? error.message : String(error);
  const secrets = globalThis.BookmarkAdvisor.Popup.Secrets;
  if (message === secrets.NO_KEY_MESSAGE) {
    return new Error(t("key_no_key"));
  }
  if (message === secrets.OLD_KEY_MESSAGE) {
    return new Error(t("key_old_migration"));
  }
  return error instanceof Error ? error : new Error(message);
}

async function saveEncryptedSecret(storageName, value, area = chrome.storage.local) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveAutomaticStorageKey(salt);
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(value),
  );
  await chromeStorageSetFromArea(area, storageName, {
    version: 2,
    kdf: "SHA-256(runtime-id)",
    cipher: "AES-GCM",
    salt: bytesToBase64(salt),
    iv: bytesToBase64(iv),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
    created_at: new Date().toISOString(),
  });
}

async function loadEncryptedSecret(storageName, area = chrome.storage.local) {
  const record = await chromeStorageGetFromArea(area, storageName);
  if (!record) {
    throw new Error(t("key_no_key"));
  }
  if (record.version !== 2) {
    throw new Error(t("key_old_migration"));
  }
  const salt = base64ToBytes(record.salt);
  const iv = base64ToBytes(record.iv);
  const ciphertext = base64ToBytes(record.ciphertext);
  const key = await deriveAutomaticStorageKey(salt);
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv },
    key,
    ciphertext,
  );
  return new TextDecoder().decode(plaintext);
}

async function deriveAutomaticStorageKey(salt) {
  const material = [
    "bookmark-advisor-api-key-v2",
    chrome.runtime.id || "unpacked-extension",
    bytesToBase64(salt),
  ].join("\n");
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(material),
  );
  return crypto.subtle.importKey(
    "raw",
    digest,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

function chromeStorageGetFromArea(area, key) {
  return new Promise((resolve, reject) => {
    area.get(key, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(result[key]);
    });
  });
}

function chromeStorageSetFromArea(area, key, value) {
  return new Promise((resolve, reject) => {
    area.set({ [key]: value }, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve();
    });
  });
}

function chromeStorageRemoveFromArea(area, key) {
  return new Promise((resolve, reject) => {
    area.remove(key, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve();
    });
  });
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(String(value || ""));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function updateKeyStorageStatus(message, className) {
  keyStorageStatusEl.textContent = message;
  keyStorageStatusEl.className = className ? `hint ${className}` : "hint";
}
