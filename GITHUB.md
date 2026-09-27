# Auf GitHub hochladen

Das Projekt ist bereits ein fertiges Git-Repository mit einem ersten Commit —
es fehlt nur noch das Gegenstück auf GitHub. Drei Wege, je nachdem was du
installiert hast.

## Weg 1: GitHub CLI (ein Befehl)

```bash
cd mp3releaser
gh auth login                      # einmalig, falls noch nicht geschehen
gh repo create mp3releaser --private --source=. --push
```

`--source=.` nimmt das vorhandene Repository, `--push` lädt den Commit gleich
hoch. Falls `gh` fehlt: `sudo apt install gh`.

## Weg 2: Repository im Browser anlegen

1. Auf <https://github.com/new> ein **privates** Repository namens
   `mp3releaser` anlegen — **ohne** README, .gitignore oder Lizenz, sonst
   gibt es beim ersten Push einen Konflikt.
2. Dann lokal:

```bash
cd mp3releaser
git remote add origin git@github.com:<dein-name>/mp3releaser.git
git push -u origin main
```

Mit HTTPS statt SSH:
`git remote add origin https://github.com/<dein-name>/mp3releaser.git`

## Weg 3: Über die API

```bash
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
     -d '{"name":"mp3releaser","private":true}' \
     https://api.github.com/user/repos

cd mp3releaser
git remote add origin https://github.com/<dein-name>/mp3releaser.git
git push -u origin main
```

Der Token braucht nur das Recht `repo`.

## Vorher kurz prüfen

**Die Lizenz.** In `LICENSE` steht `<Name eintragen>` — dort gehört dein
Name hin, sonst ist die MIT-Lizenz unvollständig. `pyproject.toml` nennt
bereits MIT.

**Was nicht mit hochgeht.** `.gitignore` schließt aus: `build/`, `dist/`,
`__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `data/` (die Ordner der
Compose-Datei) und `mp3releaser.toml` (deine gespeicherten Einstellungen,
die könnten Pfade aus deinem System enthalten).

**Was mit hochgeht.** Der Quelltext, die Tests, `packaging/`, `Dockerfile`,
`docker-compose.yml`, die beiden Vorlagen `templates/standard.skl` und
`templates/example.skl`, der Generator `tools/make_standard_skl.py`, die
Dokumentation (deutsch und englisch) und unter `releases/` das fertige
AppImage mit Prüfsumme. `git ls-files` zeigt die vollständige Liste.

**Nicht enthalten** ist das Original — weder `Mp3Releaser.exe` noch dessen
`.nfo`-Dateien oder `generic.skl`. Das ist Absicht: Die ASCII-Grafik darin
ist urheberrechtlich geschützt, und das Programm selbst gehört nicht in ein
Repository, das eine eigenständige Neuimplementierung enthält.

## Danach

```bash
git remote -v                      # zeigt, wohin gepusht wird
git log --oneline
```

Für spätere Änderungen wie gewohnt `git add -A && git commit && git push`.
Wenn du das Repository später öffentlich machen willst, lohnt vorher ein
Blick in `README.md` — dort stehen Beispielpfade aus meiner Testumgebung,
aber nichts von deinem System.
