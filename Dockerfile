# Stage 1: Build the React frontend
FROM node:18-alpine AS frontend-builder
WORKDIR /build

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# Stage 2: Python server with OpenCV headless & FastAPI
FROM python:3.10-slim
WORKDIR /app

# Install minimal system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend and website source code
COPY backend/app/ ./backend/app/
COPY backend/storage/ ./backend/storage/
COPY website/ ./website/

# Copy built frontend production bundle into website/ui
COPY --from=frontend-builder /build/dist ./website/ui/

WORKDIR /app/website

ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Start unified web service on Render's assigned $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
