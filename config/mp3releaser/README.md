# Einstellungen für den Container

Hier liegt die Konfiguration der Container-Fassung: `config.toml` in diesem
Ordner. `docker-compose.yml` hängt den Ordner `config/` nur lesend unter
`/config` ein; das Programm liest `/config/mp3releaser/config.toml`.

Ohne `config.toml` gelten die Voreinstellungen. Die Datei ist per
`.gitignore` vom Repository ausgeschlossen – sie kann Pfade deines Systems
enthalten.

Anlegen, zum Beispiel aus den Einstellungen des AppImage:

```bash
cp ~/.config/mp3releaser/config.toml config/mp3releaser/config.toml
```

oder aus der kommentierten Vorlage:

```bash
docker compose run --rm -T cli config --example > config/mp3releaser/config.toml
```

Gelesen wird beim Start. Nach einer Änderung:

```bash
docker compose restart releaser
docker compose logs releaser | grep Konfiguration
```

Im Container wirken `[naming]`, `[tags]`, `[build]` und `[web]`. `[gui]` gilt
nur für die Desktop-Anwendung. `[build] template` nennt die Vorlage, mit der
jede Sitzung beginnt – ein Name aus dem Ordner `templates/`.

## Was die Weboberfläche speichert

Diese Datei bleibt dem, der den Dienst betreibt; der Container darf sie nicht
ändern. Was in der Weboberfläche mit **„Als Standard“** gespeichert wird,
landet in einer eigenen Datei: `/settings/settings.toml` im Volume
`settings`. Ihre Werte liegen über denen hier, alles andere von hier gilt
weiter.

```bash
docker compose run --rm -T cli config                    # beide zusammen
docker compose exec releaser rm /settings/settings.toml  # zurücksetzen
```
