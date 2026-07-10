"""Execute extracted Python code and collect rendered artifacts."""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import Sample
from .utils import ensure_dir, tail_text


@dataclass
class RunnerConfig:
    python: str = sys.executable
    timeout_seconds: int = 180
    create_pdf_from_png: bool = True
    render_png_from_pdf: bool = True
    disable_network: bool = True
    env_allowlist: tuple[str, ...] = (
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "CONDA_PREFIX",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "CUDA_VISIBLE_DEVICES",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
    )
    max_memory_mb: int | None = 8192
    max_open_files: int | None = 256
    use_bwrap: bool = True
    expose_target_paths: bool = False


class CodeRunner:
    def __init__(self, config: RunnerConfig | None = None):
        self.config = config or RunnerConfig()

    def run(self, code: str, sample: Sample, output_dir: Path) -> dict[str, Any]:
        output_dir = ensure_dir(output_dir).resolve()
        script_path = output_dir / "candidate.py"
        stdout_path = output_dir / "stdout.txt"
        stderr_path = output_dir / "stderr.txt"
        candidate_png = output_dir / "candidate.png"
        candidate_pdf = output_dir / "candidate.pdf"

        script_path.write_text(code, encoding="utf-8")
        env = self._sandbox_env(output_dir, candidate_png, candidate_pdf)
        if self.config.disable_network:
            self._write_sitecustomize(output_dir)
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": str(output_dir / ".matplotlib"),
                "SCIFIGURE_OUTPUT_DIR": str(output_dir),
                "SCIFIGURE_CANDIDATE_PNG": str(candidate_png),
                "SCIFIGURE_CANDIDATE_PDF": str(candidate_pdf),
            }
        )
        if self.config.expose_target_paths and sample.target_png:
            env["SCIFIGURE_TARGET_PNG"] = str(sample.target_png)
        if self.config.expose_target_paths and sample.target_pdf:
            env["SCIFIGURE_TARGET_PDF"] = str(sample.target_pdf)

        started = time.monotonic()
        timed_out = False
        returncode: int | None
        stdout = ""
        stderr = ""
        process: subprocess.Popen[str] | None = None
        try:
            command, sandbox_mode = self._execution_command(script_path, output_dir)
            process = subprocess.Popen(
                command,
                cwd=output_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                preexec_fn=self._resource_limiter(),
            )
            stdout, stderr = process.communicate(timeout=self.config.timeout_seconds)
            returncode = process.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = None
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if process is not None:
                self._kill_process_group(process)
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")

        elapsed = time.monotonic() - started
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")

        discovered_png = self._normalize_artifact(output_dir, candidate_png, "*.png")
        discovered_pdf = self._normalize_artifact(output_dir, candidate_pdf, "*.pdf")
        pdf_fallback = None
        png_fallback = None

        if discovered_png and not discovered_pdf and self.config.create_pdf_from_png:
            pdf_fallback = self._create_pdf_from_png(discovered_png, candidate_pdf)
            discovered_pdf = candidate_pdf if candidate_pdf.exists() else None
        if discovered_pdf and not discovered_png and self.config.render_png_from_pdf:
            png_fallback = self._render_png_from_pdf(discovered_pdf, candidate_png)
            discovered_png = candidate_png if candidate_png.exists() else None

        return {
            "script_path": script_path,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "stdout_tail": tail_text(stdout, 4000),
            "stderr_tail": tail_text(stderr, 4000),
            "returncode": returncode,
            "timed_out": timed_out,
            "command_success": (not timed_out and returncode == 0),
            "elapsed_seconds": round(elapsed, 3),
            "candidate_png": discovered_png,
            "candidate_pdf": discovered_pdf,
            "candidate_png_exists": bool(discovered_png and discovered_png.exists()),
            "candidate_pdf_exists": bool(discovered_pdf and discovered_pdf.exists()),
            "pdf_from_png_fallback": pdf_fallback,
            "png_from_pdf_fallback": png_fallback,
            "sandbox": {
                "cwd": output_dir,
                "mode": sandbox_mode,
                "bwrap_available": bool(shutil.which("bwrap")),
                "env_allowlist": list(self.config.env_allowlist),
                "disable_network": self.config.disable_network,
                "max_memory_mb": self.config.max_memory_mb,
                "max_open_files": self.config.max_open_files,
                "start_new_session": True,
                "timeout_kills_process_group": True,
            },
        }

    def _execution_command(self, script_path: Path, output_dir: Path) -> tuple[list[str], str]:
        bwrap = shutil.which("bwrap") if self.config.use_bwrap and os.name == "posix" else None
        if not bwrap:
            return [self.config.python, "-u", str(script_path)], "python_guard_fallback"

        command = [
            bwrap,
            "--die-with-parent",
            "--unshare-pid",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(output_dir),
            str(output_dir),
            "--chdir",
            str(output_dir),
        ]
        if self.config.disable_network:
            command.insert(1, "--unshare-net")
        command.extend([self.config.python, "-u", str(script_path)])
        return command, "bubblewrap_os_sandbox"

    def _sandbox_env(self, output_dir: Path, candidate_png: Path, candidate_pdf: Path) -> dict[str, str]:
        env = {key: os.environ[key] for key in self.config.env_allowlist if key in os.environ}
        env["PYTHONUNBUFFERED"] = "1"
        env["MPLBACKEND"] = "Agg"
        env["MPLCONFIGDIR"] = str(output_dir / ".matplotlib")
        env["PYTHONNOUSERSITE"] = "1"
        env["SCIFIGURE_OUTPUT_DIR"] = str(output_dir)
        env["SCIFIGURE_CANDIDATE_PNG"] = str(candidate_png)
        env["SCIFIGURE_CANDIDATE_PDF"] = str(candidate_pdf)
        if self.config.disable_network:
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(output_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
            env["SCIFIGURE_DISABLE_NETWORK"] = "1"
            env["SCIFIGURE_SANDBOX_OUTPUT_DIR"] = str(output_dir)
        return env

    @staticmethod
    def _write_sitecustomize(output_dir: Path) -> None:
        (output_dir / "sitecustomize.py").write_text(
            """
import os

if os.environ.get("SCIFIGURE_DISABLE_NETWORK") == "1":
    import builtins
    from pathlib import Path
    import socket
    import os as _os

    _sandbox_root = Path(os.environ.get("SCIFIGURE_SANDBOX_OUTPUT_DIR", ".")).resolve()

    def _inside_sandbox(path):
        try:
            resolved = Path(path).expanduser().resolve()
        except Exception:
            return True
        return resolved == _sandbox_root or _sandbox_root in resolved.parents

    def _write_mode(mode):
        return any(flag in str(mode) for flag in ("w", "a", "x", "+"))

    _orig_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        if _write_mode(mode) and not _inside_sandbox(file):
            raise OSError("Write access outside SciFigure2Code sandbox is disabled")
        return _orig_open(file, mode, *args, **kwargs)

    builtins.open = _guarded_open

    _orig_path_open = Path.open

    def _guarded_path_open(self, mode="r", *args, **kwargs):
        if _write_mode(mode) and not _inside_sandbox(self):
            raise OSError("Write access outside SciFigure2Code sandbox is disabled")
        return _orig_path_open(self, mode, *args, **kwargs)

    Path.open = _guarded_path_open

    def _guarded_destructive(fn):
        def wrapped(path, *args, **kwargs):
            if not _inside_sandbox(path):
                raise OSError("Destructive filesystem access outside SciFigure2Code sandbox is disabled")
            return fn(path, *args, **kwargs)
        return wrapped

    for _name in ("remove", "unlink", "rmdir"):
        if hasattr(_os, _name):
            setattr(_os, _name, _guarded_destructive(getattr(_os, _name)))

    class _SciFigureBlockedSocket(socket.socket):
        def connect(self, *args, **kwargs):
            raise OSError("Network access is disabled by SciFigure2Code sandbox")

        def connect_ex(self, *args, **kwargs):
            return 1

    socket.socket = _SciFigureBlockedSocket
    socket.create_connection = lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError("Network access is disabled by SciFigure2Code sandbox")
    )
""".lstrip(),
            encoding="utf-8",
        )

    def _resource_limiter(self):
        def limit_resources() -> None:
            try:
                import resource

                cpu_seconds = max(1, int(self.config.timeout_seconds) + 5)
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
                if self.config.max_memory_mb:
                    memory = int(self.config.max_memory_mb) * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
                if self.config.max_open_files:
                    files = int(self.config.max_open_files)
                    resource.setrlimit(resource.RLIMIT_NOFILE, (files, files))
            except Exception:
                pass

        if os.name != "posix":
            return None
        return limit_resources

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[str]) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                    return
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    return
            except Exception:
                pass
        try:
            process.kill()
        except Exception:
            pass

    @staticmethod
    def _normalize_artifact(output_dir: Path, expected: Path, pattern: str) -> Path | None:
        if expected.exists():
            return expected
        candidates = [
            path
            for path in output_dir.rglob(pattern)
            if path.is_file() and ".matplotlib" not in path.parts and path.name not in {"target.png", "target.pdf"}
        ]
        if not candidates:
            return None
        source = max(candidates, key=lambda path: (path.stat().st_mtime, path.stat().st_size))
        if source.resolve() != expected.resolve():
            shutil.copy2(source, expected)
        return expected if expected.exists() else source

    @staticmethod
    def _create_pdf_from_png(png_path: Path, pdf_path: Path) -> dict[str, Any]:
        try:
            from PIL import Image

            with Image.open(png_path) as image:
                image.convert("RGB").save(pdf_path)
            return {"ok": True, "source": png_path, "output": pdf_path}
        except Exception as exc:
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    @staticmethod
    def _render_png_from_pdf(pdf_path: Path, png_path: Path) -> dict[str, Any]:
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            return {"ok": False, "error": "pdftoppm not found"}
        try:
            prefix = png_path.with_suffix("")
            completed = subprocess.run(
                [pdftoppm, "-png", "-singlefile", str(pdf_path), str(prefix)],
                cwd=png_path.parent,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            return {
                "ok": completed.returncode == 0 and png_path.exists(),
                "returncode": completed.returncode,
                "stderr_tail": tail_text(completed.stderr or "", 2000),
            }
        except Exception as exc:
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
