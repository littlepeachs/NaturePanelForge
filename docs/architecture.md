# Architecture

NaturePanelForge is organized around staged artifacts. Each stage reads a narrow manifest and writes a new directory with machine-checkable outputs.

## Public Modes

The GitHub-facing entry point is `forge.py`, which exposes four modes:

- **`single-panel-image`**: one already-cropped target panel image goes directly into the reproduction loop. It returns the generated code file `reproduce_panel.py`, rendered outputs `reproduce_panel.png` and `reproduce_panel.pdf`, plus `user_reproduce_summary.json` and `result.json`. The JSON summary records the panel directory, target image path, generated code path, rendered PNG/PDF paths, review status, missing-output checks, and generated code text.
- **`single-full-image`**: one user-supplied full figure image is normalized into `FullFigures/full_figures.csv`, then passed to the Codex panel-splitting loop. It writes reviewed panel crops, panel-splitting specs, and review artifacts.
- **`single-paper`**: one open-access Nature-family paper runs through the paper pipeline, from retrieval and full-figure download into downstream processing. `--download-only` stops after paper and full-figure assets.
- **`batched-paper`**: the same paper pipeline runs across many papers, controlled by `--target-papers`, `--batch-size`, and `--max-batches`.

Maintainer-hosted gallery demo:

```text
https://uu543493-83c1-74a94416.nma1.seetacloud.com:8448/
```

The repository does not depend on this hosted demo. The gallery is a static site and can be served from any exported gallery directory.

## Stage 1: Paper To Full Figure

Input:

- query domain
- year range
- target paper count

Core files:

- `agent_loop/keyword_query_builder.py`
- `nature_panel_forge/download_nature_oa_figures.py`
- `nature_panel_forge/build_figure_assets.py`
- `nature_panel_forge/run_continuous_pipeline.py`

Output:

- `Papers/papers.csv`
- `Papers/papers.json`
- `FullFigures/full_figures.csv`
- `FigurePDFs/`

## Stage 2: Panel Split

Core file:

- `agent_loop/codex_panel_split.py`

Agent loop:

1. Split agent proposes boxes and writes crop code/spec.
2. Review agent checks labels, ticks, labels, legends, colorbars, titles, and edge visibility.
3. If review fails, the split agent edits the crop code/spec and reruns.
4. The final panel crops and review summary are saved.

Meaning:

- protects panel boundaries and keeps scientific context complete
- prevents missing panel letters, truncated labels, clipped legends, and partial axes
- produces reviewed panel crops that downstream scoring and reproduction can trust

Output:

- `Panels_codex_full/`
- `PanelReviews_codex_full/`
- `PanelSplitSpecsCodex_full/status.csv`

## Stage 3: Qwen Scoring

Core files:

- `agent_loop/build_codex_panels_manifest.py`
- `agent_loop/qwen_panel_scoring.py`

Output:

- `QwenPanelScore/panel_scores.csv`
- one `qwen_score.json` per panel

## Stage 4: Code Reproduction

Core files:

- `nature_panel_forge/export_qwen_selected_panels.py`
- `examples/prompt_codex_reproduce_fig02_g.py`

Agent loop:

1. Code agent writes `reproduce_panel.py`.
2. The script renders PNG/PDF.
3. Review agent compares target and render.
4. Failed review triggers code edits and rerendering.

Meaning:

- turns a target panel into editable plotting code rather than a raster copy
- saves code, rendered PNG/PDF, run logs, and a machine-readable review summary
- creates the silver-standard reference used for figure-to-code benchmark tasks

Output:

- `Reproduce_Statistical/`
- `Reproduce_Statistical_Reviews/`
- `Reproduce_Statistical_Specs/`

## Single-Panel-Image Workflow

Core files:

- `forge.py`
- `nature_panel_forge/reproduce_image.py`
- `scripts/reproduce_image.sh`
- `examples/prompt_codex_reproduce_fig02_g.py`

This workflow lets a user provide one already-cropped target panel image directly. The script creates a standard panel bundle:

- `target.png`
- `metadata.json`
- `qwen_score.json`
- `panel_dirs.txt`

It then calls the same Codex reproduction loop used by the full pipeline. The final output contract is:

- `reproduce_panel.py`
- `reproduce_panel.png`
- `reproduce_panel.pdf`
- `user_reproduce_summary.json` and `result.json`, including the target path, generated code path, rendered PNG/PDF paths, review status, missing-output checks, and generated code text
- review notes and review summary

Dry-run mode prepares the bundle and prints the underlying command but does not run the live contract check. Dry-run summaries therefore set `live_contract_checked=false` and `contract_passed=false`.

## Single-Full-Image Workflow

Core files:

- `forge.py`
- `agent_loop/codex_panel_split.py`

This workflow lets a user provide one complete full figure image. It creates a synthetic full-figure manifest and then runs the panel-splitting loop.

Output:

- `FullFigures/full_figures.csv`
- `FullFigures/full_figures.json`
- `user_full_figure_metadata.json`
- `Panels_codex_full/`
- `PanelReviews_codex_full/`
- `PanelSplitSpecsCodex_full/status.csv`

## Stage 5: Final Refine

Core files:

- `nature_panel_forge/prepare_refined_reproduce_panels.py`
- `examples/prompt_codex_refine_reproduce.py`

The refine stage only starts from first-pass panels with `review_passed=true`.

Agent loop:

1. Polish agent edits the existing `reproduce_panel.py`; it does not replace the workflow with image editing.
2. Audit agent checks Arial typography, label/tick/legend overlap, scientific symbols, edge visibility, compactness, and remaining visual differences.
3. Failed audits trigger another code edit and rerender pass.
4. The final pass records review status plus complexity and concise panel-content description when available.

Meaning:

- raises publication-quality layout without changing the target image
- improves consistency across panels and domains
- records complexity and description metadata for benchmark slicing

Output:

- `Reproduce_Statistical_Refined/`
- `Reproduce_Statistical_Refined_Reviews/`
- `Reproduce_Statistical_Refined_Specs/`

## Stage 6: Gallery

Core files:

- `nature_panel_forge/export_reproduced_gallery.py`
- `gallery/tools/build_catalog.py`
- `gallery/index.html`
- `gallery/assets/app.js`
- `gallery/assets/styles.css`

The gallery is static. It can be served with Python's built-in HTTP server.

## Skill Packaging

Core files:

- `skills/codex-panel-reproduce/SKILL.md`
- `scripts/install_skills.sh`

The Codex reproduce/refine workflow is packaged as a local skill so another Codex instance can load the procedure directly. Install with:

```bash
bash scripts/install_skills.sh
```

Dry-run the installer with:

```bash
DRY_RUN=1 bash scripts/install_skills.sh
```

The installer copies bundled skills into `${CODEX_HOME:-$HOME/.codex}/skills`.
