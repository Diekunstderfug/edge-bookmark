let loadedPlan = null;
let loadedSummary = null;
let lastExecutionReport = null;

const ENCRYPTED_KEY_STORAGE_NAME = "bookmarkAdvisorOpenAIKey";
const ENCRYPTED_KEY_DRAFT_STORAGE_NAME = "bookmarkAdvisorOpenAIKeyDraft";
const LLM_SETTINGS_STORAGE_NAME = "bookmarkAdvisorLlmSettings";
const UI_DRAFT_STORAGE_NAME = "bookmarkAdvisorPopupDraft";
const DEFAULT_LLM_SETTINGS = {
  apiBaseUrl: "https://api.openai.com/v1",
  apiStyle: "auto",
  model: "gpt-4o-mini",
};
const DEFAULT_UI_DRAFT = {
  activeTab: "plan",
  focusPath: "/收藏夹栏/奇妙小工具",
  maxActions: "40",
};

const fileInput = document.getElementById("plan-file");
const apiKeyInput = document.getElementById("api-key");
const apiBaseUrlInput = document.getElementById("api-base-url");
const apiStyleInput = document.getElementById("api-style");
const endpointPreviewEl = document.getElementById("endpoint-preview");
const keyStorageStatusEl = document.getElementById("key-storage-status");
const modelInput = document.getElementById("model");
const maxActionsInput = document.getElementById("max-actions");
const focusPathInput = document.getElementById("focus-path");
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
const saveCredentialsButton = document.getElementById("save-credentials-btn");
const forgetKeyButton = document.getElementById("forget-key-btn");
const downloadReportButton = document.getElementById("download-report-btn");
const planTabButton = document.getElementById("plan-tab-btn");
const settingsTabButton = document.getElementById("settings-tab-btn");
const planTab = document.getElementById("plan-tab");
const settingsTab = document.getElementById("settings-tab");
let restoringInputs = false;
let cacheWriteInFlight = false;
let cacheWriteQueued = false;

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
  } catch (error) {
    loadedPlan = null;
    loadedSummary = null;
    lastExecutionReport = null;
    downloadReportButton.disabled = true;
    renderError(error instanceof Error ? error.message : String(error));
    executeButton.disabled = true;
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
    updateKeyStorageStatus("Enter an HTTPS API base URL before saving.", "error");
    return;
  }
  if (!settings.model) {
    updateKeyStorageStatus("Enter a model name before saving.", "error");
    return;
  }

  saveCredentialsButton.disabled = true;
  try {
    const hostGranted = await ensureHostPermission(settings.apiBaseUrl);
    if (!hostGranted) {
      updateKeyStorageStatus("Host permission denied. Allow access to the API origin when prompted, then try again.", "error");
      return;
    }
    await saveLlmSettings(settings);
    if (apiKeyInput.value.trim()) {
      await saveEncryptedApiKey(apiKeyInput.value.trim());
      await saveEncryptedApiKeyDraft(apiKeyInput.value.trim());
      requestInputCacheWrite();
      updateKeyStorageStatus("LLM settings saved. API key encrypted locally and cached for this popup.", "ok");
    } else {
      const savedKey = await chromeStorageGet(ENCRYPTED_KEY_STORAGE_NAME);
      updateKeyStorageStatus(
        savedKey
          ? "LLM settings saved. Existing encrypted API key kept."
          : "LLM settings saved. Paste an API key and save again when ready.",
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
    updateKeyStorageStatus("Saved encrypted API key removed. LLM endpoint settings were kept.", "warning");
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
    renderError("Set an HTTPS OpenAI-compatible API base URL in LLM Settings.");
    showTab("settings", { persist: true });
    return;
  }
  if (!settings.model) {
    renderError("Set a model name in LLM Settings.");
    showTab("settings", { persist: true });
    return;
  }

  let apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    try {
      apiKey = await loadEncryptedApiKey();
      updateKeyStorageStatus("Encrypted API key loaded for this request.", "ok");
    } catch (_savedKeyError) {
      try {
        apiKey = await loadEncryptedApiKeyDraft();
        apiKeyInput.value = apiKey;
        updateKeyStorageStatus("Encrypted draft API key restored for this request.", "warning");
      } catch (_draftKeyError) {
        updateKeyStorageStatus("No usable encrypted API key found. Paste one in Settings.", "error");
      }
    }
  }
  if (!apiKey) {
    renderError("Paste an API key in LLM Settings, or save one encrypted locally first.");
    showTab("settings", { persist: true });
    return;
  }

  generateAiButton.disabled = true;
  executeButton.disabled = true;
  statusEl.textContent = "Exporting current bookmarks and asking the configured LLM for a reviewed plan...";
  statusEl.className = "";

  try {
    const hostGranted = await ensureHostPermission(settings.apiBaseUrl);
    if (!hostGranted) {
      throw new Error("Host permission denied. Allow access to the API origin when prompted, then try again.");
    }
    await saveLlmSettings(settings);
    const response = await sendRuntimeMessage({
      type: "generate-ai-plan",
      options: {
        apiKey,
        apiBaseUrl: settings.apiBaseUrl,
        apiStyle: settings.apiStyle,
        model: settings.model,
        maxActions: maxActionsInput.value,
        focusPath: focusPathInput.value.trim(),
      },
    });
    if (response && response.error) {
      throw new Error(response.error);
    }
    if (!response || !response.reviewed_plan) {
      throw new Error("AI planner did not return a reviewed plan.");
    }
    loadPlan(response.reviewed_plan);
    if (loadedSummary && loadedSummary.ok) {
      statusEl.textContent = `AI plan generated with ${loadedSummary.executableActions.length} executable action(s). Review before executing.`;
      statusEl.className = loadedSummary.warnings.length > 0 ? "warning" : "ok";
    }
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    generateAiButton.disabled = false;
  }
});

