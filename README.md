# PC Tools

Kleine Windows-App mit ein paar praktischen PC-Steuerungen.

## Funktionen

- **Ausschalt-Timer** — fährt den PC nach einer einstellbaren Zeit herunter (Schnellwahl 30 Min / 1 / 2 / 3 h, Standard 2 h, ±15-Min-Feinjustierung, Live-Anzeige „Aus um HH:MM Uhr“, jederzeit abbrechbar).
- **Bildschirm abdunkeln** — macht alle Monitore schwarz, bis du klickst oder eine Taste drückst.

## Download

Die fertige `.exe` wird bei jedem Push automatisch von GitHub gebaut:

1. Auf der Repo-Seite rechts auf **Releases** klicken (Eintrag „Neueste Version“).
2. `PC-Tools.exe` herunterladen.
3. Doppelklick zum Starten — keine Installation nötig.

> **Windows-Hinweis:** Beim ersten Start meldet sich evtl. „Windows hat Ihren PC geschützt“ (SmartScreen), weil die `.exe` nicht signiert ist. Auf **Weitere Informationen → Trotzdem ausführen** klicken. Das ist bei selbstgebauten Tools normal.

## Selbst bauen (optional)

    pip install -r requirements.txt
    pyinstaller --onefile --noconsole --name PC-Tools pc_tools.py

Die fertige Datei liegt danach unter `dist/PC-Tools.exe`.
