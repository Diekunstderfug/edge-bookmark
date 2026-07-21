/* chrome.bookmarks 的后台 Promise adapter。 */

(function attachBookmarkApi(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  function runtimeLastError() {
    return globalScope.chrome && chrome.runtime ? chrome.runtime.lastError : null;
  }

  function assertAvailable() {
    if (
      !globalScope.chrome ||
      !chrome.bookmarks ||
      typeof chrome.bookmarks.getTree !== "function"
    ) {
      throw new Error(
        "Bookmark permission is unavailable. Enable the extension's Bookmarks permission, then reload the extension."
      );
    }
  }

  function call(method, ...args) {
    assertAvailable();
    return new Promise(function (resolve, reject) {
      chrome.bookmarks[method](...args, function (result) {
        const lastError = runtimeLastError();
        if (lastError) {
          reject(new Error(lastError.message));
          return;
        }
        resolve(result);
      });
    });
  }

  function search(query) {
    assertAvailable();
    return new Promise(function (resolve, reject) {
      chrome.bookmarks.search(query, function (results) {
        const lastError = runtimeLastError();
        if (lastError) {
          reject(new Error(lastError.message));
          return;
        }
        resolve(results || []);
      });
    });
  }

  function getTree() { return call("getTree"); }
  function get(id) { return call("get", id); }
  function getChildren(id) { return call("getChildren", id); }
  function create(details) { return call("create", details); }
  function update(id, changes) { return call("update", id, changes); }
  function move(id, destination) { return call("move", id, destination); }
  function remove(id) { return call("remove", id); }

  background.BookmarkApi = Object.freeze({
    assertAvailable,
    call,
    create,
    get,
    getChildren,
    getTree,
    move,
    remove,
    search,
    update,
  });
})(globalThis);
