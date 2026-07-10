# Dataset Refinement Workflow

This document describes how NaturePanelForge turns open-access scientific
figures into clean SciFigure2Code benchmark samples.

## Goal

The refined benchmark keeps only panel-level chart-to-code samples that are
usable for executable plotting-code evaluation. A clean sample should contain:

- `target.png` and, when available, `target.pdf` from the original paper panel;
- `reproduce_panel.py`, an editable Python/matplotlib reconstruction;
- `reproduce_panel.png` and `reproduce_panel.pdf`, rendered from that code;
- `description.md` with panel content, chart subtype, domain, and complexity;
- audit metadata proving the sample does not depend on copying the target image.

The current released clean manifest contains 6,740 samples from an 8,385-panel
formal gallery.

## Refinement Stages

1. Paper and figure collection

   Use open-access paper metadata and full-figure assets. NaturePanelForge keeps
   DOI, journal, subject, topic, caption, figure label, and local file paths.

   ```bash
   python3 forge.py single-paper \
     --doi 10.1038/s41467-025-12345-6 \
     --subject biology \
     --topic AI_biology \
     --figures-per-paper 5 \
     --download-only
   ```

2. Panel splitting

   Compound figures are split into complete panel crops. Review checks panel
   letters, axes, legends, colorbars, annotations, and edge visibility.

   ```bash
   python3 forge.py single-full-image \
     --image /path/to/full_figure.png \
     --paper-id demo_paper \
     --caption "A complete multi-panel scientific figure." \
     --out-root UserRuns/full_demo
   ```

3. Qwen panel classification and scoring

   A local Qwen vision model classifies statistical/data panels and records
   quality signals such as clarity, data purity, code reproducibility, and
   overall visual quality. These are construction-time filters, not final
   model-evaluation scores.

   ```bash
   export QWEN_MODEL_PATH=/path/to/Qwen3.6-27B
   bash scripts/run_demo_qwen_score.sh
   ```

4. Code reproduction

   The Codex reproduce loop writes `reproduce_panel.py`, renders PNG/PDF, and
   reviews the output against `target.png`. The target image is not loaded or
   edited by the generated plotting code.

   ```bash
   python3 forge.py single-panel-image \
     --image /path/to/target_panel.png \
     --panel-id demo_panel \
     --chart-type grouped_bar \
     --caption "A grouped bar chart with error bars." \
     --out-root UserRuns/panel_demo
   ```

5. Final Refine

   The refine loop starts from a passing first reproduction and improves
   publication-style details: font consistency, compactness, edge clipping,
   scientific symbols, label/tick/legend overlap, and panel-specific style.

   ```bash
   bash scripts/run_demo_refine.sh
   ```

6. Clean-sample audit

   Samples are excluded from the clean benchmark if they have execution or
   artifact problems, direct image dependency, pixel painting or raster tracing,
   plotting-logic errors, severe text overlap, or other audit failures.

   Clean benchmark summary:

   | Status | Count |
   |---|---:|
   | Formal gallery panels | 8,385 |
   | Clean benchmark candidates | 6,740 |
   | Minor issues excluded | 1,308 |
   | Major issues excluded | 67 |
   | Critical issues excluded | 270 |

   Clean complexity distribution:

   | Complexity | Count |
   |---|---:|
   | Low | 1,868 |
   | Medium | 4,165 |
   | High | 707 |

## Benchmark Manifests

The repository stores only a small smoke manifest:

```text
SciFigure2Code/benchmark_ready/
```

Main files:

- `clean_tiny100.json`: deterministic 100-sample smoke benchmark.
- `clean_summary.json`: clean-set distribution statistics.
- `metric_dimensions.json`: metric definitions.

Larger manifests, including `clean_mini500.json`, `clean_dev1000.json`, and
`clean_samples.json`, should be downloaded from the Hugging Face dataset
release. Use `--dataset` or `SCIFIGURE_DATASET` to choose the downloaded
manifest at evaluation time.
