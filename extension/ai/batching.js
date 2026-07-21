/* AI 规划快照分批、并发映射与 activation 合并。 */

(function attachAiBatching(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const ai = root.AI || (root.AI = {});

  function splitPlanningSnapshot(snapshot, threshold, size) {
    const bookmarks = snapshot.bookmarks || [];
    if (bookmarks.length <= threshold) {
      return [snapshot];
    }
    const parts = [];
    for (let index = 0; index < bookmarks.length; index += size) {
      parts.push({
        ...snapshot,
        bookmarks: bookmarks.slice(index, index + size),
      });
    }
    return parts;
  }

  async function mapWithConcurrency(items, concurrency, mapper) {
    const results = new Array(items.length);
    let nextIndex = 0;
    const workers = new Array(Math.min(concurrency, items.length)).fill(null).map(async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        results[index] = await mapper(items[index], index);
      }
    });
    await Promise.all(workers);
    return results;
  }

  function mergeActivationPayloads(payloads) {
    const summaryParts = [];
    const activationByKey = new Map();
    const nodeScopedKeyByNode = new Map();

    for (const payload of payloads || []) {
      const overview = payload && payload.summary ? payload.summary.overview : "";
      if (overview) {
        summaryParts.push(String(overview));
      }
      for (const activation of (payload && payload.activations) || []) {
        const key = activationDedupeKey(activation);
        const existing = activationByKey.get(key);
        if (existing && !activationShouldReplace(existing, activation)) {
          continue;
        }
        if (isBookmarkScopedActivation(activation)) {
          const nodeKey = String(activation.node_id || "");
          const previousKey = nodeScopedKeyByNode.get(nodeKey);
          const previous = previousKey ? activationByKey.get(previousKey) : null;
          if (previous && previousKey !== key && !activationShouldReplace(previous, activation)) {
            continue;
          }
          if (previousKey && previousKey !== key) {
            activationByKey.delete(previousKey);
          }
          nodeScopedKeyByNode.set(nodeKey, key);
        }
        activationByKey.set(key, activation);
      }
    }

    return {
      summary: {
        overview: summaryParts.length ? summaryParts.join("; ") : "Generated in cached parts.",
      },
      activations: Array.from(activationByKey.values()),
    };
  }

  function activationDedupeKey(activation) {
    return [
      String(activation.op || ""),
      String(activation.node_id || ""),
      String(activation.target || ""),
      String(activation.duplicate_of_id || ""),
    ].join("::");
  }

  function isBookmarkScopedActivation(activation) {
    return ["move_bookmark", "remove_duplicate", "keep_for_review"].includes(
      String(activation.op || ""),
    ) && !!activation.node_id;
  }

  function activationShouldReplace(existing, candidate) {
    const existingConfidence = finiteNumber(existing.confidence, 0);
    const candidateConfidence = finiteNumber(candidate.confidence, 0);
    if (candidateConfidence !== existingConfidence) {
      return candidateConfidence > existingConfidence;
    }
    return existing.op === "keep_for_review" && candidate.op !== "keep_for_review";
  }

  function finiteNumber(value, fallback) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
  }

  ai.Batching = Object.freeze({
    activationDedupeKey,
    activationShouldReplace,
    isBookmarkScopedActivation,
    mapWithConcurrency,
    mergeActivationPayloads,
    splitPlanningSnapshot,
  });
})(globalThis);
