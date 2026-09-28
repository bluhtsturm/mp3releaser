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

Im Container wirken `[naming]`, `[tags]` und `[build]`. `[gui]` gilt nur für
die Desktop-Anwendung; die Vorlage wählt man im Web aus dem Ordner
`templates/`, `[build] template` bleibt dort ohne Wirkung.
