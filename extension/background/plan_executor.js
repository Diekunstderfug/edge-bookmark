/* Reviewed plan 的执行顺序、checkpoint 与报告聚合。 */

(function attachPlanExecutor(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  function create(dependencies) {
    const options = dependencies || {};
    const planSchema = options.planSchema || root.PlanSchema;
    const executionPolicy = options.executionPolicy || background.ExecutionPolicy;
    const actionHandlers = options.actionHandlers;
    const bookmarkApi = options.bookmarkApi || background.BookmarkApi;
    const bookmarkTree = options.bookmarkTree;
    const checkpointStore = options.checkpointStore;
    const saveReport = options.saveReport;
    const now = typeof options.now === "function" ? options.now : () => new Date();
    const createExecutionId = typeof options.createExecutionId === "function"
      ? options.createExecutionId
      : () => `exec-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const locatorLabel = typeof options.locatorLabel === "function"
      ? options.locatorLabel
      : defaultLocatorLabel;

    if (!planSchema || !executionPolicy || !actionHandlers || !bookmarkApi || !bookmarkTree) {
      throw new Error("PlanExecutor requires schema, policy, handlers, bookmark api, and bookmark tree.");
    }
    if (!checkpointStore || typeof checkpointStore.save !== "function" ||
        typeof checkpointStore.clear !== "function") {
      throw new Error("PlanExecutor requires checkpointStore.save/clear.");
    }
    if (typeof saveReport !== "function") {
      throw new Error("PlanExecutor requires saveReport(report).");
    }

    async function execute(plan, executionOptions) {
      const runtime = executionOptions || {};
      const focusPath = runtime.focusPath || "";
      const onProgress = typeof runtime.onProgress === "function"
        ? runtime.onProgress
        : async function () {};
      const shouldCancel = typeof runtime.shouldCancel === "function"
        ? runtime.shouldCancel
        : async function () { return false; };

      executionPolicy.validateExecutablePlan(plan);
      const stopOnFailure =
        (plan.summary && plan.summary.stop_on_failure === true) ||
        (plan.details && plan.details.stop_on_failure === true);
      const executionId = createExecutionId();
      const grouped = new Map(planSchema.EXECUTION_ORDER.map((type) => [type, []]));
      for (const action of plan.actions) {
        if (executionPolicy.isExecutablePlanAction(plan, action)) {
          grouped.get(action.action_type).push(action);
        }
      }

      const succeeded = [];
      const failures = [];
      const totalActions = planSchema.EXECUTION_ORDER.reduce(
        (sum, actionType) => sum + grouped.get(actionType).length,
        0,
      );
      await checkpointStore.save({
        executionId,
        totalActions,
        done: 0,
        succeeded: [],
        failures: [],
      });
      await assertNotCancelled(shouldCancel);
      await onProgress("Starting plan execution...");
      const bookmarkRoots = await bookmarkApi.getTree();
      const indexes = bookmarkTree.buildFolderPathIndex(bookmarkRoots && bookmarkRoots[0]);

      let stoppedOnFailure = false;
      for (const actionType of planSchema.EXECUTION_ORDER) {
        for (const action of grouped.get(actionType)) {
          await assertNotCancelled(shouldCancel);
          try {
            await actionHandlers.apply(action, {
              executionId,
              focusPath,
              idToPath: indexes.idToPath,
              pathToId: indexes.pathToId,
            });
            succeeded.push({
              actionId: action.action_id || "",
              actionType,
              target: action.to_path || action.target_path || locatorLabel(action),
              result: "succeeded",
              executed_at: now().toISOString(),
            });
          } catch (error) {
            failures.push({
              actionId: action.action_id || "",
              actionType,
              target: action.to_path || action.target_path || locatorLabel(action),
              error: error.message || String(error),
              executed_at: now().toISOString(),
            });
            if (stopOnFailure) {
              stoppedOnFailure = true;
              break;
            }
          }

          const done = succeeded.length + failures.length;
          await checkpointStore.save({ executionId, totalActions, done, succeeded, failures });
          await onProgress(`Executing action ${done}/${totalActions}...`);
          await assertNotCancelled(shouldCancel);
        }
        if (stoppedOnFailure) break;
      }

      const report = {
        plan_version: plan.plan_version || "2",
        plan_kind: plan.plan_kind || "reviewed",
        executed_at: succeeded[0]?.executed_at || now().toISOString(),
        succeeded,
        failures,
      };
      await saveReport(report);
      await checkpointStore.clear();
      await onProgress("Execution report saved for popup restore.");
      return report;
    }

    return Object.freeze({ execute });
  }

  async function assertNotCancelled(shouldCancel) {
    if (await shouldCancel()) {
      const error = new Error("Cancelled by user.");
      error.name = "AbortError";
      throw error;
    }
  }

  function defaultLocatorLabel(action) {
    const bookmark = action.bookmark_locator || {};
    const folder = action.folder_locator || {};
    return bookmark.title || bookmark.id || action.bookmark_id ||
      folder.path || folder.id || action.folder_id || "";
  }

  background.PlanExecutor = Object.freeze({ create });
})(globalThis);
