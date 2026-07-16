from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from SciFigure2Code.evaluation.dataset import DatasetLoader
from SciFigure2Code.evaluation.prompts import (
    PromptConfig,
    build_cot_answer_prompt,
    build_cot_reasoning_prompt,
    build_prompt_bundle,
    materialize_prompt_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "SciFigure2Code/benchmark_ready/clean_tiny100.json"
EXEMPLAR_ID = "10-1038-s41467-025-66220-x__fig05_b"


class PromptModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        loader = DatasetLoader(DATASET)
        cls.targets = loader.load(limit=2)
        cls.exemplar = loader.load(sample_ids=[EXEMPLAR_ID])[0]

    def test_native_icl_uses_reference_render_and_code(self) -> None:
        bundle = build_prompt_bundle(
            self.targets[0],
            PromptConfig(mode="oneshot", supports_multi_image=True),
            one_shot_sample=self.exemplar,
        )
        self.assertEqual(bundle.one_shot_strategy, "native_multi_image")
        self.assertEqual(bundle.image_paths, [self.exemplar.reference_png, self.targets[0].target_png])
        self.assertEqual(bundle.image_roles, ["one_shot_exemplar", "target"])
        self.assertIn("Reference code for Image 1", bundle.prompt)

    def test_single_image_icl_materializes_labeled_tile(self) -> None:
        bundle = build_prompt_bundle(
            self.targets[0],
            PromptConfig(mode="icl", supports_multi_image=False),
            one_shot_sample=self.exemplar,
        )
        self.assertEqual(bundle.one_shot_strategy, "tiled_single_image")
        with tempfile.TemporaryDirectory() as tmp:
            materialized = materialize_prompt_bundle(bundle, Path(tmp))
            self.assertEqual(len(materialized.image_paths), 1)
            self.assertTrue(materialized.image_paths[0].exists())
            self.assertEqual(materialized.image_roles, ["one_shot_exemplar_and_target_tile"])
            from PIL import Image

            with Image.open(materialized.image_paths[0]) as image:
                self.assertEqual(image.size, (2048, 1076))

    def test_cot_uses_a_separate_reasoning_turn(self) -> None:
        bundle = build_prompt_bundle(self.targets[0], PromptConfig(mode="cot"))
        reasoning = build_cot_reasoning_prompt(bundle)
        self.assertIn("reasoning stage", reasoning)
        self.assertIn("PLAN_COMPLETE", reasoning)
        answer = build_cot_answer_prompt(bundle.prompt, "chart type: line plot\nPLAN_COMPLETE")
        self.assertIn("<reconstruction_plan>", answer)
        self.assertIn("chart type: line plot", answer)


if __name__ == "__main__":
    unittest.main()
