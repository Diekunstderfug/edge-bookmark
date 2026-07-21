/* 书签树 locator、路径索引与目录创建。 */

(function attachBookmarkTree(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  function create(dependencies) {
    const options = dependencies || {};
    const api = options.api;
    const normalizeUrl = options.normalizeUrl;
    if (!api) {
      throw new Error("BookmarkTree requires a bookmark api adapter.");
    }
    if (typeof normalizeUrl !== "function") {
      throw new Error("BookmarkTree requires normalizeUrl(url).");
    }

    async function resolveFolderId(action, folderPathIndex, idToPath) {
      const locator = action.folder_locator || {};
      const candidateId = locator.id || action.folder_id || "";
      if (candidateId) {
        let nodes = null;
        try {
          nodes = await api.get(candidateId);
        } catch (_error) {
          nodes = null;
        }
        if (nodes && nodes[0]) {
          if (!nodes[0].url && await folderNodeMatchesLocator(nodes[0], action, idToPath)) {
            return candidateId;
          }
          throw new Error("Folder locator id did not match the current folder metadata");
        }
      }

      const path = locator.path || action.from_path || "";
      if (!path) return "";
      if (folderPathIndex && folderPathIndex.has(path)) {
        return folderPathIndex.get(path);
      }
      const tree = await api.getTree();
      return resolvePathToFolderId(tree[0], path, folderPathIndex);
    }

    async function resolveBookmarkId(action, idToPath) {
      const locator = action.bookmark_locator || {};
      const candidateId = locator.id || action.bookmark_id || "";
      const hasTitle = typeof locator.title === "string" && locator.title.length > 0;
      const hasStrongLocator = Boolean(locator.url || locator.normalized_url || hasTitle);
      if (candidateId) {
        let nodes = null;
        try {
          nodes = await api.get(candidateId);
        } catch (_error) {
          nodes = null;
        }
        if (nodes && nodes[0]) {
          if (nodes[0].url && await bookmarkNodeMatchesLocator(nodes[0], action, idToPath)) {
            return candidateId;
          }
          throw new Error("Bookmark locator id did not match the current bookmark metadata");
        }
        if (!hasStrongLocator) return "";
      }

      const searchUrl = locator.url || "";
      if (searchUrl) {
        const matches = await api.search({ url: searchUrl });
        for (const node of matches) {
          if (
            (locator.title ? node.title === locator.title : true) &&
            (locator.folder_path
              ? await nodeParentPath(node.parentId, idToPath) === locator.folder_path
              : true)
          ) {
            return node.id;
          }
        }
      }

      const searchQuery = hasTitle
        ? { title: locator.title }
        : locator.normalized_url
          ? { url: locator.normalized_url }
          : null;
      if (!searchQuery) return "";

      const allMatches = await api.search(searchQuery);
      for (const node of allMatches) {
        if (!node.url) continue;
        if (
          (locator.normalized_url
            ? normalizeUrl(node.url || "") === locator.normalized_url
            : true) &&
          (locator.folder_path
            ? await nodeParentPath(node.parentId, idToPath) === locator.folder_path
            : true)
        ) {
          return node.id;
        }
      }
      return "";
    }

    async function bookmarkNodeMatchesLocator(node, action, idToPath) {
      const locator = action.bookmark_locator || {};
      if (locator.title && node.title !== locator.title) return false;
      if (locator.url && node.url !== locator.url) return false;
      if (locator.normalized_url && normalizeUrl(node.url || "") !== locator.normalized_url) {
        return false;
      }
      if (
        locator.folder_path &&
        await nodeParentPath(node.parentId, idToPath) !== locator.folder_path
      ) {
        return false;
      }
      return true;
    }

    async function folderNodeMatchesLocator(node, action, idToPath) {
      const locator = action.folder_locator || {};
      if (locator.name && node.title !== locator.name) return false;
      const expectedPath = expectedFolderPath(action);
      if (!expectedPath) return true;
      const parentPath = await nodeParentPath(node.parentId, idToPath);
      const actualPath = `${parentPath}/${node.title || ""}`.replace(/\/+/g, "/");
      return actualPath === expectedPath;
    }

    function expectedFolderPath(action) {
      const locator = action.folder_locator || {};
      return locator.path || action.from_path || "";
    }

    async function nodeParentPath(parentId, idPathIndex) {
      if (!parentId) return "";
      if (idPathIndex && idPathIndex.has(parentId)) {
        return idPathIndex.get(parentId);
      }
      const chain = [];
      let currentId = parentId;
      while (currentId && currentId !== "0") {
        const nodes = await api.get(currentId);
        if (!nodes || !nodes[0]) break;
        const node = nodes[0];
        chain.unshift(node.title || "");
        currentId = node.parentId;
      }
      return `/${chain.filter(Boolean).join("/")}`;
    }

    async function ensureFolderPath(folderPath, folderPathIndex, idToPath) {
      const parts = folderPath.split("/").filter(Boolean);
      if (parts.length === 0) {
        throw new Error("folder path must not be empty");
      }
      const createdFolders = [];

      if (folderPathIndex && folderPathIndex.has(folderPath)) {
        return { id: folderPathIndex.get(folderPath), createdFolders };
      }

      if (folderPathIndex) {
        const rootPath = `/${parts[0]}`;
        let currentId = folderPathIndex.get(rootPath);
        if (!currentId) {
          throw new Error(`Could not resolve root folder: ${parts[0]}`);
        }

        for (let index = 1; index < parts.length; index += 1) {
          const path = `/${parts.slice(0, index + 1).join("/")}`;
          let nextId = folderPathIndex.get(path);
          if (!nextId) {
            const part = parts[index];
            const next = await api.create({ parentId: currentId, title: part });
            nextId = next.id;
            folderPathIndex.set(path, nextId);
            if (idToPath) idToPath.set(nextId, path);
            createdFolders.push({
              id: nextId,
              parentId: currentId,
              title: next.title || part,
              path,
            });
          }
          currentId = nextId;
        }
        return { id: currentId, createdFolders };
      }

      const tree = await api.getTree();
      const rootNode = tree[0];
      let current = (rootNode.children || []).find((node) => node.title === parts[0]);
      if (!current) {
        throw new Error(`Could not resolve root folder: ${parts[0]}`);
      }

      for (let index = 1; index < parts.length; index += 1) {
        const part = parts[index];
        let next = (current.children || []).find(
          (node) => !node.url && node.title === part,
        );
        if (!next) {
          const refreshedChildren = await api.getChildren(current.id);
          next = (refreshedChildren || []).find(
            (node) => !node.url && node.title === part,
          );
        }
        if (!next) {
          next = await api.create({ parentId: current.id, title: part });
          createdFolders.push({
            id: next.id,
            parentId: current.id,
            title: next.title || part,
            path: `/${parts.slice(0, index + 1).join("/")}`,
          });
        }
        current = next;
      }
      return { id: current.id, createdFolders };
    }

    function createExecutionContext(rootNode) {
      const indexes = buildFolderPathIndex(rootNode);
      return {
        pathToId: indexes.pathToId,
        idToPath: indexes.idToPath,
        ensureFolderPath: (path) => ensureFolderPath(path, indexes.pathToId, indexes.idToPath),
        parentPath: (parentId) => nodeParentPath(parentId, indexes.idToPath),
        removePrefix: (prefix) => removeFolderPathIndexPrefix(
          indexes.pathToId,
          prefix,
          indexes.idToPath,
        ),
        renamePrefix: (oldPrefix, newPrefix) => updateFolderPathIndexPrefix(
          indexes.pathToId,
          oldPrefix,
          newPrefix,
          indexes.idToPath,
        ),
        resolveBookmarkId: (action) => resolveBookmarkId(action, indexes.idToPath),
        resolveFolderId: (action) => resolveFolderId(
          action,
          indexes.pathToId,
          indexes.idToPath,
        ),
      };
    }

    return Object.freeze({
      bookmarkNodeMatchesLocator,
      buildFolderPathIndex,
      createExecutionContext,
      ensureFolderPath,
      expectedFolderPath,
      folderNodeMatchesLocator,
      nodeParentPath,
      removeFolderPathIndexPrefix,
      resolveBookmarkId,
      resolveFolderId,
      resolvePathToFolderId,
      updateFolderPathIndexPrefix,
    });
  }

  function resolvePathToFolderId(rootNode, folderPath, folderPathIndex) {
    if (folderPathIndex && folderPathIndex.has(folderPath)) {
      return folderPathIndex.get(folderPath);
    }
    const parts = folderPath.split("/").filter(Boolean);
    if (!rootNode || parts.length === 0) return "";
    let current = (rootNode.children || []).find((node) => node.title === parts[0]);
    if (!current) return "";
    for (const part of parts.slice(1)) {
      current = (current.children || []).find((node) => !node.url && node.title === part);
      if (!current) return "";
    }
    return current.id;
  }

  function buildFolderPathIndex(rootNode) {
    const pathToId = new Map();
    const idToPath = new Map();

    function visit(node, parentPath) {
      if (!node || node.url) return;
      const path = node.title
        ? `${parentPath}/${node.title}`.replace(/\/+/g, "/")
        : parentPath;
      if (node.id !== "0" && path) {
        pathToId.set(path, node.id);
        idToPath.set(node.id, path);
      }
      for (const child of node.children || []) visit(child, path);
    }

    visit(rootNode, "");
    return { pathToId, idToPath };
  }

  function updateFolderPathIndexPrefix(folderPathIndex, oldPrefix, newPrefix, idToPath) {
    if (!oldPrefix || !newPrefix || oldPrefix === newPrefix) return;
    const updates = [];
    for (const [path, id] of folderPathIndex.entries()) {
      if (path === oldPrefix || path.startsWith(`${oldPrefix}/`)) {
        updates.push([path, path.replace(oldPrefix, newPrefix), id]);
      }
    }
    for (const [oldPath, newPath, id] of updates) {
      folderPathIndex.delete(oldPath);
      folderPathIndex.set(newPath, id);
      if (idToPath) idToPath.set(id, newPath);
    }
  }

  function removeFolderPathIndexPrefix(folderPathIndex, prefix, idToPath) {
    if (!prefix) return;
    for (const path of Array.from(folderPathIndex.keys())) {
      if (path === prefix || path.startsWith(`${prefix}/`)) {
        const id = folderPathIndex.get(path);
        folderPathIndex.delete(path);
        if (idToPath) idToPath.delete(id);
      }
    }
  }

  background.BookmarkTree = Object.freeze({
    buildFolderPathIndex,
    create,
    removeFolderPathIndexPrefix,
    resolvePathToFolderId,
    updateFolderPathIndexPrefix,
  });
})(globalThis);
