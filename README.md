# Wichtelhaus

Ein unsichtbarer Wichtel (wie Pumuckl) wohnt im Wichtelhaus. Er wacht jeden Tag
zu einer anderen Zeit auf, frühstückt, bastelt, spielt, räumt auf, schaut aus
dem Fenster, wird müde und geht schlafen. Man sieht ihn nie, aber am Licht merkt
man, wo er gerade ist:

- **Innenlicht** (NeoPixel, 56 LEDs in 4 Reihen à 14 als Deckenleuchten): warmweiß, wenn es
  draußen dunkel ist **und** der Wichtel wach ist. Der Raum, in dem er gerade
  ist, leuchtet heller, die anderen gedämpft. Weiche Übergänge, beim
  Schlafengehen dimmt es langsam ab. Steht er nachts auf, gibt es kurz ein
  Nachtlicht in der Küche.
- **Ofen** (ein paar LEDs, die wie Feuer flackern): brennt, wenn es draußen
  kälter als 5 °C ist und der Wichtel wach ist. Nach dem Einschlafen glimmt noch
  eine Stunde Glut.
- **Außenlicht** (Relais, Lichterkette): von Sonnenuntergang bis Sonnenaufgang
  oder bis zu einer einstellbaren Uhrzeit.
- **Laterne** (eigenes Relais, LED-Lämpchen an der Tür): von Sonnenuntergang bis
  Sonnenaufgang.

