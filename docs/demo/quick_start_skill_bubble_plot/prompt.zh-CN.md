# 中文 Prompt

```text
请使用已安装的 codex-panel-reproduce skill，帮我复现这个科学论文 panel 图像为可编辑的 Python/matplotlib 代码。

目标图像：docs/demo/quick_start_skill_bubble_plot/target.png
可选 PDF：docs/demo/quick_start_skill_bubble_plot/target.pdf
输出根目录：UserRuns/my_skill_test
panel id：my_skill_test
图类型：bubble_plot
caption：A faceted GO enrichment bubble plot with Human and Mouse columns, biological process labels on the left, x axis as -log10(p.value), bubble size encoding log10(count), and colors encoding biological groups.

要求：
1. 使用 codex-panel-reproduce skill。
2. 不要使用 Qwen scoring，这是本地用户提供的图片。
3. 不要手工修改图片，只生成可执行绘图代码。
4. 运行 NaturePanelForge 的单图复现 workflow。
5. 生成 reproduce_panel.py、reproduce_panel.png、reproduce_panel.pdf。
6. 生成 review notes、review summary、run log。
7. 最后告诉我输出目录、review_passed、contract_passed、最终 PNG 尺寸和重新渲染命令。
```
