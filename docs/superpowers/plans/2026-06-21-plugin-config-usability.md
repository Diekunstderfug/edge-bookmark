# Plugin Config Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the extension popup configuration into clearer daily workflow, AI service, organization strategy, and diagnostics areas without changing bookmark execution behavior.

**Architecture:** Keep the vanilla MV3 popup and existing storage model. Reshape `popup.html` sections and update `popup.js` tab routing, draft persistence, i18n labels, and test harness IDs. Existing LLM settings and preferences remain compatible; only the visible grouping and active-tab values change.

**Tech Stack:** Vanilla HTML/CSS/JavaScript in `extension/`, Chrome MV3 APIs mocked in Node tests, Python `unittest`/`pytest` test runner.

---

## Scope

This plan changes only popup configuration usability. It does not change AI prompt generation, plan linting, service worker execution, undo behavior, rules, storage encryption, or bookmark mutation logic.

## File Structure

- Modify `extension/popup.html`: change tab labels and move controls into four sections: Organize, AI Service, Strategy, Diagnostics.
- Modify `extension/popup.js`: update i18n labels, element bindings, tab routing, active-tab persistence, and preference handlers for the new sections.
- Modify `tests/test_extension_popup_state.py`: update the DOM harness ID list and add regression tests for four-tab behavior and backward-compatible active-tab restoration.
- Optionally modify `README.md` after implementation if user-facing instructions still describe the old three-tab layout.

## UI Target

```text
Organize
- Focus folder
- Organization notes
- Generate AI Plan
- Load plan JSON
- Status, stats, action preview
- Revise, execute, undo, continue, download report

AI Service
- API base URL
- Endpoint preview
- API key
- Model
- Save Credentials / Forget Key
- Key storage status
- Advanced connection settings
  - Endpoint mode
  - Request timeout
  - Max retries

Strategy
- Planning style
- Root loose bookmark protection
- Max actions
- Post-organization sort

Diagnostics
- Language
- Export Current Snapshot
- Security note
```

## Compatibility Rules

- Existing stored `bookmarkAdvisorLlmSettings` keys remain unchanged: `apiBaseUrl`, `apiStyle`, `model`, `requestTimeout`.
- Existing stored `bookmarkAdvisorPreferences` keys remain unchanged: `protectRootLooseBookmarks`, `sortOrder`, `planningStyle`, `lang`.
- Existing stored `bookmarkAdvisorPopupDraft` fields remain readable. Map old active tabs as follows:

```javascript
const ACTIVE_TAB_ALIASES = {
  plan: "organize",
  settings: "ai-service",
  preferences: "strategy",
};
```

- New active tab values are `organize`, `ai-service`, `strategy`, and `diagnostics`.
- `maxActions` stays in `bookmarkAdvisorPopupDraft` for compatibility, but the control moves from Organize to Strategy.
- `maxRetries` stays in `bookmarkAdvisorPopupDraft` for compatibility, but the control moves inside AI Service advanced settings.

---

### Task 1: Add Popup Tab Regression Tests

**Files:**
- Modify: `tests/test_extension_popup_state.py`
- Test: `tests/test_extension_popup_state.py`

- [ ] **Step 1: Update the popup test harness element IDs**

In `_popup_prefix`, replace the `ids` array with this complete list:

```javascript
const ids = [
  'plan-file', 'api-key', 'api-base-url', 'api-style', 'endpoint-preview',
  'key-storage-status', 'model', 'request-timeout', 'max-retries', 'max-actions',
  'focus-path', 'user-instruction', 'status', 'stats', 'total-count',
  'executable-count', 'review-count', 'error-count', 'warning-count',
  'rejected-count', 'preview-list', 'execute-btn', 'export-snapshot-btn',
  'generate-ai-btn', 'revise-ai-btn', 'save-credentials-btn', 'forget-key-btn',
  'download-report-btn', 'undo-btn', 'continue-btn', 'spinner',
  'organize-tab-btn', 'ai-service-tab-btn', 'strategy-tab-btn',
  'diagnostics-tab-btn', 'organize-tab', 'ai-service-tab', 'strategy-tab',
  'diagnostics-tab', 'pref-protect-root', 'pref-sort-order',
  'pref-planning-style', 'pref-lang', 'cancel-job-btn'
];
```

- [ ] **Step 2: Update initial hidden tab setup in the harness**