executeButton.addEventListener("click", async () => {
  if (!loadedPlan || !loadedSummary || !loadedSummary.ok) {
    return;
  }
  executeButton.disabled = true;
  statusEl.textContent = "Executing reviewed plan inside Edge...";
  statusEl.className = "";
  try {
    const response = await sendRuntimeMessage({
      type: "apply-reviewed-plan",
      plan: loadedPlan,
    });
    lastExecutionReport = response;
    downloadReportButton.disabled = false;
    renderExecutionResult(response);
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    executeButton.disabled = false;
  }
});

exportSnapshotButton.addEventListener("click", async () => {
  exportSnapshotButton.disabled = true;
  statusEl.textContent = "Exporting current Edge snapshot...";
  statusEl.className = "";
  try {
    const response = await sendRuntimeMessage({
      type: "export-snapshot",
    });
    downloadJson(response, buildFilename("snapshot"));
    statusEl.textContent = "Current snapshot exported.";
    statusEl.className = "ok";
  } catch (error) {
    renderError(error instanceof Error ? error.message : String(error));
  } finally {
    exportSnapshotButton.disabled = false;
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
}

async function initializeSavedSettings() {
  try {
    restoringInputs = true;
    const settings = await loadLlmSettings();
    applyLlmSettings(settings);
    applyUiDraft(await loadUiDraft());
    await restoreEncryptedDraftApiKey();
    await refreshSavedKeyStatus();
    updateEndpointPreview();
  } catch (error) {
    updateKeyStorageStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    restoringInputs = false;
    attachInputCacheHandlers();
    requestInputCacheWrite();
  }
}

function attachInputCacheHandlers() {
  const fields = [
    apiBaseUrlInput,
    apiStyleInput,
    modelInput,
    apiKeyInput,
    focusPathInput,
    maxActionsInput,
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
    requestInputCacheWrite();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      requestInputCacheWrite();
    }
  });
  window.addEventListener("blur", () => {
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
  await chromeStorageSet(UI_DRAFT_STORAGE_NAME, {
    version: 1,
    activeTab: settingsTab.hidden ? "plan" : "settings",
    apiBaseUrl: apiBaseUrlInput.value,
    apiStyle: apiStyleInput.value,
    model: modelInput.value,
    focusPath: focusPathInput.value,
    maxActions: maxActionsInput.value,
    updated_at: new Date().toISOString(),
  });

  const apiKeyDraft = apiKeyInput.value.trim();
  if (apiKeyDraft) {
    await saveEncryptedApiKeyDraft(apiKeyDraft);
  } else {
    await chromeStorageRemove(ENCRYPTED_KEY_DRAFT_STORAGE_NAME);
  }
}

function showTab(name, options = {}) {
  const showSettings = name === "settings";
  planTab.hidden = showSettings;
  settingsTab.hidden = !showSettings;
  planTabButton.classList.toggle("active", !showSettings);
  settingsTabButton.classList.toggle("active", showSettings);
  planTabButton.setAttribute("aria-selected", String(!showSettings));
  settingsTabButton.setAttribute("aria-selected", String(showSettings));
  if (options.persist) {
    requestInputCacheWrite();
  }
}

function renderSummary(summary) {
  if (summary.errors.length > 0) {
    statusEl.className = "error";
    statusEl.textContent = `Plan failed lint with ${summary.errors.length} error(s).`;
  } else if (summary.warnings.length > 0) {
    statusEl.className = "warning";
    statusEl.textContent = `Plan passed lint with ${summary.warnings.length} warning(s).`;
  } else {
    statusEl.className = "ok";
    statusEl.textContent = "Reviewed plan validated. Approved actions can now run.";
  }

  statsEl.hidden = false;
  totalCountEl.textContent = String(summary.totalActions);
  executableCountEl.textContent = String(summary.executableActions.length);
  reviewCountEl.textContent = String(summary.reviewActions.length);
  errorCountEl.textContent = String(summary.errors.length);
  warningCountEl.textContent = String(summary.warnings.length);

  previewListEl.innerHTML = "";
  for (const item of buildSummaryItems(summary)) {
    const li = document.createElement("li");
    li.textContent = item;
    previewListEl.appendChild(li);
  }
}

function loadPlan(plan) {
  const summary = BookmarkPlanLint.lintPlan(plan);
  loadedPlan = plan;
  loadedSummary = summary;
  lastExecutionReport = null;
  downloadReportButton.disabled = true;
  renderSummary(summary);
  executeButton.disabled = !summary.ok || summary.executableActions.length === 0;
}

function renderExecutionResult(report) {
  const failures = report.failures || [];
  const succeeded = report.succeeded || [];
  statusEl.className = failures.length === 0 ? "ok" : "error";
  statusEl.textContent =
    failures.length === 0
      ? `Execution complete. Applied ${succeeded.length} actions.`
      : `Execution complete with ${failures.length} failures.`;

  previewListEl.innerHTML = "";
  const items = [
    `Succeeded: ${succeeded.length}`,
    `Failed: ${failures.length}`,
    ...failures.map((failure) => `${failure.actionId || failure.actionType}: ${failure.error}`),
  ];
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    previewListEl.appendChild(li);
  }
}

function renderError(message) {
  statusEl.className = "error";
  statusEl.textContent = message;
  statsEl.hidden = true;
  previewListEl.innerHTML = "";
}

function buildSummaryItems(summary) {
  const diagnostics = [
    ...summary.errors.map(BookmarkPlanLint.formatDiagnostic),
    ...summary.warnings.map(BookmarkPlanLint.formatDiagnostic),
  ];

  if (!summary.ok) {
    return diagnostics;
  }

  return diagnostics.concat(summarizeActions(summary.executableActions, summary.reviewActions));
}

function summarizeActions(executableActions, reviewActions) {
  const preview = [];
  for (const action of executableActions.slice(0, 12)) {
    const target = action.to_path || action.target_path || action.to_name || action.from_path || "";
    const status = BookmarkPlanLint.resolveActionStatus(loadedPlan || {}, action);
    preview.push(`${action.action_type} [${status}] -> ${target}`);
  }
  if (executableActions.length > 12) {
    preview.push(`... and ${executableActions.length - 12} more executable actions`);
  }
  if (reviewActions.length > 0) {
    preview.push(`${reviewActions.length} review-only or blocked actions will not run`);
  }
  return preview;
}

function sendRuntimeMessage(payload) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(payload, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
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
        updateKeyStorageStatus("Older passphrase-protected key found. Paste the key and save again to migrate.", "warning");
      } else {
        updateKeyStorageStatus("Encrypted API key saved locally. No unlock password is required.", "ok");
      }
    } else if (draftRecord) {
      updateKeyStorageStatus("Encrypted API key draft restored. Click Save Credentials to make it the active key.", "warning");
    } else {
      updateKeyStorageStatus("No encrypted API key saved.", "");
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
    activeTab: ["plan", "settings"].includes(saved.activeTab) ? saved.activeTab : DEFAULT_UI_DRAFT.activeTab,
    apiBaseUrl: typeof saved.apiBaseUrl === "string" ? saved.apiBaseUrl : "",
    apiStyle: typeof saved.apiStyle === "string" ? saved.apiStyle : "",
    model: typeof saved.model === "string" ? saved.model : "",
    focusPath: typeof saved.focusPath === "string" ? saved.focusPath : DEFAULT_UI_DRAFT.focusPath,
    maxActions: typeof saved.maxActions === "string" ? saved.maxActions : DEFAULT_UI_DRAFT.maxActions,
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
  showTab(draft.activeTab || DEFAULT_UI_DRAFT.activeTab);
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
  parsed.pathname = parsed.pathname.replace(/\/responses$/, "");
  parsed.pathname = parsed.pathname.replace(/\/chat\/completions$/, "");
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
  return ["auto", "responses", "chat_completions"].includes(style) ? style : "auto";
}

function updateEndpointPreview() {
  try {
    const baseUrl = normalizeHttpsBaseUrl(apiBaseUrlInput.value || DEFAULT_LLM_SETTINGS.apiBaseUrl);
    endpointPreviewEl.className = "hint";
    endpointPreviewEl.textContent = `Will call ${baseUrl}/responses and ${baseUrl}/chat/completions.`;
  } catch (error) {
    endpointPreviewEl.className = "hint error";
    endpointPreviewEl.textContent = error instanceof Error ? error.message : String(error);
  }
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
    throw new Error("No encrypted API key is saved.");
  }
  if (record.version !== 2) {
    throw new Error("Saved API key uses the older passphrase format. Paste and save it again.");
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

function chromeStorageGet(key) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.get(key, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(result[key]);
    });
  });
}

function chromeStorageSet(key, value) {
  return new Promise((resolve, reject) => {
    chrome.storage.local.set({ [key]: value }, () => {
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