Die Sonnenzeiten werden mit `astral` für den echten Standort berechnet,
Sommer- und Winterzeit über `Europe/Vienna`. Die Außentemperatur kommt alle
20 Minuten von [Open-Meteo](https://open-meteo.com) (ohne API-Key). Ist das
Internet weg, läuft das Programm mit dem letzten Wert weiter.

## Hardware

| Teil | Anschluss am Pi 3B |
|---|---|
| WS2812-Band, 56 LEDs, Daten (DIN) | GPIO 18 (Pin 12), am besten über einen Pegelwandler 74AHCT125 auf 5 V und mit 330-Ω-Widerstand in Reihe |
| WS2812-Band, 5 V und GND | direkt ans **5-V-Netzteil**, nicht über den Pi |
| 8-Kanal-Relaismodul: Außenlicht (Lichterkette) | GPIO 21 (Pin 40), schaltet bei LOW |
| 8-Kanal-Relaismodul: Laterne (LED-Lämpchen an der Tür) | GPIO 20 (Pin 38), schaltet bei LOW |
| weitere Relais-Eingänge (derzeit frei) | GPIO 12, 13, 16, 19 |
| Relais-Modul VCC / GND | 5 V (Pin 2) / GND (Pin 6) |
| **GND** | Pi, Netzteil und Band brauchen eine gemeinsame Masse |

**Netzteil:** 56 LEDs ziehen bei vollem Weiß bis zu 3,4 A. Mit
`max_helligkeit: 0.1` und Warmweiß sind es real nur ein paar hundert mA. Ein
5-V-Netzteil mit 2 A reicht, dazu am besten ein 1000-µF-Kondensator zwischen
5 V und GND am Bandanfang. Den Pi am besten mit eigenem Netzteil
versorgen.

**Audio:** Das Onboard-Audio des Pi nutzt dieselbe PWM wie GPIO 18 und muss aus
sein (`dtparam=audio=off`). Das trägt `install.sh` selbst ein.

**Relais:** Die meisten Module schalten bei LOW (`active_low: true`). Schaltet
das Licht genau verkehrt herum, in der `config.yaml` auf `false` stellen.

## Raspberry Pi neu aufsetzen

1. Mit dem **Raspberry Pi Imager** *Raspberry Pi OS Lite (64-bit), Bookworm* auf
   den USB-Stick schreiben. Im Imager unter „Einstellungen“ Hostname
   (z. B. `wichtelhaus`), Benutzer, WLAN und **SSH** aktivieren.
2. Stick an den Pi 3B, booten, per SSH verbinden: `ssh <benutzer>@wichtelhaus.local`
3. Installieren:
   ```bash
   sudo apt-get install -y git
   git clone https://github.com/dachart2/wichtelhaus.git
   cd wichtelhaus
   sudo ./install.sh
   sudo reboot
   ```
4. Verkabelung testen (Zonen einzeln, dann Ofen, dann Relais):
   ```bash
   sudo systemctl stop wichtelhaus
   sudo .venv/bin/python -m wichtelhaus --test-hardware
   sudo systemctl start wichtelhaus
   ```
5. Log ansehen: `journalctl -u wichtelhaus -f`

> Der Pi 3B bootet vom USB-Stick nur, wenn das USB-Boot-Bit gesetzt ist. Das
> war bei dir schon so, da er vorher vom Stick lief.

## Konfiguration

Alles steht in [`config.yaml`](config.yaml): Standort, Pins, Anzahl der LEDs,
Zonen, Ofen-LEDs, Temperaturgrenze, Helligkeiten, Farbe, Zeitfenster des
Wichtels und die Abschaltzeit des Außenlichts. Uhrzeiten bitte in
Anführungszeichen schreiben (`"23:30"`). Nach einer Änderung:
`sudo systemctl restart wichtelhaus`.

Den Ofen bilden standardmäßig die LEDs 0–3 am Rand der Küchen-Zone
(`ofen.pixel`). Mit `nur_ofen: true` leuchten sie nie als Deckenlicht.

## Ausprobieren ohne Hardware (PC oder Pi)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/python -m wichtelhaus --sim             # echte Zeit, echtes Wetter
```

Zeitraffer, ein ganzer Tag in 24 Sekunden, mit kaltem Wetter:

```bash
.venv/bin/python -m wichtelhaus --sim --speed 3600 --start "2026-12-01 05:00" --days 1 --temp -3
```

Weitere Optionen:

| Option | Bedeutung |
|---|---|
| `--speed N` | Zeitraffer-Faktor (720 = ein Tag in 2 Minuten) |
| `--start "JJJJ-MM-TT HH:MM"` | simulierte Startzeit |
| `--days N` | nach N simulierten Tagen beenden |
| `--temp N` | Außentemperatur fest vorgeben, z. B. `-3` oder `9` |
| `--seed N` | gleicher Zufall, Lauf wiederholbar |
| `--live` | eine farbige, laufend aktualisierte Statuszeile (Zonen und Ofenflackern) |
| `--no-color` | ohne Farben |
| `--test-hardware` | Zonen, Ofen und Relais nacheinander testen |

Tests: `python -m unittest discover -s tests`

## Aufbau

```
wichtelhaus/
  app.py      Hauptschleife, Licht- und Ofenlogik, Kommandozeile
  wichtel.py  der Wichtel: Tagesplan, Müdigkeit, Aktivitäten, Räume
  sun.py      Sonnenauf-/-untergang (astral), Dunkelheit, Außenlicht
  weather.py  Temperatur von Open-Meteo mit Zwischenspeicher
  fire.py     Feuerflackern
  outputs.py  NeoPixel und Relais, oder Simulation
  config.py   config.yaml laden und prüfen
```

Die früheren Skripte `test.py` und `improved_test.py` (zufällige Wach- und
Schlafzeit) sind in `wichtel.py` aufgegangen (`random_time_between`).

## Backup, damit nichts mehr verloren geht

- **Code:** liegt auf GitHub. Wer am Pi etwas ändert, committet und pusht.
- **Einstellungen:** `config.yaml` liegt im Repo. Lokale Änderungen am Pi
  ebenfalls committen, oder zumindest mit
  `scp <benutzer>@wichtelhaus.local:~/wichtelhaus/config.yaml .` sichern.
- **Ganzer Stick:** Wenn alles läuft, einmal ein Image ziehen. Unter Windows mit
  *Win32 Disk Imager* („Read“), unter Linux mit
  `sudo dd if=/dev/sdX of=wichtelhaus.img bs=4M status=progress`. Mit
  [PiShrink](https://github.com/Drewsif/PiShrink) wird das Image klein. Zum
  Wiederherstellen das Image einfach mit dem Raspberry Pi Imager auf einen
  neuen Stick schreiben.
- **Stick schonen:** USB-Sticks gehen von vielen Schreibzugriffen kaputt. Das
  Programm schreibt nur alle 20 Minuten eine winzige Datei. Wer mehr will,
  schaltet in `raspi-config` → *Performance* → *Overlay File System* das
  Dateisystem schreibgeschützt (dann gehen Änderungen nach einem Neustart
  verloren). Noch besser ist eine kleine SSD statt eines Sticks.