Replace the current setup that hides only `settings-tab` with:

```javascript
element('ai-service-tab').hidden = true;
element('strategy-tab').hidden = true;
element('diagnostics-tab').hidden = true;
```

- [ ] **Step 3: Add a test for the four target tabs**

Add this method to `ExtensionPopupStateTest`:

```python
def test_four_config_tabs_switch_and_persist(self) -> None:
    script = self._popup_prefix(lang="en", active_job=None) + """
        require(storageHelpersPath);
        require(actionConstantsPath);
        require(popupPath);
        (async () => {
          await waitFor(() => onChangedListener !== null);
          element('ai-service-tab-btn').click();
          await waitFor(() => storage.bookmarkAdvisorPopupDraft &&
            storage.bookmarkAdvisorPopupDraft.activeTab === 'ai-service');
          const afterAi = {
            organizeHidden: element('organize-tab').hidden,
            aiHidden: element('ai-service-tab').hidden,
            strategyHidden: element('strategy-tab').hidden,
            diagnosticsHidden: element('diagnostics-tab').hidden,
            aiSelected: element('ai-service-tab-btn').attributes['aria-selected'],
            activeTab: storage.bookmarkAdvisorPopupDraft.activeTab
          };
          element('diagnostics-tab-btn').click();
          await waitFor(() => storage.bookmarkAdvisorPopupDraft.activeTab === 'diagnostics');
          console.log(JSON.stringify({
            afterAi,
            diagnosticsHidden: element('diagnostics-tab').hidden,
            diagnosticsSelected: element('diagnostics-tab-btn').attributes['aria-selected'],
            activeTab: storage.bookmarkAdvisorPopupDraft.activeTab
          }));
        })();
    """
    result = self._node_script(script)
    self.assertEqual(
        result,
        {
            "afterAi": {
                "organizeHidden": True,
                "aiHidden": False,
                "strategyHidden": True,
                "diagnosticsHidden": True,
                "aiSelected": "true",
                "activeTab": "ai-service",
            },
            "diagnosticsHidden": False,
            "diagnosticsSelected": "true",
            "activeTab": "diagnostics",
        },
    )
```

- [ ] **Step 4: Add a test for old active-tab aliases**

Add this method to `ExtensionPopupStateTest`:

```python
def test_old_active_tab_preferences_restores_strategy(self) -> None:
    script = self._popup_prefix(lang="en", active_job=None) + """
        storage.bookmarkAdvisorPopupDraft = {
          version: 2,
          activeTab: 'preferences',
          apiBaseUrl: 'https://api.openai.com/v1',
          apiStyle: 'auto',
          model: 'gpt-5.4-mini',
          requestTimeout: '180',
          focusPath: '',
          maxActions: '40',
          maxRetries: '1',
          userInstruction: '',
          updated_at: '2026-06-21T00:00:00.000Z'
        };
        require(storageHelpersPath);
        require(actionConstantsPath);
        require(popupPath);
        (async () => {
          await waitFor(() => onChangedListener !== null);
          console.log(JSON.stringify({
            organizeHidden: element('organize-tab').hidden,
            aiHidden: element('ai-service-tab').hidden,
            strategyHidden: element('strategy-tab').hidden,
            diagnosticsHidden: element('diagnostics-tab').hidden,
            strategySelected: element('strategy-tab-btn').attributes['aria-selected']
          }));
        })();
    """
    result = self._node_script(script)
    self.assertEqual(
        result,
        {
            "organizeHidden": True,
            "aiHidden": True,
            "strategyHidden": False,
            "diagnosticsHidden": True,
            "strategySelected": "true",
        },
    )
```

- [ ] **Step 5: Run the focused popup tests and verify failure**

Run:

```bash
python -m pytest tests/test_extension_popup_state.py -x -q
```

Expected before implementation: FAIL because `organize-tab-btn`, `ai-service-tab-btn`, `strategy-tab-btn`, `diagnostics-tab-btn`, and related panels are not bound by `popup.js`.

---

### Task 2: Reshape Popup HTML Into Four Sections

**Files:**
- Modify: `extension/popup.html`
- Test: `tests/test_extension_popup_state.py`

- [ ] **Step 1: Replace the tab bar**

Replace the existing three tab buttons with:

