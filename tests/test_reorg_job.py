from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bookmark_advisor.executor import apply_reviewed_semantic_plan
from bookmark_advisor.job_runner import init_reorg_job, load_reorg_job, run_reorg_job
from bookmark_advisor.models import BookmarkLocator, SemanticAction, SemanticPlan
from bookmark_advisor.parser import load_snapshot
from bookmark_advisor.snapshot_io import (
    build_enriched_snapshot_document,
    build_review_queue_document,
    build_snapshot_document,
)


def write_rules_file(base_dir: Path) -> Path:
    rules_path = base_dir / "rules.yaml"
    rules_path.write_text(
        textwrap.dedent(
            """
            defaults:
              protect_root_loose_bookmarks: true
              allow_new_folders_in_advise: true
              generic_new_folder_names: [EDU, ORG]

            category_hints:
              ai: [chatgpt, openai]

            folder_relocations: []
            bookmark_relocations: []

            protected_paths:
              - /收藏夹栏
              - /其他收藏夹
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return rules_path


def write_bookmarks_file(base_dir: Path) -> Path:
    source = base_dir / "Bookmarks"
    source.write_text(
        """
        {
          "roots": {
            "bookmark_bar": {
              "type": "folder",
              "name": "收藏夹栏",
              "children": [
                {
                  "type": "folder",
                  "id": "10",
                  "name": "AI",
                  "children": []
                },
                {
                  "type": "url",
                  "id": "11",
                  "name": "ChatGPT",
                  "url": "https://chatgpt.com/"
                },
                {
                  "type": "url",
                  "id": "12",
                  "name": "Local Admin",
                  "url": "http://192.168.3.10/"
                },
                {
                  "type": "url",
                  "id": "13",
                  "name": "New Tab",
                  "url": "edge://newtab/"
                }
              ]
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    return source


def fake_draft_plan() -> SemanticPlan:
    return SemanticPlan(
        plan_version="2",
        plan_kind="draft",
        source="bookmark-advisor",
        created_at="2026-04-22T10:00:00",
        source_snapshot="enriched-snapshot.json",
        rules_source="rules.yaml",
        model="test-model",
        summary={"overview": "move ChatGPT", "total_actions": 1},
        actions=[
            SemanticAction(
                action_id="a-0001",
                action_type="move_bookmark",
                status="proposed",
                reason="Reviewed AI assistant bookmark",
                confidence=0.95,
                bookmark_locator=BookmarkLocator(
                    id="11",
                    title="ChatGPT",
                    url="https://chatgpt.com/",
                    normalized_url="https://chatgpt.com/",
                    folder_path="/收藏夹栏",
                ),
                from_path="/收藏夹栏",
                to_path="/收藏夹栏/AI",
                details={
                    "evidence": {
                        "review_status": "reviewed",
                        "review_method": "agent_web",
                        "summary": "General AI assistant product.",
                    }
                },
            )
        ],
    )


class ReorgJobTest(unittest.TestCase):
    def test_build_review_queue_filters_internal_and_special_urls(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_document = build_snapshot_document(load_snapshot(write_bookmarks_file(temp_path))).to_dict()
            queue = build_review_queue_document(snapshot_document)
            self.assertEqual(len(queue.items), 1)
            self.assertEqual(queue.items[0].bookmark_id, "11")
            self.assertEqual(queue.items[0].normalized_url, "https://chatgpt.com/")

    def test_build_enriched_snapshot_merges_review_by_bookmark_and_url(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_document = build_snapshot_document(load_snapshot(write_bookmarks_file(temp_path))).to_dict()
            review_queue = build_review_queue_document(snapshot_document)
            review_document = {
                "review_version": "1",
                "created_at": "2026-04-22T10:00:00",
                "source_snapshot": review_queue.source_snapshot,
                "items": [
                    {
                        "bookmark_id": "11",
                        "url": "https://chatgpt.com/",
                        "normalized_url": "https://chatgpt.com/",
                        "folder_path": "/收藏夹栏",
                        "review_status": "reviewed",
                        "review_method": "agent_web",
                        "final_url": "https://chatgpt.com/",
                        "page_title": "ChatGPT",
                        "meta_description": "AI assistant",
                        "site_name": "ChatGPT",
                        "h1": "ChatGPT",
                        "content_kind": "product",
                        "one_line_summary": "General AI assistant product.",
                        "review_confidence": 0.95,
                        "notes": "",
                    }
                ],
            }
            enriched = build_enriched_snapshot_document(snapshot_document, review_document)
            bookmarks = {bookmark.id: bookmark for bookmark in enriched.bookmarks}
            self.assertEqual(bookmarks["11"].review_status, "reviewed")
            self.assertEqual(bookmarks["11"].one_line_summary, "General AI assistant product.")
            self.assertEqual(bookmarks["12"].review_status, "skipped_internal")
            self.assertEqual(bookmarks["13"].review_status, "skipped_internal")

    def test_run_job_waits_for_review_file(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            rules = write_rules_file(temp_path)
            _job, job_path = init_reorg_job(
                workspace=temp_path,
                source_bookmarks_path=source,
                rules_path=rules,
                primary_backend="extension",
            )
            first = run_reorg_job(job_path)
            self.assertEqual(first["current_phase"], "review")
            second = run_reorg_job(job_path)
            self.assertEqual(second["status"], "waiting_for_review")
            self.assertEqual(second["current_phase"], "review")

    def test_run_job_waits_for_extension_execution_after_review(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            rules = write_rules_file(temp_path)
            _job, job_path = init_reorg_job(
                workspace=temp_path,
                source_bookmarks_path=source,
                rules_path=rules,
                primary_backend="extension",
            )
            run_reorg_job(job_path)
            job = load_reorg_job(job_path)
            review_queue = json.loads(Path(job.review_queue_path).read_text(encoding="utf-8"))
            Path(job.url_review_path).write_text(
                json.dumps(
                    {
                        "review_version": "1",
                        "created_at": "2026-04-22T10:00:00",
                        "source_snapshot": review_queue["source_snapshot"],
                        "items": [
                            {
                                "bookmark_id": "11",
                                "url": "https://chatgpt.com/",
                                "normalized_url": "https://chatgpt.com/",
                                "folder_path": "/收藏夹栏",
                                "review_status": "reviewed",
                                "review_method": "agent_web",
                                "final_url": "https://chatgpt.com/",
                                "page_title": "ChatGPT",
                                "meta_description": "AI assistant",
                                "site_name": "ChatGPT",
                                "h1": "ChatGPT",
                                "content_kind": "product",
                                "one_line_summary": "General AI assistant product.",
                                "review_confidence": 0.95,
                                "notes": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with patch("bookmark_advisor.job_runner.plan_with_openai", return_value=fake_draft_plan()):
                result = run_reorg_job(job_path)
            self.assertEqual(result["status"], "waiting_for_extension_execution")
            self.assertEqual(result["current_phase"], "waiting_for_extension_execution")
            self.assertEqual(result["primary_backend"], "extension")
            self.assertTrue(Path(job.reviewed_plan_path).exists())
            reviewed = json.loads(Path(job.reviewed_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(reviewed["actions"][0]["status"], "approved")
            completed = load_reorg_job(job_path).state.completed_phases
            self.assertIn("apply", completed)

    def test_run_job_can_apply_write_source_backend(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            rules = write_rules_file(temp_path)
            _job, job_path = init_reorg_job(
                workspace=temp_path,
                source_bookmarks_path=source,
                rules_path=rules,
                primary_backend="write_source",
                allow_write_source=True,
            )
            run_reorg_job(job_path)
            job = load_reorg_job(job_path)
            review_queue = json.loads(Path(job.review_queue_path).read_text(encoding="utf-8"))
            Path(job.url_review_path).write_text(
                json.dumps(
                    {
                        "review_version": "1",
                        "created_at": "2026-04-22T10:00:00",
                        "source_snapshot": review_queue["source_snapshot"],
                        "items": [
                            {
                                "bookmark_id": "11",
                                "url": "https://chatgpt.com/",
                                "normalized_url": "https://chatgpt.com/",
                                "folder_path": "/收藏夹栏",
                                "review_status": "reviewed",
                                "review_method": "agent_web",
                                "final_url": "https://chatgpt.com/",
                                "page_title": "ChatGPT",
                                "meta_description": "AI assistant",
                                "site_name": "ChatGPT",
                                "h1": "ChatGPT",
                                "content_kind": "product",
                                "one_line_summary": "General AI assistant product.",
                                "review_confidence": 0.95,
                                "notes": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with patch("bookmark_advisor.job_runner.plan_with_openai", return_value=fake_draft_plan()):
                result = run_reorg_job(job_path, allow_write_source=True)
            self.assertEqual(result["status"], "done")
            payload = json.loads(source.read_text(encoding="utf-8"))
            ai_folder = payload["roots"]["bookmark_bar"]["children"][0]
            ai_titles = [child.get("name") for child in ai_folder.get("children", []) if child.get("type") == "url"]
            self.assertIn("ChatGPT", ai_titles)
            backup_dir = temp_path / "data" / "backups"
            self.assertTrue(any(backup_dir.iterdir()))

    def test_write_source_requires_runtime_allow_flag(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            rules = write_rules_file(temp_path)
            _job, job_path = init_reorg_job(
                workspace=temp_path,
                source_bookmarks_path=source,
                rules_path=rules,
                primary_backend="write_source",
                allow_write_source=True,
            )
            run_reorg_job(job_path)
            job = load_reorg_job(job_path)
            review_queue = json.loads(Path(job.review_queue_path).read_text(encoding="utf-8"))
            Path(job.url_review_path).write_text(
                json.dumps(
                    {
                        "review_version": "1",
                        "created_at": "2026-04-22T10:00:00",
                        "source_snapshot": review_queue["source_snapshot"],
                        "items": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with patch("bookmark_advisor.job_runner.plan_with_openai", return_value=fake_draft_plan()):
                with self.assertRaisesRegex(ValueError, "runtime allow_write_source"):
                    run_reorg_job(job_path)

    def test_enriched_snapshot_rejects_stale_review_source(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_document = build_snapshot_document(load_snapshot(write_bookmarks_file(temp_path))).to_dict()
            review_document = {
                "review_version": "1",
                "created_at": "2026-04-22T10:00:00",
                "source_snapshot": "other-snapshot.json",
                "items": [],
            }
            with self.assertRaisesRegex(ValueError, "source_snapshot does not match"):
                build_enriched_snapshot_document(snapshot_document, review_document)

    def test_enriched_snapshot_requires_review_source_identity(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_document = build_snapshot_document(load_snapshot(write_bookmarks_file(temp_path))).to_dict()
            review_document = {
                "review_version": "1",
                "created_at": "2026-04-22T10:00:00",
                "items": [],
            }
            with self.assertRaisesRegex(ValueError, "source_snapshot is required"):
                build_enriched_snapshot_document(snapshot_document, review_document)

    def test_enriched_snapshot_rejects_review_from_same_source_with_different_content(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            first_snapshot = build_snapshot_document(load_snapshot(source)).to_dict()
            first_queue = build_review_queue_document(first_snapshot)

            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["roots"]["bookmark_bar"]["children"].append(
                {"type": "url", "id": "99", "name": "Later", "url": "https://later.example/"}
            )
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            second_snapshot = build_snapshot_document(load_snapshot(source)).to_dict()

            review_document = {
                "review_version": "1",
                "created_at": "2026-04-22T10:00:00",
                "source_snapshot": first_queue.source_snapshot,
                "items": [],
            }
            with self.assertRaisesRegex(ValueError, "source_snapshot does not match"):
                build_enriched_snapshot_document(second_snapshot, review_document)

    def test_job_manifest_artifact_paths_must_stay_in_job_directory(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            rules = write_rules_file(temp_path)
            _job, job_path = init_reorg_job(
                workspace=temp_path,
                source_bookmarks_path=source,
                rules_path=rules,
                primary_backend="extension",
            )
            payload = json.loads(job_path.read_text(encoding="utf-8"))
            payload["workspace"] = "/"
            payload["snapshot_path"] = str(temp_path / "outside-snapshot.json")
            job_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "job artifact path must stay within the job directory"):
                run_reorg_job(job_path)
            self.assertFalse((temp_path / "outside-snapshot.json").exists())

    def test_enriched_snapshot_ignores_review_with_stale_folder_path(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            snapshot_document = build_snapshot_document(load_snapshot(write_bookmarks_file(temp_path))).to_dict()
            review_queue = build_review_queue_document(snapshot_document)
            review_document = {
                "review_version": "1",
                "created_at": "2026-04-22T10:00:00",
                "source_snapshot": review_queue.source_snapshot,
                "items": [
                    {
                        "bookmark_id": "11",
                        "url": "https://chatgpt.com/",
                        "normalized_url": "https://chatgpt.com/",
                        "folder_path": "/收藏夹栏/Old",
                        "review_status": "reviewed",
                        "review_method": "agent_web",
                    }
                ],
            }
            enriched = build_enriched_snapshot_document(snapshot_document, review_document)
            bookmarks = {bookmark.id: bookmark for bookmark in enriched.bookmarks}
            self.assertEqual(bookmarks["11"].review_status, "missing")

    def test_apply_reviewed_semantic_plan_preserves_folder_rename_target(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            destination = temp_path / "out.json"
            reviewed_plan = {
                "actions": [
                    {
                        "action_type": "rename_folder",
                        "status": "approved",
                        "reason": "rename test folder",
                        "confidence": 0.99,
                        "folder_locator": {
                            "id": "10",
                            "name": "AI",
                            "path": "/收藏夹栏/AI",
                        },
                        "to_name": "AI Tools",
                    }
                ]
            }

            apply_reviewed_semantic_plan(
                reviewed_plan,
                source_path=source,
                destination=destination,
                write_source=False,
            )

            payload = json.loads(destination.read_text(encoding="utf-8"))
            children = payload["roots"]["bookmark_bar"]["children"]
            folder_names = [child.get("name") for child in children if child.get("type") == "folder"]
            self.assertIn("AI Tools", folder_names)

    def test_apply_reviewed_semantic_plan_deletes_empty_folder_only(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = write_bookmarks_file(temp_path)
            destination = temp_path / "out.json"
            reviewed_plan = {
                "actions": [
                    {
                        "action_type": "delete_empty_folder",
                        "status": "approved",
                        "reason": "empty folder cleanup",
                        "confidence": 0.99,
                        "folder_locator": {
                            "id": "10",
                            "name": "AI",
                            "path": "/收藏夹栏/AI",
                        },
                        "from_path": "/收藏夹栏/AI",
                    }
                ]
            }

            apply_reviewed_semantic_plan(
                reviewed_plan,
                source_path=source,
                destination=destination,
                write_source=False,
            )

            payload = json.loads(destination.read_text(encoding="utf-8"))
            children = payload["roots"]["bookmark_bar"]["children"]
            folder_names = [child.get("name") for child in children if child.get("type") == "folder"]
            self.assertNotIn("AI", folder_names)


if __name__ == "__main__":
    unittest.main()
