(function attachBookmarkPlanLint(globalScope) {
  const EXECUTABLE_ACTIONS = new Set([
    "rename_folder",
    "create_folder",
    "move_folder",
    "move_bookmark",
    "remove_duplicate",
  ]);
  const EXECUTABLE_STATUSES = new Set(["approved", "edited"]);
  const KNOWN_ACTION_TYPES = new Set([...EXECUTABLE_ACTIONS, "keep_for_review"]);
  const KNOWN_ACTION_STATUSES = new Set(["approved", "edited", "proposed", "blocked"]);
  const KNOWN_PLAN_KEYS = new Set([
    "actions",
    "backup_path",
    "created_at",
    "executor",
    "mode",
    "model",
    "output_path",
    "plan_kind",
    "plan_version",
    "report_path",
    "rules_source",
    "source",
    "source_path",
    "source_snapshot",
    "summary",
  ]);
  const KNOWN_ACTION_KEYS = new Set([
    "action_id",
    "action_type",
    "bookmark_id",
    "bookmark_locator",
    "confidence",
    "details",
    "duplicate_of",
    "folder_id",
    "folder_locator",
    "folder_name",
    "from_path",
    "reason",
    "status",
    "target_path",
    "to_name",
    "to_path",
  ]);

  function parsePlanText(text) {
    try {
      return JSON.parse(text);
    } catch (error) {
      throw new Error(formatJsonParseError(text, error));
    }
  }

  function lintPlan(plan) {
    const errors = [];
    const warnings = [];
    const executableActions = [];
    const reviewActions = [];

    if (!isPlainObject(plan)) {
      errors.push(diagnostic("error", "$", "Plan must be a JSON object."));
      return buildSummary(0, errors, warnings, executableActions, reviewActions);
    }

    warnUnknownKeys(plan, KNOWN_PLAN_KEYS, "$", warnings);

    if (plan.plan_version !== undefined && typeof plan.plan_version !== "string") {
      errors.push(diagnostic("error", "$.plan_version", "plan_version must be a string when present."));
    }
    if (plan.plan_kind !== undefined && typeof plan.plan_kind !== "string") {
      errors.push(diagnostic("error", "$.plan_kind", "plan_kind must be a string when present."));
    }
    if (plan.summary !== undefined && !isPlainObject(plan.summary)) {
      warnings.push(diagnostic("warning", "$.summary", "summary should be an object when present."));
    }
    if (!Array.isArray(plan.actions)) {
      errors.push(diagnostic("error", "$.actions", "Plan must contain an actions array."));
      return buildSummary(0, errors, warnings, executableActions, reviewActions);
    }

    plan.actions.forEach((action, index) => {
      const actionPath = `$.actions[${index}]`;
      if (!isPlainObject(action)) {
        errors.push(diagnostic("error", actionPath, "Each action must be a JSON object."));
        return;
      }

      warnUnknownKeys(action, KNOWN_ACTION_KEYS, actionPath, warnings);

      const actionType = readNonEmptyString(action.action_type);
      if (!actionType) {
        errors.push(diagnostic("error", `${actionPath}.action_type`, "action_type is required."));
      } else if (!KNOWN_ACTION_TYPES.has(actionType)) {
        errors.push(
          diagnostic(
            "error",
            `${actionPath}.action_type`,
            `Unsupported action_type "${actionType}".`,
          ),
        );
      }

      if (!readNonEmptyString(action.reason)) {
        errors.push(diagnostic("error", `${actionPath}.reason`, "reason must be a non-empty string."));
      }

      if (typeof action.confidence !== "number" || !Number.isFinite(action.confidence)) {
        errors.push(
          diagnostic("error", `${actionPath}.confidence`, "confidence must be a finite number."),
        );
      } else if (action.confidence < 0 || action.confidence > 1) {
        warnings.push(
          diagnostic(
            "warning",
            `${actionPath}.confidence`,
            "confidence is usually expected to be between 0 and 1.",
          ),
        );
      }

      if (action.status !== undefined && !KNOWN_ACTION_STATUSES.has(String(action.status))) {
        warnings.push(
          diagnostic(
            "warning",
            `${actionPath}.status`,
            `Unknown status "${String(action.status)}"; it will be treated conservatively.`,
          ),
        );
      }

      validateOptionalObject(action.bookmark_locator, `${actionPath}.bookmark_locator`, errors);
      validateOptionalObject(action.folder_locator, `${actionPath}.folder_locator`, errors);
      validateOptionalObject(action.details, `${actionPath}.details`, errors);

      if (actionType) {
        lintActionShape(actionType, action, actionPath, errors);
      }

      const status = resolveActionStatus(plan, action);
      if (actionType === "keep_for_review" || !EXECUTABLE_STATUSES.has(status)) {
        reviewActions.push(action);
      } else if (actionType && EXECUTABLE_ACTIONS.has(actionType)) {
        executableActions.push(action);
      }
    });

    return buildSummary(plan.actions.length, errors, warnings, executableActions, reviewActions);
  }

  function lintActionShape(actionType, action, actionPath, errors) {
    switch (actionType) {
      case "rename_folder":
        requireFolderLocator(action, actionPath, errors);
        requireNonEmptyString(action.to_name, `${actionPath}.to_name`, errors);
        return;
      case "create_folder":
        requireNonEmptyString(action.target_path, `${actionPath}.target_path`, errors);
        return;
      case "move_folder":
        requireFolderLocator(action, actionPath, errors);
        requireNonEmptyString(action.to_path, `${actionPath}.to_path`, errors);
        return;
      case "move_bookmark":
        requireBookmarkLocator(action, actionPath, errors);
        requireNonEmptyString(action.to_path, `${actionPath}.to_path`, errors);
        return;
      case "remove_duplicate":
        requireBookmarkLocator(action, actionPath, errors);
        return;
      case "keep_for_review":
        return;
      default:
        return;
    }
  }

  function requireBookmarkLocator(action, actionPath, errors) {
    if (hasBookmarkLocator(action)) {
      return;
    }
    errors.push(
      diagnostic(
        "error",
        actionPath,
        "Bookmark action needs bookmark_id or bookmark_locator with id/title/url.",
      ),
    );
  }

  function requireFolderLocator(action, actionPath, errors) {
    if (hasFolderLocator(action)) {
      return;
    }
    errors.push(
      diagnostic(
        "error",
        actionPath,
        "Folder action needs folder_id or folder_locator with id/path/name.",
      ),
    );
  }

  function requireNonEmptyString(value, path, errors) {
    if (readNonEmptyString(value)) {
      return;
    }
    errors.push(diagnostic("error", path, "Must be a non-empty string."));
  }

  function validateOptionalObject(value, path, errors) {
    if (value === undefined) {
      return;
    }
    if (!isPlainObject(value)) {
      errors.push(diagnostic("error", path, "Must be an object when present."));
    }
  }

  function hasBookmarkLocator(action) {
    const locator = isPlainObject(action.bookmark_locator) ? action.bookmark_locator : {};
    return Boolean(
      readNonEmptyString(action.bookmark_id) ||
        readNonEmptyString(locator.id) ||
        readNonEmptyString(locator.url) ||
        readNonEmptyString(locator.normalized_url) ||
        readNonEmptyString(locator.title),
    );
  }

  function hasFolderLocator(action) {
    const locator = isPlainObject(action.folder_locator) ? action.folder_locator : {};
    return Boolean(
      readNonEmptyString(action.folder_id) ||
        readNonEmptyString(locator.id) ||
        readNonEmptyString(locator.path) ||
        readNonEmptyString(locator.name),
    );
  }

  function warnUnknownKeys(objectValue, knownKeys, path, warnings) {
    for (const key of Object.keys(objectValue)) {
      if (!knownKeys.has(key)) {
        warnings.push(
          diagnostic("warning", `${path}.${key}`, "Unknown key; check for a typo or stale field."),
        );
      }
    }
  }

  function resolveActionStatus(plan, action) {
    if (readNonEmptyString(action.status)) {
      return String(action.status);
    }
    return String(plan.plan_version) === "1" ? "approved" : "proposed";
  }

  function buildSummary(totalActions, errors, warnings, executableActions, reviewActions) {
    return {
      ok: errors.length === 0,
      totalActions,
      executableActions,
      reviewActions,
      errors,
      warnings,
    };
  }

  function formatDiagnostic(entry) {
    const prefix = entry.level === "warning" ? "WARNING" : "ERROR";
    return `[${prefix}] ${entry.path}: ${entry.message}`;
  }

  function diagnostic(level, path, message) {
    return { level, path, message };
  }

  function readNonEmptyString(value) {
    return typeof value === "string" && value.trim() ? value.trim() : "";
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function formatJsonParseError(text, error) {
    const raw = error instanceof Error ? error.message : String(error);
    const match = raw.match(/position\s+(\d+)/i);
    if (!match) {
      return `Invalid JSON: ${raw}`;
    }
    const offset = Number.parseInt(match[1], 10);
    const before = text.slice(0, offset);
    const lines = before.split("\n");
    const line = lines.length;
    const column = lines[lines.length - 1].length + 1;
    return `Invalid JSON at line ${line}, column ${column}: ${raw}`;
  }

  globalScope.BookmarkPlanLint = {
    EXECUTABLE_ACTIONS,
    EXECUTABLE_STATUSES,
    formatDiagnostic,
    lintPlan,
    parsePlanText,
    resolveActionStatus,
  };
})(globalThis);
