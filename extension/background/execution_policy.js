/* Reviewed plan 执行前校验、focus scope 策略与 quarantine 路径决策。 */

(function attachExecutionPolicy(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});
  const planSchema = root.PlanSchema;
  const pathUtils = root.PathUtils;

  if (!planSchema) {
    throw new Error("shared/plan_schema.js must load before background/execution_policy.js");
  }
  if (!pathUtils) {
    throw new Error("shared/path_utils.js must load before background/execution_policy.js");
  }

  const QUARANTINE_FOLDER_NAME = "_Quarantine";

  function validateExecutablePlan(plan) {
    if (!plan || typeof plan !== "object" || !Array.isArray(plan.actions)) {
      throw new Error("Plan must contain an actions array.");
    }
    for (const action of plan.actions) {
      if (!action.action_type) {
        throw new Error("Action missing action_type");
      }
      if (!planSchema.isKnownActionType(action.action_type)) {
        throw new Error(`Unknown action_type: ${action.action_type}`);
      }
    }
  }

  function isExecutablePlanAction(plan, action) {
    const resolvedStatus = planSchema.resolveActionStatus(plan, action);
    const classificationAction = resolvedStatus !== String(action.status || "").trim()
      ? Object.assign({}, action, { status: resolvedStatus })
      : action;
    return planSchema.isExecutableAction(classificationAction);
  }

  function checkActionPolicy(action, focusPath) {
    if (!focusPath) {
      return { allowed: true };
    }
    const type = action.action_type;

    switch (type) {
      case "create_folder": {
        const targetPath = action.target_path || "";
        if (!pathUtils.pathWithinScope(targetPath, focusPath)) {
          return {
            allowed: false,
            reason: `create_folder target ${targetPath} is outside focus scope ${focusPath}`,
          };
        }
        return { allowed: true };
      }
      case "move_bookmark":
      case "move_folder": {
        const fromPath = action.from_path || "";
        const toPath = action.to_path || "";
        if (!pathUtils.pathWithinScope(fromPath, focusPath)) {
          return {
            allowed: false,
            reason: `${type} source ${fromPath} is outside focus scope ${focusPath}`,
          };
        }
        if (!pathUtils.pathWithinScope(toPath, focusPath)) {
          return {
            allowed: false,
            reason: `${type} destination ${toPath} is outside focus scope ${focusPath}`,
          };
        }
        return { allowed: true };
      }
      case "rename_folder": {
        const fromPath = action.from_path || "";
        if (!pathUtils.pathWithinScope(fromPath, focusPath)) {
          return {
            allowed: false,
            reason: `rename_folder path ${fromPath} is outside focus scope ${focusPath}`,
          };
        }
        return { allowed: true };
      }
      case "remove_duplicate": {
        const fromPath = action.from_path || (action.bookmark_locator || {}).folder_path || "";
        if (fromPath && !pathUtils.pathWithinScope(fromPath, focusPath)) {
          return {
            allowed: false,
            reason: `remove_duplicate source ${fromPath} is outside focus scope ${focusPath}`,
          };
        }
        return { allowed: true };
      }
      case "delete_empty_folder": {
        const fromPath = action.from_path || (action.folder_locator || {}).path || "";
        if (fromPath && !pathUtils.pathWithinScope(fromPath, focusPath)) {
          return {
            allowed: false,
            reason: `delete_empty_folder path ${fromPath} is outside focus scope ${focusPath}`,
          };
        }
        return { allowed: true };
      }
      case "keep_for_review":
        return { allowed: true };
      default:
        return { allowed: false, reason: `Unknown action_type: ${type}` };
    }
  }

  // 执行层应把从 chrome.bookmarks 读取的当前真实路径传入此断言，
  // 不能只依赖 plan 中的 from_path。
  function assertPathWithinFocus(path, focusPath, label) {
    if (focusPath && !pathUtils.pathWithinScope(path, focusPath)) {
      throw new Error(`${label} ${path} is outside focus scope ${focusPath}`);
    }
  }

  function quarantinePathUnder(parentPath) {
    const normalizedParent = pathUtils.normalizePath(parentPath);
    return normalizedParent === "/"
      ? `/${QUARANTINE_FOLDER_NAME}`
      : `${normalizedParent}/${QUARANTINE_FOLDER_NAME}`;
  }

  function quarantinePathFromFolderIndex(folderPathIndex) {
    if (!folderPathIndex || typeof folderPathIndex.keys !== "function") {
      return "";
    }
    for (const path of folderPathIndex.keys()) {
      if (typeof path === "string" && path.startsWith("/") && !path.includes("/", 1)) {
        return quarantinePathUnder(path);
      }
    }
    return "";
  }

  function quarantinePathFromBookmarkTree(tree) {
    const rootNode = tree && tree[0];
    const firstBar = rootNode && (rootNode.children || []).find((node) => !node.url);
    if (!firstBar) {
      throw new Error("Could not find a bookmark root folder for quarantine.");
    }
    return quarantinePathUnder(firstBar.title || firstBar.id);
  }

  // 只解析调用方已经拥有的状态；若返回空字符串，调用方再实时读取 bookmark tree。
  function knownQuarantinePath(focusPath, folderPathIndex = null) {
    if (focusPath) {
      return quarantinePathUnder(focusPath);
    }
    return quarantinePathFromFolderIndex(folderPathIndex);
  }

  background.ExecutionPolicy = Object.freeze({
    QUARANTINE_FOLDER_NAME,
    assertPathWithinFocus,
    checkActionPolicy,
    isExecutablePlanAction,
    knownQuarantinePath,
    quarantinePathFromBookmarkTree,
    quarantinePathFromFolderIndex,
    quarantinePathUnder,
    validateExecutablePlan,
  });
})(globalThis);
