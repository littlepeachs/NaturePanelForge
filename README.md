<h1 align="center">
  <img src="docs/assets/icon.png" alt="NaturePanelForge icon" width="180"><br/>
  NaturePanelForge
</h1>

<p align="center">
  <b>Forge Nature-level scientific panels into executable plotting code.</b><br/>
  Retrieve open-access papers, split full figures into reviewed panels, classify them with Qwen, and reproduce statistical panels with Codex agent loops.
</p>

<p align="center">
  <a href="https://littlepeachs.github.io/NaturePanelForge/"><img alt="Project page" src="https://img.shields.io/badge/Project%20Page-GitHub%20Pages-111827?style=flat&logo=githubpages&logoColor=white"></a>
  <a href="https://uu543493-83c1-74a94416.nma1.seetacloud.com:8448/"><img alt="Gallery live demo" src="https://img.shields.io/badge/Gallery-live%20demo-2563eb?style=flat&logo=googlechrome&logoColor=white"></a>
  <a href="#usage"><img alt="Usage four modes" src="https://img.shields.io/badge/Usage-4%20modes-0f766e?style=flat&logo=python&logoColor=white"></a>
  <a href="#agent-workflow"><img alt="Agent loop refine" src="https://img.shields.io/badge/Agent%20Loop-reproduce%20%2B%20refine-ea580c?style=flat&logo=openai&logoColor=white"></a>
  <a href="docs/intro_and_methods.md"><img alt="Method and stats" src="https://img.shields.io/badge/Method-stats%20%2B%20dataset-7c3aed?style=flat&logo=readme&logoColor=white"></a>
  <a href="#install-the-codex-skill"><img alt="Codex skill install" src="https://img.shields.io/badge/Codex%20Skill-installable-0891b2?style=flat&logo=gnubash&logoColor=white"></a>
</p>

<p align="center">
  <img src="docs/assets/diagram.png" alt="NaturePanelForge input-output schematic: target scientific panel and optional metadata are converted into runnable Python plotting code." width="100%">
</p>

<p align="center">
  <a href="#usage">Usage</a> |
  <a href="#quick-start-demo">Quick Start Demo</a> |
  <a href="#agent-workflow">Agent Workflow</a> |
  <a href="#codex-reproduction-examples">Examples</a> |
  <a href="#setup">Setup</a> |
  <a href="docs/intro_and_methods.md">Method</a> |
  <a href="TUTORIAL.md">Tutorial</a>
</p>

<p align="center">
  <b>English</b> | <a href="README.zh-CN.md">中文</a>
</p>

NaturePanelForge is a code-first workflow for turning scientific figure images and open-access Nature-family papers into panel-level, executable plotting-code reconstruction tasks. The repository does not depend on the hosted gallery demo.

![NaturePanelForge gallery walkthrough](docs/assets/show_preview.gif)

[![Watch walkthrough video](docs/assets/watch_walkthrough_button.svg)](docs/assets/show_compressed.mp4)

![NaturePanelForge gallery home](docs/assets/nature_panel_forge_web1.png)

![NaturePanelForge gallery catalog](docs/assets/nature_panel_forge_web2.png)

For the project introduction, methods, current dataset counts, Qwen score distributions, and Codex refine complexity distribution, see [Introduction and Methods](docs/intro_and_methods.md).

## Quick Start Demo

The quick start has two simple paths:

### **Mode 1. Direct Code Mode**

**Run the checked-in plotting code directly.** This is the fastest path: no Codex loop and no skill installation.

<table>
<tr>
<td width="50%" align="center"><b>Direct Code Mode Target</b></td>
<td width="50%" align="center"><b>Direct Code Mode Reproduction</b></td>
</tr>
<tr>
<td><img src="docs/demo/quick_start_bubble_plot/target.png" alt="Direct code mode target GO enrichment bubble plot panel" width="100%"/></td>
<td><img src="docs/demo/quick_start_bubble_plot/reproduce_panel.png" alt="Direct code mode reproduced GO enrichment bubble plot panel" width="100%"/></td>
</tr>
</table>

One command:

```bash
bash scripts/run_quick_start_demo.sh
```

It rerenders the checked-in script and images:

```text
docs/demo/quick_start_bubble_plot/reproduce_panel.py
docs/demo/quick_start_bubble_plot/reproduce_panel.png
docs/demo/quick_start_bubble_plot/reproduce_panel.pdf
```

