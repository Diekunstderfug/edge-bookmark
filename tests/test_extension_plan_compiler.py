"""Independent contract tests for the extension AI plan compiler."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = ROOT / "extension" / "shared" / "plan_schema.js"
PATH_UTILS = ROOT / "extension" / "shared" / "path_utils.js"
SNAPSHOT_MODEL = ROOT / "extension" / "ai" / "snapshot_model.js"
PLAN_COMPILER = ROOT / "extension" / "ai" / "plan_compiler.js"

SNAPSHOT = {
    "source_path": "edge-bookmarks-api",
    "focus_path": "/收藏夹栏/AI",
    "folders": [
        {"id": "f-ai", "name": "AI", "path": "/收藏夹栏/AI"},
        {"id": "f-tools", "name": "Tools", "path": "/收藏夹栏/AI/Tools"},
        {"id": "f-dest", "name": "Organized", "path": "/收藏夹栏/AI/Organized"},
        {"id": "f-out", "name": "Outside", "path": "/收藏夹栏/Outside"},
    ],
    "bookmarks": [
        {
            "id": "b1",
            "title": "Alpha AI",
            "url": "https://example.com/a?utm_source=x",
            "normalized_url": "https://example.com/a",
            "folder_path": "/收藏夹栏/AI",
            "review_status": "fast_reviewed",
        },
        {
            "id": "b2",
            "title": "Alpha duplicate",
            "url": "https://example.com/a",
            "normalized_url": "https://example.com/a",
            "folder_path": "/收藏夹栏/AI/Tools",
            "review_status": "fast_reviewed",
        },
        {
            "id": "b3",
            "title": "Outside bookmark",
            "url": "https://outside.example/item",
            "normalized_url": "https://outside.example/item",
            "folder_path": "/收藏夹栏/Outside",
            "review_status": "fast_reviewed",
        },
        {
            "id": "b-root",
            "title": "Root loose bookmark",
            "url": "https://root.example/item",
            "normalized_url": "https://root.example/item",
            "folder_path": "/收藏夹栏",
            "review_status": "fast_reviewed",
        },
    ],
}

EMPTY_RULES = {
    "defaults": {},
    "protected_paths": [],
    "category_hints": {},
    "folder_relocations": [],
    "bookmark_relocations": [],
}


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS tests")
class ExtensionPlanCompilerTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          const planSchemaPath = {json.dumps(str(PLAN_SCHEMA))};
          const pathUtilsPath = {json.dumps(str(PATH_UTILS))};
          const snapshotModelPath = {json.dumps(str(SNAPSHOT_MODEL))};
          const compilerPath = {json.dumps(str(PLAN_COMPILER))};
          require(planSchemaPath);
          require(pathUtilsPath);
          require(snapshotModelPath);
          require(compilerPath);
          const snapshot = {json.dumps(SNAPSHOT, ensure_ascii=False)};
          const emptyRules = {json.dumps(EMPTY_RULES)};
          function makeCompiler(settings = {{}}) {{
            return globalThis.BookmarkAdvisor.AI.PlanCompiler.create({{
              planSchema: globalThis.BookmarkAdvisor.PlanSchema,
              pathUtils: globalThis.BookmarkAdvisor.PathUtils,
              snapshotModel: globalThis.BookmarkAdvisor.AI.SnapshotModel,
              getFastRules: () => settings.rules || emptyRules,
              getRulesSource: () => Object.prototype.hasOwnProperty.call(settings, 'source')
                ? settings.source
                : 'test-fast-rules',
              getRulesDiagnostic: () => settings.diagnostic || '',
              clock: settings.clock || (() => 0),
              performance: settings.performance || {{ now: () => 0 }},
              log: settings.log || (() => {{}}),
            }});
          }}
          {body}
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_compile_activation_plan_preserves_action_order_and_review_fallbacks(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const compiler = makeCompiler();
                const draft = compiler.compileActivationPlan({
                  summary: 'invalid summary is repaired',
                  activations: [
                    { op: 'move_bookmark', node_id: 'b1', target: '/收藏夹栏/AI/Tools', confidence: '0.91', reason: 'Move\nnear tools' },
                    { op: 'move_folder', node_id: 'f-tools', target: '/收藏夹栏/AI/Organized', confidence: 0.9, reason: 'Group tools' },
                    { op: 'rename_folder', node_id: 'f-tools', target: 'AI Tools', confidence: 0.8, reason: 'Clear name' },
                    { op: 'create_folder', target: '/收藏夹栏/AI/New', confidence: 0.7, reason: 'New category' },
                    { op: 'remove_duplicate', node_id: 'b2', duplicate_of_id: 'b1', confidence: 0.99, reason: 'Same URL' },
                    { op: 'delete_empty_folder', node_id: 'f-dest', confidence: 0.88, reason: 'Empty' },
                    { op: 'keep_for_review', node_id: 'b1', confidence: 0.2, reason: 'Ambiguous' },
                    { op: 'remove_duplicate', node_id: 'b1', duplicate_of_id: 'b3', confidence: 0.5, reason: 'Maybe same' },
                  ],
                }, snapshot);
                console.log(JSON.stringify({
                  summary: draft.summary,
                  types: draft.actions.map((action) => action.action_type),
                  first: draft.actions[0],
                  rename: draft.actions[2],
                  duplicate: draft.actions[4],
                  invalidDuplicate: draft.actions[7],
                }));
                """
            ),
        )
        self.assertEqual(result["summary"], {})
        self.assertEqual(
            result["types"],
            [
                "move_bookmark",
                "move_folder",
                "rename_folder",
                "create_folder",
                "remove_duplicate",
                "delete_empty_folder",
                "keep_for_review",
                "keep_for_review",
            ],
        )
        first = cast(dict[str, object], result["first"])
        self.assertEqual(first["reason"], "Move near tools")
        self.assertEqual(first["confidence"], 0.91)
        self.assertEqual(first["from_path"], "/收藏夹栏/AI")
        self.assertEqual(first["to_path"], "/收藏夹栏/AI/Tools")
        self.assertEqual(cast(dict[str, object], first["bookmark_locator"])["id"], "b1")
        self.assertEqual(result["rename"]["to_name"], "AI Tools")
        self.assertEqual(result["duplicate"]["from_path"], "/收藏夹栏/AI/Tools")
        self.assertEqual(
            result["invalidDuplicate"]["reason"],
            "Maybe same [Duplicate removal activation could not be verified locally.]",
        )

    def test_unknown_references_have_exact_lint_errors_and_can_be_pruned(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const compiler = makeCompiler();
                const payload = {
                  summary: {},
                  activations: [
                    { op: 'move_bookmark', node_id: 'missing-b', target: '/收藏夹栏/AI/Tools' },
                    { op: 'move_folder', node_id: 'missing-f', target: '/收藏夹栏/AI' },
                    { op: 'remove_duplicate', node_id: 'b1', duplicate_of_id: 'missing-dup' },
                    { op: 'keep_for_review', node_id: 'missing-review' },
                    { op: 'create_folder', target: '/收藏夹栏/AI/New' },
                  ],
                };
                const errors = compiler.lintActivationPayload(payload, snapshot);
                const pruned = compiler.pruneInvalidActivationReferences(payload, snapshot);
                console.log(JSON.stringify({
                  errors,
                  onlyReferences: compiler.lintErrorsAreOnlyReferenceErrors(errors),
                  dropped: pruned.dropped,
                  remainingOps: pruned.payload.activations.map((activation) => activation.op),
                }));
                """
            ),
        )
        self.assertEqual(
            result["errors"],
            [
                "activations[0].node_id must reference an existing bookmark id.",
                "activations[1].node_id must reference an existing folder id.",
                "activations[2].duplicate_of_id must reference an existing bookmark id.",
                "activations[3].node_id must reference an existing bookmark or folder id.",
            ],
        )
        self.assertEqual(result["onlyReferences"], True)
        self.assertEqual(result["dropped"], 4)
        self.assertEqual(result["remainingOps"], ["create_folder"])

    def test_lint_rejects_focus_escape_and_folder_descendant_move(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const compiler = makeCompiler();
                const errors = compiler.lintActivationPayload({ activations: [
                  { op: 'move_bookmark', node_id: 'b3', target: '/收藏夹栏/Outside' },
                  { op: 'create_folder', target: 'relative-folder' },
                  { op: 'move_folder', node_id: 'f-tools', target: '/收藏夹栏/AI/Tools/Child' },
                ] }, snapshot);
                console.log(JSON.stringify(errors));
                """
            ),
        )
        self.assertEqual(
            result,
            [
                "activations[0].node_id must stay within the focused folder.",
                "activations[0].target must stay within the focused folder.",
                "activations[1].target must be an absolute folder path.",
                "activations[1].target must stay within the focused folder.",
                "activations[2].target must not be the same folder or its descendant.",
            ],
        )

    def test_finalize_blocks_low_confidence_and_preserves_rules_metadata(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const logs = [];
                const ticks = [10, 22];
                const compiler = makeCompiler({
                  source: 'custom-rules-source',
                  diagnostic: 'rules diagnostic',
                  clock: () => 1000,
                  performance: { now: () => ticks.shift() },
                  log: (message, level) => logs.push([level, message]),
                });
                const draft = compiler.compileActivationPlan({ summary: { overview: 'Test plan' }, activations: [
                  { op: 'move_bookmark', node_id: 'b1', target: '/收藏夹栏/AI/Tools', confidence: 0.4, reason: 'Low confidence' },
                  { op: 'create_folder', target: '/收藏夹栏/AI/New', confidence: 0.95, reason: 'High confidence' },
                  { op: 'keep_for_review', node_id: 'b1', confidence: 1, reason: 'Review only' },
                ] }, snapshot);
                const plan = compiler.finalizeDraftPlan({
                  draft,
                  snapshot,
                  model: 'test-model',
                  autoApproveThreshold: 0.85,
                });
                console.log(JSON.stringify({ plan, logs }));
                """
            ),
        )
        plan = cast(dict[str, object], result["plan"])
        self.assertEqual(plan["created_at"], "1970-01-01T00:00:01.000Z")
        self.assertEqual(plan["rules_source"], "custom-rules-source")
        self.assertEqual(plan["model"], "test-model")
        summary = cast(dict[str, object], plan["summary"])
        self.assertEqual(summary["rules_diagnostic"], "rules diagnostic")
        self.assertEqual(summary["approved_actions"], 1)
        self.assertEqual(summary["blocked_actions"], 2)
        actions = cast(list[dict[str, object]], plan["actions"])
        self.assertEqual([action["status"] for action in actions], ["blocked", "approved", "blocked"])
        self.assertEqual(actions[0]["details"]["finalize_reason"], "below-threshold")
        self.assertEqual(actions[1]["details"]["finalize_reason"], "auto-approved")
        self.assertNotIn("finalize_reason", actions[2]["details"])
        self.assertEqual(result["logs"], [["log", "finalizeDraftPlan: 3 actions, 12ms"]])

    def test_fast_rules_instance_can_supply_rules_source_and_diagnostic(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const fastRules = {
                  get: () => emptyRules,
                  getSource: () => 'instance-rules-source',
                  getDiagnostic: () => 'instance diagnostic',
                };
                const compiler = globalThis.BookmarkAdvisor.AI.PlanCompiler.create({
                  planSchema: globalThis.BookmarkAdvisor.PlanSchema,
                  pathUtils: globalThis.BookmarkAdvisor.PathUtils,
                  snapshotModel: globalThis.BookmarkAdvisor.AI.SnapshotModel,
                  fastRules,
                  clock: () => 0,
                  performance: { now: () => 0 },
                  log: () => {},
                });
                const plan = compiler.finalizeDraftPlan({
                  draft: { summary: {}, actions: [] },
                  snapshot,
                  model: 'test',
                  autoApproveThreshold: 0.85,
                });
                console.log(JSON.stringify({
                  source: plan.rules_source,
                  diagnostic: plan.summary.rules_diagnostic,
                }));
                """
            ),
        )
        self.assertEqual(
            result,
            {"source": "instance-rules-source", "diagnostic": "instance diagnostic"},
        )

    def test_forced_rules_and_protected_root_guardrail_keep_order_and_overrides(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const rules = {
                  defaults: {},
                  protected_paths: ['/收藏夹栏'],
                  category_hints: {},
                  folder_relocations: [{
                    from: '/收藏夹栏/AI/Tools',
                    to: '/收藏夹栏/AI/Organized',
                    reason: 'Forced folder move',
                  }],
                  bookmark_relocations: [{
                    match: { title_contains: 'alpha ai' },
                    to: '/收藏夹栏/AI/Organized',
                    reason: 'Forced bookmark move',
                  }],
                };
                const compiler = makeCompiler({ rules });
                const protectedMove = compiler.normalizeAction({
                  action_type: 'move_bookmark',
                  reason: 'Move root bookmark',
                  confidence: 0.99,
                  bookmark_locator: {
                    id: 'b-root',
                    title: 'Root loose bookmark',
                    url: 'https://root.example/item',
                    normalized_url: 'https://root.example/item',
                    folder_path: '/收藏夹栏',
                  },
                  from_path: '/收藏夹栏',
                  to_path: '/收藏夹栏/AI',
                });
                const plan = compiler.finalizeDraftPlan({
                  draft: { summary: {}, actions: [protectedMove] },
                  snapshot,
                  model: 'test-model',
                  autoApproveThreshold: 0.85,
                });
                console.log(JSON.stringify(plan.actions));
                """
            ),
        )
        actions = cast(list[dict[str, object]], result)
        self.assertEqual(
            [action["action_type"] for action in actions],
            ["keep_for_review", "move_folder", "move_bookmark"],
        )
        self.assertEqual(actions[0]["status"], "blocked")
        self.assertEqual(actions[0]["details"]["guardrail"], "extension-review-required")
        self.assertIn("Blocked by protected root loose-bookmark rule.", actions[0]["reason"])
        self.assertEqual(actions[1]["status"], "approved")
        self.assertEqual(actions[1]["confidence"], 0.99)
        self.assertEqual(actions[1]["details"]["rule_override"], "forced-folder-relocation")
        self.assertEqual(actions[2]["status"], "approved")
        self.assertEqual(actions[2]["confidence"], 0.98)
        self.assertEqual(actions[2]["details"]["rule_override"], "forced-bookmark-relocation")

    def test_revision_merge_replaces_scope_and_finalize_dedupes_first_action(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const compiler = makeCompiler();
                const existing = {
                  summary: { old: true, overview: 'old' },
                  actions: [
                    { action_type: 'move_bookmark', bookmark_locator: { id: 'b1' }, to_path: '/收藏夹栏/AI/Tools', reason: 'old move' },
                    { action_type: 'rename_folder', folder_locator: { id: 'f-tools', path: '/收藏夹栏/AI/Tools' }, to_name: 'Old name', reason: 'old rename' },
                    { action_type: 'create_folder', target_path: '/收藏夹栏/AI/Keep', reason: 'keep this' },
                  ],
                };
                const delta = {
                  summary: { overview: 'new' },
                  actions: [
                    { action_type: 'move_bookmark', bookmark_locator: { id: 'b1' }, to_path: '/收藏夹栏/AI/Organized', reason: 'new move' },
                    { action_type: 'rename_folder', folder_locator: { id: 'f-tools', path: '/收藏夹栏/AI/Tools' }, to_name: 'New name', reason: 'new rename' },
                  ],
                };
                const merged = compiler.mergeRevisionDraft(existing, delta);

                const duplicateOne = compiler.normalizeAction({
                  action_type: 'move_bookmark', bookmark_locator: { id: 'b1', folder_path: '/收藏夹栏/AI' },
                  from_path: '/收藏夹栏/AI', to_path: '/收藏夹栏/AI/Tools', confidence: 0.4, reason: 'first',
                });
                const duplicateTwo = compiler.normalizeAction({
                  action_type: 'move_bookmark', bookmark_locator: { id: 'b1', folder_path: '/收藏夹栏/AI' },
                  from_path: '/收藏夹栏/AI', to_path: '/收藏夹栏/AI/Tools', confidence: 0.99, reason: 'second',
                });
                const deduped = compiler.finalizeDraftPlan({
                  draft: { summary: {}, actions: [duplicateOne, duplicateTwo] },
                  snapshot,
                  model: 'test',
                  autoApproveThreshold: 0.85,
                });
                console.log(JSON.stringify({
                  mergedSummary: merged.summary,
                  mergedTypes: merged.actions.map((action) => action.action_type),
                  mergedReasons: merged.actions.map((action) => action.reason),
                  keys: merged.actions.map(compiler.revisionActionScopeKey),
                  deduped: deduped.actions,
                }));
                """
            ),
        )
        self.assertEqual(result["mergedSummary"], {"old": True, "overview": "new"})
        self.assertEqual(result["mergedTypes"], ["create_folder", "move_bookmark", "rename_folder"])
        self.assertEqual(result["mergedReasons"], ["keep this", "new move", "new rename"])
        self.assertEqual(
            result["keys"],
            ["create_folder:/收藏夹栏/AI/Keep", "bookmark:b1", "folder:f-tools"],
        )
        deduped = cast(list[dict[str, object]], result["deduped"])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["reason"], "first")
        self.assertEqual(deduped[0]["confidence"], 0.4)
        self.assertEqual(deduped[0]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
