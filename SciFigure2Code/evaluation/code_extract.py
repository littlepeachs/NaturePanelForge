"""Extract executable Python code from model responses."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from .schemas import CodeExtractionResult


FENCE_RE = re.compile(r"^[ \t]*```(?P<lang>[^\n`]*)\n(?P<body>.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
CODE_TAG_RE = re.compile(r"<code[^>]*>(?P<body>.*?)</code>", re.DOTALL | re.IGNORECASE)
GLM_BOX_RE = re.compile(r"<\|begin_of_box\|>(?P<body>.*?)<\|end_of_box\|>", re.DOTALL)
GLM_BOX_START_RE = re.compile(r"<\|begin_of_box\|>(?P<body>.*)", re.DOTALL)
THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)
UNMATCHED_THINK_RE = re.compile(r"<think\b[^>]*>.*$", re.DOTALL | re.IGNORECASE)
PY_LANG_HINTS = {"python", "py", "python3"}
PY_START_RE = re.compile(
    r"^\s*(#!.*python|import\s+|from\s+\S+\s+import\s+|def\s+|class\s+|@|if\s+__name__\s*==|[A-Za-z_][A-Za-z0-9_]*\s*=)",
    re.MULTILINE,
)
PYLOT_ALIAS_RE = re.compile(
    r"^\s*(?:import\s+matplotlib\.pyplot\s+as\s+plt|from\s+matplotlib\s+import\s+pyplot\s+as\s+plt)\b"
)
MATPLOTLIB_IMPORT_RE = re.compile(r"^\s*import\s+matplotlib\s*(?:#.*)?$")
BACKEND_USE_RE = re.compile(r"^\s*(?:plt|matplotlib|matplotlib\.pyplot|mpl)\.use\s*\(")
SHOW_RE = re.compile(r"^\s*(?:plt|matplotlib\.pyplot)\.show\s*\([^)]*\)\s*;?\s*(?:#.*)?$")
SAVE_BLOCK_LINE_RE = re.compile(
    r"^\s*(?:"
    r"png_path\s*=.*SCIFIGURE_CANDIDATE_PNG.*|"
    r"pdf_path\s*=.*SCIFIGURE_CANDIDATE_PDF.*|"
    r"fig\.savefig\s*\(\s*png_path\b.*|"
    r"fig\.savefig\s*\(\s*pdf_path\b.*|"
    r"plt\.savefig\s*\(\s*os\.environ\.get\(\s*['\"]SCIFIGURE_CANDIDATE_(?:PNG|PDF)['\"].*"
    r")\s*$"
)
REQUIRED_SAVE_BLOCK = (
    'png_path = os.environ.get("SCIFIGURE_CANDIDATE_PNG", "candidate.png")\n'
    'pdf_path = os.environ.get("SCIFIGURE_CANDIDATE_PDF", "candidate.pdf")\n'
    'fig.savefig(png_path, dpi=200, bbox_inches="tight")\n'
    'fig.savefig(pdf_path, bbox_inches="tight")'
)


def extract_python_code(text: str) -> CodeExtractionResult:
    text = _strip_chat_echo(text or "")
    text = _strip_thinking_blocks(text)
    json_code = _extract_json_code(text)
    if json_code is not None:
        return _finalize(json_code, strategy="json_code_field", fenced_blocks=0)

    boxed = GLM_BOX_RE.findall(text)
    if boxed:
        chosen = max(boxed, key=_python_score)
        return _finalize(chosen, strategy="glm_box", fenced_blocks=0)
    boxed_start = GLM_BOX_START_RE.search(text)
    if boxed_start:
        return _finalize(boxed_start.group("body"), strategy="glm_box_unclosed", fenced_blocks=0)

    fenced = _extract_fenced_blocks(text)
    if fenced:
        python_blocks = [block for block in fenced if block["is_python"]]
        candidates = python_blocks or fenced
        chosen = max(candidates, key=lambda block: _python_score(block["body"]))
        strategy = "python_fenced_block" if chosen["is_python"] else "generic_fenced_block"
        return _finalize(chosen["body"], strategy=strategy, fenced_blocks=len(fenced))

    tagged = CODE_TAG_RE.findall(text)
    if tagged:
        chosen = max(tagged, key=_python_score)
        return _finalize(chosen, strategy="code_tag", fenced_blocks=0)

    return _finalize(_strip_to_python(text), strategy="plain_text", fenced_blocks=0)


def _extract_json_code(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("code", "python", "script"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _extract_fenced_blocks(text: str) -> list[dict[str, Any]]:
    blocks = []
    for match in FENCE_RE.finditer(text):
        lang = match.group("lang").strip().lower().split()[0] if match.group("lang") else ""
        body = match.group("body").strip()
        if not body:
            continue
        blocks.append({"lang": lang, "body": body, "is_python": lang in PY_LANG_HINTS})
    return blocks


def _strip_to_python(text: str) -> str:
    text = text.replace("```python", "").replace("```py", "").replace("```", "")
    match = PY_START_RE.search(text)
    if match:
        text = text[match.start() :]
    lines = text.strip().splitlines()
    while lines and _looks_like_narration(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip() + ("\n" if lines else "")


def _strip_chat_echo(text: str) -> str:
    """Drop decoded user/prompt echo and keep only the assistant's generated answer."""

    markers = (
        "<|im_start|>assistant\n",
        "\nassistant\n\n",
        "\nassistant\n",
        "assistant\n\n",
        "assistant\n",
    )
    best_index = -1
    best_marker = ""
    for marker in markers:
        index = text.rfind(marker)
        if index > best_index:
            best_index = index
            best_marker = marker
    if best_index >= 0:
        return text[best_index + len(best_marker) :].lstrip()
    return text


