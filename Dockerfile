# Weboberflaeche im Container.
#
# Bewusst schlank: kein GTK, kein ffmpeg. Der Dienst liest und schreibt
# Metadaten, er kodiert nichts.
FROM python:3.12-slim AS base

# Nicht als root laufen. Der Dienst braucht keine erhoehten Rechte - die
# braucht nur, wer den Container startet.
RUN useradd --create-home --uid 1000 releaser

WORKDIR /app
COPY pyproject.toml README.md ./
COPY releaser ./releaser
COPY templates ./templates

RUN pip install --no-cache-dir . fastapi uvicorn \
    && rm -rf /root/.cache

USER releaser

# Wird ueber docker-compose gesetzt. Ohne Einhaengepunkte zeigt die
# Oberflaeche nichts - das ist Absicht, nicht ein Fehler.
ENV RELEASER_MOUNTS=""
ENV RELEASER_TEMPLATES="/app/templates"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/info')"

ENTRYPOINT ["python", "-m", "releaser"]
CMD ["web", "--host", "0.0.0.0", "--port", "8000", "--templates", "/app/templates"]
