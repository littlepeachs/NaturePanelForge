#!/usr/bin/env python3
"""Example: call Codex CLI from Python code.

This script uses `codex exec`, which is the non-interactive Codex CLI mode.
It captures the final assistant message with `--output-last-message` and can
optionally stream the CLI JSONL events for logging/debugging.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def require_codex_cli() -> str:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex CLI was not found in PATH")
    return codex


def run_codex(
    prompt: str,
    *,
    cwd: Path,
    model: str | None = None,
    sandbox: str = "workspace-write",
    timeout: int = 600,
    stream_events: bool = False,
) -> str:
    """Run `codex exec` once and return the final assistant message."""

    codex = require_codex_cli()

    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt") as last_message:
        cmd = [
            codex,
            "exec",
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            last_message.name,
            "--sandbox",
            sandbox,
            "--cd",
            str(cwd),
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        events: list[dict] = []
        try:
            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "raw_stdout", "text": line}
                events.append(event)
                if stream_events:
                    print(json.dumps(event, ensure_ascii=False), flush=True)

            stderr = process.stderr.read() if process.stderr else ""
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise TimeoutError(f"codex exec timed out after {timeout} seconds") from exc

        final_text = Path(last_message.name).read_text(encoding="utf-8").strip()
        if return_code != 0:
            event_summary = "\n".join(json.dumps(e, ensure_ascii=False) for e in events[-5:])
            raise RuntimeError(
                "codex exec failed with exit code "
                f"{return_code}\n\nstderr:\n{stderr}\n\nlast events:\n{event_summary}"
            )

        return final_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call Codex CLI from Python.")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="List the top-level files in this project and explain what this repository appears to do.",
        help="Prompt passed to `codex exec`.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory passed to `codex exec --cd`.",
    )
    parser.add_argument("--model", help="Optional Codex model override.")
    parser.add_argument(
        "--sandbox",
        default="workspace-write",
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="Codex CLI sandbox mode.",
    )
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds.")
    parser.add_argument("--stream-events", action="store_true", help="Print JSONL events as Codex runs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        answer = run_codex(
            args.prompt,
            cwd=args.cwd.resolve(),
            model=args.model,
            sandbox=args.sandbox,
            timeout=args.timeout,
            stream_events=args.stream_events,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
