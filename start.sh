#!/bin/sh
set -e

# Backend — internal only, on 127.0.0.1:8000
( cd /app/backend && python3 -m uvicorn api:app --host 127.0.0.1 --port 8000 ) &

# Frontend — the exposed entry point on 3004 (proxies /api to the backend)
export PORT=3004
export HOSTNAME=0.0.0.0
exec node /app/frontend/server.js
