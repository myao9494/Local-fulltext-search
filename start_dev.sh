#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
RUN_DIR="${ROOT_DIR}/.run"
BACKEND_PORT="${BACKEND_PORT:-8081}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_API_HOST="${FRONTEND_API_HOST:-mac-mini}"

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

start_backend() {
  echo "Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}"
  (
    cd "${BACKEND_DIR}"
    SEARCH_APP_HOST="${BACKEND_HOST}" SEARCH_APP_PORT="${BACKEND_PORT}" \
      nohup "${BACKEND_DIR}/.venv/bin/python" run.py > "${RUN_DIR}/backend.log" 2>&1 &
    echo $! > "${RUN_DIR}/backend.pid"
  )
}

start_frontend() {
  echo "Starting frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}"
  (
    cd "${FRONTEND_DIR}"
    VITE_API_BASE_URL="http://${FRONTEND_API_HOST}:${BACKEND_PORT}" \
      nohup "${FRONTEND_DIR}/node_modules/.bin/vite" --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" > "${RUN_DIR}/frontend.log" 2>&1 &
    echo $! > "${RUN_DIR}/frontend.pid"
  )
}

kill_port "${BACKEND_PORT}"
kill_port "${FRONTEND_PORT}"
ensure_backend_env
ensure_frontend_env
start_backend
start_frontend

echo "Backend log: ${RUN_DIR}/backend.log"
echo "Frontend log: ${RUN_DIR}/frontend.log"
echo "Backend URL: http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "Frontend URL: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "Frontend API Base URL: http://${FRONTEND_API_HOST}:${BACKEND_PORT}"
