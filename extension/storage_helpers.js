/* Compatibility facade for shared storage and path helpers. */

(function attachLegacyStorageHelpers(globalScope) {
  if (typeof require === "function") {
    if (!globalScope.BookmarkAdvisor || !globalScope.BookmarkAdvisor.Protocol) {
      require("./shared/message_protocol.js");
    }
    if (!globalScope.BookmarkAdvisor.Storage) {
      require("./shared/storage.js");
    }
    if (!globalScope.BookmarkAdvisor.PathUtils) {
      require("./shared/path_utils.js");
    }
  }

  const root = globalScope.BookmarkAdvisor || {};
  const protocol = root.Protocol;
  const storage = root.Storage;
  const paths = root.PathUtils;
  if (!protocol || !storage || !paths) {
    throw new Error(
      "shared/message_protocol.js, shared/storage.js, and shared/path_utils.js must load before storage_helpers.js",
    );
  }

  globalScope.LAST_PLAN_STORAGE_NAME = protocol.STORAGE_KEYS.LAST_PLAN;
  globalScope.LAST_REPORT_STORAGE_NAME = protocol.STORAGE_KEYS.LAST_REPORT;
  globalScope.ACTIVE_JOB_STORAGE_NAME = protocol.STORAGE_KEYS.ACTIVE_JOB;
  globalScope.UNDO_LOG_STORAGE_NAME = protocol.STORAGE_KEYS.UNDO_LOG;
  globalScope.chromeStorageSet = storage.set;
  globalScope.chromeStorageGet = storage.get;
  globalScope.chromeStorageRemove = storage.remove;
  globalScope.saveLastPlan = storage.saveLastPlan;
  globalScope.saveLastReport = storage.saveLastReport;
  globalScope.normalizePath = paths.normalizePath;
  globalScope.pathWithinScope = paths.pathWithinScope;
})(globalThis);
