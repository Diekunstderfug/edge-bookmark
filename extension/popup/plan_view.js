(function attachPopupPlanView(globalScope) {
  const root = globalScope.BookmarkAdvisor = globalScope.BookmarkAdvisor || {};
  const popup = root.Popup = root.Popup || {};

  function create(dependencies) {
    const options = dependencies || {};
    const reviewCategoryKey = options.reviewCategoryKey || "__review__";
    const rejectedCategoryKey = options.rejectedCategoryKey || "__rejected__";
    const reportOnlyActions = options.reportOnlyActions || new Set();
    const isExecutableAction = options.isExecutableAction;
    const t = typeof options.t === "function" ? options.t : (key) => key;

    if (typeof isExecutableAction !== "function") {
      throw new Error("Popup PlanView requires isExecutableAction.");
    }

    function actionDisplayStatus(action) {
      const type = String(action.action_type || "");
      if (type === "keep_for_review") {
        return actionReviewAgreed(action) ? "executable" : "review";
      }
      const status = String(action.status || "").trim();
      if (status === "approved" || status === "edited") return "executable";
      if (status === "blocked") return "blocked";
      if (status === "rejected") return "rejected";
      return "pending";
    }

    function actionReviewAgreed(action) {
      if (reportOnlyActions.has(String(action.action_type || ""))) {
        return isExecutableAction(action);
      }
      return actionDisplayStatus(action) === "executable";
    }

    function categoryKeyForAction(action) {
      const displayStatus = actionDisplayStatus(action);
      if (displayStatus === "rejected") return rejectedCategoryKey;
      if (displayStatus !== "executable") return reviewCategoryKey;
      const type = String(action.action_type || "");
      if (type === "move_bookmark" || type === "move_folder") {
        return String(action.to_path || "/unclassified");
      }
      if (type === "create_folder") {
        return String(action.target_path || "/unclassified");
      }
      if (
        type === "rename_folder" ||
        type === "remove_duplicate" ||
        type === "delete_empty_folder"
      ) {
        return String(action.from_path || "/unclassified");
      }
      return reviewCategoryKey;
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

    function sortCategories(categories) {
      return categories.slice().sort((a, b) => {
        const aIsRejected = a.key === rejectedCategoryKey;
        const bIsRejected = b.key === rejectedCategoryKey;
        if (aIsRejected && !bIsRejected) return 1;
        if (!aIsRejected && bIsRejected) return -1;
        const aIsReview = a.key === reviewCategoryKey;
        const bIsReview = b.key === reviewCategoryKey;
        if (aIsReview && !bIsReview) return 1;
        if (!aIsReview && bIsReview) return -1;
        return b.actions.length - a.actions.length;
      });
    }

    function shouldShowQuickAgreeAction(_action, isReviewCategory) {
      return isReviewCategory;
    }

    function actionTitle(action) {
      const locator = action.bookmark_locator || {};
      const folderLocator = action.folder_locator || {};
      if (String(action.action_type || "") === "keep_for_review") {
        return locator.title ||
          folderLocator.name ||
          String(action.reason || "") ||
          t("action_review_item");
      }
      return locator.title || folderLocator.name || String(action.action_type || "");
    }

    function actionTypeLabel(type) {
      const labels = {
        move_bookmark: "action_move",
        move_folder: "action_move",
        rename_folder: "action_rename",
        create_folder: "action_create",
        remove_duplicate: "action_dedup",
        delete_empty_folder: "action_delete_empty_folder",
        keep_for_review: "action_review",
      };
      return labels[type] ? t(labels[type]) : type;
    }

    function confidenceClass(value) {
      if (value >= 0.85) return "high";
      if (value >= 0.5) return "medium";
      return "low";
    }

    function lastSegment(path) {
      if (!path || path === reviewCategoryKey) return path || "";
      const parts = path.replace(/\/+$/, "").split("/");
      return parts[parts.length - 1] || "/";
    }

    return Object.freeze({
      actionDisplayStatus,
      actionReviewAgreed,
      actionTitle,
      actionTypeLabel,
      categoryKeyForAction,
      confidenceClass,
      groupActionsByCategory,
      lastSegment,
      shouldShowQuickAgreeAction,
      sortCategories,
    });
  }

  popup.PlanView = Object.freeze({ create });
})(globalThis);
