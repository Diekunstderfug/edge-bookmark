importScripts("ai_planner.js");
importScripts("storage_helpers.js");

const EXECUTION_ORDER = [
  "rename_folder",
  "create_folder",
  "move_folder",
  "move_bookmark",
  "remove_duplicate",
];
const EXECUTABLE_STATUSES = new Set(["approved", "edited"]);
const ACTIVE_JOB_STALE_MS = 30 * 60 * 1000;
let runningJobId = "";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message) {
    return undefined;
  }

  if (message.type === "apply-reviewed-plan") {
    runDirectMutatingOperation("apply-reviewed-plan", () => executeReviewedPlan(message.plan, reportProgress))
      .then((result) => sendResponse(result))
      .catch((error) => {
        reportProgress(`Execution failed: ${error.message || String(error)}`);
        sendResponse({
          succeeded: [],
          failures: [{ actionType: "plan", error: error.message || String(error) }],
          executed_at: new Date().toISOString(),
        });
      });
    return true;
  }

  if (message.type === "export-snapshot") {
    exportCurrentSnapshot()
      .then((result) => sendResponse(result))
      .catch((error) => {
        sendResponse({ error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "generate-ai-plan") {
    runDirectMutatingOperation("generate-ai-plan", () => generateAiReviewedPlan(message.options || {}, reportProgress))
      .then((result) => sendResponse(result))
      .catch((error) => {
        reportProgress(`AI planning failed: ${error.message || String(error)}`);
        sendResponse({ error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "revise-ai-plan") {
    runDirectMutatingOperation("revise-ai-plan", () => reviseAiReviewedPlan(message.plan, message.options || {}, reportProgress))
      .then((result) => sendResponse(result))
      .catch((error) => {
        reportProgress(`AI plan revision failed: ${error.message || String(error)}`);
        sendResponse({ error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "start-background-job") {
    startBackgroundJob(message.job_type, message.payload || {})
      .then((response) => sendResponse(response))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  if (message.type === "get-active-job") {
    getActiveJobForPopup()
      .then((job) => sendResponse({ job: job || null }))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  if (message.type === "list-folders") {
    listFolders()
      .then((folders) => sendResponse({ folders }))
      .catch((error) => sendResponse({ error: error.message || String(error) }));
    return true;
  }

  return undefined;
});

async function startBackgroundJob(jobType, payload) {
  if (!["generate-ai-plan", "revise-ai-plan", "apply-reviewed-plan"].includes(jobType)) {
    return { error: `Unsupported background job type: ${jobType}` };
  }
  if (runningJobId) {
    return { error: "Background job already running in this service worker." };
  }
  runningJobId = "starting";
  let existingJob;
  try {
    existingJob = await chromeStorageGet(ACTIVE_JOB_STORAGE_NAME);
  } catch (error) {
    runningJobId = "";
    throw error;
  }
  if (isFreshRunningJob(existingJob)) {
    runningJobId = "";
    return { error: `Background job already running: ${existingJob.type}` };
  }
  if (isStaleRunningJob(existingJob)) {
    try {
      await failJob(existingJob, "Background job timed out before completion.");
    } catch (error) {
      runningJobId = "";
      throw error;
    }
  }
  const job = {
    id: `job-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    type: jobType,
    status: "running",
    progress: "Starting background job...",
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  runningJobId = job.id;
  void saveActiveJob(job).then(() => runBackgroundJob(job, payload)).catch((error) => {
    void failJob(job, error.message || String(error));
  });
  return { job };
}

async function runDirectMutatingOperation(jobType, callback) {
  if (runningJobId) {
    throw new Error(`Background job already running: ${jobType}`);
  }
  runningJobId = `direct-${jobType}-${Date.now()}`;
  try {
    const existingJob = await chromeStorageGet(ACTIVE_JOB_STORAGE_NAME);
    if (isFreshRunningJob(existingJob)) {
      throw new Error(`Background job already running: ${existingJob.type}`);
    }
    return await callback();
  } finally {
    if (runningJobId.startsWith(`direct-${jobType}-`)) {
      runningJobId = "";
    }
  }
}

async function getActiveJobForPopup() {
  const job = await chromeStorageGet(ACTIVE_JOB_STORAGE_NAME);
  if (isStaleRunningJob(job)) {
    const failed = await failJob(job, "Background job timed out before completion.");
    return failed;
  }
  return job || null;
}

function isFreshRunningJob(job) {
  return !!job && job.status === "running" && !isStaleRunningJob(job);
}

function isStaleRunningJob(job) {
  if (!job || job.status !== "running") {
    return false;
  }
  const updatedAt = Date.parse(job.updated_at || job.started_at || "");
  return !Number.isFinite(updatedAt) || Date.now() - updatedAt > ACTIVE_JOB_STALE_MS;
}

async function failJob(job, message) {
  const failed = {
    ...job,
    status: "failed",
    progress: message,
    error: message,
    updated_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  };
  if (runningJobId === job.id) {
    runningJobId = "";
  }
  await saveActiveJob(failed);
  return failed;
}

async function runBackgroundJob(job, payload) {
  const onProgress = (message) => jobProgress(job, message);
  if (job.type === "generate-ai-plan") {
    const result = await generateAiReviewedPlan(payload.options || {}, onProgress);
    await finishJob(job, result, "AI plan generated.");
    return;
  }
  if (job.type === "revise-ai-plan") {
    const result = await reviseAiReviewedPlan(payload.plan, payload.options || {}, onProgress);
    await finishJob(job, result, "AI plan revision complete.");
    return;
  }
  if (job.type === "apply-reviewed-plan") {
    const result = await executeReviewedPlan(payload.plan, onProgress);
    await finishJob(job, result, "Execution complete.");
  }
}

async function finishJob(job, result, progress) {
  await saveActiveJob({
    ...job,
    status: "succeeded",
    progress,
    result,
    updated_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  });
  if (runningJobId === job.id) {
    runningJobId = "";
  }
}

function saveActiveJob(job) {
  return chromeStorageSet(ACTIVE_JOB_STORAGE_NAME, job);
}

function jobProgress(job, message) {
  const updated = {
    ...job,
    status: "running",
    progress: message,
    updated_at: new Date().toISOString(),
  };
  return Promise.all([
    saveActiveJob(updated),
    chromeStorageSet("bookmarkAdvisorProgress", { message, updated_at: Date.now() }),
  ]);
}

async function generateAiReviewedPlan(options, onProgress = reportProgress) {
  await onProgress("Exporting current bookmarks...");
  const snapshot = await exportCurrentSnapshot();
  await onProgress("Calling LLM endpoint...");
  const result = await BookmarkAdvisorAI.generateReviewedPlan({
    ...options,
    onProgress,
    snapshot,
  });
  await saveLastPlan(result.reviewed_plan);
  await onProgress("AI plan generated and saved for popup restore.");
  return result;
}

async function reviseAiReviewedPlan(plan, options, onProgress = reportProgress) {
  if (!plan || typeof plan !== "object" || !Array.isArray(plan.actions)) {
    throw new Error("Load a reviewed plan before asking the LLM to revise it.");
  }
  await onProgress("Exporting current bookmarks...");
  const snapshot = await exportCurrentSnapshot();
  await onProgress("Calling LLM endpoint to revise current plan...");
  const result = await BookmarkAdvisorAI.reviseReviewedPlan({
    ...options,
    existingPlan: plan,
    onProgress,
    snapshot,
  });
  await saveLastPlan(result.reviewed_plan);
  await onProgress("AI plan revision saved for popup restore.");
  return result;
}

async function executeReviewedPlan(plan, onProgress = reportProgress) {
  validateExecutablePlan(plan);

  const grouped = new Map(EXECUTION_ORDER.map((actionType) => [actionType, []]));
  for (const action of plan.actions) {
    if (
      !EXECUTABLE_ACTIONS().has(action.action_type) ||
      !EXECUTABLE_STATUSES.has(resolveActionStatus(plan, action))
    ) {
      continue;
    }
    grouped.get(action.action_type).push(action);
  }

  const succeeded = [];
  const failures = [];
  const executedAt = new Date().toISOString();
  const totalActions = EXECUTION_ORDER.reduce(
    (sum, actionType) => sum + grouped.get(actionType).length, 0,
  );

  await onProgress("Starting plan execution...");

  for (const actionType of EXECUTION_ORDER) {
    for (const action of grouped.get(actionType)) {
      try {
        await applyAction(action);
        succeeded.push({
          actionId: action.action_id || "",
          actionType,
          result: "succeeded",
          executed_at: executedAt,
        });
      } catch (error) {
        failures.push({
          actionId: action.action_id || "",
          actionType,
          target: action.to_path || action.target_path || locatorLabel(action),
          error: error.message || String(error),
          executed_at: executedAt,
        });
      }
      await onProgress(`Executing action ${succeeded.length + failures.length}/${totalActions}...`);
    }
  }

  const report = {
    plan_version: plan.plan_version || "2",
    plan_kind: plan.plan_kind || "reviewed",
    executed_at: executedAt,
    succeeded,
    failures,
  };
  await saveLastReport(report);
  await onProgress("Execution report saved for popup restore.");
  return report;
}

async function exportCurrentSnapshot() {
  assertBookmarkApiAvailable();
  const tree = await bookmarkCall("getTree");
  const folders = [];
  const bookmarks = [];
  const root = tree[0];
  walkTree(root, "", folders, bookmarks);
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

function validateExecutablePlan(plan) {
  if (!plan || typeof plan !== "object" || !Array.isArray(plan.actions)) {
    throw new Error("Plan must contain an actions array.");
  }
  for (const action of plan.actions) {
    if (!action.action_type) {
      throw new Error("Action missing action_type");
    }
    if (action.action_type === "keep_for_review") {
      continue;
    }
    if (!EXECUTABLE_ACTIONS().has(action.action_type)) {
      throw new Error(`Unknown action_type: ${action.action_type}`);
    }
  }
}

async function applyAction(action) {
  switch (action.action_type) {
    case "create_folder":
      if (!action.target_path) {
        throw new Error("create_folder requires target_path");
      }
      await ensureFolderPath(action.target_path);
      return;
    case "rename_folder":
      if (!action.to_name) {
        throw new Error("rename_folder requires to_name");
      }
      await renameFolder(action);
      return;
    case "move_folder":
      if (!action.to_path) {
        throw new Error("move_folder requires to_path");
      }
      await moveFolder(action);
      return;
    case "move_bookmark":
      if (!action.to_path) {
        throw new Error("move_bookmark requires to_path");
      }
      await moveBookmark(action);
      return;
    case "remove_duplicate":
      await removeBookmark(action);
      return;
    default:
      throw new Error(`Unsupported action_type: ${action.action_type}`);
  }
}

async function renameFolder(action) {
  const folderId = await resolveFolderId(action);
  if (!folderId) {
    throw new Error("Could not resolve folder by locator");
  }
  await bookmarkCall("update", folderId, { title: action.to_name });
}

async function moveFolder(action) {
  const folderId = await resolveFolderId(action);
  if (!folderId) {
    throw new Error("Could not resolve folder by locator");
  }
  const fromPath = expectedFolderPath(action);
  if (fromPath && (action.to_path === fromPath || action.to_path.startsWith(`${fromPath}/`))) {
    throw new Error("move_folder destination must not be the source folder or its descendant");
  }
  const destinationFolderId = await ensureFolderPath(action.to_path);
  await bookmarkCall("move", folderId, { parentId: destinationFolderId });
}

async function moveBookmark(action) {
  const bookmarkId = await resolveBookmarkId(action);
  if (!bookmarkId) {
    throw new Error("Could not resolve bookmark by locator");
  }
  const destinationFolderId = await ensureFolderPath(action.to_path);
  await bookmarkCall("move", bookmarkId, { parentId: destinationFolderId });
}

async function removeBookmark(action) {
  const bookmarkId = await resolveBookmarkId(action);
  if (!bookmarkId) {
    throw new Error("Could not resolve bookmark by locator");
  }
  await bookmarkCall("remove", bookmarkId);
}

async function resolveFolderId(action) {
  const locator = action.folder_locator || {};
  const candidateId = locator.id || action.folder_id || "";
  if (candidateId) {
    let nodes = null;
    try {
      nodes = await bookmarkCall("get", candidateId);
    } catch (_error) {
      nodes = null;
    }
    if (nodes && nodes[0]) {
      if (!nodes[0].url && await folderNodeMatchesLocator(nodes[0], action)) {
        return candidateId;
      }
      throw new Error("Folder locator id did not match the current folder metadata");
    }
  }

  const tree = await bookmarkCall("getTree");
  const path = locator.path || action.from_path || "";
  if (!path) {
    return "";
  }
  return resolvePathToFolderId(tree[0], path);
}

async function resolveBookmarkId(action) {
  const locator = action.bookmark_locator || {};
  const candidateId = locator.id || action.bookmark_id || "";
  if (candidateId) {
    let nodes = null;
    try {
      nodes = await bookmarkCall("get", candidateId);
    } catch (_error) {
      nodes = null;
    }
    if (nodes && nodes[0]) {
      if (nodes[0].url && await bookmarkNodeMatchesLocator(nodes[0], action)) {
        return candidateId;
      }
      throw new Error("Bookmark locator id did not match the current bookmark metadata");
    }
  }

  const searchUrl = locator.url || "";
  if (searchUrl) {
    const matches = await bookmarkSearch({ url: searchUrl });
    for (const node of matches) {
      if ((locator.title ? node.title === locator.title : true) &&
          (locator.folder_path ? await nodeParentPath(node.parentId) === locator.folder_path : true)) {
        return node.id;
      }
    }
  }

  const allMatches = await bookmarkSearch({ title: locator.title || "" });
  for (const node of allMatches) {
    if (!node.url) {
      continue;
    }
    const normalizedNodeUrl = normalizeUrl(node.url || "");
    if (
      (locator.normalized_url ? normalizedNodeUrl === locator.normalized_url : true) &&
      (locator.folder_path ? await nodeParentPath(node.parentId) === locator.folder_path : true)
    ) {
      return node.id;
    }
  }
  return "";
}

async function bookmarkNodeMatchesLocator(node, action) {
  const locator = action.bookmark_locator || {};
  if (locator.title && node.title !== locator.title) {
    return false;
  }
  if (locator.url && node.url !== locator.url) {
    return false;
  }
  if (locator.normalized_url && normalizeUrl(node.url || "") !== locator.normalized_url) {
    return false;
  }
  if (locator.folder_path && await nodeParentPath(node.parentId) !== locator.folder_path) {
    return false;
  }
  return true;
}

async function folderNodeMatchesLocator(node, action) {
  const locator = action.folder_locator || {};
  if (locator.name && node.title !== locator.name) {
    return false;
  }
  const expectedPath = expectedFolderPath(action);
  if (expectedPath) {
    const parentPath = await nodeParentPath(node.parentId);
    const actualPath = `${parentPath}/${node.title || ""}`.replace(/\/+/g, "/");
    return actualPath === expectedPath;
  }
  return true;
}

function expectedFolderPath(action) {
  const locator = action.folder_locator || {};
  return locator.path || action.from_path || "";
}

async function nodeParentPath(parentId) {
  if (!parentId) {
    return "";
  }
  const chain = [];
  let currentId = parentId;
  while (currentId && currentId !== "0") {
    const nodes = await bookmarkCall("get", currentId);
    if (!nodes || !nodes[0]) {
      break;
    }
    const node = nodes[0];
    chain.unshift(node.title || "");
    currentId = node.parentId;
  }
  return `/${chain.filter(Boolean).join("/")}`;
}

async function ensureFolderPath(folderPath) {
  const parts = folderPath.split("/").filter(Boolean);
  if (parts.length === 0) {
    throw new Error("folder path must not be empty");
  }

  const tree = await bookmarkCall("getTree");
  const root = tree[0];
  let current = (root.children || []).find((node) => node.title === parts[0]);
  if (!current) {
    throw new Error(`Could not resolve root folder: ${parts[0]}`);
  }

  for (const part of parts.slice(1)) {
    let next = (current.children || []).find(
      (node) => !node.url && node.title === part,
    );
    if (!next) {
      const refreshedChildren = await bookmarkCall("getChildren", current.id);
      next = (refreshedChildren || []).find(
        (node) => !node.url && node.title === part,
      );
    }
    if (!next) {
      next = await bookmarkCall("create", {
        parentId: current.id,
        title: part,
      });
    }
    current = next;
  }

  return current.id;
}

function resolvePathToFolderId(root, folderPath) {
  const parts = folderPath.split("/").filter(Boolean);
  let current = (root.children || []).find((node) => node.title === parts[0]);
  if (!current) {
    return "";
  }
  for (const part of parts.slice(1)) {
    current = (current.children || []).find((node) => !node.url && node.title === part);
    if (!current) {
      return "";
    }
  }
  return current.id;
}

function bookmarkCall(method, ...args) {
  assertBookmarkApiAvailable();
  return new Promise((resolve, reject) => {
    chrome.bookmarks[method](...args, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(result);
    });
  });
}

function assertBookmarkApiAvailable() {
  if (!chrome.bookmarks || typeof chrome.bookmarks.getTree !== "function") {
    throw new Error("Bookmark permission is unavailable. Enable the extension's Bookmarks permission, then reload the extension.");
  }
}

function bookmarkSearch(query) {
  return new Promise((resolve, reject) => {
    chrome.bookmarks.search(query, (results) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(results || []);
    });
  });
}

function EXECUTABLE_ACTIONS() {
  return new Set(EXECUTION_ORDER);
}

function locatorLabel(action) {
  const bookmark = action.bookmark_locator || {};
  const folder = action.folder_locator || {};
  return bookmark.title || bookmark.id || action.bookmark_id || folder.path || folder.id || action.folder_id || "";
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

function resolveActionStatus(plan, action) {
  if (action.status) {
    return action.status;
  }
  return plan.plan_version === "1" ? "approved" : "proposed";
}

function reportProgress(message) {
  return chromeStorageSet("bookmarkAdvisorProgress", { message, updated_at: Date.now() });
}
