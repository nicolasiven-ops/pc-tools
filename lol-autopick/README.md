# LoL Auto-Pick

Begleit-Tool für League of Legends: nimmt die Queue an, **bannt** und **pickt**
in der Champion-Auswahl automatisch nach deinen Prioritätslisten und
benachrichtigt dich, sobald das Spiel losgeht – ideal, um während der Wartezeit
kurz vom PC wegzugehen.

## Funktionen

- **Queue-Accept** – nimmt den Ready-Check sofort an, wenn ein Match gefunden wird.
- **Auto-Pick mit Prioritätsliste** – bis zu **fünf** Champions in Wunsch­reihen­folge.
  Das Tool merkt den ersten **verfügbaren** vor und lockt ihn, wenn du dran bist.
  Ist dein 1. Wunsch gebannt oder schon weg, rutscht es automatisch zum nächsten.
- **Auto-Ban mit Prioritätsliste** – bis zu **drei** Bann-Champions. Bannt den
  ersten verfügbaren, wenn du an der Reihe bist. Mit zwei Sicherheitsregeln:
  - bannt **nie** einen Champion, der auf deiner eigenen Pick-Liste steht,
  - bannt **nie** einen Champion, den ein Mitspieler gerade vormerkt.
- **Spielstart-Benachrichtigung** – holt das Fenster nach vorne und spielt einen
  Ton, sobald das Spiel startet.

Die Auswahl wird in `~/.lol_autopick.json` gespeichert und beim nächsten Start
wieder geladen.

## Oberfläche

Dunkles Design in LoL-/Hextech-Farben. Links eine **Champion-Suche** mit
Portraits (Live vom Client geladen) – anklicken fügt zur aktiven Liste hinzu
(umschaltbar zwischen **Picks** und **Bans**). Rechts die beiden Prioritäts­listen,
deren Einträge sich per ▲▼ umsortieren und mit ✕ entfernen lassen.

## Funktionsweise (kurz)

Der League-Client betreibt lokal eine REST-API auf `127.0.0.1` – dieselbe, die
Riots Client selbst nutzt. Das Tool liest Port und Auth-Token aus dem laufenden
`LeagueClientUx`-Prozess (Fallback: `lockfile`) und spricht damit die Endpunkte
für Ready-Check, Champion-Auswahl, Bann-/Pick-Aktionen, Champion-Bilder und
Spielphase an. Mehr dazu in `lcu.py`.

## Starten

    pip install -r requirements.txt
    python app.py

1. League-Client starten (Reihenfolge egal – das Tool verbindet sich automatisch).
2. Sobald „verbunden" oben rechts erscheint, Champions über die Suche zu Pick- und
   Bann-Liste hinzufügen und sortieren.
3. **Start** klicken und in die Queue gehen. (Vor dem Verbinden zeigt das Tool nur
   deine gespeicherten Namen; die volle Liste mit Bildern kommt vom Client.)

## Als .exe bauen (optional)

Aus dem Ordner `lol-autopick/`:

    pip install pyinstaller
    pyinstaller --onedir --noconsole --noupx --icon lol-autopick.ico --version-file version_info.txt --name LoL-AutoPick app.py

Das fertige Paket liegt danach im Ordner `dist/LoL-AutoPick/` (Start: die
`LoL-AutoPick.exe` darin). `--onedir` wird `--onefile` vorgezogen, weil die
selbst-entpackende Einzel-Exe von Windows Defender oft fälschlich als Virus
gemeldet wird. Im Repo baut das GitHub-Actions-Workflow das Paket automatisch
und legt es als `LoL-AutoPick.zip` in die Releases.

## „Defender meldet einen Virus" – Fehlalarm

PyInstaller-Programme werden von Windows Defender häufig fälschlich als Malware
erkannt (selbst-entpackender Loader, keine Signatur, plus das Auslesen des
League-Prozesses für den Auth-Token). Der Code ist offen und wird per CI
gebaut – es ist ein **False Positive**. Gegenmaßnahmen, von einfach nach gründlich:

- Das `--onedir`-ZIP (wie oben) statt einer Einzel-Exe verwenden.
- Die Datei in Defender als **Fehlalarm an Microsoft melden**
  (https://www.microsoft.com/wdsi/filesubmission) – wird meist binnen Tagen
  zentral entschärft.
- Den Ordner in den **Defender-Ausschlüssen** eintragen.
- 100 % sauber: **aus dem Quellcode starten** (`python app.py`) oder die `.exe`
  mit einem (kostenpflichtigen) Zertifikat **signieren**.

## ⚠️ Wichtiger Hinweis (Terms of Service)

Dieses Tool automatisiert ausschließlich **Client-Komfort** (Queue annehmen,
bannen, picken) – es greift **nicht** ins laufende Spiel ein (kein Scripting,
kein Aimbot o. ä.). Trotzdem gilt: Laut Riots Nutzungsbedingungen ist *jede*
Automatisierung des Clients streng genommen unzulässig. Bans wegen reiner
LCU-Tools sind in der Praxis sehr selten, aber nicht ausgeschlossen.
**Nutzung auf eigenes Risiko.**

## Bekannte Grenzen (Prototyp)

- Ausgelegt auf Modi mit echter Champion-Auswahl (Draft/Ranked). Bei Blind Pick
  oder ARAM gibt es keine klassische Bann-/Pick-Aktion.
- Pickt/bannt sofort, sobald du an der Reihe bist (kein Verzögern, kein
  Trade-Handling).
- Die Champion-Suche mit Bildern füllt sich erst, wenn der Client verbunden ist.
