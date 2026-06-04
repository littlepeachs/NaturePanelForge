from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from PIL import Image

import forge


def make_image(path: Path, size: tuple[int, int] = (160, 100)) -> None:
    image = Image.new("RGB", size, "white")
    for x in range(20, 140):
        for y in range(40, 80):
            image.putpixel((x, y), (15, 118, 110))
    image.save(path)


class ForgeModeTests(unittest.TestCase):
    def test_paper_identifier_query_handles_doi_pmcid_and_urls(self) -> None:
        self.assertEqual(
            forge.paper_identifier_query(Namespace(doi="https://doi.org/10.1038/s41467-025-12345-6")),
            '"10.1038/s41467-025-12345-6"[DOI]',
        )
        self.assertEqual(
            forge.paper_identifier_query(Namespace(doi="", pmcid="1234567")),
            "(PMC1234567[PMCID] OR 1234567[UID])",
        )
        self.assertEqual(
            forge.paper_identifier_query(
                Namespace(doi="", pmcid="", paper_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7654321/")
            ),
            "(PMC7654321[PMCID] OR 7654321[UID])",
        )
        self.assertEqual(
            forge.paper_identifier_query(
                Namespace(doi="", pmcid="", paper_url="", paper_query="Nature*[Journal]", search_term="")
            ),
            "Nature*[Journal]",
        )

    def test_prepare_single_full_image_run_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "full.png"
            make_image(image_path)

            run_dir, csv_path = forge.prepare_single_full_image_run(
                image_path=image_path,
                out_root=root / "run",
                paper_id="demo-paper",
                figure_index=2,
                caption="A full multi-panel figure.",
            )

            self.assertEqual(run_dir, root / "run")
            self.assertTrue(csv_path.exists())
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["paper_id"], "demo-paper")
            self.assertEqual(rows[0]["figure_index"], "2")
            self.assertTrue(Path(rows[0]["relative_path"]).exists())
            metadata = json.loads((run_dir / "user_full_figure_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["mode"], "single-full-image")

    def test_single_panel_image_subcommand_delegates_to_reproduce_image(self) -> None:
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
                "forge.py",
                "single-panel-image",
                "--image",
                str(image_path),
                "--out-root",
                str(root / "out"),
                "--panel-id",
                "panel-a",
                "--chart-type",
                "bar",
                "--dry-run",
                "--print-command",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(subprocess, "run", fake_run):
                self.assertEqual(forge.main(), 0)

            self.assertEqual(len(calls), 1)
            self.assertIn("nature_panel_forge.reproduce_image", calls[0])
            self.assertIn("--dry-run", calls[0])
            self.assertIn("--panel-id", calls[0])
            self.assertIn("panel-a", calls[0])

    def test_single_full_image_subcommand_builds_manifest_and_split_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "full.png"
            make_image(image_path)
            calls: list[list[str]] = []

            def fake_run(cmd, cwd=None, check=False):
                calls.append([str(item) for item in cmd])

                class Result:
                    returncode = 0

                return Result()

            argv = [
                "forge.py",
                "single-full-image",
                "--image",
                str(image_path),
                "--out-root",
                str(root / "full_run"),
                "--paper-id",
                "demo",
                "--caption",
                "Full figure.",
                "--dry-run",
                "--skip-existing",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(subprocess, "run", fake_run):
                self.assertEqual(forge.main(), 0)

            csv_path = root / "full_run" / "FullFigures" / "full_figures.csv"
            self.assertTrue(csv_path.exists())
            self.assertEqual(len(calls), 1)
            self.assertIn("codex_panel_split.py", calls[0][1])
            self.assertIn("--full-figures-csv", calls[0])
            self.assertIn(str(csv_path), calls[0])
            self.assertIn("--skip-existing", calls[0])

    def test_single_paper_subcommand_uses_exact_doi_query(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, cwd=None, check=False):
            calls.append([str(item) for item in cmd])

            class Result:
                returncode = 0

            return Result()

        argv = [
            "forge.py",
            "single-paper",
            "--doi",
            "10.1038/s41467-025-12345-6",
            "--download-only",
            "--dry-run",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(subprocess, "run", fake_run):
            self.assertEqual(forge.main(), 0)

        self.assertEqual(len(calls), 1)
        self.assertIn("nature_panel_forge.run_continuous_pipeline", calls[0])
        self.assertIn("--target-papers", calls[0])
        self.assertEqual(calls[0][calls[0].index("--target-papers") + 1], "1")
        self.assertIn("--search-term", calls[0])
        self.assertEqual(calls[0][calls[0].index("--search-term") + 1], '"10.1038/s41467-025-12345-6"[DOI]')
        self.assertIn("--skip-qwen", calls[0])
        self.assertIn("--skip-codex", calls[0])

    def test_batched_paper_subcommand_sets_batch_counts_and_codex_args(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, cwd=None, check=False):
            calls.append([str(item) for item in cmd])

            class Result:
                returncode = 0

            return Result()

        argv = [
            "forge.py",
            "batched-paper",
            "--subject",
            "materials",
            "--topic",
            "AI_materials",
            "--target-papers",
            "20",
            "--batch-size",
            "10",
            "--codex-jobs",
            "4",
            "--max-codex-processes",
            "8",
            "--quality-limit",
            "5",
            "--dry-run",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(subprocess, "run", fake_run):
            self.assertEqual(forge.main(), 0)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("--subject") + 1], "materials")
        self.assertEqual(calls[0][calls[0].index("--topic") + 1], "AI_materials")
        self.assertEqual(calls[0][calls[0].index("--target-papers") + 1], "20")
        self.assertEqual(calls[0][calls[0].index("--batch-size") + 1], "10")
        self.assertEqual(calls[0][calls[0].index("--codex-jobs") + 1], "4")
        self.assertEqual(calls[0][calls[0].index("--max-codex-processes") + 1], "8")
        self.assertEqual(calls[0][calls[0].index("--quality-limit") + 1], "5")


if __name__ == "__main__":
    unittest.main()
