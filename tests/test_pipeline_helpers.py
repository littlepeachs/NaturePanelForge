from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from agent_loop import qwen_panel_scoring
from agent_loop.codex_panel_split import expected_labels, labels_from_caption
from export_qwen_selected_panels import data_selection_failure_reason
from gallery.tools.build_catalog import image_complexity, maybe_float, to_bool
from prepare_refined_reproduce_panels import eligible_records


class PipelineHelperTests(unittest.TestCase):
    def test_qwen_extract_json_normalizes_scores_and_categories(self) -> None:
        raw = """
        <think>hidden reasoning</think>
        ```json
        {
          "category": "data_statistical",
          "data_subtype": "unknown_type",
          "is_complete_panel": true,
          "has_foreign_overlap": false,
          "xy_label_applicable": true,
          "xy_label_complete": "YES",
          "xytick_applicable": true,
          "xytick_complete": "no",
          "clarity_integrity_score": 12,
          "data_purity": "pure_data_statistical",
          "data_purity_score": 11,
          "code_reproducibility_score": 9.25,
          "aesthetic_score": 8.5,
          "overall_quality_score": 8.75,
          "confidence": 2,
          "short_reason": "clean statistical panel"
        }
        ```
        """
        score = qwen_panel_scoring.extract_json(raw)
        self.assertEqual(score["category"], "data_statistical")
        self.assertEqual(score["data_subtype"], "other_data_display")
        self.assertEqual(score["xy_label_complete"], "yes")
        self.assertEqual(score["xytick_complete"], "no")
        self.assertEqual(score["clarity_integrity_score"], 10.0)
        self.assertEqual(score["data_purity_score"], 10.0)
        self.assertEqual(score["confidence"], 1.0)
        self.assertTrue(score["is_good_quality"])

    def test_qwen_validate_non_data_panel_clears_data_subtype_and_purity_score(self) -> None:
        score = qwen_panel_scoring.validate_score(
            {
                "category": "schematic",
                "data_subtype": "bar",
                "data_purity": "pure_data_statistical",
                "data_purity_score": 10,
            }
        )
        self.assertEqual(score["category"], "schematic")
        self.assertIsNone(score["data_subtype"])
        self.assertEqual(score["data_purity"], "not_data_statistical")
        self.assertIsNone(score["data_purity_score"])

    def test_data_selection_thresholds_accept_and_reject_expected_rows(self) -> None:
        args = argparse.Namespace(
            min_data_purity_score=10.0,
            min_code_reproducibility_score=9.0,
            min_aesthetic_score=8.0,
        )
        good = {
            "data_purity_score": "10",
            "code_reproducibility_score": "9",
            "aesthetic_score": "8",
        }
        low_aesthetic = {
            "data_purity_score": "10",
            "code_reproducibility_score": "9",
            "aesthetic_score": "7.9",
        }
        self.assertIsNone(data_selection_failure_reason(good, args))
        reason = data_selection_failure_reason(low_aesthetic, args)
        self.assertIsNotNone(reason)
        self.assertIn("aesthetic_score=7.9<threshold=8", reason)

    def test_caption_label_parsing_and_manifest_override(self) -> None:
        labels, mapping = labels_from_caption("a Sample sizes. b-d Grouped outcomes. e Final panel.")
        self.assertEqual(labels, ["a", "b", "c", "d", "e"])
        self.assertIn("Grouped outcomes", mapping["c"])

        labels, _ = expected_labels({"parsed_panel_labels": "x,y", "caption": "a Wrong caption."})
        self.assertEqual(labels, ["x", "y"])

    def test_eligible_records_selects_review_passed_panels_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_data = root / "Reproduce_Statistical"
            source_reviews = root / "Reproduce_Statistical_Reviews"
            source_specs = root / "Reproduce_Statistical_Specs"

            good_panel = source_data / "bar" / "panel_good"
            good_review = source_reviews / "bar" / "panel_good"
            good_panel.mkdir(parents=True)
            good_review.mkdir(parents=True)
            for filename in ["target.png", "reproduce_panel.py", "reproduce_panel.png", "reproduce_panel.pdf"]:
                (good_panel / filename).write_bytes(b"ok")
            (good_review / "reproduce_panel_review_summary.json").write_text(
                json.dumps({"review_passed": True, "review_rounds_completed": 4}),
                encoding="utf-8",
            )

            bad_panel = source_data / "bar" / "panel_bad"
            bad_review = source_reviews / "bar" / "panel_bad"
            bad_panel.mkdir(parents=True)
            bad_review.mkdir(parents=True)
            (bad_review / "reproduce_panel_review_summary.json").write_text(
                json.dumps({"review_passed": False}),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                source_data_dir=source_data,
                source_reviews_dir=source_reviews,
                source_specs_dir=source_specs,
                limit=0,
            )
            records, ignored, total = eligible_records(args)
            self.assertEqual(total, 1)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["panel_id"], "panel_good")
            self.assertEqual(len(ignored), 1)
            self.assertEqual(ignored[0]["ignore_reason"], "review_not_passed")

    def test_gallery_scalar_helpers_and_image_complexity(self) -> None:
        self.assertEqual(maybe_float("3.5"), 3.5)
        self.assertIsNone(maybe_float("not-a-number"))
        self.assertTrue(to_bool("yes"))
        self.assertFalse(to_bool(""))

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "panel.png"
            image = Image.new("RGB", (64, 64), "white")
            for index in range(8, 56):
                image.putpixel((index, index), (0, 0, 0))
                image.putpixel((index, 63 - index), (220, 20, 60))
            image.save(image_path)
            complexity = image_complexity(image_path)

        self.assertGreaterEqual(complexity["score"], 0)
        self.assertLessEqual(complexity["score"], 100)
        self.assertIn("entropy", complexity)
        self.assertIn("edgeDensity", complexity)


if __name__ == "__main__":
    unittest.main()
