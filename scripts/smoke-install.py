"""Install a release wheel with uv tool and exercise it outside the checkout."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


root = Path(__file__).resolve().parent.parent
directory = Path(sys.argv[1] if len(sys.argv) > 1 else "dist").resolve()
(wheel,) = directory.glob("*.whl")
uv = shutil.which("uv")
node = shutil.which("node")
assert uv and node, "The release smoke test needs uv and Node"
with tempfile.TemporaryDirectory(prefix="rcoder-install-") as temporary:
    work = Path(temporary)
    env = {
        **os.environ,
        "UV_TOOL_DIR": str(work / "tools"),
        "UV_TOOL_BIN_DIR": str(work / "bin"),
    }
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [
            uv,
            "tool",
            "install",
            "--default-index",
            "https://pypi.org/simple",
            "--python",
            sys.executable,
            str(wheel),
        ],
        cwd=work,
        env=env,
        check=True,
    )
    suffix = ".exe" if os.name == "nt" else ""
    python = (
        work
        / "tools/reuleauxcoder"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    for command in ("rcoder", "rcoder-cli", "rcoder-tui"):
        subprocess.run(
            [str(work / "bin" / (command + suffix)), "--version"],
            cwd=work,
            env={**env, "PATH": ""},
            check=True,
        )
    bundle = subprocess.check_output(
        [
            str(python),
            "-c",
            "from importlib.resources import files; print(files('reuleauxcoder') / '_tui/cli.mjs')",
        ],
        cwd=work,
        env=env,
        text=True,
    ).strip()
    subprocess.run(
        [node, bundle, "--help"],
        cwd=work,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    if os.name != "nt":
        subprocess.run(
            [
                str(python),
                str(root / "reuleauxcoder-tui/test/terminal_smoke.py"),
                "--launcher",
                str(work / "bin/rcoder"),
            ],
            cwd=work,
            env=env,
            check=True,
            timeout=30,
        )
print(
    "uv tool installation, all entry points and standalone TUI passed outside the checkout."
)
