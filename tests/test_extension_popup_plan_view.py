"""Tests for popup plan display classification helpers."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "extension" / "popup" / "plan_view.js"


def _run_node(body: str) -> object:
    script = f"""
      require({json.dumps(str(MODULE))});
      const view = globalThis.BookmarkAdvisor.Popup.PlanView.create({{
        reviewCategoryKey: "__review__",
        rejectedCategoryKey: "__rejected__",
        reportOnlyActions: new Set(["keep_for_review"]),
        isExecutableAction: (action) =>
          action.status === "approved" && action.details?.review_agreed === true,
        t: (key) => key,
      }});
      {body}
    """
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip())


class PopupPlanViewTest(unittest.TestCase):
    def test_action_status_preserves_review_agreement_contract(self) -> None:
        result = _run_node(
            """
            console.log(JSON.stringify({
              approved: view.actionDisplayStatus({status: "approved", action_type: "move_bookmark"}),
              pending: view.actionDisplayStatus({status: "proposed", action_type: "move_bookmark"}),
              review: view.actionDisplayStatus({status: "approved", action_type: "keep_for_review"}),
              agreed: view.actionDisplayStatus({
                status: "approved",
                action_type: "keep_for_review",
                details: {review_agreed: true},
              }),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "approved": "executable",
                "pending": "pending",
                "review": "review",
                "agreed": "executable",
            },
        )

    def test_categories_group_and_sort_review_and_rejected_last(self) -> None:
        result = _run_node(
            """
            const groups = view.groupActionsByCategory([
              {status: "approved", action_type: "move_bookmark", to_path: "/Work"},
              {status: "approved", action_type: "move_folder", to_path: "/Work"},
              {status: "proposed", action_type: "move_bookmark", to_path: "/Later"},
              {status: "rejected", action_type: "create_folder", target_path: "/Skip"},
            ]);
            console.log(JSON.stringify(
              view.sortCategories(groups).map((group) => [group.key, group.actions.length])
            ));
            """
        )
        self.assertEqual(
            result,
            [["/Work", 2], ["__review__", 1], ["__rejected__", 1]],
        )

    def test_labels_and_path_helpers_are_ui_only(self) -> None:
        result = _run_node(
            """
            console.log(JSON.stringify({
              title: view.actionTitle({action_type: "keep_for_review", reason: "Needs context"}),
              label: view.actionTypeLabel("remove_duplicate"),
              confidence: [
                view.confidenceClass(0.9),
                view.confidenceClass(0.7),
                view.confidenceClass(0.1),
              ],
              segment: view.lastSegment("/收藏夹栏/编程/"),
            }));
            """
        )
        self.assertEqual(
            result,
            {
                "title": "Needs context",
                "label": "action_dedup",
                "confidence": ["high", "medium", "low"],
                "segment": "编程",
            },
        )


if __name__ == "__main__":
    unittest.main()
