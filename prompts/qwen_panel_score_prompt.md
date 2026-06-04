# Qwen Panel Scoring Prompt Blueprint

Role: local Qwen vision judge.

For each panel, return JSON with:

- `category`: `schematic`, `data_statistical`, `chemical_structure`, `characterization_photo`, or `other_uncertain`
- `data_subtype`: chart subtype when `category=data_statistical`
- `data_purity_score`: 0-10
- `code_reproducibility_score`: 0-10
- `aesthetic_score`: 0-10
- `label_completeness`: yes/no
- `tick_completeness`: yes/no
- `legend_completeness`: yes/no
- `colorbar_completeness`: yes/no
- `reason`: concise explanation

Selection gate for statistical reproduction:

```text
data_purity_score >= 10
code_reproducibility_score >= 9
aesthetic_score >= 8
```
