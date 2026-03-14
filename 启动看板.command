#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
echo "正在启动作业跟踪看板..."
echo "请在浏览器中打开: http://127.0.0.1:5000"
open "http://127.0.0.1:5000"
python app.py
