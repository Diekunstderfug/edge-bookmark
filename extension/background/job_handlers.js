/* generate/revise/apply 三类后台任务的阶段编排。 */

(function attachJobHandlers(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const background = root.Background || (root.Background = {});

  function create(dependencies) {
    const options = dependencies || {};
    const protocol = options.protocol || root.Protocol;
    const snapshotExport = options.snapshotExport || background.SnapshotExport;
    const runLlm = options.runLlm;
    const executePlan = options.executePlan;
    const saveLastPlan = options.saveLastPlan;
    const log = typeof options.log === "function" ? options.log : function () {};

    if (!protocol || !snapshotExport || typeof runLlm !== "function" ||
        typeof executePlan !== "function" || typeof saveLastPlan !== "function") {
      throw new Error("JobHandlers requires protocol, snapshot, LLM, executor, and plan storage.");
    }
    const JOB_TYPES = protocol.JOB_TYPES;
    const JOB_STAGES = protocol.JOB_STAGES;

    async function run(job, payload, context) {
      const runtime = context || {};
      if (job.type === JOB_TYPES.GENERATE_AI_PLAN) {
        return generate(job, payload, runtime);
      }
      if (job.type === JOB_TYPES.REVISE_AI_PLAN) {
        return revise(job, payload, runtime);
      }
      if (job.type === JOB_TYPES.APPLY_REVIEWED_PLAN) {
        return apply(job, payload, runtime);
      }
      throw new Error(`Unsupported background job type: ${job.type}`);
    }

    async function generate(job, payload, context) {
      const onProgress = requireCallback(context, "onProgress");
      const setStage = requireCallback(context, "setStage");
      const finish = requireCallback(context, "finish");
      log(`[BookmarkAdvisor][SW] runGenerateAiPlan start, jobId=${job.id}`);
      await setStage(job, JOB_STAGES.EXPORT);
      await onProgress("Exporting current bookmarks...");
      const startedAt = Date.now();
      const snapshot = await snapshotExport.exportCurrentSnapshot();
      const elapsedMs = Date.now() - startedAt;
      await onProgress(
        `Snapshot: ${(snapshot.bookmarks || []).length} bookmarks, ` +
        `${(snapshot.folders || []).length} folders (${elapsedMs}ms)`,
      );

      await setStage(job, JOB_STAGES.LLM);
      await onProgress("Creating offscreen document for LLM call...");
      if (typeof context.ensureOffscreen === "function") {
        await context.ensureOffscreen();
      }
      await onProgress("Calling LLM via offscreen document...");
      const llmPayload = generationLlmPayload(payload, snapshot);
      const result = await runLlm(job, "generate", llmPayload, context.controller);

      await setStage(job, JOB_STAGES.SAVE);
      await saveLastPlan(result.reviewed_plan);
      await onProgress("AI plan generated and saved for popup restore.");
      await finish(job, result, "AI plan generated.");
      log(`[BookmarkAdvisor][SW] runGenerateAiPlan complete`);
      return result;
    }

    async function revise(job, payload, context) {
      if (!payload.plan || typeof payload.plan !== "object" || !Array.isArray(payload.plan.actions)) {
        throw new Error("Load a reviewed plan before asking the LLM to revise it.");
      }
      const onProgress = requireCallback(context, "onProgress");
      const setStage = requireCallback(context, "setStage");
      const finish = requireCallback(context, "finish");
      log(`[BookmarkAdvisor][SW] runReviseAiPlan start, jobId=${job.id}`);
      await setStage(job, JOB_STAGES.EXPORT);
      await onProgress("Exporting current bookmarks...");
      const startedAt = Date.now();
      const snapshot = await snapshotExport.exportCurrentSnapshot();
      const elapsedMs = Date.now() - startedAt;
      await onProgress(
        `Snapshot: ${(snapshot.bookmarks || []).length} bookmarks, ` +
        `${(snapshot.folders || []).length} folders (${elapsedMs}ms)`,
      );

      await setStage(job, JOB_STAGES.LLM);
      await onProgress("Creating offscreen document for LLM call...");
      if (typeof context.ensureOffscreen === "function") {
        await context.ensureOffscreen();
      }
      await onProgress("Calling LLM via offscreen document...");
      const llmPayload = revisionLlmPayload(payload, snapshot);
      const result = await runLlm(job, "revise", llmPayload, context.controller);

      await setStage(job, JOB_STAGES.SAVE);
      await saveLastPlan(result.reviewed_plan);
      await onProgress("AI plan revision saved for popup restore.");
      await finish(job, result, "AI plan revision complete.");
      log(`[BookmarkAdvisor][SW] runReviseAiPlan complete`);
      return result;
    }

    async function apply(job, payload, context) {
      const onProgress = requireCallback(context, "onProgress");
      const finish = requireCallback(context, "finish");
      const result = await executePlan(
        payload.plan,
        payload.focusPath || "",
        onProgress,
        { id: job.id },
      );
      await finish(job, result, "Execution complete.");
      return result;
    }

    return Object.freeze({ apply, generate, revise, run });
  }

  function generationLlmPayload(payload, snapshot) {
    const options = payload.options || {};
    return {
      apiKey: options.apiKey,
      apiBaseUrl: options.apiBaseUrl,
      apiStyle: options.apiStyle,
      model: options.model,
      maxActions: options.maxActions,
      requestTimeoutMs: options.requestTimeoutMs,
      maxRetries: options.maxRetries,
      focusPath: options.focusPath,
      userInstruction: options.userInstruction,
      preferences: options.preferences,
      snapshot,
    };
  }

  function revisionLlmPayload(payload, snapshot) {
    const options = payload.options || {};
    return {
      options: {
        apiKey: options.apiKey,
        apiBaseUrl: options.apiBaseUrl,
        apiStyle: options.apiStyle,
        model: options.model,
        maxActions: options.maxActions,
        requestTimeoutMs: options.requestTimeoutMs,
        maxRetries: options.maxRetries,
        focusPath: options.focusPath,
        userInstruction: options.userInstruction,
        preferences: options.preferences,
        snapshot,
      },
      plan: payload.plan,
    };
  }

  function requireCallback(context, name) {
    if (typeof context[name] !== "function") {
      throw new Error(`JobHandlers requires context.${name}().`);
    }
    return context[name];
  }

  background.JobHandlers = Object.freeze({ create, generationLlmPayload, revisionLlmPayload });
})(globalThis);
