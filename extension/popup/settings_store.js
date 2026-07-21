/* Popup 配置持久化与 API host permission 边界。 */

(function attachSettingsStore(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const popup = root.Popup || (root.Popup = {});

  const DEFAULT_MODEL = "gpt-5.4-mini";
  const DEFAULT_REQUEST_TIMEOUT = "180";
  const UI_DRAFT_VERSION = 3;
  const ACTIVE_TAB_ALIASES = Object.freeze({
    plan: "organize",
    settings: "ai-service",
    preferences: "strategy",
  });
  const ACTIVE_TABS = Object.freeze(["organize", "ai-service", "strategy", "diagnostics"]);

  function create(dependencies) {
    const options = dependencies || {};
    const chromeApi = options.chrome;
    const protocol = options.protocol;
    const aiEndpoint = options.aiEndpoint;

    validateDependencies(chromeApi, protocol, aiEndpoint);

    const storageKeys = protocol.STORAGE_KEYS;
    const defaultLlmSettings = Object.freeze({
      apiBaseUrl: aiEndpoint.DEFAULT_API_BASE_URL,
      apiStyle: aiEndpoint.DEFAULT_API_STYLE,
      model: DEFAULT_MODEL,
      requestTimeout: DEFAULT_REQUEST_TIMEOUT,
    });
    const defaultPreferences = Object.freeze({
      protectRootLooseBookmarks: "yes",
      sortOrder: "none",
      planningStyle: "balanced",
      lang: "en",
    });
    const defaultUiDraft = Object.freeze({
      activeTab: "organize",
      focusPath: "",
      maxActions: "40",
      maxRetries: "",
    });
    const defaults = Object.freeze({
      llmSettings: defaultLlmSettings,
      preferences: defaultPreferences,
      uiDraft: defaultUiDraft,
    });

    function normalizeActiveTabName(name) {
      const candidate = ACTIVE_TAB_ALIASES[name] || name || defaultUiDraft.activeTab;
      return ACTIVE_TABS.includes(candidate) ? candidate : defaultUiDraft.activeTab;
    }

    function normalizeLlmSettings(settings) {
      const value = settings || {};
      return {
        apiBaseUrl: normalizeHttpsBaseUrl(value.apiBaseUrl || defaultLlmSettings.apiBaseUrl),
        apiStyle: normalizeApiStyle(value.apiStyle || defaultLlmSettings.apiStyle),
        model: String(value.model || defaultLlmSettings.model).trim(),
        requestTimeout: String(value.requestTimeout || defaultLlmSettings.requestTimeout).trim(),
      };
    }

    async function loadLlmSettings() {
      const saved = await getFromArea(chromeApi.storage.local, storageKeys.LLM_SETTINGS);
      if (!saved || typeof saved !== "object") {
        return { ...defaultLlmSettings };
      }
      return normalizeLlmSettings({ ...defaultLlmSettings, ...saved });
    }

    async function saveLlmSettings(settings) {
      const normalized = normalizeLlmSettings(settings);
      await setInArea(chromeApi.storage.local, storageKeys.LLM_SETTINGS, normalized);
      return normalized;
    }

    function normalizeUiDraft(saved) {
      if (!saved || typeof saved !== "object") {
        return { ...defaultUiDraft };
      }
      return {
        activeTab: normalizeActiveTabName(saved.activeTab),
        apiBaseUrl: typeof saved.apiBaseUrl === "string" ? saved.apiBaseUrl : "",
        apiStyle: typeof saved.apiStyle === "string" ? saved.apiStyle : "",
        model: typeof saved.model === "string" ? saved.model : "",
        requestTimeout: typeof saved.requestTimeout === "string"
          ? saved.requestTimeout
          : defaultLlmSettings.requestTimeout,
        focusPath: typeof saved.focusPath === "string"
          ? saved.focusPath
          : defaultUiDraft.focusPath,
        maxActions: typeof saved.maxActions === "string"
          ? saved.maxActions
          : defaultUiDraft.maxActions,
        maxRetries: typeof saved.maxRetries === "string"
          ? saved.maxRetries
          : defaultUiDraft.maxRetries,
        userInstruction: typeof saved.userInstruction === "string" ? saved.userInstruction : "",
      };
    }

    async function loadUiDraft() {
      const saved = await getFromArea(chromeApi.storage.local, storageKeys.POPUP_DRAFT);
      return normalizeUiDraft(saved);
    }

    async function saveUiDraft(draft) {
      const normalized = normalizeUiDraft(draft);
      const stored = {
        version: UI_DRAFT_VERSION,
        ...normalized,
        updated_at: draft && typeof draft.updated_at === "string"
          ? draft.updated_at
          : new Date().toISOString(),
      };
      await setInArea(chromeApi.storage.local, storageKeys.POPUP_DRAFT, stored);
      return stored;
    }

    function normalizePreferences(saved) {
      const value = saved && typeof saved === "object" ? saved : {};
      return {
        protectRootLooseBookmarks: ["yes", "no"].includes(value.protectRootLooseBookmarks)
          ? value.protectRootLooseBookmarks
          : defaultPreferences.protectRootLooseBookmarks,
        sortOrder: ["none", "alpha-asc", "alpha-desc"].includes(value.sortOrder)
          ? value.sortOrder
          : defaultPreferences.sortOrder,
        planningStyle: ["balanced", "conservative", "aggressive"].includes(value.planningStyle)
          ? value.planningStyle
          : defaultPreferences.planningStyle,
        lang: ["zh", "en"].includes(value.lang)
          ? value.lang
          : defaultPreferences.lang,
      };
    }

    async function loadPreferences() {
      const saved = await preferencesStorageGet();
      if (!saved || typeof saved !== "object") {
        return { ...defaultPreferences };
      }
      return normalizePreferences(saved);
    }

    async function savePreferences(preferences) {
      const normalized = normalizePreferences(preferences);
      await preferencesStorageSet(normalized);
      return normalized;
    }

    async function preferencesStorageGet() {
      const syncArea = chromeApi.storage && chromeApi.storage.sync;
      if (syncArea && typeof syncArea.get === "function") {
        try {
          return await getFromArea(syncArea, storageKeys.PREFERENCES);
        } catch (error) {
          if (!isSyncStorageError(error)) throw error;
        }
      }
      return getFromArea(chromeApi.storage.local, storageKeys.PREFERENCES);
    }

    async function preferencesStorageSet(value) {
      const syncArea = chromeApi.storage && chromeApi.storage.sync;
      if (syncArea && typeof syncArea.set === "function") {
        try {
          await setInArea(syncArea, storageKeys.PREFERENCES, value);
          return;
        } catch (error) {
          if (!isSyncStorageError(error)) throw error;
        }
      }
      await setInArea(chromeApi.storage.local, storageKeys.PREFERENCES, value);
    }

    function normalizeHttpsBaseUrl(value) {
      return aiEndpoint.normalizeBaseUrl(value, { allowEmpty: true, defaultValue: "" });
    }

    function normalizeApiStyle(value) {
      return aiEndpoint.normalizeStyle(value);
    }

    function extractOrigin(apiBaseUrl) {
      return aiEndpoint.extractOrigin(apiBaseUrl);
    }

    async function checkHostPermission(origin) {
      if (!origin || !chromeApi.permissions) {
        return false;
      }
      return new Promise((resolve) => {
        chromeApi.permissions.contains({ origins: [origin] }, (granted) => {
          resolve(!!granted);
        });
      });
    }

    async function requestHostPermission(origin) {
      if (!origin || !chromeApi.permissions) {
        return false;
      }
      return new Promise((resolve) => {
        chromeApi.permissions.request({ origins: [origin] }, (granted) => {
          resolve(!!granted);
        });
      });
    }

    async function ensureHostPermission(apiBaseUrl) {
      const origin = extractOrigin(apiBaseUrl);
      if (!origin) {
        return false;
      }
      if (await checkHostPermission(origin)) {
        return true;
      }
      return requestHostPermission(origin);
    }

    function runtimeLastError() {
      return chromeApi.runtime ? chromeApi.runtime.lastError : null;
    }

    function getFromArea(area, key) {
      return new Promise((resolve, reject) => {
        area.get(key, (result) => {
          const lastError = runtimeLastError();
          if (lastError) {
            reject(new Error(lastError.message));
            return;
          }
          resolve(result[key]);
        });
      });
    }

    function setInArea(area, key, value) {
      return new Promise((resolve, reject) => {
        area.set({ [key]: value }, () => {
          const lastError = runtimeLastError();
          if (lastError) {
            reject(new Error(lastError.message));
            return;
          }
          resolve();
        });
      });
    }

    return Object.freeze({
      ACTIVE_TABS,
      ACTIVE_TAB_ALIASES,
      DEFAULT_LLM_SETTINGS: defaultLlmSettings,
      DEFAULT_PREFERENCES: defaultPreferences,
      DEFAULT_UI_DRAFT: defaultUiDraft,
      UI_DRAFT_VERSION,
      checkHostPermission,
      defaults,
      ensureHostPermission,
      extractOrigin,
      loadLlmSettings,
      loadPreferences,
      loadUiDraft,
      normalizeActiveTabName,
      normalizeApiStyle,
      normalizeHttpsBaseUrl,
      normalizeLlmSettings,
      normalizePreferences,
      normalizeUiDraft,
      requestHostPermission,
      saveLlmSettings,
      savePreferences,
      saveUiDraft,
    });
  }

  function validateDependencies(chromeApi, protocol, aiEndpoint) {
    if (!chromeApi || !chromeApi.storage || !chromeApi.storage.local ||
        typeof chromeApi.storage.local.get !== "function" ||
        typeof chromeApi.storage.local.set !== "function") {
      throw new Error("SettingsStore requires chrome.storage.local get/set.");
    }
    if (!protocol || !protocol.STORAGE_KEYS) {
      throw new Error("SettingsStore requires the shared message protocol.");
    }
    if (!aiEndpoint || typeof aiEndpoint.normalizeBaseUrl !== "function" ||
        typeof aiEndpoint.normalizeStyle !== "function" ||
        typeof aiEndpoint.extractOrigin !== "function") {
      throw new Error("SettingsStore requires the shared AI endpoint helpers.");
    }
  }

  function isSyncStorageError(error) {
    return error instanceof Error && /chrome\.storage\.sync|sync/i.test(error.message || "");
  }

  popup.SettingsStore = Object.freeze({ create });
})(globalThis);
