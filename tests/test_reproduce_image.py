from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from nature_panel_forge import reproduce_image


def make_image(path: Path, size: tuple[int, int] = (120, 80)) -> None:
    img = Image.new("RGB", size, "white")
    for x in range(20, 100):
        for y in range(30, 60):
            img.putpixel((x, y), (37, 99, 235))
    img.save(path)


class ReproduceImageTests(unittest.TestCase):
    def test_safe_name_normalizes_user_values(self) -> None:
        self.assertEqual(reproduce_image.safe_name("Panel A / dose response"), "Panel_A_dose_response")
        self.assertEqual(reproduce_image.safe_name("..."), "user_panel")
        self.assertEqual(reproduce_image.safe_name(""), "user_panel")

    def test_copy_image_to_target_requires_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                reproduce_image.copy_image_to_target(root / "missing.png", root / "target.png")

    def test_build_panel_bundle_creates_standard_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "target_input.png"
            make_image(image_path)

            panel_dir, metadata = reproduce_image.build_panel_bundle(
                image_path=image_path,
                out_root=root / "out",
                panel_id="Demo Panel",
                caption="A simple blue bar.",
                chart_type="bar chart",
                overwrite=False,
            )

            self.assertEqual(panel_dir.name, "Demo_Panel")
            self.assertTrue((panel_dir / "target.png").exists())
            self.assertTrue((panel_dir / "metadata.json").exists())
            self.assertTrue((panel_dir / "qwen_score.json").exists())
            panel_list = root / "out" / "Reproduce_Statistical" / "panel_dirs.txt"
            self.assertEqual(panel_list.read_text(encoding="utf-8").strip(), str(panel_dir))
            stored = json.loads((panel_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["caption"], "A simple blue bar.")
            self.assertEqual(stored["image_width"], 120)
            self.assertEqual(stored["image_height"], 80)
            self.assertEqual(metadata["data_subtype"], "bar_chart")

    def test_build_panel_bundle_copies_optional_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "target_input.png"
            pdf_path = root / "target_input.pdf"
            make_image(image_path)
            pdf_path.write_bytes(b"%PDF-1.4\n% fake test pdf\n")

            panel_dir, metadata = reproduce_image.build_panel_bundle(
                image_path=image_path,
                source_pdf=pdf_path,
                out_root=root / "out",
                panel_id="Panel A",
                caption="",
                chart_type="line",
            )

            self.assertTrue((panel_dir / "target.pdf").exists())
            self.assertEqual(metadata["target_pdf_path"], str(panel_dir / "target.pdf"))

    def test_build_panel_bundle_requires_existing_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "target_input.png"
            make_image(image_path)

            with self.assertRaises(FileNotFoundError):
                reproduce_image.build_panel_bundle(
                    image_path=image_path,
                    source_pdf=root / "missing.pdf",
                    out_root=root / "out",
                    panel_id="Panel A",
                    caption="",
                    chart_type="line",
                )

    def test_build_panel_bundle_overwrite_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "target_input.png"
            make_image(image_path)

            panel_dir, _ = reproduce_image.build_panel_bundle(
                image_path=image_path,
                out_root=root / "out",
                panel_id="Panel A",
                caption="",
                chart_type="line",
            )
            stale = panel_dir / "stale.txt"
            stale.write_text("old", encoding="utf-8")

            panel_dir, _ = reproduce_image.build_panel_bundle(
                image_path=image_path,
                out_root=root / "out",
                panel_id="Panel A",
                caption="",
                chart_type="line",
                overwrite=True,
            )
            self.assertFalse(stale.exists())

    def test_build_codex_command_points_to_agent_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = reproduce_image.parse_args(
                [
                    "--image",
                    str(root / "input.png"),
                    "--model",
                    "gpt-5.4",
                    "--dry-run",
                    "--skip-existing",
                    "--process-user",
                    "tester",
                ]
            )
            panel_dir = root / "out" / "Reproduce_Statistical" / "bar" / "panel_a"
            cmd = reproduce_image.build_codex_command(args, panel_dir, root / "out")

            joined = " ".join(cmd)
            self.assertIn("examples/prompt_codex_reproduce_fig02_g.py", joined)
            self.assertIn("--panel-dir", cmd)
            self.assertIn(str(panel_dir), cmd)
            self.assertIn("--dry-run", cmd)
            self.assertIn("--skip-existing", cmd)
            self.assertIn("--review-rounds", cmd)
            self.assertIn("4", cmd)

    def test_build_codex_command_includes_stream_events_and_pdf_source_is_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = reproduce_image.parse_args(
                [
                    "--image",
                    str(root / "input.png"),
                    "--stream-events",
                    "--process-user",
                    "tester",
                ]
            )
            panel_dir = root / "out" / "Reproduce_Statistical" / "line" / "panel_b"
            cmd = reproduce_image.build_codex_command(args, panel_dir, root / "out")
            self.assertIn("--stream-events", cmd)
            self.assertNotIn("--source-pdf", cmd)

    def test_main_dry_run_prepares_bundle_without_real_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "panel.png"
            make_image(image_path)
            calls: list[list[str]] = []

            def fake_run(cmd, cwd=None, check=False):
                calls.append([str(item) for item in cmd])

                class Result:
                    returncode = 0

                return Result()

            argv = [
                "reproduce_image.py",
                "--image",
                str(image_path),
                "--out-root",
                str(root / "user_run"),
                "--panel-id",
                "panel one",
                "--caption",
                "User supplied panel.",
                "--process-user",
                "tester",
                "--dry-run",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(subprocess, "run", fake_run):
                self.assertEqual(reproduce_image.main(), 0)

            panel_dir = root / "user_run" / "Reproduce_Statistical" / "user_supplied" / "panel_one"
            self.assertTrue((panel_dir / "target.png").exists())
            self.assertTrue((panel_dir / "user_reproduce_summary.json").exists())
            self.assertTrue((panel_dir / "result.json").exists())
            summary = json.loads((panel_dir / "user_reproduce_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "dry_run")
            self.assertFalse(summary["live_contract_checked"])
            self.assertFalse(summary["contract_passed"])
            self.assertTrue(calls)
            self.assertIn("--dry-run", calls[0])

    def test_build_result_summary_requires_live_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel_dir = root / "out" / "Reproduce_Statistical" / "bar" / "panel_a"
            panel_dir.mkdir(parents=True)
            metadata = {"target_png_path": str(panel_dir / "target.png")}

            summary, return_code = reproduce_image.build_result_summary(
                panel_dir=panel_dir,
                out_root=root / "out",
                metadata=metadata,
                exit_code=0,
                dry_run=False,
            )

            self.assertEqual(return_code, 1)
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["contract_passed"])
            self.assertIn("reproduce_panel.py", "\n".join(summary["missing_outputs"]))

    def test_build_result_summary_returns_code_when_review_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_root = root / "out"
            panel_dir = out_root / "Reproduce_Statistical" / "bar" / "panel_a"
            review_dir = out_root / "Reproduce_Statistical_Reviews" / "bar" / "panel_a"
            panel_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            (panel_dir / "reproduce_panel.py").write_text("print('plot')\n", encoding="utf-8")
            (panel_dir / "reproduce_panel.png").write_bytes(b"png")
            (panel_dir / "reproduce_panel.pdf").write_bytes(b"%PDF")
            (review_dir / "reproduce_panel_review_summary.json").write_text(
                json.dumps({"status": "ok", "review_passed": True}),
                encoding="utf-8",
            )
            metadata = {"target_png_path": str(panel_dir / "target.png")}

            summary, return_code = reproduce_image.build_result_summary(
                panel_dir=panel_dir,
                out_root=out_root,
                metadata=metadata,
                exit_code=0,
                dry_run=False,
            )

            self.assertEqual(return_code, 0)
            self.assertEqual(summary["status"], "ok")
            self.assertTrue(summary["live_contract_checked"])
            self.assertTrue(summary["contract_passed"])
            self.assertEqual(summary["code"], "print('plot')\n")
            self.assertTrue(summary["review_passed"])


if __name__ == "__main__":
    unittest.main()
