/* Compatibility facade for the shared reviewed-plan schema. */

(function attachLegacyActionConstants(globalScope) {
  if (
    (!globalScope.BookmarkAdvisor || !globalScope.BookmarkAdvisor.PlanSchema) &&
    typeof require === "function"
  ) {
    require("./shared/plan_schema.js");
  }

  const schema = globalScope.BookmarkAdvisor && globalScope.BookmarkAdvisor.PlanSchema;
  if (!schema) {
    throw new Error("shared/plan_schema.js must load before action_constants.js");
  }

  const EXECUTION_ORDER = schema.EXECUTION_ORDER;
  const EXECUTABLE_ACTIONS = new Set(schema.MUTATION_ACTION_TYPES);
  const REPORT_ONLY_ACTIONS = new Set(schema.REPORT_ACTION_TYPES);
  const EXECUTABLE_STATUSES = new Set(schema.EXECUTABLE_STATUSES);

  globalScope.EXECUTION_ORDER = EXECUTION_ORDER;
  globalScope.EXECUTABLE_ACTIONS = EXECUTABLE_ACTIONS;
  globalScope.REPORT_ONLY_ACTIONS = REPORT_ONLY_ACTIONS;
  globalScope.EXECUTABLE_STATUSES = EXECUTABLE_STATUSES;
  globalScope.isExecutableAction = schema.isExecutableAction;
})(globalThis);