```html
<div class="tabs" role="tablist" aria-label="Bookmark Advisor sections">
  <button id="organize-tab-btn" class="tab-button active" type="button" role="tab" aria-selected="true" aria-controls="organize-tab" data-i18n="tab_organize">Organize</button>
  <button id="ai-service-tab-btn" class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="ai-service-tab" data-i18n="tab_ai_service">AI Service</button>
  <button id="strategy-tab-btn" class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="strategy-tab" data-i18n="tab_strategy">Strategy</button>
  <button id="diagnostics-tab-btn" class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="diagnostics-tab" data-i18n="tab_diagnostics">Diagnostics</button>
</div>
```

- [ ] **Step 2: Make the tab grid support four equal tabs**

Keep the existing `.tabs` selector but change its grid template to:

```css
.tabs {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin: 12px 0;
}
```

- [ ] **Step 3: Rename the main plan section to Organize and remove strategy/diagnostic controls**

Change the opening section tag to:

```html
<section id="organize-tab" class="tab-panel" role="tabpanel" aria-labelledby="organize-tab-btn">
```

Inside its first panel, keep only focus folder, organization notes, and generate action:

```html
<div class="panel">
  <strong data-i18n="label_ai_planning">Generate organization plan</strong>
  <label for="focus-path" data-i18n="label_focus_folder">Focus folder</label>
  <select id="focus-path">
    <option value="" data-i18n="opt_all_bookmarks">All bookmarks</option>
  </select>
  <label for="user-instruction" data-i18n="label_user_instruction">Organization notes</label>
  <textarea id="user-instruction" rows="2" data-i18n-placeholder="placeholder_instruction" placeholder="Describe how you want the AI to organize your bookmarks (optional)"></textarea>
  <button id="generate-ai-btn" type="button" data-i18n="btn_generate">Generate AI Plan</button>
</div>
```

Keep the plan file input panel, status/stats panel, action preview panel, revise/execute buttons, undo button, continue button, and download report button in this section.

- [ ] **Step 4: Rename the LLM section to AI Service and fold advanced connection settings**

Change the opening section tag to:

```html
<section id="ai-service-tab" class="tab-panel" role="tabpanel" aria-labelledby="ai-service-tab-btn" hidden>
```

Use this panel content:

```html
<div class="panel">
  <strong data-i18n="label_ai_service">AI service connection</strong>
  <label for="api-base-url" data-i18n="label_api_url">API base URL</label>
  <input id="api-base-url" type="text" value="https://api.openai.com/v1" spellcheck="false">
  <p class="hint" id="endpoint-preview">Requests will use the configured provider base URL.</p>

  <label for="api-key" data-i18n="label_api_key">API key</label>
  <input id="api-key" type="password" autocomplete="off" placeholder="sk-..., sk-or-..., provider key">

  <label for="model">Model</label>
  <input id="model" type="text" value="gpt-5.4-mini" spellcheck="false">
  <p class="hint" data-i18n="hint_model_speed">Use fast models (gpt-5.4-mini, deepseek-v4-flash, gemini-2.5-flash). Reasoning/thinking models (deepseek-v4-pro, o3) are much slower.</p>

  <details>
    <summary data-i18n="label_advanced_connection">Advanced connection settings</summary>
    <label for="api-style" data-i18n="label_endpoint_mode">Endpoint mode</label>
    <select id="api-style">
      <option value="auto">Auto fallback</option>
      <option value="responses">Responses API</option>
      <option value="chat_completions">Chat Completions</option>
      <option value="completions">Completions</option>
    </select>

    <div class="wide-row">
      <div>
        <label for="request-timeout" data-i18n="label_request_timeout">Request timeout (seconds)</label>
        <input id="request-timeout" type="number" min="10" max="300" value="120">
      </div>
      <div>
        <label for="max-retries" data-i18n="label_max_retries">Max retries</label>
        <input id="max-retries" type="number" min="0" max="3" value="1">
      </div>
    </div>
    <p class="hint" data-i18n="hint_timeout_max">Max 300s - MV3 service worker lifecycle limit</p>
  </details>

  <div class="button-row">
    <button id="save-credentials-btn" class="secondary" type="button" data-i18n="btn_save">Save Credentials</button>
    <button id="forget-key-btn" class="danger" type="button" data-i18n="btn_forget">Forget Key</button>
  </div>
  <p class="hint" id="key-storage-status">No saved key checked yet.</p>
</div>
```

