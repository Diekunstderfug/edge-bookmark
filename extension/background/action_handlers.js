/* Reviewed plan 的单动作执行器。所有平台与领域依赖均由 factory 注入。 */

(function attachActionHandlers(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  function create(dependencies) {
    const options = dependencies || {};
    const bookmarkApi = options.bookmarkApi;
    const bookmarkTree = options.bookmarkTree;
    const executionPolicy = options.executionPolicy;
    const undoLog = options.undoLog;

    if (!bookmarkApi) {
      throw new Error("ActionHandlers requires bookmarkApi.");
    }
    if (!bookmarkTree) {
      throw new Error("ActionHandlers requires bookmarkTree.");
    }
    if (!executionPolicy) {
      throw new Error("ActionHandlers requires executionPolicy.");
    }
    if (!undoLog) {
      throw new Error("ActionHandlers requires undoLog.");
    }

    function contextValues(context) {
      const value = context || {};
      return {
        focusPath: value.focusPath || "",
        executionId: value.executionId || "",
        pathToId: value.pathToId || null,
        idToPath: value.idToPath || null,
      };
    }

    function nodePath(parentPath, title) {
      return `${parentPath}/${title || ""}`.replace(/\/+/g, "/");
    }

    async function currentFolderPath(node, idToPath) {
      return nodePath(
        await bookmarkTree.nodeParentPath(node.parentId, idToPath),
        node.title,
      );
    }

    async function resolveQuarantinePath(focusPath, pathToId) {
      const knownPath = executionPolicy.knownQuarantinePath(focusPath, pathToId);
      if (knownPath) return knownPath;
      return executionPolicy.quarantinePathFromBookmarkTree(
        await bookmarkApi.getTree(),
      );
    }

    async function createFolder(action, context) {
      if (!action.target_path) {
        throw new Error("create_folder requires target_path");
      }
      const { executionId, pathToId, idToPath } = contextValues(context);
      const result = await bookmarkTree.ensureFolderPath(
        action.target_path,
        pathToId,
        idToPath,
      );
      if (executionId) {
        for (const folder of result.createdFolders) {
          await undoLog.recordCreatedFolder(executionId, action, folder);
        }
      }
    }

    async function renameFolder(action, context) {
      if (!action.to_name) {
        throw new Error("rename_folder requires to_name");
      }
      const { executionId, pathToId, idToPath } = contextValues(context);
      const folderId = await bookmarkTree.resolveFolderId(action, pathToId, idToPath);
      if (!folderId) {
        throw new Error("Could not resolve folder by locator");
      }
      const [folderNode] = await bookmarkApi.get(folderId);
      if (executionId) {
        await undoLog.recordRenamedFolder(
          executionId,
          action,
          { id: folderId, title: folderNode.title },
        );
      }
      await bookmarkApi.update(folderId, { title: action.to_name });
      if (pathToId) {
        const parentPath = await bookmarkTree.nodeParentPath(folderNode.parentId, idToPath);
        const oldPath = bookmarkTree.expectedFolderPath(action) || nodePath(parentPath, folderNode.title);
        const newPath = nodePath(parentPath, action.to_name);
        bookmarkTree.updateFolderPathIndexPrefix(pathToId, oldPath, newPath, idToPath);
      }
    }

    async function deleteEmptyFolder(action, context) {
      const { executionId, pathToId, idToPath } = contextValues(context);
      const folderId = await bookmarkTree.resolveFolderId(action, pathToId, idToPath);
      if (!folderId) {
        throw new Error("Could not resolve folder by locator");
      }
      const [folderNode] = await bookmarkApi.get(folderId);
      const folderPath = bookmarkTree.expectedFolderPath(action) ||
        await currentFolderPath(folderNode, idToPath);

      // chrome.bookmarks.remove 是空目录删除的原子仲裁：若目录在执行瞬间非空，
      // 浏览器会拒绝删除。失败后才读取 children，以便返回更明确的错误。
      try {
        await bookmarkApi.remove(folderId);
      } catch (removeError) {
        const children = await bookmarkApi.getChildren(folderId);
        if ((children || []).length > 0) {
          throw new Error("delete_empty_folder requires the folder to be empty");
        }
        throw removeError;
      }

      if (pathToId) {
        bookmarkTree.removeFolderPathIndexPrefix(pathToId, folderPath, idToPath);
      }
      // 只有浏览器确认删除成功后才写入 recreate-folder 撤销记录。
      if (executionId) {
        await undoLog.recordDeletedFolder(executionId, action, {
          id: folderId,
          path: folderPath,
          title: folderNode.title,
          parentId: folderNode.parentId,
        });
      }
    }

    async function moveFolder(action, context) {
      if (!action.to_path) {
        throw new Error("move_folder requires to_path");
      }
      const { focusPath, executionId, pathToId, idToPath } = contextValues(context);
      const sourceFolderId = await bookmarkTree.resolveFolderId(action, pathToId, idToPath);
      if (!sourceFolderId) {
        throw new Error("Could not resolve folder by locator");
      }
      const fromPath = bookmarkTree.expectedFolderPath(action);
      if (fromPath && (action.to_path === fromPath || action.to_path.startsWith(`${fromPath}/`))) {
        throw new Error("move_folder destination must not be the source folder or its descendant");
      }

      const [sourceNode] = await bookmarkApi.get(sourceFolderId);
      const actualSourcePath = await currentFolderPath(sourceNode, idToPath);
      executionPolicy.assertPathWithinFocus(
        actualSourcePath,
        focusPath,
        "move_folder source",
      );
      const destination = await bookmarkTree.ensureFolderPath(
        action.to_path,
        pathToId,
        idToPath,
      );
      if (executionId) {
        await undoLog.recordMovedNode(executionId, action, {
          id: sourceFolderId,
          parentId: sourceNode.parentId,
          title: sourceNode.title,
        });
      }
      await bookmarkApi.move(sourceFolderId, { parentId: destination.id });
      if (pathToId) {
        const oldPath = fromPath || actualSourcePath;
        const newPath = nodePath(action.to_path, sourceNode.title);
        bookmarkTree.updateFolderPathIndexPrefix(pathToId, oldPath, newPath, idToPath);
      }
    }

    async function moveBookmark(action, context) {
      if (!action.to_path) {
        throw new Error("move_bookmark requires to_path");
      }
      const { focusPath, executionId, pathToId, idToPath } = contextValues(context);
      const bookmarkId = await bookmarkTree.resolveBookmarkId(action, idToPath);
      if (!bookmarkId) {
        throw new Error("Could not resolve bookmark by locator");
      }
      const [node] = await bookmarkApi.get(bookmarkId);
      const actualSourcePath = await bookmarkTree.nodeParentPath(node.parentId, idToPath);
      executionPolicy.assertPathWithinFocus(
        actualSourcePath,
        focusPath,
        "move_bookmark source",
      );
      const destination = await bookmarkTree.ensureFolderPath(
        action.to_path,
        pathToId,
        idToPath,
      );
      if (executionId) {
        await undoLog.recordMovedNode(executionId, action, {
          id: bookmarkId,
          parentId: node.parentId,
          title: node.title,
          url: node.url || null,
        });
      }
      await bookmarkApi.move(bookmarkId, { parentId: destination.id });
    }

    async function removeDuplicate(action, context) {
      const { focusPath, executionId, pathToId, idToPath } = contextValues(context);
      // 保留当前执行语义：duplicate locator 自己做实时 parent path 校验，
      // 而不是依赖执行开始时构建的 idToPath 快照。
      const bookmarkId = await bookmarkTree.resolveBookmarkId(action);
      if (!bookmarkId) {
        throw new Error("Could not resolve bookmark by locator");
      }
      const [node] = await bookmarkApi.get(bookmarkId);
      const actualSourcePath = await bookmarkTree.nodeParentPath(node.parentId, idToPath);
      executionPolicy.assertPathWithinFocus(
        actualSourcePath,
        focusPath,
        "remove_duplicate source",
      );
      const quarantinePath = await resolveQuarantinePath(focusPath, pathToId);
      executionPolicy.assertPathWithinFocus(
        quarantinePath,
        focusPath,
        "remove_duplicate quarantine",
      );
      const quarantineFolder = await bookmarkTree.ensureFolderPath(
        quarantinePath,
        pathToId,
        idToPath,
      );
      if (executionId) {
        await undoLog.recordMovedNode(executionId, action, {
          id: bookmarkId,
          parentId: node.parentId,
          title: node.title,
          url: node.url || null,
        });
      }
      await bookmarkApi.move(bookmarkId, { parentId: quarantineFolder.id });
    }

    async function keepForReview() {}

    const handlers = Object.freeze({
      create_folder: createFolder,
      rename_folder: renameFolder,
      delete_empty_folder: deleteEmptyFolder,
      move_folder: moveFolder,
      move_bookmark: moveBookmark,
      remove_duplicate: removeDuplicate,
      keep_for_review: keepForReview,
    });

    async function apply(action, context) {
      const { focusPath } = contextValues(context);
      const policy = executionPolicy.checkActionPolicy(action, focusPath);
      if (!policy.allowed) {
        throw new Error(`Policy blocked: ${policy.reason}`);
      }
      const handler = handlers[action.action_type];
      if (!handler) {
        throw new Error(`Unsupported action_type: ${action.action_type}`);
      }
      await handler(action, context || {});
    }

    return Object.freeze({ apply });
  }

  background.ActionHandlers = Object.freeze({ create });
})(globalThis);
