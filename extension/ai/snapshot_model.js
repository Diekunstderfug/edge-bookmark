/* AI 规划使用的快照规范化与 URL 快速审查模型。 */

(function attachAiSnapshotModel(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  if (!root.PathUtils && typeof require === "function") {
    require("../shared/path_utils.js");
  }
  if (!root.PathUtils) {
    throw new Error("shared/path_utils.js must load before ai/snapshot_model.js");
  }
  const ai = root.AI || (root.AI = {});
  const pathWithinScope = root.PathUtils.pathWithinScope;
  const IPV4_RE = /^\d{1,3}(\.\d{1,3}){3}$/;

  function buildPlanningSnapshot(snapshot, focusPath) {
    const folders = (snapshot.folders || []).map(normalizeFolder);
    const bookmarks = (snapshot.bookmarks || [])
      .map(normalizeBookmark)
      .filter((bookmark) => !focusPath || pathWithinScope(bookmark.folder_path, focusPath))
      .map((bookmark) => {
        const requiresReview = urlRequiresReview(bookmark.url);
        return {
          ...bookmark,
          review_status: requiresReview ? "fast_reviewed" : "skipped_internal",
          review_method: requiresReview
            ? "extension_fast_title_domain"
            : "system_skip",
          page_title: bookmark.title,
          one_line_summary: bookmark.domain
            ? `${bookmark.title} (${bookmark.domain})`
            : bookmark.title,
          review_confidence: requiresReview ? 0.35 : 1.0,
        };
      });

    return {
      snapshot_version: "2",
      source: snapshot.source || "edge-extension",
      source_path: snapshot.source_path || "edge-bookmarks-api",
      created_at: snapshot.created_at || new Date().toISOString(),
      focus_path: focusPath,
      folders: folders.filter((folder) => (
        !focusPath ||
        pathWithinScope(folder.path, focusPath) ||
        focusPath.startsWith(`${folder.path}/`)
      )),
      bookmarks,
    };
  }

  function normalizeFolder(folder) {
    return {
      id: String(folder.id || ""),
      name: String(folder.name || ""),
      path: String(folder.path || ""),
      parent_path: folder.parent_path || null,
      root_key: String(folder.root_key || ""),
      depth: nonNegativeInteger(folder.depth, 0),
      bookmark_count: nonNegativeInteger(folder.bookmark_count, 0),
      subfolder_count: nonNegativeInteger(folder.subfolder_count, 0),
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
      depth: nonNegativeInteger(bookmark.depth, 0),
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
      if (IPV4_RE.test(hostname) || hostname.includes(":")) {
        return false;
      }
      return hostname.includes(".");
    } catch (_error) {
      return false;
    }
  }

  function nonNegativeInteger(value, fallback) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) {
      return fallback;
    }
    return Math.floor(numberValue);
  }

  ai.SnapshotModel = Object.freeze({
    bookmarkLocator,
    buildPlanningSnapshot,
    normalizeBookmark,
    normalizeFolder,
    urlRequiresReview,
  });
})(globalThis);
