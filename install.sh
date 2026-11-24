#!/usr/bin/env bash
# Wichtelhaus auf dem Raspberry Pi einrichten: venv, Pakete, Audio aus, systemd-Dienst.
# Aufruf im Projektordner:  sudo ./install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte mit sudo ausführen: sudo ./install.sh" >&2
    exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "==> Projektordner: $DIR"

echo "==> Systempakete"
apt-get update
apt-get install -y python3-venv python3-dev build-essential git

echo "==> Python-Umgebung (.venv) und Bibliotheken"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --upgrade pip
"$DIR/.venv/bin/pip" install -r "$DIR/requirements-pi.txt"

echo "==> Onboard-Audio aus (stört die PWM auf GPIO 18)"
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
REBOOT=0
if grep -qE '^[[:space:]]*dtparam=audio=off' "$CFG"; then
    echo "    schon aus"
else
    cp "$CFG" "$CFG.bak-wichtelhaus"
    if grep -qE '^[[:space:]]*dtparam=audio=on' "$CFG"; then
        sed -i -E 's/^[[:space:]]*dtparam=audio=on/dtparam=audio=off/' "$CFG"
    else
        printf '\n[all]\ndtparam=audio=off\n' >> "$CFG"
    fi
    echo "    in $CFG eingetragen (Sicherung: $CFG.bak-wichtelhaus)"
    REBOOT=1
fi

echo "==> Uhrzeit: Dienst wartet beim Booten auf NTP (der Pi hat keine Echtzeituhr)"
systemctl enable systemd-time-wait-sync.service 2>/dev/null || true

echo "==> systemd-Dienst"
sed "s|@DIR@|$DIR|g" "$DIR/wichtelhaus.service" > /etc/systemd/system/wichtelhaus.service
systemctl daemon-reload
systemctl enable wichtelhaus.service

if [ "$REBOOT" -eq 1 ]; then
    echo
    echo "Fertig. Bitte jetzt neu starten:  sudo reboot"
    echo "Danach startet der Wichtel von selbst. Log:  journalctl -u wichtelhaus -f"
else
    systemctl restart wichtelhaus.service
    echo
    echo "Fertig, der Dienst läuft. Log:  journalctl -u wichtelhaus -f"
fi
