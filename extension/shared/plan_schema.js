/* Reviewed plan 与 action 的共享契约。 */

(function attachPlanSchema(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});

  const EXECUTION_ORDER = Object.freeze([
    "rename_folder",
    "delete_empty_folder",
    "create_folder",
    "move_folder",
    "move_bookmark",
    "remove_duplicate",
    "keep_for_review",
  ]);
  const MUTATION_ACTION_TYPES = Object.freeze([
    "rename_folder",
    "delete_empty_folder",
    "create_folder",
    "move_folder",
    "move_bookmark",
    "remove_duplicate",
  ]);
  const REPORT_ACTION_TYPES = Object.freeze(["keep_for_review"]);
  const AI_ACTIVATION_ACTION_TYPES = Object.freeze([
    "rename_folder",
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
    "delete_empty_folder",
    "keep_for_review",
  ]);
  const EXECUTABLE_STATUSES = Object.freeze(["approved", "edited"]);
  const KNOWN_ACTION_STATUSES = Object.freeze([
    "approved",
    "edited",
    "proposed",
    "blocked",
    "rejected",
  ]);
  const KNOWN_PLAN_KEYS = Object.freeze([
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
  const KNOWN_ACTION_KEYS = Object.freeze([
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

  const mutationTypes = new Set(MUTATION_ACTION_TYPES);
  const reportTypes = new Set(REPORT_ACTION_TYPES);
  const executableStatuses = new Set(EXECUTABLE_STATUSES);

  function readNonEmptyString(value) {
    return typeof value === "string" && value.trim() ? value.trim() : "";
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function isKnownActionType(actionType) {
    const value = String(actionType || "");
    return mutationTypes.has(value) || reportTypes.has(value);
  }

  function resolveActionStatus(plan, action) {
    if (readNonEmptyString(action && action.status)) {
      return String(action.status);
    }
    return String(plan && plan.plan_version) === "1" ? "approved" : "proposed";
  }

  function isExecutableAction(action) {
    if (!action || typeof action !== "object") return false;
    const actionType = String(action.action_type || "");
    const status = String(action.status || "").trim();
    if (reportTypes.has(actionType)) {
      return executableStatuses.has(status) &&
        Boolean(action.details && action.details.review_agreed === true);
    }
    return mutationTypes.has(actionType) && executableStatuses.has(status);
  }

  function hasBookmarkLocator(action) {
    const locator = isPlainObject(action && action.bookmark_locator)
      ? action.bookmark_locator
      : {};
    return Boolean(
      readNonEmptyString(action && action.bookmark_id) ||
      readNonEmptyString(locator.id) ||
      readNonEmptyString(locator.url) ||
      readNonEmptyString(locator.normalized_url) ||
      readNonEmptyString(locator.title)
    );
  }

  function hasFolderLocator(action) {
    const locator = isPlainObject(action && action.folder_locator)
      ? action.folder_locator
      : {};
    return Boolean(
      readNonEmptyString(action && action.folder_id) ||
      readNonEmptyString(locator.id) ||
      readNonEmptyString(locator.path) ||
      readNonEmptyString(locator.name)
    );
  }

  function validateActionShape(actionType, action, actionPath) {
    const value = action || {};
    const path = actionPath || "$";
    const issues = [];

    function requireBookmarkLocator() {
      if (!hasBookmarkLocator(value)) {
        issues.push({
          path,
          message: "Bookmark action needs bookmark_id or bookmark_locator with id/title/url.",
        });
      }
    }

    function requireFolderLocator() {
      if (!hasFolderLocator(value)) {
        issues.push({
          path,
          message: "Folder action needs folder_id or folder_locator with id/path/name.",
        });
      }
    }

    function requireString(field) {
      if (!readNonEmptyString(value[field])) {
        issues.push({ path: `${path}.${field}`, message: "Must be a non-empty string." });
      }
    }

    switch (String(actionType || "")) {
      case "rename_folder":
        requireFolderLocator();
        requireString("to_name");
        break;
      case "create_folder":
        requireString("target_path");
        break;
      case "move_folder":
        requireFolderLocator();
        requireString("to_path");
        break;
      case "move_bookmark":
        requireBookmarkLocator();
        requireString("to_path");
        break;
      case "remove_duplicate":
        requireBookmarkLocator();
        break;
      case "delete_empty_folder":
        requireFolderLocator();
        break;
      case "keep_for_review":
      default:
        break;
    }
    return issues;
  }

  root.PlanSchema = Object.freeze({
    EXECUTION_ORDER,
    AI_ACTIVATION_ACTION_TYPES,
    MUTATION_ACTION_TYPES,
    REPORT_ACTION_TYPES,
    EXECUTABLE_STATUSES,
    KNOWN_ACTION_STATUSES,
    KNOWN_PLAN_KEYS,
    KNOWN_ACTION_KEYS,
    hasBookmarkLocator,
    hasFolderLocator,
    isExecutableAction,
    isKnownActionType,
    isPlainObject,
    readNonEmptyString,
    resolveActionStatus,
    validateActionShape,
  });
})(globalThis);
