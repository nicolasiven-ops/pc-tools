# LoL Auto-Pick

Kleines Begleit-Tool für League of Legends: nimmt die Queue an, pickt in der
Champion-Auswahl automatisch deinen bevorzugten Champion und benachrichtigt
dich, sobald das Spiel losgeht – ideal, um während der Wartezeit kurz vom PC
wegzugehen.

## Funktionen

- **Queue-Accept** – nimmt den Ready-Check sofort an, wenn ein Match gefunden wird.
- **Auto-Pick mit Prioritätsliste** – du trägst **fünf** Champions in Wunsch-
  reihenfolge ein. Das Tool merkt den ersten **verfügbaren** vor und lockt ihn,
  wenn du dran bist. Ist dein 1. Wunsch gebannt oder schon gepickt, rutscht es
  automatisch zum nächsten.
- **Spielstart-Benachrichtigung** – holt das Fenster nach vorne und spielt einen
  Ton, sobald das Spiel startet.

Die Champion-Wünsche werden in `~/.lol_autopick.json` gespeichert und beim
nächsten Start wieder geladen.

## Funktionsweise (kurz)

Der League-Client betreibt lokal eine REST-API auf `127.0.0.1` – dieselbe, die
Riots Client selbst nutzt. Das Tool liest Port und Auth-Token aus dem laufenden
`LeagueClientUx`-Prozess (Fallback: `lockfile`) und spricht damit die Endpunkte
für Ready-Check, Champion-Auswahl und Spielphase an. Mehr dazu in `lcu.py`.

## Starten

    pip install -r requirements.txt
    python app.py

1. League-Client starten (kann auch erst nach dem Tool gestartet werden).
2. Bis zu 5 Champions in Reihenfolge eintragen. Sobald der Client verbunden ist,
   schlagen die Felder Namen per Dropdown vor.
3. **Start** klicken und in die Queue gehen.

## Als .exe bauen (optional)

    pip install pyinstaller
    pyinstaller --onefile --noconsole --name LoL-AutoPick app.py

Die fertige Datei liegt danach unter `dist/LoL-AutoPick.exe`.

## ⚠️ Wichtiger Hinweis (Terms of Service)

Dieses Tool automatisiert ausschließlich **Client-Komfort** (Queue annehmen,
Champion picken) – es greift **nicht** ins laufende Spiel ein (kein Scripting,
kein Aimbot o. ä.). Trotzdem gilt: Laut Riots Nutzungsbedingungen ist *jede*
Automatisierung des Clients streng genommen unzulässig. Bans wegen reiner
LCU-Tools sind in der Praxis sehr selten, aber nicht ausgeschlossen.
**Nutzung auf eigenes Risiko.**

## Bekannte Grenzen (Prototyp)

- Ausgelegt auf Modi mit echter Champion-Auswahl (Draft/Ranked). Bei Blind Pick
  oder ARAM gibt es keine klassische Pick-Aktion.
- Bannt nicht automatisch – nur Picks.
- Pickt sofort, sobald du an der Reihe bist (kein Verzögern/Trade-Handling).
