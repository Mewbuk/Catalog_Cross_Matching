# ============================================================================
# Astrometry Console — single container running BOTH the FastAPI backend
# and the Next.js frontend. Only port 3004 is exposed (the browser entry).
# The Next.js server proxies /api/* to the backend on internal port 8000.
# ============================================================================

# ---------- Stage 1: build the Next.js frontend (standalone) ----------
FROM node:20-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: runtime with Python (astro libs) + Node ----------
FROM node:20-bookworm-slim
# Python for the astronomy backend
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Backend + its (heavy) dependencies: astropy / photutils / astroquery / scipy
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r backend/requirements.txt
COPY backend/ ./backend/

# Frontend: the self-contained standalone server + static assets
COPY --from=frontend-build /app/frontend/.next/standalone ./frontend/
COPY --from=frontend-build /app/frontend/.next/static ./frontend/.next/static

COPY start.sh ./start.sh
RUN chmod +x ./start.sh

ENV BACKEND_URL=http://127.0.0.1:8000
EXPOSE 3004
CMD ["./start.sh"]