- [ ] **Step 5: Replace Preferences with Strategy**

Create this section:

```html
<section id="strategy-tab" class="tab-panel" role="tabpanel" aria-labelledby="strategy-tab-btn" hidden>
  <div class="panel">
    <strong data-i18n="label_strategy">Organization strategy</strong>

    <label for="pref-planning-style" data-i18n="label_planning_style">Planning style</label>
    <select id="pref-planning-style">
      <option value="balanced" data-i18n="opt_style_balanced">Balanced - reasonable moves, uncertain items stay for review</option>
      <option value="conservative" data-i18n="opt_style_conservative">Conservative - only move very certain items</option>
      <option value="aggressive" data-i18n="opt_style_aggressive">Aggressive - categorize as much as possible and allow new folders</option>
    </select>

    <label for="pref-protect-root" data-i18n="label_protect_root">Root loose bookmark protection</label>
    <select id="pref-protect-root">
      <option value="yes" data-i18n="opt_protect_yes">Protected - do not auto-move root loose bookmarks</option>
      <option value="no" data-i18n="opt_protect_no">Allowed - may move root loose bookmarks into subfolders</option>
    </select>

    <label for="max-actions" data-i18n="label_max_actions">Max actions</label>
    <input id="max-actions" type="number" min="1" max="80" value="40">

    <label for="pref-sort-order" data-i18n="label_sort_order">Post-organization sort</label>
    <select id="pref-sort-order">
      <option value="none" data-i18n="opt_sort_none">No sorting (keep original order)</option>
      <option value="alpha-asc" data-i18n="opt_sort_asc">Alphabetical (A-Z)</option>
      <option value="alpha-desc" data-i18n="opt_sort_desc">Reverse alphabetical (Z-A)</option>
    </select>
  </div>
</section>
```

- [ ] **Step 6: Add Diagnostics**

Create this section:

```html
<section id="diagnostics-tab" class="tab-panel" role="tabpanel" aria-labelledby="diagnostics-tab-btn" hidden>
  <div class="panel">
    <strong data-i18n="label_diagnostics">Diagnostics</strong>
    <label for="pref-lang" data-i18n="label_language">Language</label>
    <select id="pref-lang">
      <option value="zh">中文</option>
      <option value="en">English</option>
    </select>

    <button id="export-snapshot-btn" type="button" data-i18n="btn_export">Export Current Snapshot</button>
    <div style="height: 8px;"></div>
    <p class="hint" data-i18n="key_security_note">Stored keys are obfuscated using the extension ID, not strong encryption.</p>
  </div>
</section>
```

- [ ] **Step 7: Run the focused popup tests**

Run:

```bash
python -m pytest tests/test_extension_popup_state.py -x -q
```

Expected after HTML-only change: still FAIL because `popup.js` still binds old tab IDs.

---

### Task 3: Update Popup JavaScript Tab Model and Labels

**Files:**
- Modify: `extension/popup.js`
- Test: `tests/test_extension_popup_state.py`

- [ ] **Step 1: Replace tab i18n keys in English**

In the English `I18N.en` object, replace `tab_plan`, `tab_llm`, and `tab_prefs` with:

```javascript
tab_organize: "Organize",
tab_ai_service: "AI Service",
tab_strategy: "Strategy",
tab_diagnostics: "Diagnostics",
label_ai_service: "AI service connection",
label_advanced_connection: "Advanced connection settings",
label_strategy: "Organization strategy",
label_diagnostics: "Diagnostics",
```

Keep existing labels used by controls, including `label_endpoint_mode`, `label_request_timeout`, `label_max_retries`, `label_language`, `label_protect_root`, `label_sort_order`, and `label_planning_style`.

- [ ] **Step 2: Replace tab i18n keys in Chinese**

In the Chinese `I18N.zh` object, replace `tab_plan`, `tab_llm`, and `tab_prefs` with:

```javascript
tab_organize: "整理",
tab_ai_service: "AI 服务",
tab_strategy: "策略",
tab_diagnostics: "诊断",
label_ai_service: "AI 服务连接",
label_advanced_connection: "高级连接设置",
label_strategy: "整理策略",
label_diagnostics: "诊断",
```

- [ ] **Step 3: Replace tab element bindings**

Replace the old tab constants with:

