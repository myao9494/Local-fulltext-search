#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
RUN_DIR="${ROOT_DIR}/.run"
BACKEND_PORT="${BACKEND_PORT:-8081}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"

mkdir -p "${RUN_DIR}"

kill_port() {
  local port="$1"
  local pids

  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    return 0
  fi

  echo "Stopping processes on port ${port}: ${pids}"
  kill ${pids} 2>/dev/null || true
  sleep 1

  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    kill -9 ${pids} 2>/dev/null || true
  fi
}

ensure_backend_env() {
  if [[ ! -d "${BACKEND_DIR}/.venv" ]]; then
    python3 -m venv "${BACKEND_DIR}/.venv"
  fi

  if ! "${BACKEND_DIR}/.venv/bin/python" -c "import fastapi, uvicorn, pydantic" >/dev/null 2>&1; then
    "${BACKEND_DIR}/.venv/bin/pip" install -r "${BACKEND_DIR}/requirements.txt"
  fi
}

ensure_frontend_env() {
  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    (cd "${FRONTEND_DIR}" && npm install)
  fi
}

build_frontend() {
  echo "Building frontend for backend delivery"
  (
    cd "${FRONTEND_DIR}"
    VITE_API_BASE_URL="${VITE_API_BASE_URL:-}" npm run build > "${RUN_DIR}/frontend-build.log" 2>&1
  )
}

start_backend() {
  echo "Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}"
  (
    cd "${BACKEND_DIR}"
    SEARCH_APP_HOST="${BACKEND_HOST}" SEARCH_APP_PORT="${BACKEND_PORT}" \
      nohup "${BACKEND_DIR}/.venv/bin/python" run.py > "${RUN_DIR}/backend.log" 2>&1 &
    echo $! > "${RUN_DIR}/backend.pid"
  )
}

kill_port "${BACKEND_PORT}"
ensure_backend_env
ensure_frontend_env
build_frontend
start_backend

echo "Backend log: ${RUN_DIR}/backend.log"
echo "Frontend build log: ${RUN_DIR}/frontend-build.log"
echo "App URL: http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "Health check: http://${BACKEND_HOST}:${BACKEND_PORT}/api/health"
