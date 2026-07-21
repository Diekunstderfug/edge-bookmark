/* 路径规范化与 scope 判断。 */

(function attachPathUtils(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});

  function normalizePath(path) {
    if (!path || typeof path !== "string") return "/";
    let normalized = path.trim();
    if (!normalized.startsWith("/")) normalized = "/" + normalized;
    normalized = normalized.replace(/\/+$/, "");
    normalized = normalized.replace(/\/+/g, "/");
    return normalized || "/";
  }

  function pathWithinScope(path, scope) {
    if (!scope) return true;
    const normalizedPath = normalizePath(path);
    const normalizedScope = normalizePath(scope);
    return normalizedPath === normalizedScope || normalizedPath.startsWith(normalizedScope + "/");
  }

  root.PathUtils = Object.freeze({ normalizePath, pathWithinScope });
})(globalThis);
