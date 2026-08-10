#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [ ! -x "$PROJECT_PYTHON" ]; then
    echo "未找到项目虚拟环境：$PROJECT_PYTHON" >&2
    exit 1
fi

exec "$PROJECT_PYTHON" "$PROJECT_ROOT/manage.py" start "$@"