```javascript
const organizeTabButton = document.getElementById("organize-tab-btn");
const aiServiceTabButton = document.getElementById("ai-service-tab-btn");
const strategyTabButton = document.getElementById("strategy-tab-btn");
const diagnosticsTabButton = document.getElementById("diagnostics-tab-btn");
const organizeTab = document.getElementById("organize-tab");
const aiServiceTab = document.getElementById("ai-service-tab");
const strategyTab = document.getElementById("strategy-tab");
const diagnosticsTab = document.getElementById("diagnostics-tab");
```

- [ ] **Step 4: Add tab normalization helper**

Place this helper near `DEFAULT_UI_DRAFT`:

```javascript
const ACTIVE_TAB_ALIASES = {
  plan: "organize",
  settings: "ai-service",
  preferences: "strategy",
};
const ACTIVE_TABS = ["organize", "ai-service", "strategy", "diagnostics"];

function normalizeActiveTabName(name) {
  const candidate = ACTIVE_TAB_ALIASES[name] || name || "organize";
  return ACTIVE_TABS.includes(candidate) ? candidate : "organize";
}
```

- [ ] **Step 5: Update the default draft active tab**

Change `DEFAULT_UI_DRAFT.activeTab` to:

```javascript
activeTab: "organize",
```

- [ ] **Step 6: Replace `initializeTabs`**

Replace the function with:

```javascript
function initializeTabs() {
  organizeTabButton.addEventListener("click", () => showTab("organize", { persist: true }));
  aiServiceTabButton.addEventListener("click", () => showTab("ai-service", { persist: true }));
  strategyTabButton.addEventListener("click", () => showTab("strategy", { persist: true }));
  diagnosticsTabButton.addEventListener("click", () => showTab("diagnostics", { persist: true }));
}
```

- [ ] **Step 7: Replace `buildUiDraftSnapshot` active-tab logic**

Use:

```javascript
function buildUiDraftSnapshot() {
  return {
    version: 3,
    activeTab: !organizeTab.hidden ? "organize" :
      !aiServiceTab.hidden ? "ai-service" :
      !strategyTab.hidden ? "strategy" : "diagnostics",
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
```

- [ ] **Step 8: Replace `showTab`**

Use:

```javascript
function showTab(name, options = {}) {
  const activeName = normalizeActiveTabName(name);
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
```

- [ ] **Step 9: Update UI draft application**

Find `applyUiDraft`. Ensure it calls the tab normalizer:

```javascript
function applyUiDraft(draft) {
  if (!draft || typeof draft !== "object") {
    showTab(DEFAULT_UI_DRAFT.activeTab, { persist: false });
    return;
  }
  apiBaseUrlInput.value = draft.apiBaseUrl || DEFAULT_LLM_SETTINGS.apiBaseUrl;
  apiStyleInput.value = draft.apiStyle || DEFAULT_LLM_SETTINGS.apiStyle;
  modelInput.value = draft.model || DEFAULT_LLM_SETTINGS.model;
  requestTimeoutInput.value = draft.requestTimeout || DEFAULT_LLM_SETTINGS.requestTimeout;
  focusPathInput.value = draft.focusPath || DEFAULT_UI_DRAFT.focusPath;
  _pendingFocusPath = focusPathInput.value;
  maxActionsInput.value = draft.maxActions || DEFAULT_UI_DRAFT.maxActions;
  maxRetriesInput.value = draft.maxRetries ?? DEFAULT_UI_DRAFT.maxRetries;
  userInstructionInput.value = draft.userInstruction || "";
  showTab(normalizeActiveTabName(draft.activeTab), { persist: false });
}
```

If the existing function has additional current behavior, preserve it and only replace the active-tab normalization and element field assignments shown above.

- [ ] **Step 10: Run the focused popup tests**

Run:

```bash
python -m pytest tests/test_extension_popup_state.py -x -q
```

Expected: PASS for the new tab tests. If an older popup test fails because it asserts old tab names or IDs, update that assertion to the new user-visible grouping while preserving the same behavior being tested.

---

### Task 4: Keep Settings Persistence and Generation Behavior Stable

**Files:**
- Modify: `tests/test_extension_popup_state.py`
- Modify: `extension/popup.js`
- Test: `tests/test_extension_popup_state.py`

- [ ] **Step 1: Add a regression test that moved controls still feed generation options**

Add this method to `ExtensionPopupStateTest`:

