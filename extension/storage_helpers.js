/* Shared storage constants and helpers for popup.js and service_worker.js. */

var LAST_PLAN_STORAGE_NAME = "bookmarkAdvisorLastPlan";
var LAST_REPORT_STORAGE_NAME = "bookmarkAdvisorLastReport";
var ACTIVE_JOB_STORAGE_NAME = "bookmarkAdvisorActiveJob";
var UNDO_LOG_STORAGE_NAME = "bookmarkAdvisorUndoLog";

function chromeStorageSet(key, value) {
  return new Promise(function (resolve, reject) {
    chrome.storage.local.set({ [key]: value }, function () {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve();
    });
  });
}

function chromeStorageGet(key) {
  return new Promise(function (resolve, reject) {
    chrome.storage.local.get(key, function (result) {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(result[key]);
    });
  });
}

function chromeStorageRemove(key) {
  return new Promise(function (resolve, reject) {
    chrome.storage.local.remove(key, function () {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve();
    });
  });
}

function saveLastPlan(plan) {
  return chromeStorageSet(LAST_PLAN_STORAGE_NAME, {
    plan: plan,
    saved_at: new Date().toISOString(),
  });
}

function saveLastReport(report) {
  return chromeStorageSet(LAST_REPORT_STORAGE_NAME, report);
}

function pathWithinScope(path, scope) {
  if (!scope) return true;
  return path === scope || path.startsWith(scope + "/");
}

/* Ensure visibility when loaded via Node require() in tests. */
if (typeof globalThis !== "undefined") {
  globalThis.LAST_PLAN_STORAGE_NAME = LAST_PLAN_STORAGE_NAME;
  globalThis.LAST_REPORT_STORAGE_NAME = LAST_REPORT_STORAGE_NAME;
  globalThis.ACTIVE_JOB_STORAGE_NAME = ACTIVE_JOB_STORAGE_NAME;
  globalThis.UNDO_LOG_STORAGE_NAME = UNDO_LOG_STORAGE_NAME;
  globalThis.chromeStorageSet = chromeStorageSet;
  globalThis.chromeStorageGet = chromeStorageGet;
  globalThis.chromeStorageRemove = chromeStorageRemove;
  globalThis.saveLastPlan = saveLastPlan;
  globalThis.saveLastReport = saveLastReport;
  globalThis.pathWithinScope = pathWithinScope;
}
