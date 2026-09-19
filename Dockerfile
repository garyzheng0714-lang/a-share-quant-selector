FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Shanghai
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py updater.py ./
COPY strategy ./strategy
COPY utils ./utils
COPY --from=frontend /frontend/dist ./frontend/dist
RUN useradd --uid 10001 --create-home quant && mkdir -p data && chown -R quant:quant /app
USER quant
EXPOSE 5000
CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=1", "--threads=4", "--timeout=60", "app:app"]
