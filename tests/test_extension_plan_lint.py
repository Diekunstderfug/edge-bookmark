"""Extension plan lint status semantics tests."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import cast


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PLAN_LINT = _REPO_ROOT / "extension" / "plan_lint.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS plan lint tests")
class ExtensionPlanLintTest(unittest.TestCase):
    def _node_eval(self, expression: str) -> object:
        script = (
            f"require({json.dumps(str(_PLAN_LINT))});\n"
            f"const result = {expression};\n"
            "console.log(JSON.stringify(result));\n"
        )
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=15,
        )
        return cast(object, json.loads(completed.stdout))

    def test_proposed_action_is_review_not_executable(self):
        summary = self._node_eval(
            """
            BookmarkPlanLint.lintPlan({
              actions: [{
                action_id: 'a-1',
                action_type: 'move_bookmark',
                status: 'proposed',
                reason: 'not approved yet',
                confidence: 0.5,
                bookmark_locator: { id: '10', title: 'Example', url: 'https://example.com' },
                to_path: '/收藏夹栏/AI'
              }]
            })
            """
        )
        summary_dict = cast(dict[str, object], summary)
        self.assertEqual(len(cast(list[object], summary_dict["executableActions"])), 0)
        self.assertEqual(len(cast(list[object], summary_dict["reviewActions"])), 1)


if __name__ == "__main__":
    _ = unittest.main()
