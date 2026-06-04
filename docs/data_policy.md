# Data Policy

NaturePanelForge is intended to be released as a code repository.

The repository should not include:

- publisher figure images
- downloaded paper PDFs
- panel crops
- reproduced figures
- run logs
- model outputs from private runs
- model weights
- Hugging Face caches
- Codex raw logs from private experiments

The `.gitignore` file excludes these classes by default.

Documentation assets may include UI screenshots, workflow diagrams, icons, and other project-explanation images under `docs/assets/`. They should not include publisher figure panels, downloaded paper figures, reproduced chart panels, or model-generated benchmark outputs.

Users are responsible for checking the licenses of downloaded open-access papers and figures. Generated reproductions are useful for benchmarking and model training, but they are not original author plotting code and should be labeled as reconstructed references.
