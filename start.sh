#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export ADMIN_INVITE_CODE="${ADMIN_INVITE_CODE:-robot2026}"
export ROBOT_ORIGIN="${ROBOT_ORIGIN:-http://192.168.0.73:8021}"
export PHOTO_STORAGE_DIR="${PHOTO_STORAGE_DIR:-/home/lab/robot_photos}"
mkdir -p "${PHOTO_STORAGE_DIR}"
# 虚拟环境：/home/lab/robot_user_backend/.venv
if [ -f ".venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
exec uvicorn main:app --host 0.0.0.0 --port 8022
