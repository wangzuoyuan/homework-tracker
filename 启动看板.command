#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
  PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "未找到可用的 Python 解释器。"
  exit 1
fi

PORT="${BOARD_PORT:-5050}"

echo "正在启动作业跟踪看板..."
echo "项目目录: $SCRIPT_DIR"
echo "浏览器地址: http://127.0.0.1:$PORT"

"$PYTHON_BIN" -c 'import socket, sys; port = int(sys.argv[1]); s = socket.socket(); s.settimeout(0.2); ok = s.connect_ex(("127.0.0.1", port)) == 0; s.close(); sys.exit(0 if ok else 1)' "$PORT"
if [ $? -eq 0 ]; then
  echo "检测到 $PORT 端口已被占用，可能已有一个看板实例在运行。"
  open "http://127.0.0.1:$PORT"
else
  (
    sleep 2
    open "http://127.0.0.1:$PORT"
  ) &
  BOARD_PORT="$PORT" "$PYTHON_BIN" app.py
fi
