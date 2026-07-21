/* 执行撤销日志：持久化变更前状态，并按最近一次 execution 逆序回滚。 */

(function attachUndoLog(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  if (!root.Protocol && typeof require === "function") {
    require("../shared/message_protocol.js");
  }
  const protocol = root.Protocol;
  if (!protocol) {
    throw new Error("shared/message_protocol.js must load before background/undo_log.js");
  }

  const TYPES = Object.freeze({
    MOVE: "move",
    RENAME: "rename",
    DELETE_FOLDER: "delete_folder",
    CREATE_FOLDER: "create_folder",
  });
  const MAX_EXECUTION_IDS = 20;

  function create(dependencies) {
    const options = dependencies || {};
    const storage = options.storage;
    const bookmarkApi = options.bookmarkApi;
    const bookmarkTree = options.bookmarkTree;

    if (!storage || typeof storage.get !== "function" || typeof storage.set !== "function") {
      throw new Error("UndoLog requires a storage adapter with get/set methods.");
    }
    if (!bookmarkApi) {
      throw new Error("UndoLog requires a bookmark api adapter.");
    }
    if (!bookmarkTree || typeof bookmarkTree.ensureFolderPath !== "function") {
      throw new Error("UndoLog requires bookmarkTree.ensureFolderPath(path).");
    }

    const storageKey = protocol.STORAGE_KEYS.UNDO_LOG;

    async function recordUndo(executionId, action, before, undoType) {
      const entry = {
        undo_id: `undo-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        execution_id: executionId,
        action_id: action.action_id || "",
        action_type: action.action_type,
        before,
        undo_action: undoType === TYPES.DELETE_FOLDER
          ? { type: TYPES.DELETE_FOLDER, id: before.id }
          : undoType === TYPES.RENAME
            ? { type: TYPES.RENAME, id: before.id, title: before.title }
            : undoType === TYPES.CREATE_FOLDER
              ? { type: TYPES.CREATE_FOLDER, path: before.path }
              : { type: TYPES.MOVE, id: before.id, parentId: before.parentId },
        timestamp: new Date().toISOString(),
      };

      const log = (await storage.get(storageKey)) || [];
      log.push(entry);
      const executionIds = [...new Set(log.map((item) => item.execution_id))];
      if (executionIds.length > MAX_EXECUTION_IDS) {
        const staleIds = new Set(
          executionIds.slice(0, executionIds.length - MAX_EXECUTION_IDS),
        );
        await storage.set(
          storageKey,
          log.filter((item) => !staleIds.has(item.execution_id)),
        );
      } else {
        await storage.set(storageKey, log);
      }
    }

    function recordMovedNode(executionId, action, before) {
      return recordUndo(executionId, action, before, TYPES.MOVE);
    }

    function recordRenamedFolder(executionId, action, before) {
      return recordUndo(executionId, action, before, TYPES.RENAME);
    }

    function recordCreatedFolder(executionId, action, before) {
      return recordUndo(executionId, action, before, TYPES.DELETE_FOLDER);
    }

    function recordDeletedFolder(executionId, action, before) {
      return recordUndo(executionId, action, before, TYPES.CREATE_FOLDER);
    }

    async function undoLastExecution() {
      const log = (await storage.get(storageKey)) || [];
      if (log.length === 0) {
        return { undone: false, reason: "No undo log entries found." };
      }

      const lastExecutionId = log[log.length - 1].execution_id;
      const entries = [];
      const remaining = [];
      for (const entry of log) {
        (entry.execution_id === lastExecutionId ? entries : remaining).push(entry);
      }

      const undone = [];
      const undoFailures = [];
      for (const entry of entries.slice().reverse()) {
        try {
          const undoAction = entry.undo_action;
          if (undoAction.type === TYPES.MOVE) {
            await bookmarkApi.move(undoAction.id, { parentId: undoAction.parentId });
          } else if (undoAction.type === TYPES.RENAME) {
            await bookmarkApi.update(undoAction.id, { title: undoAction.title });
          } else if (undoAction.type === TYPES.DELETE_FOLDER) {
            await bookmarkApi.remove(undoAction.id);
          } else if (undoAction.type === TYPES.CREATE_FOLDER) {
            await bookmarkTree.ensureFolderPath(undoAction.path);
          }
          undone.push(entry.undo_id);
        } catch (error) {
          undoFailures.push({
            undo_id: entry.undo_id,
            error: error.message || String(error),
          });
        }
      }

      await storage.set(storageKey, remaining);
      return {
        undone: true,
        execution_id: lastExecutionId,
        count: undone.length,
        failures: undoFailures,
        hasMore: remaining.length > 0,
      };
    }

    return Object.freeze({
      TYPES,
      recordCreatedFolder,
      recordDeletedFolder,
      recordMovedNode,
      recordRenamedFolder,
      recordUndo,
      undoLastExecution,
    });
  }

  background.UndoLog = Object.freeze({ create, TYPES });
})(globalThis);
