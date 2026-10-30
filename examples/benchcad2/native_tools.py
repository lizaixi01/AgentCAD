"""Codex transport for BenchCAD's unmodified Python tools, without AgentCAD.

Only the model workbench is mounted in Docker. Session state and sealed answers
are host-side, outside that mount. tools.py and sitecustomize.py are supplied by
the pinned BenchCAD checkout during staging, not implemented by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Protocol

FINALISE = "\n\nimport tools as _harness_tools\n_harness_tools.finish(globals())\n"


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def limit_output(value: str, budget: int = 10_000) -> str:
    """The native episode's first/last 5,000-byte observation limit."""
    value = value.strip()
    encoded = value.encode("utf-8")
    if len(encoded) <= budget:
        return value
    head = encoded[:budget // 2].decode("utf-8", errors="ignore")
    tail = encoded[-budget // 2:].decode("utf-8", errors="ignore")
    return head + f"\n[... output limited to {budget} bytes ...]\n" + tail


def artifact(workspace: Path) -> Path | None:
    """Native artifact precedence: ready directory, final.step, graph."""
    sub = workspace / "submission"
    parts = [p for p in (sub / "parts").glob("*")
             if p.is_file() and p.suffix.lower() in (".step", ".stp")]
    if parts and (sub / "assembly/instances.json").is_file():
        return sub
    for name in ("final.step", "pred_graph.json"):
        path = workspace / name
        if path.is_file():
            return path
    return None


def checked_artifact(path: Path, workspace: Path) -> Path:
    """Never follow a model-created link into the host's filesystem."""
    workspace = workspace.resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(workspace):
        raise ValueError("Submitted artifact must stay in the model workbench")
    for child in path.rglob("*") if path.is_dir() else []:
        if child.is_symlink() or not child.resolve().is_relative_to(workspace):
            raise ValueError("Submitted artifact contains a link or escaped path")
    return path


@dataclass
class Execution:
    returncode: int
    stdout: str
    stderr: str
    images: list[Path]


class Executor(Protocol):
    def run(self, code: str, number: int, timeout: float) -> Execution: ...


class DockerExecutor:
    def __init__(self, workspace: Path, private: Path, image: str,
                 context: str, label: str):
        self.workspace, self.private = workspace, private
        self.image, self.context, self.label = image, context, label
        self.identifier = hashlib.sha256(str(workspace).encode()).hexdigest()[:16]

    def command(self, number: int) -> list[str]:
        name = f"benchcad-native-{self.identifier}-{number}"
        return ["docker", "--context", self.context, "run", "--rm", "--name", name,
                "--label", f"benchcad.native.experiment={self.label}",
                "--label", f"benchcad.native.workspace={self.identifier}",
                "--network", "none", "--memory", "2g", "--cpus", "1",
                "--user", "1000:1000", "--pids-limit", "256", "--read-only",
                "--tmpfs", "/tmp:size=256m", "--security-opt", "no-new-privileges",
                "-e", "PYTHONPATH=/work", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-e", "XDG_CACHE_HOME=/tmp/.cache", "-e", "OPENBLAS_NUM_THREADS=1",
                "-e", "OMP_NUM_THREADS=1", "-e", "MKL_NUM_THREADS=1",
                "-v", f"{self.workspace}:/work", "-w", "/work",
                self.image, "python", "_run.py"]

    def run(self, code: str, number: int, timeout: float) -> Execution:
        script = self.workspace / "_run.py"
        if script.is_symlink() or not script.resolve().is_relative_to(self.workspace.resolve()):
            raise ValueError("The program path must stay inside the workbench")
        script.write_text(code, encoding="utf-8", newline="\n")
        folder = self.private / f"program-{number:03d}"
        folder.mkdir(parents=True, exist_ok=False)
        folder.joinpath("code.py").write_text(code, encoding="utf-8", newline="\n")
        before = {p.name: p.stat().st_mtime_ns for p in self.workspace.glob("*.png") if p.is_file()}
        command = self.command(number)
        dump(folder / "command.json", {"command": command})
        started = time.monotonic()
        timed_out = False
        with (folder / "stdout.bin").open("wb") as out, (folder / "stderr.bin").open("wb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err)
            try:
                process.wait(timeout=timeout)
                result = process.returncode
            except subprocess.TimeoutExpired:
                timed_out, result = True, -1
                subprocess.run(["docker", "--context", self.context, "rm", "-f",
                                f"benchcad-native-{self.identifier}-{number}"],
                               capture_output=True, timeout=30)
                process.kill()
                process.wait(timeout=30)
            finally:
                subprocess.run(["docker", "--context", self.context, "rm", "-f",
                                f"benchcad-native-{self.identifier}-{number}"],
                               capture_output=True, timeout=30)

        def tail(path: Path) -> str:
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 1_000_000))
                return stream.read().decode("utf-8", errors="replace")

        stdout, stderr = tail(folder / "stdout.bin"), tail(folder / "stderr.bin")
        if timed_out:
            stderr += f"\ntimeout after {timeout:.1f}s"
        fresh = sorted((p for p in self.workspace.glob("*.png")
                        if p.is_file() and before.get(p.name) != p.stat().st_mtime_ns),
                       key=lambda p: (-p.stat().st_mtime_ns, p.name))
        images = []
        from PIL import Image
        for path in fresh:
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(self.workspace.resolve()):
                    continue
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    if im.width * im.height < 512:
                        continue
                saved = folder / path.name
                shutil.copy2(path, saved)
                images.append(saved)
            except (OSError, ValueError, Image.DecompressionBombError):
                continue
        dump(folder / "execution.json", {"returncode": result,
             "seconds": round(time.monotonic() - started, 3),
             "timed_out": timed_out, "images": [p.name for p in images]})
        return Execution(result, stdout, stderr, images)


class NativeSession:
    def __init__(self, workspace: Path, private: Path, executor: Executor,
                 deadline: float, call_limit: int = 100, exec_timeout: int = 300):
        self.workspace, self.private, self.executor = workspace.resolve(), private.resolve(), executor
        if self.private.is_relative_to(self.workspace) or self.workspace.is_relative_to(self.private):
            raise ValueError("Private session state must be outside the model mount")
        self.private.mkdir(parents=True, exist_ok=True)
        self.deadline, self.call_limit, self.exec_timeout = deadline, call_limit, exec_timeout
        self.calls = max((int(p.name.removeprefix("program-")) for p in self.private.glob("program-*")
                          if p.is_dir() and p.name.removeprefix("program-").isdigit()), default=0)
        self.lock = threading.Lock()

    @property
    def marker(self) -> Path:
        return self.private / "answer.json"

    def execute(self, code: str, submit: bool = False) -> tuple[dict, list[Path]]:
        with self.lock:
            if self.marker.exists():
                return {"ok": True, "finished": True,
                        **json.loads(self.marker.read_text(encoding="utf-8"))}, []
            self.calls += 1
            if self.calls > self.call_limit or time.time() >= self.deadline:
                return {"ok": False, "error": {"code": "BUDGET_EXHAUSTED"}}, []
            program = code + FINALISE if submit else code
            result = self.executor.run(program, self.calls,
                                       min(self.exec_timeout, max(0.001, self.deadline - time.time())))
            data = {"ok": result.returncode == 0, "returncode": result.returncode,
                    "stdout": limit_output(result.stdout), "stderr": limit_output(result.stderr),
                    "images": [p.name for p in result.images], "submitted": False}
            if result.returncode:
                data["error"] = {"code": "PYTHON_EXECUTION_FAILED"}
            if submit:
                answer = artifact(self.workspace) if result.returncode == 0 else None
                marker = {"terminal": True, "submitted": False, "status": "submit_failed",
                          "timestamp": time.time(), "program": self.calls, "returncode": result.returncode}
                if time.time() >= self.deadline:
                    marker["status"] = "timeout"
                elif answer is not None:
                    try:
                        answer = checked_artifact(answer, self.workspace)
                        sealed = self.private / "sealed" / answer.name
                        sealed.parent.mkdir(exist_ok=True)
                        if answer.is_dir():
                            shutil.copytree(answer, sealed)
                        else:
                            shutil.copy2(answer, sealed)
                        marker.update(submitted=True, status="completed",
                                      path=sealed.relative_to(self.private).as_posix())
                    except (OSError, ValueError) as exc:
                        data.update(ok=False, error={"code": "INVALID_ARTIFACT", "message": str(exc)})
                marker["timestamp"] = time.time()
                if marker["timestamp"] > self.deadline:
                    marker.update(submitted=False, status="timeout")
                    marker.pop("path", None)
                dump(self.marker, marker)
                data.update(finished=True, submitted=marker["submitted"], status=marker["status"])
                if not marker["submitted"] and data["ok"]:
                    data.update(ok=False, error={"code": "NO_FINAL_ARTIFACT"})
            return data, result.images


def serve(config_path: Path) -> None:
    from mcp.server.fastmcp import FastMCP, Image
    config = json.loads(config_path.read_text(encoding="utf-8"))
    workspace, private = Path(config["workspace"]), config_path.parent
    session = NativeSession(workspace, private,
                            DockerExecutor(workspace, private, config["image"],
                                           config["docker_context"], config["experiment"]),
                            config["deadline"], config["calls"], config["exec_timeout"])
    server = FastMCP("benchcad-native")

    @server.tool()
    def execute_python(code: str, submit: bool = False) -> list:
        """Run Python in the isolated BenchCAD workbench. Files persist, memory does not.
        Use import tools for the native export, crop and assembly functions. New
        top-level PNGs are shown automatically. submit=True executes this final
        program plus tools.finish(globals()), seals its answer and ends the episode,
        even if the program fails. Do not submit until your program is complete.
        """
        from PIL import Image as PILImage
        data, images = session.execute(code, submit)
        content = [json.dumps(data, ensure_ascii=False, allow_nan=False)]
        for path in images:
            with PILImage.open(path) as original:
                im = original.convert("RGB")
                im.thumbnail((2000, 2000))
                stream = io.BytesIO()
                im.save(stream, format="PNG")
            content.append(Image(data=stream.getvalue(), format="png"))
        return content

    server.run(transport="stdio")


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
