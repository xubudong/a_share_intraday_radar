from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TextIO


ROOT_DIR = Path(__file__).resolve().parents[1]
LAUNCH_LOG = ROOT_DIR / ".radar.launch.log"
_launch_log_stream: TextIO | None = None


def expected_interpreters() -> set[Path]:
    if os.name == "nt":
        scripts_dir = ROOT_DIR / ".venv" / "Scripts"
        return {scripts_dir / "python.exe", scripts_dir / "pythonw.exe"}
    return {ROOT_DIR / ".venv" / "bin" / "python"}


def configure_hidden_output() -> None:
    global _launch_log_stream
    if sys.stdout is not None and sys.stderr is not None:
        return
    _launch_log_stream = LAUNCH_LOG.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _launch_log_stream
    sys.stderr = _launch_log_stream


def validate_runtime() -> int:
    expected = expected_interpreters()
    existing = {path.resolve() for path in expected if path.exists()}
    if not existing:
        paths = " 或 ".join(str(path) for path in sorted(expected, key=str))
        print(f"未找到项目虚拟环境 Python：{paths}")
        print("启动脚本不会创建环境或回退到系统 Python。")
        return 1

    try:
        current = Path(sys.executable).resolve()
    except OSError:
        current = Path(sys.executable)
    if current not in existing:
        print(f"当前解释器不属于项目 .venv：{current}")
        print("请通过 manage.ps1、manage.sh、start.bat 或 start_hidden.vbs 运行。")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_hidden_output()
    runtime_error = validate_runtime()
    if runtime_error:
        return runtime_error

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    import radar

    return radar.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