def _strip_thinking_blocks(text: str) -> str:
    """Remove Qwen/Kimi-style reasoning tags before extracting executable code."""

    text = THINK_BLOCK_RE.sub("\n", text)
    return UNMATCHED_THINK_RE.sub("\n", text)


def _looks_like_narration(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    return lowered.startswith(("this code", "the script", "it will", "note:", "explanation:"))


def _python_score(code: str) -> int:
    score = len(code)
    for token in ("import ", "from ", "plt.", "matplotlib", "savefig", "candidate", "def "):
        if token in code:
            score += 500
    return score


def _finalize(code: str, strategy: str, fenced_blocks: int) -> CodeExtractionResult:
    code = _normalize_execution_contract(code.strip())
    if code:
        strategy = f"{strategy}+execution_contract"
    compile_ok = False
    compile_error = None
    if code:
        try:
            ast.parse(code)
            compile_ok = True
        except SyntaxError as exc:
            compile_error = f"{exc.__class__.__name__}: {exc}"
    return CodeExtractionResult(
        code=code + ("\n" if code else ""),
        strategy=strategy,
        fenced_blocks=fenced_blocks,
        compile_ok=compile_ok,
        compile_error=compile_error,
    )


def _normalize_execution_contract(code: str) -> str:
    """Make extracted scripts satisfy the benchmark execution contract."""

    if not code:
        return ""

    normalized_lines: list[str] = []
    for line in code.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()
        if stripped == "import os":
            continue
        if MATPLOTLIB_IMPORT_RE.match(line):
            continue
        if BACKEND_USE_RE.match(line):
            continue
        if stripped.startswith("from __future__ import "):
            continue
        if SHOW_RE.match(line):
            continue
        if SAVE_BLOCK_LINE_RE.match(line):
            continue
        normalized_lines.append(line.rstrip())

    while normalized_lines and not normalized_lines[0].strip():
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1].strip():
        normalized_lines.pop()

    normalized = ["import os", "import matplotlib", 'matplotlib.use("Agg")']
    if not any(PYLOT_ALIAS_RE.match(line) for line in normalized_lines):
        normalized.append("import matplotlib.pyplot as plt")
    normalized.extend(normalized_lines)
    normalized.extend(["", "fig = plt.gcf()", *REQUIRED_SAVE_BLOCK.splitlines()])
    return "\n".join(normalized).strip()
