"""LCU (League Client Update) API helper for the auto-pick tool.

The running League client exposes a local REST API on 127.0.0.1, secured with
a self-signed certificate and HTTP Basic auth. The port and auth token are
published two ways:

  * in the LeagueClientUx process command line
    (--app-port=… / --remoting-auth-token=…), and
  * in a `lockfile` inside the install directory
    (name:pid:port:password:protocol).

We inspect the process first because that works no matter where League is
installed, and fall back to a few well-known lockfile locations.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests
import urllib3

# The client uses a self-signed cert; silence the resulting warning noise.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROCESS_NAMES = ("LeagueClientUx.exe", "LeagueClientUx")

# Fallback lockfile locations if the process can't be inspected (e.g. no psutil).
LOCKFILE_CANDIDATES = [
    Path(r"C:/Riot Games/League of Legends/lockfile"),
    Path(r"D:/Riot Games/League of Legends/lockfile"),
    Path.home() / "Riot Games/League of Legends/lockfile",
]


def _normalize(name):
    """Lower-case and strip punctuation so 'Kai'Sa' and 'kaisa' match.

    Null-safe: some champion-summary entries carry a null alias, and feeding
    that to the matcher must not blow up the whole champion load.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _credentials_from_process():
    """Return (port, token) by reading the LeagueClientUx command line."""
    try:
        import psutil
    except ImportError:
        return None
    for proc in psutil.process_iter(["name", "cmdline"]):
        if (proc.info.get("name") or "") not in PROCESS_NAMES:
            continue
        cmdline = " ".join(proc.info.get("cmdline") or [])
        port = re.search(r"--app-port=(\d+)", cmdline)
        token = re.search(r"--remoting-auth-token=([\w-]+)", cmdline)
        if port and token:
            return int(port.group(1)), token.group(1)
    return None


def _credentials_from_lockfile():
    """Return (port, token) from the first readable lockfile."""
    for path in LOCKFILE_CANDIDATES:
        try:
            text = path.read_text()
        except OSError:
            continue
        parts = text.strip().split(":")
        if len(parts) >= 5:                       # name:pid:port:password:proto
            return int(parts[2]), parts[3]
    return None


class LCU:
    """Thin wrapper around the local League client REST API."""

    def __init__(self, port, token):
        self.port = port
        self.token = token
        self.base = f"https://127.0.0.1:{port}"
        self.session = requests.Session()
        self.session.auth = ("riot", token)       # username is always "riot"
        self.session.verify = False               # self-signed local cert
        self.session.headers["Accept"] = "application/json"

    @classmethod
    def connect(cls):
        """Find a running client and return an LCU, or None if none is up."""
        creds = _credentials_from_process() or _credentials_from_lockfile()
        return cls(*creds) if creds else None

    # --- low-level --------------------------------------------------------- #
    def get(self, path):
        return self.session.get(self.base + path, timeout=5)

    def post(self, path, json=None):
        return self.session.post(self.base + path, json=json, timeout=5)

    def patch(self, path, json=None):
        return self.session.patch(self.base + path, json=json, timeout=5)

    def delete(self, path):
        return self.session.delete(self.base + path, timeout=5)

    # --- high-level helpers ------------------------------------------------ #
    def gameflow_phase(self):
        """Current phase, e.g. 'Lobby', 'ReadyCheck', 'ChampSelect', 'InProgress'."""
        r = self.get("/lol-gameflow/v1/gameflow-phase")
        return r.json() if r.ok else None          # endpoint returns a JSON string

    def champion_list(self):
        """Return [{id, name, alias}] for every champion, sorted by name."""
        r = self.get("/lol-game-data/assets/v1/champion-summary.json")
        r.raise_for_status()
        champs = [
            {"id": c["id"], "name": c["name"], "alias": c.get("alias") or c["name"]}
            for c in r.json()
            if c.get("id", -1) >= 0                 # id -1 is the "None" placeholder
        ]
        return sorted(champs, key=lambda c: c["name"])

    def ready_check(self):
        r = self.get("/lol-matchmaking/v1/ready-check")
        return r.json() if r.ok else None

    def accept_ready_check(self):
        return self.post("/lol-matchmaking/v1/ready-check/accept")

    def champ_select_session(self):
        r = self.get("/lol-champ-select/v1/session")
        return r.json() if r.ok else None

    def pickable_champion_ids(self):
        """Champions the local player can pick right now (excludes bans/taken/unowned)."""
        r = self.get("/lol-champ-select/v1/pickable-champion-ids")
        return set(r.json()) if r.ok else set()

    def bannable_champion_ids(self):
        """Champions the local player can ban right now (excludes already-banned)."""
        r = self.get("/lol-champ-select/v1/bannable-champion-ids")
        return set(r.json()) if r.ok else set()

    def hover_champion(self, action_id, champion_id):
        """Declare intent without locking (completed stays false)."""
        return self.patch(
            f"/lol-champ-select/v1/session/actions/{action_id}",
            json={"championId": champion_id},
        )

    def complete_action(self, action_id, champion_id):
        """Lock a pick or confirm a ban (sets completed=true)."""
        return self.patch(
            f"/lol-champ-select/v1/session/actions/{action_id}",
            json={"championId": champion_id, "completed": True},
        )

    def champion_icon(self, champion_id):
        """Return the PNG bytes of a champion's square portrait, or None."""
        r = self.get(f"/lol-game-data/assets/v1/champion-icons/{champion_id}.png")
        return r.content if r.ok else None

    # --- lobby / matchmaking (auto-start) ---------------------------------- #
    def lobby(self):
        r = self.get("/lol-lobby/v2/lobby")
        return r.json() if r.ok else None

    def available_queues(self):
        """All game queues with their id, gameMode and queueAvailability."""
        r = self.get("/lol-game-queues/v1/queues")
        return r.json() if r.ok else []

    def create_lobby(self, queue_id):
        """Open (or switch to) a lobby for the given queue id."""
        return self.post("/lol-lobby/v2/lobby", json={"queueId": queue_id})

    def start_matchmaking(self):
        return self.post("/lol-lobby/v2/lobby/matchmaking/search")

    def stop_matchmaking(self):
        return self.delete("/lol-lobby/v2/lobby/matchmaking/search")

    def friends(self):
        """Friends list; entries carry summonerId, name/gameName and availability."""
        r = self.get("/lol-chat/v1/friends")
        return r.json() if r.ok else []

    def invite(self, summoner_ids):
        body = [{"toSummonerId": sid} for sid in summoner_ids]
        return self.post("/lol-lobby/v2/lobby/invitations", json=body)

    def received_invitations(self):
        r = self.get("/lol-lobby/v2/received-invitations")
        return r.json() if r.ok else []

    def accept_invitation(self, invitation_id):
        return self.post(
            f"/lol-lobby/v2/received-invitations/{invitation_id}/accept")
