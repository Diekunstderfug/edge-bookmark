/* 书签树快照导出与 URL 元数据提取。 */

(function attachSnapshotExport(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});
  if (!background.BookmarkApi && typeof require === "function") {
    require("./bookmark_api.js");
  }
  const bookmarkApi = background.BookmarkApi;
  if (!bookmarkApi) {
    throw new Error("background/bookmark_api.js must load before background/snapshot_export.js");
  }

  /** Parity with Python bookmark_advisor.utils.normalize_url — same steps, same order. */
  function normalizeUrl(url) {
    if (!url) return "";
    try {
      var parsed = new URL(url);
      var scheme = parsed.protocol.slice(0, -1);
      var host = parsed.host;
      var path = decodeURIComponent(parsed.pathname);
      if (
        (parsed.protocol === "http:" && (parsed.port === "80" || parsed.port === "")) ||
        (parsed.protocol === "https:" && (parsed.port === "443" || parsed.port === ""))
      ) {
        host = parsed.hostname;
      }
      if (path.length > 1) {
        path = path.replace(/\/+$/, "") || "/";
      }
      var kept = [];
      for (var entry of parsed.searchParams.entries()) {
        var key = entry[0], value = entry[1];
        var lowered = key.toLowerCase();
        if (
          lowered === "spm" ||
          lowered === "ref" ||
          lowered === "fbclid" ||
          lowered === "gclid" ||
          lowered === "_" ||
          lowered.startsWith("utm_")
        ) {
          continue;
        }
        if (value === "") {
          continue;
        }
        kept.push([key, value]);
      }
      kept.sort(function (a, b) {
        if (a[0] < b[0]) return -1;
        if (a[0] > b[0]) return 1;
        if (a[1] < b[1]) return -1;
        if (a[1] > b[1]) return 1;
        return 0;
      });
      var query = kept
        .map(function (pair) { return encodeURIComponent(pair[0]) + "=" + encodeURIComponent(pair[1]); })
        .join("&");
      return scheme + "://" + host + path + (query ? "?" + query : "");
    } catch (_error) {
      return url || "";
    }
  }

  function extractDomain(url) {
    try {
      return new URL(url).host.toLowerCase();
    } catch (_error) {
      return "";
    }
  }

  function walkTree(node, parentPath, folders, bookmarks) {
    const isFolder = !node.url;
    const path = node.title ? `${parentPath}/${node.title}` : parentPath;

    if (isFolder && node.id !== "0") {
      const childFolders = (node.children || []).filter((child) => !child.url).length;
      const childBookmarks = (node.children || []).filter((child) => !!child.url).length;
      folders.push({
        id: node.id,
        name: node.title || "",
        path,
        parent_path: parentPath || null,
        root_key: parentPath ? "" : node.title || "",
        depth: parentPath ? path.split("/").filter(Boolean).length - 1 : 0,
        bookmark_count: childBookmarks,
        subfolder_count: childFolders,
        folder_type: node.folderType || "",
        syncing: typeof node.syncing === "boolean" ? node.syncing : null,
      });
    }

    for (const child of node.children || []) {
      if (child.url) {
        bookmarks.push({
          id: child.id,
          title: child.title || "",
          url: child.url || "",
          normalized_url: normalizeUrl(child.url || ""),
          domain: extractDomain(child.url || ""),
          folder_id: node.id,
          folder_path: path,
          top_level_folder: path.split("/").filter(Boolean)[1] || "",
          root_key: path.split("/").filter(Boolean)[0] || "",
          path: `${path}/${child.title || ""}`,
          depth: path.split("/").filter(Boolean).length,
        });
      } else {
        walkTree(child, path, folders, bookmarks);
      }
    }
  }

  async function exportCurrentSnapshot() {
    bookmarkApi.assertAvailable();
    const tree = await bookmarkApi.call("getTree");
    const folders = [];
    const bookmarks = [];
    const rootNode = tree[0];
    walkTree(rootNode, "", folders, bookmarks);
    return {
      snapshot_version: "1",
      source: "edge-extension",
      source_path: "edge-bookmarks-api",
      created_at: new Date().toISOString(),
      folders,
      bookmarks,
    };
  }

  async function listFolders() {
    const snapshot = await exportCurrentSnapshot();
    return (snapshot.folders || [])
      .slice()
      .sort((a, b) => a.path.localeCompare(b.path, "zh-Hans-CN"));
  }

  background.BookmarkUtils = Object.freeze({ normalizeUrl, extractDomain });
  background.SnapshotExport = Object.freeze({
    exportCurrentSnapshot,
    listFolders,
    walkTree,
    normalizeUrl,
    extractDomain,
  });
})(globalThis);