### **Mode 2. Install Codex Skill Mode**

**Install the bundled Code Skill, then run one Prompt inside Codex.** Codex uses `codex-panel-reproduce` to read the target image, write editable Python/matplotlib code, render the reproduction image/PDF, and save review files.

<table>
<tr>
<td width="50%" align="center"><b>Codex Skill Mode Target</b></td>
<td width="50%" align="center"><b>Codex Skill Mode Reproduction</b></td>
</tr>
<tr>
<td><img src="docs/demo/quick_start_skill_bubble_plot/target.png" alt="Codex Skill mode target GO enrichment bubble plot panel" width="100%"/></td>
<td><img src="docs/demo/quick_start_skill_bubble_plot/reproduce_panel.png" alt="Codex Skill mode reproduced GO enrichment bubble plot panel" width="100%"/></td>
</tr>
</table>

One sentence to Codex:

**Install the NaturePanelForge Codex skill for me: https://github.com/littlepeachs/NaturePanelForge**

Codex will read the repository, install the bundled `codex-panel-reproduce` skill, and verify that it is available locally.

One-sentence Prompt after install:

**English Prompt:** **Use the installed `codex-panel-reproduce` skill to reproduce `docs/demo/quick_start_skill_bubble_plot/target.png` as editable Python/matplotlib code; do not use Qwen scoring; save outputs under `UserRuns/my_skill_test`; then report `review_passed`, `contract_passed`, final PNG size, and the rerender command.**

**中文 Prompt：** **请使用已安装的 `codex-panel-reproduce` skill，把 `docs/demo/quick_start_skill_bubble_plot/target.png` 复现为可编辑的 Python/matplotlib 代码；不要使用 Qwen scoring；输出到 `UserRuns/my_skill_test`；最后报告 `review_passed`、`contract_passed`、最终 PNG 尺寸和重新渲染命令。**

The target image is the input, and the reproduction image is the expected editable-code output. For the full prompts saved as files, see [English prompt](docs/demo/quick_start_skill_bubble_plot/prompt.en.md) and [中文 prompt](docs/demo/quick_start_skill_bubble_plot/prompt.zh-CN.md).

Offline rerender for the checked-in Skill Mode result:

```bash
DEMO_CASE=quick_start_skill_bubble_plot bash scripts/run_quick_start_demo.sh
```

To use your own data in the same visual style, edit the data arrays and labels in one of the demo `reproduce_panel.py` scripts, then rerun it. If your goal is specifically “take a reference plot style and redraw my new data in that style,” FigMirror is the more product-like path; NaturePanelForge focuses on building scientific panel-to-code benchmark examples from real papers.

## Agent Workflow

NaturePanelForge uses three executable agent stages. Each stage writes machine-checkable artifacts and can be resumed.

![NaturePanelForge complete workflow](docs/assets/nature_panel_forge_overview.png)


**Panel Split** converts a compound full figure into complete panel crops. A split agent writes executable crop/spec logic, and a review agent checks panel letters, axis labels, ticks, legends, colorbars, titles, annotations, and edge visibility.

**Code Reproduce** turns a target panel into `reproduce_panel.py`, `reproduce_panel.png`, and `reproduce_panel.pdf`. A code-writing agent renders the plot, and a review agent compares the output against `target.png`; fixable issues trigger code edits and rerendering.

**Final Refine** starts from first-pass reproductions that already passed review. A polish agent edits the existing code, while an audit agent checks Arial typography, label/tick/legend overlap, scientific symbols, edge clipping, compactness, complexity score, and caption-based description.

![Agent loops for high-fidelity panel-to-code reproduction](docs/assets/agent_loop.png)

This loop is the core mechanism for high-quality panel-to-code reproduction: each stage separates execution from review, records artifacts on disk, and iterates until the panel split, executable reproduction, or final refine result passes the corresponding audit.

## Codex Reproduction Examples

Target panels from real paper figures are shown beside Codex-rendered outputs. Each reproduction is generated from executable plotting code, not manual image editing.

![Target panels beside Codex reproductions](docs/assets/reproduction_examples/codex_reproduction_pairs.png)

## Usage

Use `forge.py` for the four public workflows. Each mode can be started with one command.

1. **Single cropped panel image -> plotting code**

