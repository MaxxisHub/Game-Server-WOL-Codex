WOL Proxy für Game-Server (Minecraft & Satisfactory)

Überblick
- Ziel: Ein leichtgewichtiger, robuster WOL-Proxy für ARM‑Single‑Board‑Computer (z. B. ASUS Tinker Board S mit Armbian), der die IP deines Game-Servers übernimmt, Anfragen auf Minecraft/Satisfactory abfängt, bei Bedarf per Wake‑on‑LAN (WOL) den eigentlichen Game‑Server startet und die IP wieder freigibt.
- Verhalten:
  - Wenn der Game‑Server aus ist: Das Board übernimmt dessen IP und lauscht auf den konfigurierten Ports.
  - Satisfactory: Startet den Server bereits, wenn die Serverliste geöffnet wird (UDP‑Anfrage erkannt).
  - Minecraft: Startet erst bei einem echten Join‑Versuch. In der Serverliste wird ein konfigurierbares MOTD angezeigt (z. B. „Join to start Server“). Nach einem Join‑Versuch wechselt das MOTD zu „Starting…“. Der Client erhält beim Join einen freundlichen Hinweis: „Server is starting please try again in 60 seconds“.
  - Nach dem Senden des WOL‑Pakets wird die IP sofort wieder freigegeben, damit der echte Game‑Server sie übernehmen kann.
  - Während der echte Game‑Server läuft, pingt der Proxy zyklisch. Fällt der Server später wieder aus, übernimmt das Board erneut die IP und lauscht wieder.
- Ressourcen: Minimal (Python 3, keine externen Python‑Abhängigkeiten), läuft als systemd‑Service.

Features
- IP‑Übernahme via `ip addr add/del` und ARP‑Ankündigung (`arping`) für sauberen Failover.
- Wake‑on‑LAN Magic Packet (Broadcast) mit MAC aus der Konfiguration.
- Minimaler Minecraft‑Protokoll‑Support für Status/Handshake/Login‑Disconnect, um MOTD/Version zu setzen und Join‑Versuche sauber abzufangen.
- Satisfactory‑Trigger über UDP‑Ports (Default 15000/15777/7777). Bereits eine Anfrage startet den Server.
- Automatische Erkennung des Netzwerk‑Interfaces für die Ziel‑IP.
- Einfache Web‑Ersteinrichtung (lokale Mini‑GUI) auf Port 8090, wenn keine Konfiguration vorhanden ist.
- systemd‑Service für Autostart nach Powerloss.

Unterstützte Plattform
- Getestet für Armbian/Debian‑ähnliche Systeme auf ARM‑SBCs (z. B. ASUS Tinker Board S). Sollte generell auf Linux funktionieren.

Schnellstart
1) Installation
   - Voraussetzungen: Root/Rechte für systemd, Internet für Paketinstallation.
   - Klone dieses Repo auf dein Board und installiere:
     ```bash
     git clone https://github.com/<dein-account>/wol-proxy.git
     cd wol-proxy
     sudo ./install.sh
     ```

2) Ersteinrichtung (Terminal‑Setup)
   - Nach der Installation startet automatisch ein Terminal‑Wizard (curses‑TUI) zur Ersteinrichtung.
   - Alternativ jederzeit manuell ausführen:
     ```bash
     sudo wol-proxy-setup
     ```
   - Eingaben:
     - Game‑Server IP (z. B. 192.168.1.50) und MAC (WOL)
     - Minecraft‑Port (Default 25565) und MOTD‑Texte
     - Satisfactory‑Ports (Default 15000/15777/7777)
     - Optional: CIDR automatisch erkennen (Taste „D“) oder manuell festlegen
   - Nach dem Speichern übernimmt der Dienst automatisch die Konfiguration.

3) Service steuern
   ```bash
   sudo systemctl status wol-proxy
   sudo systemctl restart wol-proxy
   sudo journalctl -u wol-proxy -f
   ```

Konfiguration
- Datei: `/opt/wol-proxy/config.json` (wird über die GUI erzeugt/aktualisiert). Beispiel:
```json
{
  "game_server_ip": "192.168.1.50",
  "game_server_mac": "AA:BB:CC:DD:EE:FF",
  "net_cidr": 24,
  "mc_port": 25565,
  "mc_motd_idle": "Join to start Server",
  "mc_motd_starting": "Starting...",
  "mc_version_label": "Offline",
  "satisfactory_ports": [15000, 15777, 7777],
  "ping_interval_sec": 3,
  "ping_fail_threshold": 10
}
```
- `net_cidr` wird in der Regel automatisch ermittelt. Bei Spezial‑Setups ggf. anpassen.

Funktionsweise (High‑Level)
- Boot → Service startet → Falls `config.json` fehlt, wartet der Dienst auf eine Konfiguration. TUI starten mit `sudo wol-proxy-setup`.
- Mit Konfiguration:
  - Prüfe, ob der echte Game‑Server erreichbar ist (Ping/TCP‑Check). Wenn nein:
    - Übernehme dessen IP (als Secondary auf dem gefundenen Interface) und kündige per ARP an.
    - Starte Listener:
      - Minecraft TCP auf `mc_port`: antwortet auf Status‑Pings mit MOTD/Version, triggert bei Login‑Start WOL, sendet freundliche Disconnect‑Nachricht und gibt IP sofort frei.
      - Satisfactory UDP auf konfigurierten Ports: jeder eingehende Query triggert WOL und gibt IP sofort frei.
  - Während „Startphase“ wird regelmäßig geprüft, ob der echte Server läuft. Sobald er erreichbar ist, bleibt die IP freigegeben und der Proxy lauscht nicht mehr.
  - Fällt der Server später wieder aus (mehrere Pings fehlgeschlagen): IP erneut übernehmen und Proxies starten.

Sicherheit & Hinweise
- Der Dienst verwaltet IP‑Adressen und lauscht auf privilegierten Ports → läuft als root. Code ist minimal gehalten und protokolliert Aktionen.
- Wake‑on‑LAN setzt WOL‑Support im BIOS/NIC des Game‑Servers voraus.
- IP‑Übernahme setzt voraus, dass der Game‑Server wirklich aus ist, um Doppelbelegung zu vermeiden.

Deinstallation
```bash
sudo ./uninstall.sh
```

Entwicklung
- Code in `src/wol_proxy`. Keine externen Python‑Abhängigkeiten.
- Starte lokal (nicht als Service) für Tests:
  ```bash
  sudo python3 -m src.wol_proxy.main --foreground --config ./config.json
  ```

Lizenz
- Bitte nach Bedarf ergänzen. Standardmäßig ohne Lizenz.
