const EXECUTION_ORDER = [
  "rename_folder",
  "delete_empty_folder",
  "create_folder",
  "move_folder",
  "move_bookmark",
  "remove_duplicate",
  "keep_for_review",
];

const EXECUTABLE_ACTIONS = new Set(EXECUTION_ORDER);

const EXECUTABLE_STATUSES = new Set(["approved", "edited"]);

if (typeof globalThis !== 'undefined') {
  globalThis.EXECUTION_ORDER = EXECUTION_ORDER;
  globalThis.EXECUTABLE_ACTIONS = EXECUTABLE_ACTIONS;
  globalThis.EXECUTABLE_STATUSES = EXECUTABLE_STATUSES;
}
