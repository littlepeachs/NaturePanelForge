# Codex Refine Prompt Blueprint

Role: final polish code agent plus review agent.

Goal: improve an already passing reproduction without overwriting the target or changing the file structure.

Read:

- `target.png`
- `reproduce_panel.py`
- `reproduce_panel.png`
- `reproduce_panel.pdf`
- previous review notes and summary
- metadata, caption, and Qwen score files when present

Requirements:

- Modify `reproduce_panel.py` rather than creating an unrelated script style.
- Use Arial consistently when available.
- Increase font size enough for readability while keeping the layout compact.
- Check x/y labels, x/y tick labels, legends, titles, annotations, panel letters, and colorbars for overlap.
- Check whether x/y label symbols, Greek letters, superscripts, subscripts, math text, and units display correctly.
- Avoid relying only on `tight_layout`; explicitly tune margins, label padding, legend placement, and colorbar axes when needed.
- Ensure labels and legends do not collide with axis spines, plotted data, or figure edges.
- Save `refine_complexity_assessment.json` with `refine_complexity_score` from 0 to 10, a concise reason, and a caption-based content summary.
- Save review notes, review summary, PNG, PDF, and the refined Python code.

Pass criteria:

- `review_passed=true`
- `font_audit_passed=true`
- `layout_audit_passed=true`
- `edge_visibility_passed=true`
