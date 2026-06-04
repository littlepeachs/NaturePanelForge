# Panel Split Prompt Blueprint

Role: split agent plus review agent.

Goal: divide one full scientific figure into panel crops using code, then review and iterate.

Requirements:

- Detect all panel labels such as `a`, `b`, `c`, `d`.
- Crop each panel so that x/y tick labels, x/y axis labels, legends, colorbars, titles, panel letters, annotations, and scale bars are fully visible.
- Do not cut off text at the figure boundaries.
- If a panel label or label text is clipped in the original source figure, keep the scientific plot content complete rather than reproducing the clipping defect.
- Save a machine-readable panel spec and one image/PDF per panel.
- Run a review pass. If the review finds missing text, clipped ticks, incomplete legend/colorbar, or wrong crop boundaries, modify the code/spec and rerun.
- Repeat for up to `CODEX_REVIEW_ROUNDS` rounds.

Review checklist:

- panel count and labels are correct
- every panel crop contains the intended scientific content
- x/y labels are complete
- x/y tick labels are complete
- legends and colorbars are complete
- panel titles and annotations are visible
- no important content is cut off at the edges
