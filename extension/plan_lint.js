/* global BookmarkAdvisor */

(function attachBookmarkPlanLint(globalScope) {
  if (
    (!globalScope.BookmarkAdvisor || !globalScope.BookmarkAdvisor.PlanSchema) &&
    typeof require === "function"
  ) {
    require("./shared/plan_schema.js");
  }
  const schema = globalScope.BookmarkAdvisor && globalScope.BookmarkAdvisor.PlanSchema;
  if (!schema) {
    throw new Error("shared/plan_schema.js must load before plan_lint.js");
  }
  const KNOWN_ACTION_TYPES = new Set([
    ...schema.MUTATION_ACTION_TYPES,
    ...schema.REPORT_ACTION_TYPES,
  ]);
  const KNOWN_ACTION_STATUSES = new Set(schema.KNOWN_ACTION_STATUSES);
  const KNOWN_PLAN_KEYS = new Set(schema.KNOWN_PLAN_KEYS);
  const KNOWN_ACTION_KEYS = new Set(schema.KNOWN_ACTION_KEYS);
  const isExecutableAction = schema.isExecutableAction;
  const isPlainObject = schema.isPlainObject;
  const readNonEmptyString = schema.readNonEmptyString;
  const resolveActionStatus = schema.resolveActionStatus;

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
        for (const issue of schema.validateActionShape(actionType, action, actionPath)) {
          errors.push(diagnostic("error", issue.path, issue.message));
        }
      }

      const status = resolveActionStatus(plan, action);
      // 用共享谓词分类。谓词读 action.status,而 lint 需要尊重 plan_version 默认 status
      // (v1 → approved),故当 resolved status 与显式 status 不同时传入副本。
      const classificationAction = status !== String(action.status || "").trim()
        ? Object.assign({}, action, { status })
        : action;
      if (isExecutableAction(classificationAction)) {
        executableActions.push(action);
      } else {
        reviewActions.push(action);
      }
    });

    return buildSummary(plan.actions.length, errors, warnings, executableActions, reviewActions);
  }

  function validateOptionalObject(value, path, errors) {
    if (value === undefined) {
      return;
    }
    if (!isPlainObject(value)) {
      errors.push(diagnostic("error", path, "Must be an object when present."));
    }
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
    formatDiagnostic,
    lintPlan,
    parsePlanText,
    resolveActionStatus,
  };
})(globalThis);