```bash
python3 forge.py single-panel-image --image /path/to/target_panel.png --panel-id demo_panel --chart-type bar --caption "A grouped bar chart with error bars and a legend." --out-root UserRuns/panel_demo --model gpt-5.4 --reasoning-effort medium --review-rounds 4 --skip-existing
```

2. **Single full figure image -> reviewed panel crops**

```bash
python3 forge.py single-full-image --image /path/to/full_figure.png --paper-id demo_paper --caption "A complete multi-panel scientific figure." --out-root UserRuns/full_demo --model gpt-5.4 --reasoning-effort medium --review-rounds 4 --skip-existing
```

3. **Single paper -> paper metadata and full figures**

```bash
python3 forge.py single-paper --doi 10.1038/s41467-025-12345-6 --subject biology --topic AI_biology --figures-per-paper 5 --download-only
```

4. **Batched papers -> full paper-to-panel-to-code workflow**

```bash
python3 forge.py batched-paper --subject materials --topic AI_materials --target-papers 20 --batch-size 20 --figures-per-paper 5 --years 2024,2025,2026 --codex-model gpt-5.4 --codex-jobs 8
```

The repository root intentionally keeps only one Python entry point, `forge.py`. Internal pipeline modules live under `nature_panel_forge/`, while stage wrappers live under `scripts/`.

`single-panel-image` is the direct user-facing image-to-code path. A live run returns:

```text
target.png
metadata.json
qwen_score.json
reproduce_panel.py
reproduce_panel.png
reproduce_panel.pdf
user_reproduce_summary.json
result.json
```

`user_reproduce_summary.json` and `result.json` include the generated code text, output paths, review status, missing-output checks, and whether the live contract passed. Dry-runs intentionally set `live_contract_checked=false` and `contract_passed=false`.

## Setup

```bash
cd NaturePanelForge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp configs/demo.env.example .env
source .env
```

Required external pieces:

- network access for paper and figure download
- Codex CLI for panel splitting, reproduction, and refine
- local Qwen vision model for panel classification/scoring

Check Codex:

```bash
codex --version
```

Set Qwen:

```bash
export QWEN_MODEL_PATH=/path/to/Qwen3.6-27B
export CUDA_VISIBLE_DEVICES=0
```

The default Qwen path is local `transformers` loading through `--qwen-backend transformers`. `--qwen-backend openai` is only an optional compatibility hook for users who intentionally run an OpenAI-compatible vision endpoint.

## Install The Codex Skill

The easiest way is to let Codex install it from this GitHub repository. Already inside Codex? Paste one sentence:

**Install the NaturePanelForge Codex skill for me: https://github.com/littlepeachs/NaturePanelForge**

Codex should clone or open the repository, install `skills/codex-panel-reproduce/SKILL.md` into the local Codex skills directory, and verify that this file exists:

```text
${CODEX_HOME:-$HOME/.codex}/skills/codex-panel-reproduce/SKILL.md
```

After installation, say:

**Use the installed `codex-panel-reproduce` skill to reproduce my target panel as editable Python/matplotlib code.**

Local Codex can then follow the single-panel reproduction/refine workflow without re-learning the prompt structure from scratch.

## Repository Layout

```text
forge.py                            # single public Python CLI entry point
nature_panel_forge/                 # internal paper, figure, export, refine, and image-to-code modules
agent_loop/                         # Codex panel splitting, manifest building, Qwen scoring
examples/                           # Codex reproduction and final-refine batch drivers
scripts/                            # portable stage wrappers and skill installer
gallery/                            # static gallery shell and catalog builder
skills/                             # local Codex skill packages
configs/                            # environment templates
docs/                               # architecture, methods, and visual assets
prompts/                            # agent prompt blueprints
```

Generated run directories look like:

```text
PipelineRuns/<subject>/<topic>/run_YYYYMMDD_HHMMSS_batch001/
  Papers/
  FullFigures/full_figures.csv
  Panels_codex_full/
  PanelReviews_codex_full/
  QwenPanelScore/
  Final_Schematic/
  Reproduce_Statistical/
  Reproduce_Statistical_Reviews/
  Reproduce_Statistical_Refined/
```

## More Documentation

- [Tutorial](TUTORIAL.md)
- [Architecture](docs/architecture.md)
- [Introduction and Methods](docs/intro_and_methods.md)

## Citation

If you use this workflow in a paper or benchmark, cite the project repository and describe the exact paper sources, model versions, scoring thresholds, and Codex review-round settings used in your run.
