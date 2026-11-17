# Imagen única para el gateway y los 4 servicios.
# El argumento SERVICIO indica la carpeta a construir, por ejemplo:
#   docker build -f backend.Dockerfile --build-arg SERVICIO=services/auth .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1. Paquete compartido (cambia poco: se aprovecha la caché de Docker)
COPY shared /opt/shared
RUN pip install /opt/shared

# 2. Dependencias propias del servicio
ARG SERVICIO
COPY ${SERVICIO}/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# 3. Código del servicio
COPY ${SERVICIO}/app ./app

# Usuario sin privilegios; /data guarda la llave de firma de audit-service
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/llaves \
    && chown -R app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
