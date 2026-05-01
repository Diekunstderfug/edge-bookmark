let loadedPlan = null;
let loadedSummary = null;
let lastExecutionReport = null;

const STRINGS = {
  en: {
    tab_plan: "Plan",
    tab_llm: "LLM",
    tab_prefs: "Preferences",
    label_ai_planning: "Generate organization plan",
    label_focus_folder: "Scope",
    label_user_instruction: "Organization notes",
    label_max_actions: "Max actions",
    btn_generate: "Generate AI Plan",
    btn_revise: "Revise Loaded Plan",
    btn_export: "Export Snapshot",
    btn_execute: "Execute Reviewed Plan",
    btn_download_report: "Download Execution Report",
    btn_save: "Save",
    btn_forget: "Forget Key",
    label_llm_config: "OpenAI-compatible LLM",
    label_api_url: "API base URL",
    label_endpoint_mode: "Endpoint mode",
    label_api_key: "API key",
    label_action_preview: "Action preview",
    label_preferences: "Preferences",
    label_language: "Language",
    label_protect_root: "Root loose bookmark protection",
    label_sort_order: "Post-organization sort",
    label_planning_style: "Planning style",
    status_no_plan: "No plan loaded.",
    status_checking_permission: "Checking API host permission...",
    status_exporting_bookmarks: "Exporting current bookmarks...",
    status_planning_background: "AI planning is running in the background. You can close and reopen this popup.",
    status_revising_exporting: "Exporting current bookmarks and revising the loaded plan...",
    status_revision_background: "Plan revision is running in the background. You can close and reopen this popup.",
    status_executing_plan: "Executing reviewed plan inside Edge...",
    status_execution_background: "Plan execution is running in the background. You can close and reopen this popup.",
    status_exporting_snapshot: "Exporting current Edge snapshot...",
    status_snapshot_exported: "Current snapshot exported.",
    status_restored_plan: "Restored last plan. Review before executing.",
    status_job_running: "Background job running...",
    status_plan_saved: "AI plan saved. Review before executing.",
    status_background_completed: "Background job completed.",
    error_need_api_base_url: "Set an HTTPS OpenAI-compatible API base URL in LLM Settings.",
    error_need_model: "Set a model name in LLM Settings.",
    error_need_api_key: "Paste an API key in LLM Settings, or save one encrypted locally first.",
    error_need_loaded_plan: "Load or generate a reviewed plan before asking the LLM to revise it.",
    error_need_revision_instruction: "Describe how the current plan should change before revising it.",
    key_enter_api_url: "Enter an HTTPS API base URL before saving.",
    key_enter_model: "Enter a model name before saving.",
    key_host_denied: "Host permission denied. Allow access to the API origin when prompted, then try again.",
    key_saved_with_key: "LLM settings saved. API key encrypted locally and cached for this popup.",
    key_saved_existing_key: "LLM settings saved. Existing encrypted API key kept.",
    key_saved_need_key: "LLM settings saved. Paste an API key and save again when ready.",
    key_removed: "Saved encrypted API key removed. LLM endpoint settings were kept.",
    key_loaded: "Encrypted API key loaded for this request.",
    key_draft_restored: "Encrypted draft API key restored for this request.",
    key_no_key: "No usable encrypted API key found. Paste one in Settings.",
    key_old_migration: "Older passphrase-protected key found. Paste the key and save again to migrate.",
    key_saved: "Encrypted API key saved locally. No unlock password is required.",
    key_draft_available: "Encrypted API key draft restored. Click Save Credentials to make it the active key.",
    key_none: "No encrypted API key saved.",
    stat_total: "Total",
    stat_executable: "Executable",
    stat_review: "Review",
    stat_errors: "Errors",
    stat_warnings: "Warnings",
    opt_all_bookmarks: "All bookmarks",
    opt_protect_yes: "Protected — do not auto-move root loose bookmarks",
    opt_protect_no: "Allowed — may move root loose bookmarks into subfolders",
    opt_sort_none: "No sorting (keep original order)",
    opt_sort_asc: "Alphabetical (A\u2192Z)",
    opt_sort_desc: "Reverse alphabetical (Z\u2192A)",
    opt_style_balanced: "Balanced — reasonable moves, uncertain items for review",
    opt_style_conservative: "Conservative — only highly confident moves",
    opt_style_aggressive: "Aggressive — organize everything, allow new folders",
    placeholder_instruction: "Example: keep work folders untouched; move React and JS docs into Programming; leave uncertain items for review.",
    cat_review: "Needs review",
    cat_review_hint: "Requires manual confirmation",
    action_move: "Move",
    action_rename: "Rename",
    action_create: "Create",
    action_dedup: "Dedup",
    action_review: "Review",
    confidence_high: "High confidence",
    confidence_medium: "Medium confidence",
    confidence_low: "Low confidence",
    lint_failed: "Plan failed lint with {n} error(s).",
    lint_warnings: "Plan passed lint with {n} warning(s).",
    lint_ok: "Reviewed plan validated. Approved actions can now run.",
    execution_applied: "Execution complete. Applied {n} actions.",
    execution_failures: "Execution complete with {n} failures.",
    execution_succeeded: "Succeeded:",
    execution_failed: "Failed:",
  },
  zh: {
    tab_plan: "\u8ba1\u5212",
    tab_llm: "LLM",
    tab_prefs: "\u504f\u597d",
    label_ai_planning: "生成整理计划",
    label_focus_folder: "整理范围",
    label_user_instruction: "整理要求",
    label_max_actions: "最多操作数",
    btn_generate: "\u751f\u6210 AI \u8ba1\u5212",
    btn_revise: "按要求修改计划",
    btn_export: "导出书签快照",
    btn_execute: "执行整理计划",
    btn_download_report: "\u4e0b\u8f7d\u6267\u884c\u62a5\u544a",
    btn_save: "\u4fdd\u5b58",
    btn_forget: "\u5220\u9664\u5bc6\u94a5",
    label_llm_config: "模型设置",
    label_api_url: "API 地址",
    label_endpoint_mode: "\u7aef\u70b9\u6a21\u5f0f",
    label_api_key: "API \u5bc6\u94a5",
    label_action_preview: "整理预览",
    label_preferences: "\u504f\u597d\u8bbe\u7f6e",
    label_language: "\u8bed\u8a00",
    label_protect_root: "\u9876\u5c42\u6563\u4e66\u7b7e\u4fdd\u62a4",
    label_sort_order: "\u6574\u7406\u540e\u6392\u5e8f",
    label_planning_style: "\u89c4\u5212\u98ce\u683c",
    status_no_plan: "还没有计划。",
    status_checking_permission: "\u6b63\u5728\u68c0\u67e5 API \u4e3b\u673a\u6743\u9650...",
    status_exporting_bookmarks: "\u6b63\u5728\u5bfc\u51fa\u5f53\u524d\u4e66\u7b7e...",
    status_planning_background: "正在后台生成计划，关闭弹窗也可以。",
    status_revising_exporting: "\u6b63\u5728\u5bfc\u51fa\u5f53\u524d\u4e66\u7b7e\u5e76\u4fee\u6539\u5df2\u52a0\u8f7d\u7684\u8ba1\u5212...",
    status_revision_background: "正在后台修改计划，关闭弹窗也可以。",
    status_executing_plan: "\u6b63\u5728 Edge \u4e2d\u6267\u884c\u5df2\u5ba1\u67e5\u7684\u8ba1\u5212...",
    status_execution_background: "正在后台执行计划，关闭弹窗也可以。",
    status_exporting_snapshot: "\u6b63\u5728\u5bfc\u51fa\u5f53\u524d Edge \u5feb\u7167...",
    status_snapshot_exported: "\u5f53\u524d\u5feb\u7167\u5df2\u5bfc\u51fa\u3002",
    status_restored_plan: "已恢复上次计划，请先检查再执行。",
    status_job_running: "\u540e\u53f0\u4efb\u52a1\u6b63\u5728\u8fd0\u884c...",
    status_plan_saved: "计划已保存，请先检查再执行。",
    status_background_completed: "\u540e\u53f0\u4efb\u52a1\u5df2\u5b8c\u6210\u3002",
    error_need_api_base_url: "请先在模型设置里填写 HTTPS API 地址。",
    error_need_model: "请先在模型设置里填写模型名称。",
    error_need_api_key: "请先在模型设置里填写或保存 API 密钥。",
    error_need_loaded_plan: "\u8bf7\u5148\u52a0\u8f7d\u6216\u751f\u6210\u5df2\u5ba1\u67e5\u7684\u8ba1\u5212\uff0c\u518d\u8ba9 LLM \u4fee\u6539\u3002",
    error_need_revision_instruction: "\u8bf7\u5148\u63cf\u8ff0\u5f53\u524d\u8ba1\u5212\u5e94\u8be5\u5982\u4f55\u66f4\u6539\uff0c\u518d\u8fdb\u884c\u4fee\u6539\u3002",
    key_enter_api_url: "\u8bf7\u5148\u8f93\u5165 HTTPS API \u57fa\u5730\u5740\u518d\u4fdd\u5b58\u3002",
    key_enter_model: "\u8bf7\u5148\u8f93\u5165\u6a21\u578b\u540d\u79f0\u518d\u4fdd\u5b58\u3002",
    key_host_denied: "\u4e3b\u673a\u6743\u9650\u88ab\u62d2\u7edd\u3002\u8bf7\u5728\u63d0\u793a\u65f6\u5141\u8bb8\u8bbf\u95ee API \u6e90\uff0c\u7136\u540e\u518d\u8bd5\u4e00\u6b21\u3002",
    key_saved_with_key: "LLM \u8bbe\u7f6e\u5df2\u4fdd\u5b58\u3002API \u5bc6\u94a5\u5df2\u5728\u672c\u5730\u52a0\u5bc6\u5e76\u7f13\u5b58\u5230\u6b64\u5f39\u7a97\u3002",
    key_saved_existing_key: "LLM \u8bbe\u7f6e\u5df2\u4fdd\u5b58\u3002\u5df2\u6709\u7684\u52a0\u5bc6 API \u5bc6\u94a5\u5df2\u4fdd\u7559\u3002",
    key_saved_need_key: "LLM \u8bbe\u7f6e\u5df2\u4fdd\u5b58\u3002\u8bf7\u7c98\u8d34 API \u5bc6\u94a5\u540e\u518d\u4fdd\u5b58\u3002",
    key_removed: "\u5df2\u5220\u9664\u4fdd\u5b58\u7684 API \u5bc6\u94a5\uff0cLLM \u7aef\u70b9\u8bbe\u7f6e\u5df2\u4fdd\u7559\u3002",
    key_loaded: "\u5df2\u4e3a\u672c\u6b21\u8bf7\u6c42\u52a0\u8f7d\u52a0\u5bc6 API \u5bc6\u94a5\u3002",
    key_draft_restored: "\u5df2\u6062\u590d\u52a0\u5bc6\u8349\u7a3f API \u5bc6\u94a5\uff0c\u53ef\u4f9b\u672c\u6b21\u8bf7\u6c42\u4f7f\u7528\u3002",
    key_no_key: "\u672a\u627e\u5230\u53ef\u7528\u7684\u52a0\u5bc6 API \u5bc6\u94a5\uff0c\u8bf7\u5728\u8bbe\u7f6e\u91cc\u7c98\u8d34\u4e00\u4e2a\u3002",
    key_old_migration: "\u627e\u5230\u8f83\u65e7\u7684\u53e3\u4ee4\u77ed\u8bed\u52a0\u5bc6\u5bc6\u94a5\uff0c\u8bf7\u7c98\u8d34\u5bc6\u94a5\u540e\u91cd\u65b0\u4fdd\u5b58\u4ee5\u8fc1\u79fb\u3002",
    key_saved: "\u52a0\u5bc6 API \u5bc6\u94a5\u5df2\u672c\u5730\u4fdd\u5b58\uff0c\u65e0\u9700\u89e3\u9501\u53e3\u4ee4\u3002",
    key_draft_available: "\u52a0\u5bc6 API \u5bc6\u94a5\u8349\u7a3f\u5df2\u6062\u590d\uff0c\u70b9\u51fb\u201c\u4fdd\u5b58\u201d\u4ee5\u4f7f\u5176\u6210\u4e3a\u5f53\u524d\u5bc6\u94a5\u3002",
    key_none: "\u672a\u4fdd\u5b58\u52a0\u5bc6 API \u5bc6\u94a5\u3002",
    stat_total: "\u603b\u8ba1",
    stat_executable: "\u53ef\u6267\u884c",
    stat_review: "\u5f85\u5ba1\u67e5",
    stat_errors: "\u9519\u8bef",
    stat_warnings: "\u8b66\u544a",
    opt_all_bookmarks: "\u5168\u90e8\u4e66\u7b7e",
    opt_protect_yes: "\u4fdd\u62a4 \u2014 \u4e0d\u81ea\u52a8\u6574\u7406\u6839\u76ee\u5f55\u4e0b\u7684\u6563\u4e66\u7b7e",
    opt_protect_no: "\u5141\u8bb8 \u2014 \u53ef\u5c06\u6839\u76ee\u5f55\u6563\u4e66\u7b7e\u5f52\u5165\u5b50\u6587\u4ef6\u5939",
    opt_sort_none: "\u4e0d\u6539\u53d8\u987a\u5e8f\uff08\u4fdd\u6301\u539f\u6837\uff09",
    opt_sort_asc: "\u6309\u6807\u9898\u5b57\u6bcd\u5347\u5e8f (A\u2192Z)",
    opt_sort_desc: "\u6309\u6807\u9898\u5b57\u6bcd\u964d\u5e8f (Z\u2192A)",
    opt_style_balanced: "\u5747\u8861 \u2014 \u5408\u7406\u79fb\u52a8\uff0c\u4e0d\u786e\u5b9a\u7684\u4fdd\u7559\u5ba1\u67e5",
    opt_style_conservative: "\u4fdd\u5b88 \u2014 \u53ea\u79fb\u52a8\u975e\u5e38\u786e\u5b9a\u7684\uff0c\u5176\u4f59\u4fdd\u6301\u539f\u4f4d",
    opt_style_aggressive: "\u79ef\u6781 \u2014 \u5c3d\u91cf\u5168\u90e8\u5f52\u7c7b\uff0c\u5141\u8bb8\u521b\u5efa\u65b0\u6587\u4ef6\u5939",
    placeholder_instruction: "例如：工作区不要动；React/JS 文档放进编程；不确定的先保留审查。",
    cat_review: "\u9700\u8981\u5ba1\u67e5",
    cat_review_hint: "\u9700\u4eba\u5de5\u786e\u8ba4\u6216\u8865\u5145\u4fe1\u606f",
    action_move: "\u79fb\u52a8",
    action_rename: "\u91cd\u547d\u540d",
    action_create: "\u521b\u5efa",
    action_dedup: "\u53bb\u91cd",
    action_review: "\u5ba1\u67e5",
    confidence_high: "\u9ad8\u7f6e\u4fe1\u5ea6",
    confidence_medium: "\u4e2d\u7b49\u7f6e\u4fe1\u5ea6",
    confidence_low: "\u4f4e\u7f6e\u4fe1\u5ea6",
    lint_failed: "\u8ba1\u5212\u672a\u901a\u8fc7\u68c0\u67e5\uff0c\u6709 {n} \u4e2a\u9519\u8bef\u3002",
    lint_warnings: "\u8ba1\u5212\u5df2\u901a\u8fc7\u68c0\u67e5\uff0c\u6709 {n} \u4e2a\u8b66\u544a\u3002",
    lint_ok: "\u8ba1\u5212\u5df2\u901a\u8fc7\u5ba1\u67e5\uff0c\u53ef\u6267\u884c\u5df2\u6279\u51c6\u7684\u64cd\u4f5c\u3002",
    execution_applied: "\u6267\u884c\u5b8c\u6210\uff0c\u5df2\u5e94\u7528 {n} \u4e2a\u64cd\u4f5c\u3002",
    execution_failures: "\u6267\u884c\u5b8c\u6210\uff0c\u6709 {n} \u4e2a\u5931\u8d25\u3002",
    execution_succeeded: "\u6210\u529f:",
    execution_failed: "\u5931\u8d25:",
  },
};

