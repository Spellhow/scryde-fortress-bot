"""L2Dex castle owner and siege-registration change tracker.

Only compares information publicly visible in the castle ranking table.
A missing row, missing owner, or ambiguous data never means a castle was lost.
The displayed local siege time has no verified timezone and remains a string.
"""
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import json
import re

from community.models import Event, Provenance, World, digest


@dataclass(frozen=True)
class Castle:
    identifier: str
    name: str
    owner: str
    leader: str
    siege_display: str
    attackers: tuple[str, ...]
    defenders: tuple[str, ...]


class _CastleTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.region = False
        self.table = False
        self.finished = False
        self.row = None
        self.cell = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "div" and attributes.get("id") == "tab-top_castle":
            self.region = True
        elif tag == "table" and self.region and not self.finished:
            self.table = True
        elif tag == "tr" and self.table:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).replace("\xa0", " ").strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table:
            self.table = False
            self.region = False
            self.finished = True


def _label(text, name):
    match = re.search(r"(?:^|\n)\s*" + re.escape(name) + r":[^\S\n]*([^\n]*)", text, re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _has_label(text, name):
    """Distinguish a missing source field from a genuine empty/- value."""
    return bool(re.search(
        r"(?:^|\n)\s*" + re.escape(name) + r":",
        text, re.I,
    ))


def _clans(text, label):
    value = _label(text, label)
    if value in ("", "-", "—"):
        return ()
    # The site currently shows comma-separated registered clans. Revisit the
    # fixture if its markup changes; never synthesize clans from image crests.
    return tuple(sorted({part.strip() for part in re.split(r"[,;|]", value) if part.strip() and part.strip() != "-"}))


def parse_castles(html_text: str) -> dict[str, Castle]:
    if not isinstance(html_text, str) or len(html_text) > 2_000_000:
        raise ValueError("invalid L2Dex HTML size")
    table = _CastleTable()
    table.feed(html_text)
    if not table.finished or not table.rows:
        raise ValueError("L2Dex castles table was not found")
    headings = [re.sub(r"\s+", " ", value).lower() for value in table.rows[0]]
    if headings[:6] != ["id", "picture", "name", "info", "date", "siege"]:
        raise ValueError("L2Dex castle table schema changed")
    castles = {}
    for row in table.rows[1:]:
        if len(row) < 6:
            continue
        identifier, _, name, info, display, siege = row[:6]
        if not identifier.isdecimal() or not name or not name.lower().endswith("castle"):
            continue
        if identifier in castles:
            raise ValueError("duplicate castle ID")
        # A partially loaded row missing its Clan/Attackers field is NOT
        # evidence of a changed owner or a withdrawn siege registration.
        # In particular, interpreting missing Attackers as an empty set
        # would invent a new registration when that field reappears.
        # A present but blank or dash value still means observed no attackers.
        if not _has_label(info, "Clan") or not _has_label(siege, "Attackers"):
            continue
        castles[identifier] = Castle(
            identifier=identifier, name=name,
            owner=("" if _label(info, "Clan") in ("-", "—") else _label(info, "Clan")),
            leader=_label(info, "Leader"),
            siege_display=re.sub(r"\s+", " ", display).strip(),
            attackers=_clans(siege, "Attackers"),
            defenders=_clans(siege, "Defenders"),
        )
    if not castles:
        raise ValueError("L2Dex returned no valid castles")
    return castles


def state_key(source_id: str, world: World, url: str = "") -> str:
    """A new ranking URL is a new baseline, never a false castle transfer.

    Empty URL preserves the helper's legacy two-argument call in tests; the
    live runner always provides the verified, configured URL.
    """
    return "l2dex-castles:" + digest([source_id, world.identity, url])


def load_snapshot(data: str | None) -> dict:
    if data is None:
        return {}
    decoded = json.loads(data)
    if not isinstance(decoded, dict) or decoded.get("version") != 1:
        raise ValueError("unsupported L2Dex snapshot version")
    castles = decoded.get("castles")
    if not isinstance(castles, dict):
        raise ValueError("invalid L2Dex snapshot")
    for key, value in castles.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError("invalid L2Dex castle state")
        if not isinstance(value.get("owner"), str):
            raise ValueError("invalid L2Dex castle owner")
        if not isinstance(value.get("attackers"), list) or any(not isinstance(n, str) for n in value["attackers"]):
            raise ValueError("invalid L2Dex attackers")
        if type(value.get("owner_generation", 0)) is not int or type(value.get("attack_generation", 0)) is not int:
            raise ValueError("invalid L2Dex state generation")
    return castles


def diff_castles(previous: dict | None, current: dict[str, Castle], source, now: datetime):
    """Return (observed events, JSON state); callers commit state only after delivery.

    The first observation establishes a baseline with zero notifications.
    Missing castles are retained rather than treated as a loss.
    """
    if now.utcoffset() is None:
        raise ValueError("now must include timezone")
    baseline = previous is None
    previous_castles = load_snapshot(previous)
    updated = {key: dict(value) for key, value in previous_castles.items()}
    events = []
    for identifier, castle in sorted(current.items(), key=lambda pair: int(pair[0])):
        old = previous_castles.get(identifier)
        owner = castle.owner or (old.get("owner", "") if old else "")
        old_owner = old.get("owner", "") if old else ""
        owner_gen = old.get("owner_generation", 0) if old else 0
        attack_gen = old.get("attack_generation", 0) if old else 0
        past_attackers = set(old.get("attackers", [])) if old else set()
        new_attackers = set(castle.attackers)
        # A missing/incomplete owner is not evidence of transfer. Likewise,
        # adding a newly listed castle is baseline discovery, not a conquest.
        if old and old_owner and castle.owner and old_owner.casefold() != castle.owner.casefold():
            owner_gen += 1
            events.append(Event(
                world=source.world, source_id=source.id,
                external_id=f"castle:{identifier}:owner:{owner_gen}",
                kind="castle_owner_change",
                title=f"{castle.name}: owner changed",
                body=f"Observed owner change: {old_owner} → {castle.owner}. "
                     f"Siege date displayed by L2Dex: {castle.siege_display or 'not shown'} "
                     "(timezone not specified).",
                source_url=source.url, provenance=Provenance.OBSERVED,
                observed_at=now, clan=castle.owner, object_name=castle.name,
            ))
        additions = sorted(new_attackers - past_attackers)
        if old and additions:
            attack_gen += 1
            events.append(Event(
                world=source.world, source_id=source.id,
                external_id=f"castle:{identifier}:attack-registration:{attack_gen}",
                kind="siege_registration",
                title=f"{castle.name}: new siege registration",
                body=f"New attackers listed: {', '.join(additions)}. "
                     f"Owner currently listed: {owner or 'unknown'}. "
                     f"Scheduled siege displayed as {castle.siege_display or 'unknown'} "
                     "(timezone not specified). This is a registration, not a live attack.",
                source_url=source.url, provenance=Provenance.OBSERVED,
                observed_at=now, clan=owner or None, object_name=castle.name,
            ))
        updated[identifier] = {
            "name": castle.name, "owner": owner,
            "attackers": sorted(new_attackers), "defenders": list(castle.defenders),
            "siege_display": castle.siege_display,
            "owner_generation": owner_gen, "attack_generation": attack_gen,
        }
    # Marker may be committed even when no subscriptions exist; it prevents
    # repeated baseline discovery. Do not use wall-clock as an event ID.
    encoded = json.dumps({"version": 1, "castles": updated}, ensure_ascii=False, sort_keys=True)
    return ([] if baseline else events), encoded
