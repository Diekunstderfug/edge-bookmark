/* Service Worker runtime message router. 该模块只分发消息，不注册 listener。 */

(function attachMessageRouter(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  if (!root.Protocol && typeof require === "function") {
    require("../shared/message_protocol.js");
  }

  function create(dependencies) {
    const options = dependencies || {};
    const protocol = options.protocol || root.Protocol;
    const lifecycle = options.lifecycle || {};
    const snapshotExport = options.snapshotExport || background.SnapshotExport;

    if (!protocol || !protocol.MESSAGE_TYPES || !protocol.JOB_TYPES || !protocol.JOB_STATUSES) {
      throw new Error("MessageRouter requires the shared message protocol.");
    }
    if (!snapshotExport || typeof snapshotExport.exportCurrentSnapshot !== "function") {
      throw new Error("MessageRouter requires snapshotExport.exportCurrentSnapshot().");
    }

    const messages = protocol.MESSAGE_TYPES;
    const jobTypes = protocol.JOB_TYPES;
    const jobStatuses = protocol.JOB_STATUSES;
    const startJob = requireFunction(
      options.startBackgroundJob || lifecycle.start || lifecycle.startBackgroundJob,
      "lifecycle.start()",
      lifecycle,
    );
    const waitForCompletion = requireFunction(
      options.waitForCompletion || lifecycle.waitForCompletion || lifecycle.waitForBackgroundJobCompletion,
      "lifecycle.waitForCompletion()",
      lifecycle,
    );
    const runApplyForeground = requireFunction(
      options.runApplyForeground || lifecycle.runApplyForeground || lifecycle.runApplyReviewedPlanForeground,
      "lifecycle.runApplyForeground()",
      lifecycle,
    );
    const getActive = requireFunction(
      options.getActiveJob || lifecycle.getActive || lifecycle.getActiveJobForPopup,
      "lifecycle.getActive()",
      lifecycle,
    );
    const cancelActive = requireFunction(
      options.cancelActiveJob || lifecycle.cancel || lifecycle.cancelActiveJob,
      "lifecycle.cancel()",
      lifecycle,
    );
    const runDirectMutation = requireFunction(
      options.runDirectMutation || lifecycle.runDirectMutation || lifecycle.runDirectMutatingOperation,
      "runDirectMutation()",
      lifecycle,
    );
    const undoLastExecution = requireFunction(
      options.undoLastExecution,
      "undoLastExecution()",
    );
    const handleLateOffscreenCompletion = requireFunction(
      options.handleLateOffscreenCompletion || lifecycle.handleLateOffscreenCompletion,
      "handleLateOffscreenCompletion()",
      lifecycle,
    );
    const listFolders = requireFunction(
      options.listFolders || snapshotExport.listFolders,
      "listFolders()",
      snapshotExport,
    );
    const handleOffscreenProgress = optionalFunction(
      options.handleOffscreenProgress || lifecycle.handleOffscreenProgress,
      lifecycle,
    );
    const loadLastPlan = optionalFunction(
      options.loadLastPlan || lifecycle.loadLastPlan,
      lifecycle,
    );
    const log = createLogger(options.logger || options.log);

    function listener(message, _sender, sendResponse) {
      if (!message || typeof message !== "object") {
        return undefined;
      }

      if (message.type === messages.OFFSCREEN_READY || message.type === messages.OFFSCREEN_KEEPALIVE) {
        sendResponse({ ok: true });
        return true;
      }

      if (message.type === messages.OFFSCREEN_PROGRESS) {
        if (!handleOffscreenProgress) {
          sendResponse({ ok: true });
          return true;
        }
        respondAsync(
          () => handleOffscreenProgress(message),
          sendResponse,
          () => ({ ok: true }),
          log,
        );
        return true;
      }

      if (message.type === messages.OFFSCREEN_RESULT || message.type === messages.OFFSCREEN_ERROR) {
        respondAsync(
          () => handleLateOffscreenCompletion(message),
          sendResponse,
          (job) => ({ ok: true, recovered: !!job }),
          log,
        );
        return true;
      }

      if (message.type === messages.APPLY_REVIEWED_PLAN) {
        runApplyCompatibility(message, sendResponse);
        return true;
      }

      if (message.type === messages.EXPORT_SNAPSHOT) {
        respondAsync(
          () => snapshotExport.exportCurrentSnapshot(),
          sendResponse,
          identity,
          log,
        );
        return true;
      }

      if (message.type === messages.GENERATE_AI_PLAN) {
        runPlanCompatibility(
          jobTypes.GENERATE_AI_PLAN,
          { options: message.options || {} },
          "AI planning failed",
          sendResponse,
        );
        return true;
      }

      if (message.type === messages.REVISE_AI_PLAN) {
        runPlanCompatibility(
          jobTypes.REVISE_AI_PLAN,
          { plan: message.plan, options: message.options || {} },
          "AI plan revision failed",
          sendResponse,
        );
        return true;
      }

      if (message.type === messages.START_BACKGROUND_JOB) {
        respondAsync(
          () => startJob(message.job_type, message.payload || {}),
          sendResponse,
          identity,
          log,
        );
        return true;
      }

      if (message.type === messages.GET_ACTIVE_JOB) {
        respondAsync(
          getActive,
          sendResponse,
          (job) => ({ job: job || null }),
          log,
        );
        return true;
      }

      if (message.type === messages.LIST_FOLDERS) {
        respondAsync(
          listFolders,
          sendResponse,
          (folders) => ({ folders }),
          log,
        );
        return true;
      }

      if (message.type === messages.UNDO_LAST_EXECUTION) {
        respondAsync(
          () => runDirectMutation(messages.UNDO_LAST_EXECUTION, undoLastExecution),
          sendResponse,
          identity,
          log,
        );
        return true;
      }

      if (message.type === messages.CANCEL_ACTIVE_JOB) {
        respondAsync(cancelActive, sendResponse, identity, log);
        return true;
      }

      return undefined;
    }

    function runPlanCompatibility(jobType, payload, failurePrefix, sendResponse) {
      Promise.resolve()
        .then(() => startJob(jobType, payload))
        .then(async (startResponse) => {
          if (!startResponse || startResponse.error) {
            const error = startResponse && startResponse.error
              ? startResponse.error
              : "Background job did not start.";
            log(`${failurePrefix}: ${error}`);
            sendResponse(asyncError(error));
            return;
          }

          const finalJob = await waitForCompletion(startResponse.job.id);
          if (!finalJob || finalJob.status === jobStatuses.FAILED) {
            const error = finalJob && (finalJob.error || finalJob.progress)
              ? finalJob.error || finalJob.progress
              : "Background job did not complete.";
            log(`${failurePrefix}: ${error}`);
            sendResponse(asyncError(error));
            return;
          }

          sendResponse(await reviewedPlanResponse(finalJob, loadLastPlan));
        })
        .catch((error) => {
          const message = errorMessage(error);
          log(`${failurePrefix}: ${message}`);
          sendResponse(asyncError(message));
        });
    }

    function runApplyCompatibility(message, sendResponse) {
      Promise.resolve()
        .then(() => runApplyForeground({
          plan: message.plan,
          focusPath: message.focusPath || "",
        }))
        .then((job) => {
          if (job && job.status === jobStatuses.SUCCEEDED && job.result) {
            sendResponse(job.result);
            return;
          }
          const error = (job && (job.error || job.progress)) || "Execution failed.";
          log(`Execution failed: ${error}`);
          sendResponse(executionFailureReport(error));
        })
        .catch((error) => {
          const messageText = errorMessage(error);
          log(`Execution failed: ${messageText}`);
          sendResponse(executionFailureReport(messageText));
        });
    }

    return listener;
  }

  async function reviewedPlanResponse(finalJob, loadLastPlan) {
    if (finalJob && finalJob.result && finalJob.result.reviewed_plan) {
      return { reviewed_plan: finalJob.result.reviewed_plan };
    }
    if (!loadLastPlan) {
      return null;
    }
    const lastPlan = await loadLastPlan();
    if (!lastPlan) {
      return null;
    }
    if (lastPlan.reviewed_plan) {
      return { reviewed_plan: lastPlan.reviewed_plan };
    }
    if (lastPlan.plan) {
      return { reviewed_plan: lastPlan.plan };
    }
    return { reviewed_plan: lastPlan };
  }

  function respondAsync(task, sendResponse, mapResult, log) {
    Promise.resolve()
      .then(task)
      .then((result) => sendResponse(mapResult(result)))
      .catch((error) => {
        const message = errorMessage(error);
        log(message);
        sendResponse(asyncError(message));
      });
  }

  function executionFailureReport(error) {
    return {
      succeeded: [],
      failures: [{ actionType: "plan", error }],
      executed_at: new Date().toISOString(),
    };
  }

  function asyncError(error) {
    return { ok: false, error: String(error || "Unknown error") };
  }

  function errorMessage(error) {
    return error && error.message ? error.message : String(error);
  }

  function identity(value) {
    return value;
  }

  function requireFunction(value, label, receiver) {
    if (typeof value !== "function") {
      throw new Error(`MessageRouter requires ${label}`);
    }
    return receiver ? value.bind(receiver) : value;
  }

  function optionalFunction(value, receiver) {
    if (typeof value !== "function") {
      return null;
    }
    return receiver ? value.bind(receiver) : value;
  }

  function createLogger(logger) {
    if (typeof logger === "function") {
      return function log(message) {
        try {
          suppressRejectedLog(logger(message));
        } catch (_error) {
          // 诊断日志不得阻断 sendResponse。
        }
      };
    }
    if (logger && typeof logger.error === "function") {
      return function log(message) {
        try {
          suppressRejectedLog(logger.error(message));
        } catch (_error) {
          // 诊断日志不得阻断 sendResponse。
        }
      };
    }
    return function () {};
  }

  function suppressRejectedLog(result) {
    if (result && typeof result.catch === "function") {
      result.catch(function () {});
    }
  }

  background.MessageRouter = Object.freeze({ create });
})(globalThis);
