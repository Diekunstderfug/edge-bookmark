/* fast_rules.json 加载、缓存与内置 fallback。 */

(function attachFastRules(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const ai = root.AI || (root.AI = {});

  const FALLBACK_RULES = {
    defaults: { protect_root_loose_bookmarks: true, allow_new_folders_in_advise: true },
    protected_paths: ["/收藏夹栏", "/其他收藏夹", "/移动收藏夹", "/工作区"],
    category_hints: {},
    folder_relocations: [],
    bookmark_relocations: [],
  };
  const FALLBACK_SOURCE = "extension-embedded-fast-rules-fallback";
  const JSON_SOURCE = "extension-fast-rules-json";

  function create(dependencies) {
    const options = dependencies || {};
    const chromeApi = options.chrome || globalScope.chrome;
    const fetchImpl = options.fetch || globalScope.fetch;
    const log = createLogger(options.log);
    let cache = null;
    let source = FALLBACK_SOURCE;
    let diagnostic = "";

    function get() {
      return cache || FALLBACK_RULES;
    }

    function getSource() {
      return source;
    }

    function getDiagnostic() {
      return diagnostic;
    }

    function useFallback(reason) {
      cache = FALLBACK_RULES;
      source = FALLBACK_SOURCE;
      diagnostic = `fast_rules.json load failed: ${reason}. Using built-in fallback rules.`;
      log(diagnostic, "warn");
      return cache;
    }

    async function load() {
      if (cache) {
        return cache;
      }
      try {
        if (!chromeApi || !chromeApi.runtime || typeof chromeApi.runtime.getURL !== "function") {
          return useFallback("chrome.runtime.getURL unavailable");
        }
        const rulesUrl = chromeApi.runtime.getURL("fast_rules.json");
        const response = await fetchImpl(rulesUrl);
        if (!response.ok) {
          return useFallback(`HTTP ${response.status || "error"}`);
        }
        const data = await response.json();
        cache = {
          defaults: data.defaults || FALLBACK_RULES.defaults,
          protected_paths: Array.isArray(data.protected_paths)
            ? data.protected_paths
            : FALLBACK_RULES.protected_paths,
          category_hints: data.category_hints || {},
          folder_relocations: Array.isArray(data.folder_relocations)
            ? data.folder_relocations
            : [],
          bookmark_relocations: Array.isArray(data.bookmark_relocations)
            ? data.bookmark_relocations
            : [],
        };
        source = JSON_SOURCE;
        diagnostic = "";
        return cache;
      } catch (error) {
        return useFallback(error && error.message ? error.message : String(error));
      }
    }

    return Object.freeze({
      get,
      getDiagnostic,
      getSource,
      load,
      useFallback,
    });
  }

  function createLogger(logger) {
    if (typeof logger === "function") {
      return function log(message, level) {
        try {
          const result = logger(message, level);
          if (result && typeof result.catch === "function") {
            result.catch(function () {});
          }
        } catch (_error) {
          // 诊断日志不得破坏 fallback。
        }
      };
    }
    return function log(message, level) {
      const consoleApi = globalScope.console;
      if (!consoleApi) return;
      const method = level === "warn" ? "warn" : level === "error" ? "error" : "log";
      if (typeof consoleApi[method] === "function") {
        consoleApi[method]("[BookmarkAdvisor]", message);
      }
    };
  }

  ai.FastRules = Object.freeze({ create });
})(globalThis);
