# Weboberflaeche im Container.
#
# Bewusst schlank: kein GTK, kein ffmpeg. Der Dienst liest und schreibt
# Metadaten, er kodiert nichts.
FROM python:3.12-slim AS base

# Nicht als root laufen. Der Dienst braucht keine erhoehten Rechte - die
# braucht nur, wer den Container startet.
# /settings gehoert dem Dienst: Dort speichert die Weboberflaeche ihre
# Einstellungen. Ein benanntes Volume uebernimmt beim ersten Einhaengen
# Besitzer und Rechte dieses Ordners - ohne das waere es root und nicht
# beschreibbar.
RUN useradd --create-home --uid 1000 releaser \
    && mkdir /settings && chown releaser:releaser /settings

WORKDIR /app
COPY pyproject.toml README.md ./
COPY releaser ./releaser
COPY templates ./templates

# pip selbst zuerst: Das Basisimage bringt eine aeltere Fassung mit bekannten
# Luecken mit (25.0.1). Die Pakete sind nicht festgeschrieben - jeder Bau
# holt die aktuellen; "docker compose build --pull" erneuert dazu das
# Basisimage.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . fastapi uvicorn \
    && rm -rf /root/.cache

USER releaser

# Wird ueber docker-compose gesetzt. Ohne Einhaengepunkte zeigt die
# Oberflaeche nichts - das ist Absicht, nicht ein Fehler.
ENV RELEASER_MOUNTS=""
ENV RELEASER_TEMPLATES="/app/templates"
# Einstellungen liegen unter /config/mp3releaser/config.toml - derselbe
# Aufbau wie ~/.config/mp3releaser/config.toml beim AppImage. docker-compose
# haengt dort ./config ein; fehlt die Datei, gelten die Voreinstellungen.
ENV XDG_CONFIG_HOME="/config"
# Was die Weboberflaeche als Standard speichert, liegt darueber - in einer
# eigenen Datei im Volume /settings, beschreibbar fuer den Dienst.
ENV RELEASER_SETTINGS="/settings/settings.toml"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/info')"

ENTRYPOINT ["python", "-m", "releaser"]
CMD ["web", "--host", "0.0.0.0", "--port", "8000", "--templates", "/app/templates"]