```python
def test_strategy_and_ai_service_controls_feed_generation_options(self) -> None:
    script = self._popup_prefix(lang="en", active_job=None) + """
        const sentMessages = [];
        chrome.runtime.sendMessage = (payload, callback) => {
          sentMessages.push(payload);
          if (payload.type === 'get-active-job') {
            callback({ job: null });
            return;
          }
          if (payload.type === 'list-folders') {
            callback({ folders: [] });
            return;
          }
          if (payload.type === 'start-background-job') {
            callback({ ok: true, job: { id: 'job-1', type: payload.job_type, status: 'running' } });
            return;
          }
          callback({});
        };
        require(storageHelpersPath);
        require(actionConstantsPath);
        require(popupPath);
        (async () => {
          await waitFor(() => onChangedListener !== null);
          element('api-base-url').value = 'https://api.openai.com/v1';
          element('api-key').value = 'sk-test';
          element('model').value = 'gpt-5.4-mini';
          element('max-actions').value = '17';
          element('max-retries').value = '2';
          element('pref-planning-style').value = 'conservative';
          element('pref-protect-root').value = 'yes';
          element('pref-sort-order').value = 'alpha-asc';
          element('generate-ai-btn').click();
          await waitFor(() => sentMessages.some((message) => message.type === 'start-background-job'));
          const job = sentMessages.find((message) => message.type === 'start-background-job');
          console.log(JSON.stringify(job.payload.options));
        })();
    """
    result = self._node_script(script)
    self.assertEqual(result["model"], "gpt-5.4-mini")
    self.assertEqual(result["maxActions"], "17")
    self.assertEqual(result["maxRetries"], 2)
    self.assertEqual(result["preferences"]["planningStyle"], "conservative")
    self.assertEqual(result["preferences"]["protectRootLooseBookmarks"], "yes")
    self.assertEqual(result["preferences"]["sortOrder"], "alpha-asc")
```

- [ ] **Step 2: Run the new test and verify failure only if behavior regressed**

Run:

```bash
python -m pytest tests/test_extension_popup_state.py::ExtensionPopupStateTest::test_strategy_and_ai_service_controls_feed_generation_options -q
```

Expected: PASS if element IDs were preserved correctly. FAIL means the HTML/JS move broke option collection.

- [ ] **Step 3: Fix only real option collection breakage**

If the test fails because `maxActionsInput`, `maxRetriesInput`, or preference elements are null or stale, verify these bindings exist in `popup.js`:

```javascript
const maxRetriesInput = document.getElementById("max-retries");
const maxActionsInput = document.getElementById("max-actions");
const prefProtectRoot = document.getElementById("pref-protect-root");
const prefSortOrder = document.getElementById("pref-sort-order");
const prefPlanningStyle = document.getElementById("pref-planning-style");
const prefLang = document.getElementById("pref-lang");
```

No storage key renames are needed.

- [ ] **Step 4: Commit the tested popup behavior**

Run:

```bash
git add extension/popup.html extension/popup.js tests/test_extension_popup_state.py
git commit -m "refactor(ext): reorganize popup configuration sections"
```

Expected: commit succeeds. If the working tree contains unrelated pre-existing changes, stage only the three files above and do not revert unrelated files.

---

### Task 5: Run Focused Extension Verification

**Files:**
- Test: `tests/test_extension_popup_state.py`
- Test: `tests/test_extension_endpoint_urls.py`
- Test: `tests/test_extension_service_worker_state.py`
- Test: `tests/test_extension_plan_lint.py`

- [ ] **Step 1: Run popup tests**

Run:

```bash
python -m pytest tests/test_extension_popup_state.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run endpoint tests because AI Service moved endpoint controls**

Run:

```bash
python -m pytest tests/test_extension_endpoint_urls.py -q
```

Expected: all tests pass; endpoint URL generation remains unchanged.

- [ ] **Step 3: Run focused extension regression set**

Run:

```bash
python -m pytest tests/test_extension_service_worker_state.py tests/test_extension_plan_lint.py tests/test_extension_endpoint_urls.py tests/test_extension_popup_state.py -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Run a JS syntax check for popup files**

Run:

```bash
node --check extension/popup.js
node --check extension/plan_lint.js
node --check extension/ai_planner.js
node --check extension/service_worker.js
```

Expected: each command exits 0 with no syntax errors.

---

