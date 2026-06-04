# Troubleshooting

## Codex stops after API reconnect errors

Increase retries and retry sleep:

```bash
CODEX_RETRIES=12 CODEX_RETRY_SLEEP=30 bash scripts/run_demo_reproduce.sh
```

## Too many Codex processes are running

Lower the local job count or increase the allowed process cap:

```bash
CODEX_JOBS=16 MAX_CODEX_PROCESSES=32 bash scripts/run_demo_panel_split.sh
```

## Qwen runs out of GPU memory

Lower the batch size:

```bash
SCORE_BATCH_SIZE=1 bash scripts/run_demo_qwen_score.sh
```

The scoring script is designed to skip batches that still OOM at batch size 1.

## Gallery loads but shows no panels

Build the catalog after export:

```bash
python3 gallery/tools/build_catalog.py --gallery-root gallery
```

Then serve from the `gallery/` directory:

```bash
cd gallery
python3 -m http.server 18081 --bind 0.0.0.0
```

## Single-image reproduction prepared files but no code appeared

If you used `--dry-run`, the command only prepares the panel bundle and prints the prompt.

Run without `--dry-run` to invoke Codex:

```bash
python3 reproduce_image.py --image /path/to/panel.png --out-root UserRuns/demo
```

If Codex is unavailable, check:

```bash
codex --version
```
