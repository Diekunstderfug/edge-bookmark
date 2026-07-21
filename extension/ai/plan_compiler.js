/* LLM activation 编译、校验、规则修正与 reviewed plan finalize。 */

(function attachPlanCompiler(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const ai = root.AI || (root.AI = {});

  if (typeof require === "function") {
    if (!root.PlanSchema) require("../shared/plan_schema.js");
    if (!root.PathUtils) require("../shared/path_utils.js");
    if (!ai.SnapshotModel) require("./snapshot_model.js");
  }

  const FALLBACK_RULES_SOURCE = "extension-embedded-fast-rules-fallback";

  function create(dependencies) {
    const options = dependencies || {};
    const planSchema = options.planSchema || root.PlanSchema;
    const pathUtils = options.pathUtils || root.PathUtils;
    const snapshotModel = options.snapshotModel || ai.SnapshotModel;
    const performanceApi = options.performance || globalScope.performance || { now: Date.now };
    const log = createLogger(options.log);

    if (!planSchema || !Array.isArray(planSchema.AI_ACTIVATION_ACTION_TYPES) ||
        !Array.isArray(planSchema.MUTATION_ACTION_TYPES)) {
      throw new Error("PlanCompiler requires the shared plan schema.");
    }
    if (!pathUtils || typeof pathUtils.pathWithinScope !== "function") {
      throw new Error("PlanCompiler requires pathUtils.pathWithinScope().");
    }
    if (!snapshotModel || typeof snapshotModel.bookmarkLocator !== "function") {
      throw new Error("PlanCompiler requires snapshotModel.bookmarkLocator().");
    }
    if (!performanceApi || typeof performanceApi.now !== "function") {
      throw new Error("PlanCompiler performance must expose now().");
    }

    const rulesAccess = createRulesAccess(options);
    const supportedAiActions = planSchema.AI_ACTIVATION_ACTION_TYPES;
    const executableActions = new Set(planSchema.MUTATION_ACTION_TYPES);
    const pathWithinScope = pathUtils.pathWithinScope;
    const bookmarkLocator = snapshotModel.bookmarkLocator;

    function finalizeDraftPlan({ draft, snapshot, model, autoApproveThreshold }) {
      const startedAt = performanceApi.now();
      const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
      const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.path, folder]));
      const actions = [];
      const seen = new Set();

      for (const action of draft.actions || []) {
        const normalized = normalizeAction(action);
        if (!supportedAiActions.includes(normalized.action_type)) {
          continue;
        }
        const guarded = applyActionGuardrails(normalized, bookmarkIndex);
        addAction(actions, seen, guarded);
      }

      for (const action of forcedRuleActions(snapshot, folderIndex)) {
        addAction(actions, seen, action);
      }

      const finalized = actions.map((action) => {
        if (!executableActions.has(action.action_type)) {
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
      });

      const elapsed = Math.round(performanceApi.now() - startedAt);
      log(`finalizeDraftPlan: ${finalized.length} actions, ${elapsed}ms`, "log");

      const summary = {
        overview: String((draft.summary || {}).overview || "Generated in the Edge extension via HTTPS."),
        planning_mode: "extension_https_fast",
        review_method: "extension_fast_title_domain",
        total_actions: finalized.length,
        approved_actions: finalized.filter((action) => ["approved", "edited"].includes(action.status)).length,
        blocked_actions: finalized.filter((action) => action.status === "blocked" || action.status === "proposed").length,
      };
      const rulesDiagnostic = rulesAccess.getDiagnostic();
      if (rulesDiagnostic) {
        summary.rules_diagnostic = rulesDiagnostic;
      }

      return {
        plan_version: "2",
        plan_kind: "reviewed",
        source: "bookmark-advisor-extension",
        created_at: nowTimestamp(options.clock),
        source_snapshot: snapshot.source_path || "edge-bookmarks-api",
        rules_source: rulesAccess.getSource(),
        model,
        summary,
        actions: finalized,
      };
    }

    function compileActivationPlan(activationPayload, snapshot) {
      const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
      const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.id, folder]));
      const actions = [];

      for (const activation of activationPayload.activations || []) {
        actions.push(compileActivation(activation, bookmarkIndex, folderIndex));
      }

      const rawSummary = activationPayload.summary;
      const safeSummary = rawSummary && typeof rawSummary === "object" && !Array.isArray(rawSummary)
        ? rawSummary
        : {};
      return { summary: safeSummary, actions };
    }

    function mergeRevisionDraft(existingPlan, deltaDraft) {
      const retained = [];
      const replacementKeys = new Set((deltaDraft.actions || []).map(revisionActionScopeKey).filter(Boolean));
      for (const action of existingPlan.actions || []) {
        const normalized = normalizeAction(action);
        const key = revisionActionScopeKey(normalized);
        if (key && replacementKeys.has(key)) {
          continue;
        }
        retained.push(normalized);
      }
      return {
        summary: {
          ...(existingPlan.summary || {}),
          ...(deltaDraft.summary || {}),
        },
        actions: retained.concat(deltaDraft.actions || []),
      };
    }

    function revisionActionScopeKey(action) {
      const type = String(action.action_type || "");
      if (["move_bookmark", "remove_duplicate", "keep_for_review"].includes(type)) {
        const id = action.bookmark_locator && action.bookmark_locator.id;
        return id ? `bookmark:${id}` : "";
      }
      if (["move_folder", "rename_folder", "delete_empty_folder"].includes(type)) {
        const folder = action.folder_locator || {};
        const idOrPath = folder.id || folder.path;
        return idOrPath ? `folder:${idOrPath}` : "";
      }
      if (type === "create_folder") {
        return action.target_path ? `create_folder:${action.target_path}` : "";
      }
      return "";
    }

    function lintActivationPayload(activationPayload, snapshot) {
      const errors = [];
      if (!activationPayload || typeof activationPayload !== "object") {
        return ["Response must be a JSON object."];
      }
      if (!Array.isArray(activationPayload.activations)) {
        errors.push("activations must be an array.");
        return errors;
      }

      const bookmarkIndex = new Map((snapshot.bookmarks || []).map((bookmark) => [bookmark.id, bookmark]));
      const folderIndex = new Map((snapshot.folders || []).map((folder) => [folder.id, folder]));
      const focusPath = String(snapshot.focus_path || "");

      activationPayload.activations.forEach((activation, index) => {
        const path = `activations[${index}]`;
        if (!activation || typeof activation !== "object") {
          errors.push(`${path} must be an object.`);
          return;
        }
        const op = String(activation.op || "");
        const nodeId = String(activation.node_id || "");
        const target = String(activation.target || "");
        if (!supportedAiActions.includes(op)) {
          errors.push(`${path}.op must be one of ${supportedAiActions.join(", ")}.`);
          return;
        }

        if (op === "keep_for_review") {
          if (nodeId && !bookmarkIndex.has(nodeId) && !folderIndex.has(nodeId)) {
            errors.push(`${path}.node_id must reference an existing bookmark or folder id.`);
          }
        } else if (op === "create_folder") {
          if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
          if (!pathWithinScope(target, focusPath)) errors.push(`${path}.target must stay within the focused folder.`);
        } else if (op === "move_bookmark") {
          const bookmark = bookmarkIndex.get(nodeId);
          if (!bookmark) errors.push(`${path}.node_id must reference an existing bookmark id.`);
          if (bookmark && !pathWithinScope(bookmark.folder_path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
          if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
          if (!pathWithinScope(target, focusPath)) errors.push(`${path}.target must stay within the focused folder.`);
        } else if (op === "move_folder") {
          const folder = folderIndex.get(nodeId);
          if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
          if (folder && !pathWithinScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
          if (!isAbsolutePath(target)) errors.push(`${path}.target must be an absolute folder path.`);
          if (!pathWithinScope(target, focusPath)) errors.push(`${path}.target must stay within the focused folder.`);
          if (folder && (target === folder.path || target.startsWith(`${folder.path}/`))) {
            errors.push(`${path}.target must not be the same folder or its descendant.`);
          }
        } else if (op === "rename_folder") {
          const folder = folderIndex.get(nodeId);
          if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
          if (folder && !pathWithinScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        } else if (op === "remove_duplicate") {
          const bookmark = bookmarkIndex.get(nodeId);
          const duplicateOf = bookmarkIndex.get(String(activation.duplicate_of_id || ""));
          if (!bookmark) errors.push(`${path}.node_id must reference an existing bookmark id.`);
          if (bookmark && !pathWithinScope(bookmark.folder_path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
          if (!duplicateOf) errors.push(`${path}.duplicate_of_id must reference an existing bookmark id.`);
        } else if (op === "delete_empty_folder") {
          const folder = folderIndex.get(nodeId);
          if (!folder) errors.push(`${path}.node_id must reference an existing folder id.`);
          if (folder && !pathWithinScope(folder.path, focusPath)) errors.push(`${path}.node_id must stay within the focused folder.`);
        }
      });

      return errors;
    }

    function pruneInvalidActivationReferences(activationPayload, snapshot) {
      if (!activationPayload || !Array.isArray(activationPayload.activations)) {
        return { payload: activationPayload, dropped: 0 };
      }
      const bookmarkIds = new Set((snapshot.bookmarks || []).map((bookmark) => String(bookmark.id || "")));
      const folderIds = new Set((snapshot.folders || []).map((folder) => String(folder.id || "")));
      const kept = [];
      let dropped = 0;
      for (const activation of activationPayload.activations) {
        if (!activation || typeof activation !== "object") {
          kept.push(activation);
          continue;
        }
        if (activationHasUnknownReferences(activation, bookmarkIds, folderIds)) {
          dropped += 1;
          continue;
        }
        kept.push(activation);
      }
      return {
        payload: { ...activationPayload, activations: kept },
        dropped,
      };
    }

    function lintErrorsAreOnlyReferenceErrors(lintErrors) {
      return lintErrors.length > 0 && lintErrors.every(
        (error) => String(error || "").includes("must reference an existing"),
      );
    }

    function activationHasUnknownReferences(activation, bookmarkIds, folderIds) {
      const op = String(activation.op || "");
      const nodeId = String(activation.node_id || "");
      if (op === "move_bookmark" || op === "remove_duplicate") {
        if (!bookmarkIds.has(nodeId)) {
          return true;
        }
        if (op === "remove_duplicate" && !bookmarkIds.has(String(activation.duplicate_of_id || ""))) {
          return true;
        }
        return false;
      }
      if (op === "move_folder" || op === "rename_folder" || op === "delete_empty_folder") {
        return !folderIds.has(nodeId);
      }
      if (op === "keep_for_review") {
        return !!nodeId && !bookmarkIds.has(nodeId) && !folderIds.has(nodeId);
      }
      return false;
    }

    function compileActivation(activation, bookmarkIndex, folderIndex) {
      const op = String(activation.op || "keep_for_review");
      const reason = sanitizeForPrompt(activation.reason || "Needs review.") || "Needs review.";
      const confidence = finiteNumber(activation.confidence, 0);
      const nodeId = String(activation.node_id || "");
      const target = String(activation.target || "");

      if (op === "move_bookmark") {
        const bookmark = bookmarkIndex.get(nodeId);
        if (!bookmark || !isAbsolutePath(target)) {
          return reviewActivation(activation, reason, confidence, "Move bookmark activation could not be resolved locally.");
        }
        return baseCompiledAction(activation, reason, confidence, {
          action_type: "move_bookmark",
          bookmark_locator: bookmarkLocator(bookmark),
          from_path: bookmark.folder_path,
          to_path: target,
        });
      }

      if (op === "move_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder || !isAbsolutePath(target) || target === folder.path || target.startsWith(`${folder.path}/`)) {
          return reviewActivation(activation, reason, confidence, "Move folder activation could not be resolved safely.");
        }
        return baseCompiledAction(activation, reason, confidence, {
          action_type: "move_folder",
          folder_locator: folderLocator(folder),
          from_path: folder.path,
          to_path: target,
        });
      }

      if (op === "rename_folder") {
        const folder = folderIndex.get(nodeId);
        const newTitle = sanitizeForPrompt(target);
        if (!folder || !newTitle) {
          return reviewActivation(activation, reason, confidence, "Rename folder activation could not be resolved locally.");
        }
        return baseCompiledAction(activation, reason, confidence, {
          action_type: "rename_folder",
          folder_locator: folderLocator(folder),
          from_path: folder.path,
          to_name: newTitle,
        });
      }

      if (op === "create_folder") {
        if (!isAbsolutePath(target)) {
          return reviewActivation(activation, reason, confidence, "Create folder activation did not include an absolute folder path.");
        }
        return baseCompiledAction(activation, reason, confidence, {
          action_type: "create_folder",
          target_path: target,
        });
      }

      if (op === "remove_duplicate") {
        const bookmark = bookmarkIndex.get(nodeId);
        const duplicateOf = bookmarkIndex.get(String(activation.duplicate_of_id || ""));
        if (!bookmark || !duplicateOf || bookmark.normalized_url !== duplicateOf.normalized_url) {
          return reviewActivation(activation, reason, confidence, "Duplicate removal activation could not be verified locally.");
        }
        return baseCompiledAction(activation, reason, confidence, {
          action_type: "remove_duplicate",
          bookmark_locator: bookmarkLocator(bookmark),
          from_path: bookmark.folder_path,
        });
      }

      if (op === "delete_empty_folder") {
        const folder = folderIndex.get(nodeId);
        if (!folder) {
          return reviewActivation(activation, reason, confidence, "Delete empty folder activation could not be resolved locally.");
        }
        return baseCompiledAction(activation, reason, confidence, {
          action_type: "delete_empty_folder",
          folder_locator: folderLocator(folder),
          from_path: folder.path,
        });
      }

      return reviewActivation(activation, reason, confidence, "LLM marked this item for review.");
    }

    function baseCompiledAction(activation, reason, confidence, fields) {
      return Object.assign({
        action_id: "",
        status: "proposed",
        reason,
        confidence,
        bookmark_locator: {},
        folder_locator: {},
        from_path: "",
        to_path: "",
        target_path: "",
        to_name: "",
        details: activationDetails(activation, reason, "compiled-activation"),
      }, fields);
    }

    function reviewActivation(activation, reason, confidence, reviewReason) {
      return baseCompiledAction(activation, `${reason} [${reviewReason}]`, confidence, {
        action_type: "keep_for_review",
        details: activationDetails(activation, reviewReason, "activation-review-required"),
      });
    }

    function activationDetails(activation, summary, guardrail) {
      return {
        evidence: {
          review_status: "derived",
          review_method: "extension-activation",
          summary: sanitizeForPrompt(summary || activation.reason || ""),
          rule_override: "",
        },
        guardrail,
        rule_override: "",
      };
    }

    function folderLocator(folder) {
      return { id: folder.id, name: folder.name, path: folder.path };
    }

    function isAbsolutePath(path) {
      return typeof path === "string" && path.startsWith("/") && path.length > 1;
    }

    function applyActionGuardrails(action, bookmarkIndex) {
      if (action.action_type !== "move_bookmark") {
        return action;
      }
      const bookmark = bookmarkIndex.get(action.bookmark_locator.id);
      if (!bookmark) {
        return blockForReview(action, "Bookmark locator could not be verified in the current snapshot.");
      }
      if (rulesAccess.getRules().protected_paths.includes(bookmark.folder_path)) {
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
      const rules = rulesAccess.getRules();
      const actions = [];
      const focusPath = String(snapshot.focus_path || "");
      for (let index = 0; index < rules.folder_relocations.length; index += 1) {
        const rule = rules.folder_relocations[index];
        const folder = folderIndex.get(rule.from);
        if (!folder || !pathWithinScope(folder.path, focusPath)) {
          continue;
        }
        if (!pathWithinScope(rule.to, focusPath)) {
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

      for (let index = 0; index < rules.bookmark_relocations.length; index += 1) {
        const rule = rules.bookmark_relocations[index];
        for (const bookmark of snapshot.bookmarks || []) {
          if (!pathWithinScope(bookmark.folder_path, focusPath) || !bookmarkMatchesRule(bookmark, rule)) {
            continue;
          }
          if (!pathWithinScope(rule.to, focusPath)) {
            continue;
          }
          actions.push(normalizeAction({
            action_type: "move_bookmark",
            status: "approved",
            reason: rule.reason,
            confidence: 0.98,
            bookmark_locator: bookmarkLocator(bookmark),
            from_path: bookmark.folder_path,
            to_path: rule.to,
            details: {
              evidence: {
                review_status: bookmark.review_status || "reviewed",
                review_method: "forced-rule",
                summary: rule.reason,
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

    return Object.freeze({
      activationDetails,
      activationHasUnknownReferences,
      addAction,
      applyActionGuardrails,
      baseCompiledAction,
      blockForReview,
      bookmarkMatchesRule,
      compileActivation,
      compileActivationPlan,
      finalizeDraftPlan,
      folderLocator,
      forcedRuleActions,
      isAbsolutePath,
      lintActivationPayload,
      lintErrorsAreOnlyReferenceErrors,
      mergeRevisionDraft,
      normalizeAction,
      pruneInvalidActivationReferences,
      reviewActivation,
      revisionActionScopeKey,
    });
  }

  function createRulesAccess(options) {
    const injected = options.fastRules || options.getFastRules;
    let getRules;
    let instance = null;
    if (injected && typeof injected === "object" && typeof injected.get === "function") {
      instance = injected;
      getRules = injected.get.bind(injected);
    } else if (typeof injected === "function") {
      getRules = function () {
        const value = injected();
        if (value && typeof value.get === "function") {
          return value.get();
        }
        return value;
      };
    } else {
      throw new Error("PlanCompiler requires getFastRules() or a fastRules instance.");
    }

    const sourceGetter = options.getRulesSource ||
      (instance && typeof instance.getSource === "function" ? instance.getSource.bind(instance) : null) ||
      (typeof injected.getSource === "function" ? injected.getSource.bind(injected) : null);
    const diagnosticGetter = options.getRulesDiagnostic ||
      (instance && typeof instance.getDiagnostic === "function" ? instance.getDiagnostic.bind(instance) : null) ||
      (typeof injected.getDiagnostic === "function" ? injected.getDiagnostic.bind(injected) : null);

    return {
      getRules,
      getSource: sourceGetter || function () { return FALLBACK_RULES_SOURCE; },
      getDiagnostic: diagnosticGetter || function () { return ""; },
    };
  }

  function sanitizeForPrompt(text) {
    if (!text) return "";
    const cleaned = String(text)
      .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "")
      .replace(/[\r\n\t]/g, " ")
      .replace(/ {2,}/g, " ")
      .trim();
    return cleaned.length > 500 ? cleaned.slice(0, 500) : cleaned;
  }

  function finiteNumber(value, fallback) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
  }

  function nowTimestamp(clock) {
    if (typeof clock === "function") {
      return new Date(Number(clock())).toISOString();
    }
    if (clock && typeof clock.now === "function") {
      return new Date(Number(clock.now())).toISOString();
    }
    return new Date().toISOString();
  }

  function createLogger(logger) {
    if (typeof logger === "function") {
      return function log(message, level) {
        try {
          const result = logger(message, level);
          if (result && typeof result.catch === "function") result.catch(function () {});
        } catch (_error) {
          // 诊断日志不得改变编译结果。
        }
      };
    }
    return function log(message, level) {
      const consoleApi = globalScope.console;
      if (!consoleApi) return;
      const method = level === "error" ? "error" : level === "warn" ? "warn" : "log";
      if (typeof consoleApi[method] === "function") {
        consoleApi[method]("[BookmarkAdvisor]", message);
      }
    };
  }

  ai.PlanCompiler = Object.freeze({ create });
})(globalThis);
