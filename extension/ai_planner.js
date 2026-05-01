(function attachBookmarkAdvisorAI(globalScope) {
  const DEFAULT_API_BASE_URL = "https://api.openai.com/v1";
  const DEFAULT_MODEL = "gpt-4o-mini";
  const DEFAULT_API_STYLE = "auto";
  const DEFAULT_MAX_ACTIONS = 40;
  const DEFAULT_APPROVE_THRESHOLD = 0.85;

  const SUPPORTED_AI_ACTIONS = [
    "rename_folder",
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
    "keep_for_review",
  ];
  const EXECUTABLE_ACTIONS = new Set([
    "rename_folder",
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
  ]);

  // ── Fast rules: loaded from packaged JSON, cached after first load ──
  var _fastRulesCache = null;

  var _FALLBACK_RULES = {
    defaults: { protect_root_loose_bookmarks: true, allow_new_folders_in_advise: true },
    protected_paths: ["/收藏夹栏", "/其他收藏夹", "/移动收藏夹", "/工作区"],
    category_hints: {},
    folder_relocations: [],
    bookmark_relocations: [],
  };

  function _cachedFastRules() {
    return _fastRulesCache || _FALLBACK_RULES;
  }

  async function loadFastRules() {
    if (_fastRulesCache) {
      return _fastRulesCache;
    }
    try {
      var rulesUrl = chrome.runtime.getURL("fast_rules.json");
      var response = await fetch(rulesUrl);
      if (!response.ok) {
        return _FALLBACK_RULES;
      }
      var data = await response.json();
      _fastRulesCache = {
        defaults: data.defaults || _FALLBACK_RULES.defaults,
        protected_paths: Array.isArray(data.protected_paths) ? data.protected_paths : _FALLBACK_RULES.protected_paths,
        category_hints: data.category_hints || {},
        folder_relocations: Array.isArray(data.folder_relocations) ? data.folder_relocations : [],
        bookmark_relocations: Array.isArray(data.bookmark_relocations) ? data.bookmark_relocations : [],
      };
      return _fastRulesCache;
    } catch (_error) {
      return _FALLBACK_RULES;
    }
  }

  async function generateReviewedPlan(options) {
    await loadFastRules();
    const apiKey = String(options.apiKey || "").trim();
    if (!apiKey) {
      throw new Error("OpenAI API key is required for HTTPS planning.");
    }

    const snapshot = options.snapshot || {};
    const apiBaseUrl = normalizeApiBaseUrl(options.apiBaseUrl || options.baseUrl || DEFAULT_API_BASE_URL);
    const apiStyle = normalizeApiStyle(options.apiStyle || DEFAULT_API_STYLE);
    const model = String(options.model || DEFAULT_MODEL).trim() || DEFAULT_MODEL;
    const maxActions = positiveInteger(options.maxActions, DEFAULT_MAX_ACTIONS);
    const autoApproveThreshold = finiteNumber(
      options.autoApproveThreshold,
      DEFAULT_APPROVE_THRESHOLD,
    );
    const focusPath = String(options.focusPath || "").trim();
    const planningSnapshot = buildPlanningSnapshot(snapshot, focusPath);
    const responsePayload = await requestDraftPlan({
      apiKey,
      apiBaseUrl,
      apiStyle,
      model,
      maxActions,
      snapshot: planningSnapshot,
      focusPath,
    });
    const reviewedPlan = finalizeDraftPlan({
      draft: responsePayload,
      snapshot: planningSnapshot,
      model,
      autoApproveThreshold,
    });
    return {
      reviewed_plan: reviewedPlan,
      draft_summary: responsePayload.summary || {},
      planning_mode: "https_openai_compatible",
      api_style: apiStyle,
      api_base_url: apiBaseUrl,
      model,
      focus_path: focusPath,
    };
  }

  async function requestDraftPlan({ apiKey, apiBaseUrl, apiStyle, model, maxActions, snapshot, focusPath }) {
    const systemText = buildSystemPrompt(maxActions);
    const userText = buildUserPrompt(snapshot, focusPath);
    const schema = semanticResponseSchema();
    const errors = [];

    for (const attempt of buildRequestAttempts(apiStyle)) {
      try {
        const payload = await requestCompatibleAttempt({
          attempt,
          apiBaseUrl,
          apiKey,
          model,
          schema,
          systemText,
          userText,
        });
        return parseDraftPlanText(extractAttemptText(attempt, payload));
      } catch (error) {
        errors.push(`${attempt}: ${error.message || String(error)}`);
      }
    }

    throw new Error(`OpenAI-compatible HTTPS planning failed. ${errors.join(" | ")}`);
  }

  async function requestCompatibleAttempt({ attempt, apiBaseUrl, apiKey, model, schema, systemText, userText }) {
    if (attempt === "responses_json_schema") {
      return postCompatible(endpointUrl(apiBaseUrl, "responses"), apiKey, {
        model,
        input: [
          {
            role: "system",
            content: [{ type: "input_text", text: systemText }],
          },
          {
            role: "user",
            content: [{ type: "input_text", text: userText }],
          },
        ],
        text: {
          format: {
            type: "json_schema",
            name: "bookmark_draft_plan",
            strict: true,
            schema,
          },
        },
      });
    }

    const chatPayload = {
      model,
      messages: buildChatMessages(systemText, userText, schema, attempt),
    };
    if (attempt === "chat_json_schema") {
      chatPayload.response_format = {
        type: "json_schema",
        json_schema: {
          name: "bookmark_draft_plan",
          strict: true,
          schema,
        },
      };
    } else if (attempt === "chat_json_object") {
      chatPayload.response_format = { type: "json_object" };
    }
    return postCompatible(endpointUrl(apiBaseUrl, "chat/completions"), apiKey, chatPayload);
  }

  function buildRequestAttempts(apiStyle) {
    if (apiStyle === "responses") {
      return ["responses_json_schema"];
    }
    if (apiStyle === "chat_completions") {
      return ["chat_json_schema", "chat_json_object", "chat_plain_json"];
    }
    return ["responses_json_schema", "chat_json_schema", "chat_json_object", "chat_plain_json"];
  }

  function buildChatMessages(systemText, userText, schema, attempt) {
    const messages = [{ role: "system", content: systemText }];
    if (attempt === "chat_plain_json" || attempt === "chat_json_object") {
      messages[0] = {
        role: "system",
        content: `${systemText}\nReturn a single JSON object and no Markdown fences. It must match this JSON schema:\n${JSON.stringify(schema)}`,
      };
    }
    messages.push({ role: "user", content: userText });
    return messages;
  }

  async function postCompatible(url, apiKey, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch (_error) {
      payload = { raw: text };
    }
    if (!response.ok) {
      const message = payload && payload.error && payload.error.message
        ? payload.error.message
        : text;
      throw new Error(`${response.status} ${message}`);
    }
    return payload;
  }

  function buildPlanningSnapshot(snapshot, focusPath) {
    const folders = (snapshot.folders || []).map(normalizeFolder);
    const folderPaths = new Set(folders.map((folder) => folder.path));
    const bookmarks = (snapshot.bookmarks || [])
      .map(normalizeBookmark)
      .filter((bookmark) => !focusPath || bookmark.folder_path.startsWith(focusPath))
      .map((bookmark) => ({
        ...bookmark,
        review_status: urlRequiresReview(bookmark.url) ? "reviewed" : "skipped_internal",
        review_method: urlRequiresReview(bookmark.url)
          ? "extension_fast_title_domain"
          : "system_skip",
        page_title: bookmark.title,
        one_line_summary: bookmark.domain
          ? `${bookmark.title} (${bookmark.domain})`
          : bookmark.title,
        review_confidence: urlRequiresReview(bookmark.url) ? 0.35 : 1.0,
      }));

    return {
      snapshot_version: "2",
      source: snapshot.source || "edge-extension",
      source_path: snapshot.source_path || "edge-bookmarks-api",
      created_at: snapshot.created_at || new Date().toISOString(),
      focus_path: focusPath,
      folders: folders.filter((folder) => !focusPath || folder.path.startsWith(focusPath) || folderPaths.has(folder.path)),
      bookmarks,
    };
  }

  function finalizeDraftPlan({ draft, snapshot, model, autoApproveThreshold }) {
    const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
    const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.path, folder]));
    const actions = [];
    const seen = new Set();

    for (const action of draft.actions || []) {
      const normalized = normalizeAction(action);
      if (!SUPPORTED_AI_ACTIONS.includes(normalized.action_type)) {
        continue;
      }
      const guarded = applyActionGuardrails(normalized, bookmarkIndex);
      addAction(actions, seen, guarded);
    }

    for (const action of forcedRuleActions(snapshot, folderIndex)) {
      addAction(actions, seen, action);
    }

    const finalized = actions.map((action) => {
      if (!EXECUTABLE_ACTIONS.has(action.action_type)) {
        return { ...action, status: "blocked" };
      }
      if (action.status === "approved" || action.status === "edited") {
        return action;
      }
      if (action.confidence >= autoApproveThreshold) {
        return {
          ...action,
          status: "approved",
          details: {
            ...action.details,
            finalize_reason: "auto-approved",
          },
        };
      }
      return {
        ...action,
        status: "blocked",
        details: {
          ...action.details,
          finalize_reason: "below-threshold",
        },
      };
    }).map((action, index) => ({ ...action, action_id: `a-${String(index + 1).padStart(4, "0")}` }));

    return {
      plan_version: "2",
      plan_kind: "reviewed",
      source: "bookmark-advisor-extension",
      created_at: new Date().toISOString(),
      source_snapshot: snapshot.source_path || "edge-bookmarks-api",
      rules_source: "extension-embedded-fast-rules",
      model,
      summary: {
        overview: String((draft.summary || {}).overview || "Generated in the Edge extension via HTTPS."),
        planning_mode: "extension_https_fast",
        review_method: "extension_fast_title_domain",
        total_actions: finalized.length,
        approved_actions: finalized.filter((action) => ["approved", "edited"].includes(action.status)).length,
        blocked_actions: finalized.filter((action) => action.status === "blocked").length,
      },
      actions: finalized,
    };
  }

  function applyActionGuardrails(action, bookmarkIndex) {
    if (action.action_type !== "move_bookmark") {
      return action;
    }

    const bookmark = bookmarkIndex.get(action.bookmark_locator.id);
    if (!bookmark) {
      return blockForReview(action, "Bookmark locator could not be verified in the current snapshot.");
    }
    if (_cachedFastRules().protected_paths.includes(bookmark.folder_path)) {
      return blockForReview(action, "Blocked by protected root loose-bookmark rule.");
    }
    return action;
  }

  function blockForReview(action, reason) {
    return {
      ...action,
      action_type: "keep_for_review",
      status: "blocked",
      to_path: "",
      target_path: "",
      reason: `${action.reason} [${reason}]`,
      details: {
        ...action.details,
        guardrail: "extension-review-required",
      },
    };
  }

  function addAction(actions, seen, action) {
    const key = [
      action.action_type,
      action.bookmark_locator.id || action.folder_locator.id || action.folder_locator.path,
      action.to_path || action.target_path || action.to_name || "",
    ].join("::");
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    actions.push(action);
  }

  function forcedRuleActions(snapshot, folderIndex) {
    var rules = _cachedFastRules();
    var actions = [];
    for (var i = 0; i < rules.folder_relocations.length; i++) {
      var rule = rules.folder_relocations[i];
      var folder = folderIndex.get(rule.from);
      if (!folder) {
        continue;
      }
      actions.push(normalizeAction({
        action_type: "move_folder",
        status: "approved",
        reason: rule.reason,
        confidence: 0.99,
        folder_locator: { id: folder.id, name: folder.name, path: folder.path },
        from_path: folder.path,
        to_path: rule.to,
        details: {
          evidence: {
            review_status: "derived",
            review_method: "forced-rule",
            summary: rule.reason,
            rule_override: "forced-folder-relocation",
          },
          guardrail: "forced-folder-relocation",
          rule_override: "forced-folder-relocation",
        },
      }));
    }

    for (var j = 0; j < rules.bookmark_relocations.length; j++) {
      var bkRule = rules.bookmark_relocations[j];
      for (const bookmark of snapshot.bookmarks || []) {
        if (!bookmarkMatchesRule(bookmark, bkRule)) {
          continue;
        }
        actions.push(normalizeAction({
          action_type: "move_bookmark",
          status: "approved",
          reason: bkRule.reason,
          confidence: 0.98,
          bookmark_locator: bookmarkLocator(bookmark),
          from_path: bookmark.folder_path,
          to_path: bkRule.to,
          details: {
            evidence: {
              review_status: bookmark.review_status || "reviewed",
              review_method: "forced-rule",
              summary: bkRule.reason,
              rule_override: "forced-bookmark-relocation",
            },
            guardrail: "forced-bookmark-relocation",
            rule_override: "forced-bookmark-relocation",
          },
        }));
      }
    }
    return actions;
  }

  function bookmarkMatchesRule(bookmark, rule) {
    const match = rule.match || {};
    if (match.folder_path && bookmark.folder_path !== match.folder_path) {
      return false;
    }
    if (match.title_contains && !bookmark.title.toLowerCase().includes(match.title_contains.toLowerCase())) {
      return false;
    }
    if (match.title_equals && bookmark.title !== match.title_equals) {
      return false;
    }
    if (match.url_contains && !bookmark.url.toLowerCase().includes(match.url_contains.toLowerCase())) {
      return false;
    }
    return true;
  }

  function buildSystemPrompt(maxActions) {
    return [
      "You are an expert bookmark organizer.",
      "Return JSON only.",
      "Focus on semantic organization, not cosmetic renaming.",
      "Prefer moving bookmarks into semantically appropriate existing folders.",
      "Only propose create_folder when a genuinely new category is justified.",
      `Propose at most ${maxActions} high-value actions.`,
      "Use keep_for_review for ambiguous, risky, or low-confidence items.",
      "Loose bookmarks directly under protected root paths must stay in place.",
      "Only bookmarks with review_status=reviewed may be auto-classified; unresolved bookmarks must stay in keep_for_review.",
      "The browser extension will lint and post-process your output before execution.",
    ].join(" ");
  }

  function buildUserPrompt(snapshot, focusPath) {
    var rules = _cachedFastRules();
    const rulesSummary = {
      protect_root_loose_bookmarks: rules.defaults.protect_root_loose_bookmarks,
      protected_paths: rules.protected_paths,
      forced_folder_relocations: rules.folder_relocations,
      forced_bookmark_relocations: rules.bookmark_relocations,
      fast_mode_warning: "URL review evidence is limited to current bookmark title, URL, domain, and folder path.",
    };
    const prompt = [
      "Given this Edge bookmark snapshot and these guardrails, propose a draft semantic reorganization plan.",
      "The snapshot was collected from chrome.bookmarks and enriched in fast mode with title/domain evidence only.",
      "Be conservative: if the title/domain/folder path is not enough, emit keep_for_review instead of moving.",
      "For move_bookmark, always include bookmark_locator.id, title, url, normalized_url, and folder_path from the snapshot.",
      "For move_folder or rename_folder, always include folder_locator.id, name, and path from the snapshot.",
      "Do not invent bookmarks or folders that are not implied by the snapshot.",
    ];
    if (focusPath) {
      prompt.push(`Focus on bookmarks currently under ${focusPath}. Do not propose unrelated changes outside that focus folder.`);
    }
    return `${prompt.join("\n")}\n\nRules:\n${JSON.stringify(rulesSummary, null, 2)}\n\nSnapshot:\n${JSON.stringify(compactSnapshot(snapshot), null, 2)}`;
  }

  function compactSnapshot(snapshot) {
    var sanitizedBookmarks = (snapshot.bookmarks || []).map(function (bookmark) {
      return Object.assign({}, bookmark, {
        title: sanitizeForPrompt(bookmark.title),
        url: sanitizeForPrompt(bookmark.url),
      });
    });
    return {
      created_at: snapshot.created_at,
      focus_path: snapshot.focus_path,
      folders: snapshot.folders || [],
      bookmarks: sanitizedBookmarks,
    };
  }

  function semanticResponseSchema() {
    const locatorSchema = {
      type: "object",
      additionalProperties: false,
      properties: {
        id: { type: "string" },
        title: { type: "string" },
        url: { type: "string" },
        normalized_url: { type: "string" },
        folder_path: { type: "string" },
      },
      required: ["id", "title", "url", "normalized_url", "folder_path"],
    };
    const folderLocatorSchema = {
      type: "object",
      additionalProperties: false,
      properties: {
        id: { type: "string" },
        name: { type: "string" },
        path: { type: "string" },
      },
      required: ["id", "name", "path"],
    };
    const evidenceSchema = {
      type: "object",
      additionalProperties: false,
      properties: {
        review_status: { type: "string" },
        review_method: { type: "string" },
        summary: { type: "string" },
        rule_override: { type: "string" },
      },
      required: ["review_status", "review_method", "summary", "rule_override"],
    };
    return {
      type: "object",
      additionalProperties: false,
      properties: {
        summary: {
          type: "object",
          additionalProperties: false,
          properties: {
            overview: { type: "string" },
          },
          required: ["overview"],
        },
        actions: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            properties: {
              action_id: { type: "string" },
              action_type: { type: "string", enum: SUPPORTED_AI_ACTIONS },
              status: {
                type: "string",
                enum: ["proposed", "approved", "rejected", "edited", "blocked"],
              },
              reason: { type: "string" },
              confidence: { type: "number" },
              bookmark_locator: locatorSchema,
              folder_locator: folderLocatorSchema,
              from_path: { type: "string" },
              to_path: { type: "string" },
              target_path: { type: "string" },
              to_name: { type: "string" },
              details: {
                type: "object",
                additionalProperties: false,
                properties: {
                  evidence: evidenceSchema,
                  guardrail: { type: "string" },
                  rule_override: { type: "string" },
                },
                required: ["evidence", "guardrail", "rule_override"],
              },
            },
            required: [
              "action_id",
              "action_type",
              "status",
              "reason",
              "confidence",
              "bookmark_locator",
              "folder_locator",
              "from_path",
              "to_path",
              "target_path",
              "to_name",
              "details",
            ],
          },
        },
      },
      required: ["summary", "actions"],
    };
  }

  function extractAttemptText(attempt, payload) {
    if (attempt === "responses_json_schema") {
      return extractResponsesText(payload);
    }
    return extractChatCompletionText(payload);
  }

  function parseDraftPlanText(text) {
    const cleaned = stripJsonFences(String(text || "").trim());
    try {
      return JSON.parse(cleaned);
    } catch (_error) {
      const start = cleaned.indexOf("{");
      const end = cleaned.lastIndexOf("}");
      if (start >= 0 && end > start) {
        return JSON.parse(cleaned.slice(start, end + 1));
      }
      throw new Error("Provider returned text that was not valid JSON.");
    }
  }

  function stripJsonFences(text) {
    return text
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/i, "")
      .trim();
  }

  function extractResponsesText(payload) {
    if (payload.output_text) {
      return String(payload.output_text);
    }
    for (const item of payload.output || []) {
      for (const content of item.content || []) {
        if (content.text) {
          return String(content.text);
        }
      }
    }
    throw new Error("OpenAI response did not include output text.");
  }

  function extractChatCompletionText(payload) {
    const content = payload.choices && payload.choices[0] && payload.choices[0].message
      ? payload.choices[0].message.content
      : "";
    if (typeof content === "string" && content.trim()) {
      return content;
    }
    if (Array.isArray(content)) {
      return content.map((item) => item.text || "").join("");
    }
    throw new Error("OpenAI chat completion did not include message content.");
  }

  function normalizeApiBaseUrl(value) {
    const raw = String(value || DEFAULT_API_BASE_URL).trim();
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

  function endpointUrl(apiBaseUrl, endpointPath) {
    return `${normalizeApiBaseUrl(apiBaseUrl)}/${endpointPath.replace(/^\/+/, "")}`;
  }

  function normalizeApiStyle(value) {
    const style = String(value || "").trim();
    return ["auto", "responses", "chat_completions"].includes(style) ? style : DEFAULT_API_STYLE;
  }

  function normalizeAction(action) {
    const bookmark = action.bookmark_locator || {};
    const folder = action.folder_locator || {};
    const details = action.details || {};
    const evidence = details.evidence || {};
    return {
      action_id: String(action.action_id || ""),
      action_type: String(action.action_type || ""),
      status: String(action.status || "proposed"),
      reason: String(action.reason || ""),
      confidence: finiteNumber(action.confidence, 0),
      bookmark_locator: {
        id: String(bookmark.id || ""),
        title: String(bookmark.title || ""),
        url: String(bookmark.url || ""),
        normalized_url: String(bookmark.normalized_url || ""),
        folder_path: String(bookmark.folder_path || ""),
      },
      folder_locator: {
        id: String(folder.id || ""),
        name: String(folder.name || ""),
        path: String(folder.path || ""),
      },
      from_path: String(action.from_path || bookmark.folder_path || folder.path || ""),
      to_path: String(action.to_path || ""),
      target_path: String(action.target_path || ""),
      to_name: String(action.to_name || ""),
      details: {
        evidence: {
          review_status: String(evidence.review_status || "derived"),
          review_method: String(evidence.review_method || "extension-fast"),
          summary: String(evidence.summary || action.reason || ""),
          rule_override: String(evidence.rule_override || ""),
        },
        guardrail: String(details.guardrail || ""),
        rule_override: String(details.rule_override || ""),
      },
    };
  }

  function normalizeFolder(folder) {
    return {
      id: String(folder.id || ""),
      name: String(folder.name || ""),
      path: String(folder.path || ""),
      parent_path: folder.parent_path || null,
      root_key: String(folder.root_key || ""),
      depth: positiveInteger(folder.depth, 0),
      bookmark_count: positiveInteger(folder.bookmark_count, 0),
      subfolder_count: positiveInteger(folder.subfolder_count, 0),
    };
  }

  function normalizeBookmark(bookmark) {
    return {
      id: String(bookmark.id || ""),
      title: String(bookmark.title || ""),
      url: String(bookmark.url || ""),
      normalized_url: String(bookmark.normalized_url || bookmark.url || ""),
      domain: String(bookmark.domain || ""),
      folder_id: String(bookmark.folder_id || ""),
      folder_path: String(bookmark.folder_path || ""),
      top_level_folder: bookmark.top_level_folder || "",
      root_key: String(bookmark.root_key || ""),
      path: String(bookmark.path || ""),
      depth: positiveInteger(bookmark.depth, 0),
    };
  }

  function bookmarkLocator(bookmark) {
    return {
      id: bookmark.id,
      title: bookmark.title,
      url: bookmark.url,
      normalized_url: bookmark.normalized_url,
      folder_path: bookmark.folder_path,
    };
  }

  function urlRequiresReview(url) {
    try {
      const parsed = new URL(url);
      const scheme = parsed.protocol.replace(":", "").toLowerCase();
      const hostname = parsed.hostname.toLowerCase();
      if (["file", "edge", "chrome", "about", "javascript", "data"].includes(scheme)) {
        return false;
      }
      if (!hostname || hostname === "localhost" || hostname.endsWith(".local")) {
        return false;
      }
      return hostname.includes(".");
    } catch (_error) {
      return false;
    }
  }

  function sanitizeForPrompt(text) {
    if (!text) return "";
    var cleaned = String(text)
      .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "")
      .replace(/[\r\n\t]/g, " ")
      .replace(/ {2,}/g, " ")
      .trim();
    return cleaned.length > 500 ? cleaned.slice(0, 500) : cleaned;
  }

  function positiveInteger(value, fallback) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) {
      return fallback;
    }
    return Math.floor(numberValue);
  }

  function finiteNumber(value, fallback) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
  }

  globalScope.BookmarkAdvisorAI = {
    generateReviewedPlan,
    loadFastRules,
  };
})(globalThis);
