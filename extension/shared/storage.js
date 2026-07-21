/* chrome.storage 的共享 Promise adapter。 */

(function attachStorage(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  if (!root.Protocol && typeof require === "function") {
    require("./message_protocol.js");
  }
  const protocol = root.Protocol;
  if (!protocol) {
    throw new Error("shared/message_protocol.js must load before shared/storage.js");
  }

  function localArea() {
    if (!globalScope.chrome || !chrome.storage || !chrome.storage.local) {
      throw new Error("chrome.storage.local is unavailable.");
    }
    return chrome.storage.local;
  }

  function runtimeLastError() {
    return globalScope.chrome && chrome.runtime ? chrome.runtime.lastError : null;
  }

  function setInArea(area, key, value) {
    return new Promise(function (resolve, reject) {
      area.set({ [key]: value }, function () {
        const lastError = runtimeLastError();
        if (lastError) {
          reject(new Error(lastError.message));
          return;
        }
        resolve();
      });
    });
  }

  function getFromArea(area, key) {
    return new Promise(function (resolve, reject) {
      area.get(key, function (result) {
        const lastError = runtimeLastError();
        if (lastError) {
          reject(new Error(lastError.message));
          return;
        }
        resolve(result[key]);
      });
    });
  }

  function removeFromArea(area, key) {
    return new Promise(function (resolve, reject) {
      area.remove(key, function () {
        const lastError = runtimeLastError();
        if (lastError) {
          reject(new Error(lastError.message));
          return;
        }
        resolve();
      });
    });
  }

  function set(key, value) {
    return setInArea(localArea(), key, value);
  }

  function get(key) {
    return getFromArea(localArea(), key);
  }

  function remove(key) {
    return removeFromArea(localArea(), key);
  }

  function saveLastPlan(plan) {
    return set(protocol.STORAGE_KEYS.LAST_PLAN, { plan, saved_at: new Date().toISOString() });
  }

  function saveLastReport(report) {
    return set(protocol.STORAGE_KEYS.LAST_REPORT, report);
  }

  root.Storage = Object.freeze({
    get,
    getFromArea,
    remove,
    removeFromArea,
    saveLastPlan,
    saveLastReport,
    set,
    setInArea,
  });
})(globalThis);
