# SciFigure2Code Benchmark Protocol

## Evaluation Set

Use the downloaded `clean_samples.json` as the default full benchmark candidate
set. These samples have passed the Codex audit with `status=complete` and
`severity=clean`. The GitHub repository only checks in `clean_tiny100.json` for
quick smoke tests.

Recommended subsets:

- `clean_tiny100.json`: smoke test and prompt debugging.
- `clean_mini500.json`: model development and ablation; download from the dataset release.
- `clean_dev1000.json`: medium-cost comparison; download from the dataset release.
- `clean_samples.json`: full clean benchmark; download from the dataset release.

## Input Settings

Report results separately for each setting:

1. Image-only panel-to-code: target panel image only.
2. Caption-assisted panel-to-code: target panel image plus caption and metadata.

## Required Outputs

Each model should produce executable Python plotting code. The evaluation runner should render the
code in a fixed environment and compare the generated artifact against the target panel and the
agent-verified reference package.

## Reported Metrics

Do not collapse the benchmark into only one weighted final score. Report separate dimensions:

1. Execution pass rate.
2. Visual fidelity.
3. Chart type consistency.
4. Layout consistency.
5. Data pattern fidelity.
6. Text and label fidelity.
7. Axis fidelity.
8. Legend and colorbar completeness.
9. Component completeness.
10. Clarity and overlap.
11. Scientific notation fidelity.
12. Code validity and editability.
13. Direct image dependency rate.
14. Pixel painting or raster tracing rate.

Optional aggregate scores may be shown only as secondary summaries.

## Invalidity Rules

- If code does not execute, all visual/content scores for that sample are zero.
- If the code directly loads or edits the target/source image, mark the sample invalid.
- If the code reconstructs the plot by pixel painting or raster tracing rather than meaningful plotting logic, mark it as a major code-validity failure.

## Breakdowns

Always report breakdowns by:

- complexity level,
- scientific domain,
- chart subtype.
