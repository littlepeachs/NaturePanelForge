# English Prompt

```text
Please use the installed codex-panel-reproduce skill to reproduce this scientific paper panel as editable Python/matplotlib code.

Target image: docs/demo/quick_start_skill_bubble_plot/target.png
Optional PDF: docs/demo/quick_start_skill_bubble_plot/target.pdf
Output root: UserRuns/my_skill_test
Panel id: my_skill_test
Chart type: bubble_plot
Caption: A faceted GO enrichment bubble plot with Human and Mouse columns, biological process labels on the left, x axis as -log10(p.value), bubble size encoding log10(count), and colors encoding biological groups.

Requirements:
1. Use the codex-panel-reproduce skill.
2. Do not use Qwen scoring; this is a local user-supplied image.
3. Do not manually modify images; generate executable plotting code only.
4. Run the NaturePanelForge single-panel reproduction workflow.
5. Generate reproduce_panel.py, reproduce_panel.png, and reproduce_panel.pdf.
6. Generate review notes, review summary, and run log.
7. Finally report the output directory, review_passed, contract_passed, final PNG size, and rerender command.
```