let currentLang = "zh";

function t(key) {
  return (STRINGS[currentLang] && STRINGS[currentLang][key]) || STRINGS.en[key] || key;
}

function applyLanguage(lang) {
  currentLang = ["zh", "en"].includes(lang) ? lang : "zh";
  document.querySelectorAll("[data-i18n]").forEach(function(el) {
    var key = el.getAttribute("data-i18n");
    if (key) el.textContent = t(key);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function(el) {
    var key = el.getAttribute("data-i18n-placeholder");
    if (key) el.placeholder = t(key);
  });
}

const ENCRYPTED_KEY_STORAGE_NAME = "bookmarkAdvisorOpenAIKey";
const ENCRYPTED_KEY_DRAFT_STORAGE_NAME = "bookmarkAdvisorOpenAIKeyDraft";
const LLM_SETTINGS_STORAGE_NAME = "bookmarkAdvisorLlmSettings";
const UI_DRAFT_STORAGE_NAME = "bookmarkAdvisorPopupDraft";
const PREFERENCES_STORAGE_NAME = "bookmarkAdvisorPreferences";
const RUNTIME_MESSAGE_TIMEOUT_MS = 240000;
const DEFAULT_LLM_SETTINGS = {
  apiBaseUrl: "https://api.openai.com/v1",
  apiStyle: "auto",
  model: "gpt-4o-mini",
};
const DEFAULT_PREFERENCES = {
  protectRootLooseBookmarks: "yes",
  sortOrder: "none",
  planningStyle: "balanced",
  lang: "zh",
};
const DEFAULT_UI_DRAFT = {
  activeTab: "plan",
  focusPath: "",
  maxActions: "40",
};
const REVIEW_CATEGORY_KEY = "__review__";

const fileInput = document.getElementById("plan-file");
const apiKeyInput = document.getElementById("api-key");
const apiBaseUrlInput = document.getElementById("api-base-url");
const apiStyleInput = document.getElementById("api-style");
const endpointPreviewEl = document.getElementById("endpoint-preview");
const keyStorageStatusEl = document.getElementById("key-storage-status");
const modelInput = document.getElementById("model");
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
const previewListEl = document.getElementById("preview-list");
const executeButton = document.getElementById("execute-btn");
const exportSnapshotButton = document.getElementById("export-snapshot-btn");
const generateAiButton = document.getElementById("generate-ai-btn");
const reviseAiButton = document.getElementById("revise-ai-btn");
const saveCredentialsButton = document.getElementById("save-credentials-btn");
const forgetKeyButton = document.getElementById("forget-key-btn");
const downloadReportButton = document.getElementById("download-report-btn");
const spinnerEl = document.getElementById("spinner");
const planTabButton = document.getElementById("plan-tab-btn");
const settingsTabButton = document.getElementById("settings-tab-btn");
const preferencesTabButton = document.getElementById("preferences-tab-btn");
const planTab = document.getElementById("plan-tab");
const settingsTab = document.getElementById("settings-tab");
const preferencesTab = document.getElementById("preferences-tab");
const prefProtectRoot = document.getElementById("pref-protect-root");
const prefSortOrder = document.getElementById("pref-sort-order");
const prefPlanningStyle = document.getElementById("pref-planning-style");
const prefLang = document.getElementById("pref-lang");
let restoringInputs = false;
let cacheWriteInFlight = false;
let cacheWriteQueued = false;
let activeBackgroundJob = null;

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
    if (apiKeyInput.value.trim()) {
      await saveEncryptedApiKey(apiKeyInput.value.trim());
      await saveEncryptedApiKeyDraft(apiKeyInput.value.trim());
      requestInputCacheWrite();
      updateKeyStorageStatus(t("key_saved_with_key"), "ok");
    } else {
      const savedKey = await chromeStorageGet(ENCRYPTED_KEY_STORAGE_NAME);
      updateKeyStorageStatus(
        savedKey
          ? t("key_saved_existing_key")
          : t("key_saved_need_key"),
        savedKey ? "ok" : "warning",
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
    await chromeStorageRemove(ENCRYPTED_KEY_DRAFT_STORAGE_NAME);
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
    showTab("settings", { persist: true });
    return;
  }
  if (!settings.apiBaseUrl) {
    renderError(t("error_need_api_base_url"));
    showTab("settings", { persist: true });
    return;
  }
  if (!settings.model) {
    renderError(t("error_need_model"));
    showTab("settings", { persist: true });
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
    showTab("settings", { persist: true });
    return;
  }

  generateAiButton.disabled = true;
  reviseAiButton.disabled = true;
  executeButton.disabled = true;
  updateStatus(t("status_checking_permission"), "");
  showSpinner();

  function onStorageChange(changes, areaName) {
    if (areaName !== "local") return;
    const progress = changes.bookmarkAdvisorProgress;
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
    const response = await startBackgroundJobAndRender("generate-ai-plan", {
      options: {
        apiKey,
        apiBaseUrl: settings.apiBaseUrl,
        apiStyle: settings.apiStyle,
        model: settings.model,
        maxActions: maxActionsInput.value,
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
  const userInstruction = userInstructionInput.value.trim();
  if (!userInstruction) {
    renderError(t("error_need_revision_instruction"));
    return;
  }

  let settings;
  try {
    settings = readLlmSettingsFromInputs();
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
    showTab("settings", { persist: true });
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
    showTab("settings", { persist: true });
    return;
  }

  generateAiButton.disabled = true;
  reviseAiButton.disabled = true;
  executeButton.disabled = true;
  updateStatus(t("status_checking_permission"), "");
  showSpinner();

  function onStorageChange(changes, areaName) {
    if (areaName !== "local") return;
    const progress = changes.bookmarkAdvisorProgress;
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
    const response = await startBackgroundJobAndRender("revise-ai-plan", {
      plan: loadedPlan,
      options: {
        apiKey,
        apiBaseUrl: settings.apiBaseUrl,
        apiStyle: settings.apiStyle,
        model: settings.model,
        maxActions: maxActionsInput.value,
        focusPath: focusPathInput.value,
        userInstruction,
        preferences: readPreferences(),
      },
    });
    if (response && response.error) {
      throw new Error(response.error);
    }
    updateStatus(t("status_revision_background"), "");
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
    const progress = changes.bookmarkAdvisorProgress;
    if (progress && progress.newValue) {
      updateStatus(progress.newValue.message || t("status_job_running"), "");
    }
  }
  chrome.storage.onChanged.addListener(onStorageChange);

  try {
    await startBackgroundJobAndRender("apply-reviewed-plan", {
      plan: loadedPlan,
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

exportSnapshotButton.addEventListener("click", async () => {
  exportSnapshotButton.disabled = true;
  updateStatus(t("status_exporting_snapshot"), "");
  showSpinner();
  try {
    const response = await sendRuntimeMessage({
      type: "export-snapshot",
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
  planTabButton.addEventListener("click", () => showTab("plan", { persist: true }));
  settingsTabButton.addEventListener("click", () => showTab("settings", { persist: true }));
  preferencesTabButton.addEventListener("click", () => showTab("preferences", { persist: true }));
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
    const activeJobResponse = await sendRuntimeMessage({ type: "get-active-job" }, 5000);
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
  const fields = [
    apiBaseUrlInput,
    apiStyleInput,
    modelInput,
    apiKeyInput,
    focusPathInput,
    maxActionsInput,
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
  window.addEventListener("pagehide", () => {
    persistUiDraftSnapshotNow();
    requestInputCacheWrite();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      persistUiDraftSnapshotNow();
      requestInputCacheWrite();
    }
  });
  window.addEventListener("blur", () => {
    persistUiDraftSnapshotNow();
    requestInputCacheWrite();
  });
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
  await chromeStorageSet(UI_DRAFT_STORAGE_NAME, buildUiDraftSnapshot());

  const apiKeyDraft = apiKeyInput.value.trim();
  if (apiKeyDraft) {
    await saveEncryptedApiKeyDraft(apiKeyDraft);
  } else {
    await chromeStorageRemove(ENCRYPTED_KEY_DRAFT_STORAGE_NAME);
  }
}

function buildUiDraftSnapshot() {
  return {
    version: 2,
    activeTab: !planTab.hidden ? "plan" : !settingsTab.hidden ? "settings" : "preferences",
    apiBaseUrl: apiBaseUrlInput.value,
    apiStyle: apiStyleInput.value,
    model: modelInput.value,
    focusPath: focusPathInput.value,
    maxActions: maxActionsInput.value,
    userInstruction: userInstructionInput.value,
    updated_at: new Date().toISOString(),
  };
}

function persistUiDraftSnapshotNow() {
  if (restoringInputs) {
    return;
  }
  void chromeStorageSet(UI_DRAFT_STORAGE_NAME, buildUiDraftSnapshot()).catch((error) => {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  });
}

function showTab(name, options = {}) {
  const showSettings = name === "settings";
  const showPreferences = name === "preferences";
  planTab.hidden = showSettings || showPreferences;
  settingsTab.hidden = !showSettings;
  preferencesTab.hidden = !showPreferences;
  planTabButton.classList.toggle("active", !showSettings && !showPreferences);
  settingsTabButton.classList.toggle("active", showSettings);
  preferencesTabButton.classList.toggle("active", showPreferences);
  planTabButton.setAttribute("aria-selected", String(!showSettings && !showPreferences));
  settingsTabButton.setAttribute("aria-selected", String(showSettings));
  preferencesTabButton.setAttribute("aria-selected", String(showPreferences));
  if (options.persist) {
    persistUiDraftSnapshotNow();
    requestInputCacheWrite();
  }
}

async function loadFolderList() {
  try {
    const response = await sendRuntimeMessage({ type: "list-folders" }, 10000);
    if (response && response.folders) {
      populateFolderDropdown(response.folders);
    }
  } catch (_error) {
    // folder list is best-effort; text input fallback still works
  }
}

function populateFolderDropdown(folders) {
  const current = focusPathInput.value;
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
  }
}

async function loadPreferences() {
  const saved = await preferencesStorageGet();
  if (!saved || typeof saved !== "object") {
    return { ...DEFAULT_PREFERENCES };
  }
  return {
    protectRootLooseBookmarks: ["yes", "no"].includes(saved.protectRootLooseBookmarks) ? saved.protectRootLooseBookmarks : DEFAULT_PREFERENCES.protectRootLooseBookmarks,
    sortOrder: ["none", "alpha-asc", "alpha-desc"].includes(saved.sortOrder) ? saved.sortOrder : DEFAULT_PREFERENCES.sortOrder,
    planningStyle: ["balanced", "conservative", "aggressive"].includes(saved.planningStyle) ? saved.planningStyle : DEFAULT_PREFERENCES.planningStyle,
    lang: ["zh", "en"].includes(saved.lang) ? saved.lang : DEFAULT_PREFERENCES.lang,
  };
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
    await preferencesStorageSet(readPreferences());
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

  statsEl.hidden = false;
  totalCountEl.textContent = String(summary.totalActions);
  executableCountEl.textContent = String(summary.executableActions.length);
  reviewCountEl.textContent = String(summary.reviewActions.length);
  errorCountEl.textContent = String(summary.errors.length);
  warningCountEl.textContent = String(summary.warnings.length);

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
  renderSummary(summary);
  executeButton.disabled = !summary.ok || summary.executableActions.length === 0;
  reviseAiButton.disabled = false;
}

function groupActionsByCategory(actions) {
  const groups = new Map();

  for (const action of actions) {
    const key = categoryKeyForAction(action);
    if (!groups.has(key)) {
      groups.set(key, { key, path: key, actions: [] });
    }
    groups.get(key).actions.push(action);
  }

  return Array.from(groups.values());
}

function categoryKeyForAction(action) {
  const type = String(action.action_type || "");
  if (type === "move_bookmark" || type === "move_folder") {
    return String(action.to_path || "/unclassified");
  }
  if (type === "create_folder") {
    return String(action.target_path || "/unclassified");
  }
  if (type === "rename_folder") {
    return String(action.from_path || "/unclassified");
  }
  if (type === "remove_duplicate") {
    return String(action.from_path || "/unclassified");
  }
  return REVIEW_CATEGORY_KEY;
}

function sortCategories(categories) {
  return categories.slice().sort((a, b) => {
    const aIsReview = a.key === REVIEW_CATEGORY_KEY;
    const bIsReview = b.key === REVIEW_CATEGORY_KEY;
    if (aIsReview && !bIsReview) return 1;
    if (!aIsReview && bIsReview) return -1;
    return b.actions.length - a.actions.length;
  });
}

function buildCategoryElement(category) {
  const isReview = category.key === REVIEW_CATEGORY_KEY;
  const displayName = isReview ? t("cat_review") : lastSegment(category.path);
  const subtitle = isReview ? t("cat_review_hint") : category.path;
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
    details.appendChild(buildActionItem(action, isReview));
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

function buildActionItem(action, isReview) {
  const type = String(action.action_type || "");
  const title = actionTitle(action);
  const reason = String(action.reason || "");
  const confidence = Number(action.confidence);
  const fromPath = String(action.from_path || "");
  const toPath = String(action.to_path || action.target_path || action.to_name || "");

  const item = document.createElement("div");
  item.className = "action-item";

  const titleEl = document.createElement("div");
  titleEl.className = "action-title";
  titleEl.textContent = title;

  const metaEl = document.createElement("div");
  metaEl.className = "action-meta";

  const typeLabel = document.createElement("span");
  typeLabel.className = "action-type-label" + (isReview ? " review" : "");
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

  const reasonEl = document.createElement("div");
  reasonEl.className = "action-reason";
  reasonEl.textContent = reason;

  item.appendChild(titleEl);
  item.appendChild(metaEl);
  if (reason) {
    item.appendChild(reasonEl);
  }
  return item;
}

function actionTitle(action) {
  const locator = action.bookmark_locator || {};
  const folderLocator = action.folder_locator || {};
  return locator.title || folderLocator.name || String(action.action_type || "");
}

function actionTypeLabel(type) {
  switch (type) {
    case "move_bookmark": return t("action_move");
    case "move_folder": return t("action_move");
    case "rename_folder": return t("action_rename");
    case "create_folder": return t("action_create");
    case "remove_duplicate": return t("action_dedup");
    case "keep_for_review": return t("action_review");
    default: return type;
  }
}

function confidenceClass(value) {
  if (value >= 0.85) return "high";
  if (value >= 0.5) return "medium";
  return "low";
}

function lastSegment(path) {
  if (!path || path === REVIEW_CATEGORY_KEY) return path || "";
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || "/";
}

function renderExecutionResult(report) {
  const failures = report.failures || [];
  const succeeded = report.succeeded || [];
  lastExecutionReport = report;
  downloadReportButton.disabled = false;
  saveLastReport(report);
  statusEl.className = failures.length === 0 ? "ok" : "error";
  statusEl.textContent =
    failures.length === 0
      ? t("execution_applied").replace("{n}", succeeded.length)
      : t("execution_failures").replace("{n}", failures.length);

  previewListEl.innerHTML = "";
  const list = document.createElement("ul");
  const items = [
    `${t("execution_succeeded")} ${succeeded.length}`,
    `${t("execution_failed")} ${failures.length}`,
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
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      reject(new Error("Extension background task timed out. Reload the extension and check that Bookmark permission is enabled."));
    }, timeoutMs);
    chrome.runtime.sendMessage(payload, (response) => {
      clearTimeout(timeoutId);
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

async function startBackgroundJobAndRender(jobType, payload) {
  const response = await sendRuntimeMessage({
    type: "start-background-job",
    job_type: jobType,
    payload,
  }, 10000);
  if (response && response.error) {
    throw new Error(response.error);
  }
  if (!response || !response.job) {
    throw new Error("Background executor did not return a job record.");
  }
  handleJobRecord(response.job);
  return response;
}

function handleBackgroundJobStorageChange(changes, areaName) {
  if (areaName !== "local") return;
  const activeJob = changes[ACTIVE_JOB_STORAGE_NAME];
  if (activeJob && activeJob.newValue) {
    handleJobRecord(activeJob.newValue);
  }
}

function handleJobRecord(job) {
  activeBackgroundJob = job || null;
  if (!job) {
    return;
  }
  if (job.status === "running") {
    generateAiButton.disabled = true;
    reviseAiButton.disabled = true;
    executeButton.disabled = true;
    showSpinner();
    updateStatus(job.progress || t("status_job_running"), "");
    return;
  }
  if (job.status === "succeeded") {
    hideSpinner();
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
  if (job.status === "failed") {
    hideSpinner();
    generateAiButton.disabled = false;
    reviseAiButton.disabled = !loadedPlan;
    executeButton.disabled = !loadedSummary || !loadedSummary.ok || loadedSummary.executableActions.length === 0;
    renderError(job.error || job.progress || "Background job failed.");
  }
}

function isActiveJobRunning() {
  return !!activeBackgroundJob && activeBackgroundJob.status === "running";
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
  const saved = await chromeStorageGet(LLM_SETTINGS_STORAGE_NAME);
  if (!saved || typeof saved !== "object") {
    return { ...DEFAULT_LLM_SETTINGS };
  }
  return normalizeLlmSettings({
    ...DEFAULT_LLM_SETTINGS,
    ...saved,
  });
}

async function loadUiDraft() {
  const saved = await chromeStorageGet(UI_DRAFT_STORAGE_NAME);
  if (!saved || typeof saved !== "object") {
    return { ...DEFAULT_UI_DRAFT };
  }
  return {
    activeTab: ["plan", "settings", "preferences"].includes(saved.activeTab) ? saved.activeTab : DEFAULT_UI_DRAFT.activeTab,
    apiBaseUrl: typeof saved.apiBaseUrl === "string" ? saved.apiBaseUrl : "",
    apiStyle: typeof saved.apiStyle === "string" ? saved.apiStyle : "",
    model: typeof saved.model === "string" ? saved.model : "",
    focusPath: typeof saved.focusPath === "string" ? saved.focusPath : DEFAULT_UI_DRAFT.focusPath,
    maxActions: typeof saved.maxActions === "string" ? saved.maxActions : DEFAULT_UI_DRAFT.maxActions,
    userInstruction: typeof saved.userInstruction === "string" ? saved.userInstruction : "",
  };
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
  focusPathInput.value = draft.focusPath || DEFAULT_UI_DRAFT.focusPath;
  maxActionsInput.value = draft.maxActions || DEFAULT_UI_DRAFT.maxActions;
  if (draft.userInstruction) {
    userInstructionInput.value = draft.userInstruction;
  }
  showTab(["plan", "settings", "preferences"].includes(draft.activeTab) ? draft.activeTab : DEFAULT_UI_DRAFT.activeTab);
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
  await chromeStorageSet(LLM_SETTINGS_STORAGE_NAME, normalizeLlmSettings(settings));
}

function applyLlmSettings(settings) {
  apiBaseUrlInput.value = settings.apiBaseUrl;
  apiStyleInput.value = settings.apiStyle;
  modelInput.value = settings.model;
}

function readLlmSettingsFromInputs() {
  return normalizeLlmSettings({
    apiBaseUrl: apiBaseUrlInput.value,
    apiStyle: apiStyleInput.value,
    model: modelInput.value,
  });
}

function normalizeLlmSettings(settings) {
  return {
    apiBaseUrl: normalizeHttpsBaseUrl(settings.apiBaseUrl || DEFAULT_LLM_SETTINGS.apiBaseUrl),
    apiStyle: normalizeApiStyle(settings.apiStyle || DEFAULT_LLM_SETTINGS.apiStyle),
    model: String(settings.model || DEFAULT_LLM_SETTINGS.model).trim(),
  };
}

function normalizeHttpsBaseUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  let parsed;
  try {
    parsed = new URL(raw);
  } catch (_error) {
    throw new Error("API base URL must be a valid https:// URL.");
  }
  if (parsed.protocol !== "https:") {
    throw new Error("API base URL must use https://.");
  }
  parsed.hash = "";
  parsed.search = "";
  parsed.pathname = parsed.pathname.replace(/\/+$/, "");
  return parsed.toString().replace(/\/+$/, "");
}

function extractOrigin(apiBaseUrl) {
  const normalized = normalizeHttpsBaseUrl(apiBaseUrl);
  if (!normalized) {
    return "";
  }
  const parsed = new URL(normalized);
  return parsed.origin + "/*";
}

async function checkHostPermission(origin) {
  if (!origin || typeof chrome === "undefined" || !chrome.permissions) {
    return false;
  }
  return new Promise((resolve) => {
    chrome.permissions.contains({ origins: [origin] }, (granted) => {
      resolve(!!granted);
    });
  });
}

async function requestHostPermission(origin) {
  if (!origin || typeof chrome === "undefined" || !chrome.permissions) {
    return false;
  }
  return new Promise((resolve) => {
    chrome.permissions.request({ origins: [origin] }, (granted) => {
      resolve(!!granted);
    });
  });
}

async function ensureHostPermission(apiBaseUrl) {
  const origin = extractOrigin(apiBaseUrl);
  if (!origin) {
    return false;
  }
  const alreadyGranted = await checkHostPermission(origin);
  if (alreadyGranted) {
    return true;
  }
  return requestHostPermission(origin);
}

function normalizeApiStyle(value) {
  const style = String(value || "").trim();
  return ["auto", "responses", "chat_completions", "completions"].includes(style) ? style : "auto";
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
      endpointPreviewEl.textContent = `Will try ${baseUrl}/responses, ${baseUrl}/chat/completions, then ${baseUrl}/completions.`;
    }
  } catch (error) {
    endpointPreviewEl.className = "hint error";
    endpointPreviewEl.textContent = error instanceof Error ? error.message : String(error);
  }
}

function coreEndpointKind(apiBaseUrl) {
  let parsed;
  try {
    parsed = new URL(normalizeHttpsBaseUrl(apiBaseUrl));
  } catch (_error) {
    return "";
  }
  const pathname = parsed.pathname.replace(/\/+$/, "");
  if (pathname.endsWith("/chat/completions")) {
    return "chat/completions";
  }
  if (pathname.endsWith("/responses")) {
    return "responses";
  }
  if (pathname.endsWith("/completions")) {
    return "completions";
  }
  return "";
}

async function saveEncryptedApiKey(apiKey) {
  await saveEncryptedSecret(ENCRYPTED_KEY_STORAGE_NAME, apiKey);
}

async function loadEncryptedApiKey() {
  return loadEncryptedSecret(ENCRYPTED_KEY_STORAGE_NAME);
}

async function saveEncryptedApiKeyDraft(apiKey) {
  await saveEncryptedSecret(ENCRYPTED_KEY_DRAFT_STORAGE_NAME, apiKey);
}

async function loadEncryptedApiKeyDraft() {
  return loadEncryptedSecret(ENCRYPTED_KEY_DRAFT_STORAGE_NAME);
}

async function saveEncryptedSecret(storageName, value) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveAutomaticStorageKey(salt);
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(value),
  );
  await chromeStorageSet(storageName, {
    version: 2,
    kdf: "SHA-256(runtime-id)",
    cipher: "AES-GCM",
    salt: bytesToBase64(salt),
    iv: bytesToBase64(iv),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
    created_at: new Date().toISOString(),
  });
}

async function loadEncryptedSecret(storageName) {
  const record = await chromeStorageGet(storageName);
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

function chromeStorageRemove(key) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.remove(key, () => {
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