### Task 6: Update User-Facing Docs If They Mention Old Tabs

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: documentation grep

- [ ] **Step 1: Find old tab references**

Run:

```bash
rg -n "Plan tab|LLM tab|Preferences tab|Plan 标签|LLM 标签|Preferences|偏好" README.md README.zh-CN.md
```

Expected: lines describing the old three-tab layout.

- [ ] **Step 2: Update README.md tab descriptions**

Replace the old "The popup has three tabs" section with:

```markdown
The popup is organized around four areas:

**Organize:**
- **Scope** - restrict planning and execution to a single folder tree. Leave empty to plan across all folders.
- **Organization notes** - optional instructions for how the AI should group bookmarks.
- **Plan review and execution** - generate, load, revise, execute, undo, continue, and download reports.

**AI Service:**
- **API base URL** - OpenAI or another OpenAI-compatible HTTPS endpoint.
- **API key** - saved as AES-GCM ciphertext in `chrome.storage.local`.
- **Model** - fast compatible models work best.
- **Advanced connection settings** - endpoint mode, request timeout, and retry count.

**Strategy:**
- **Planning style** - conservative, balanced, or aggressive.
- **Root loose bookmark protection** - leave root-level loose bookmarks in place by default.
- **Max actions** - cap how many actions the LLM proposes in one request.
- **Sort order** - keep original order by default, or sort by title.

**Diagnostics:**
- Set the UI language, export the current snapshot, and review the local key-storage warning.
```

- [ ] **Step 3: Update README.zh-CN.md with equivalent Chinese content**

Use this replacement:

```markdown
弹窗按四个区域组织：

**整理：**
- **范围**：限制规划和执行到某个文件夹树。留空表示处理全部书签。
- **整理说明**：给 AI 的可选归类说明。
- **计划审查和执行**：生成、加载、修改、执行、撤销、继续生成和下载报告。

**AI 服务：**
- **API 地址**：OpenAI 或其他 OpenAI-compatible HTTPS endpoint。
- **API key**：以 AES-GCM 密文形式保存到 `chrome.storage.local`。
- **模型**：推荐使用速度较快的兼容模型。
- **高级连接设置**：端点模式、请求超时和重试次数。
- **连接状态**：在同一区域查看 endpoint 预览和本地 key 存储状态。

**策略：**
- **规划风格**：保守、均衡或积极。
- **顶层散书签保护**：默认不自动移动根目录下的散书签。
- **最大动作数**：限制单次请求中 LLM 给出的动作数量。
- **排序方式**：默认保持原顺序，也可以按标题排序。

**诊断：**
- 设置界面语言，导出当前快照，并查看本地 key 存储风险说明。
```

- [ ] **Step 4: Verify no stale old-layout wording remains**

Run:

```bash
rg -n "The popup has three tabs|Plan tab|LLM tab|Preferences tab|弹窗有三个|偏好页" README.md README.zh-CN.md
```

Expected: no matches.

- [ ] **Step 5: Commit docs if changed**

Run:

```bash
git add README.md README.zh-CN.md
git commit -m "docs: describe popup configuration sections"
```

Expected: commit succeeds if docs changed. If Step 1 found no old tab references, skip this commit.

---

## Final Verification

- [ ] Run:

```bash
python -m pytest tests/test_extension_service_worker_state.py tests/test_extension_plan_lint.py tests/test_extension_endpoint_urls.py tests/test_extension_popup_state.py -x -q
```

Expected: all selected extension tests pass.

- [ ] Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: Python unittest suite passes or reports only pre-existing failures unrelated to popup layout. Record any unrelated failures in the final handoff.

- [ ] Run:

```bash
git status --short
```

Expected: only intentional uncommitted files remain. If the repository was already dirty before implementation, do not clean or revert unrelated files.

## Rollback Plan

If the popup layout causes regression, revert only the popup usability commits:

```bash
git revert <popup-config-commit>
```

Do not revert unrelated pre-existing changes in the working tree.

## Notes for Implementer

- Keep all controls with their existing IDs where possible. Moving a control in HTML should not require changing its storage key or message payload.
- Do not add a build step, bundler, npm package, or CSS framework.
- Do not change `extension/service_worker.js` for this plan unless a test proves that popup payload shape changed unexpectedly.
- The repo may already contain unrelated dirty files. Stage only files explicitly listed by each task.
