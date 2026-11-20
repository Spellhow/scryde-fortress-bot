"""Offline GitHub-only destination credential checks.

Reports environment *variable names*, never values, chat IDs, bot tokens,
or webhook URLs. This checks presence and webhook URL shape only; actual
permissions must be confirmed by an explicitly authorized delivery probe.
"""
from .publishers import _official_discord_webhook


def active_destination_ids(config):
    """Only targets with at least one potentially active source/schedule."""
    world_sources = {
        (source.world.identity, source.id)
        for source in config.sources if source.enabled
    }
    worlds_with_schedules = {
        schedule.world.identity
        for schedule in config.schedules if schedule.enabled
    }
    active = set()
    for sub in config.subscriptions:
        matches_source = any(
            identity == sub.world.identity
            and (not sub.source_ids or source_id in sub.source_ids)
            for identity, source_id in world_sources
        )
        matches_schedule = (
            sub.world.identity in worlds_with_schedules
            and (not sub.source_ids or "manual_schedule" in sub.source_ids)
            and (not sub.event_types or "event_reminder" in sub.event_types)
        )
        if matches_source or matches_schedule:
            active.add(sub.destination_id)
    return active


def check_credentials(config, credential_env):
    """Return (active_targets_count, issues), never inspecting remote APIs."""
    active = active_destination_ids(config)
    issues = []
    for alias in sorted(active):
        destination = config.destinations[alias]
        address = credential_env.get(destination.address_env, "")
        if not isinstance(address, str) or not address.strip():
            issues.append((destination.address_env, "missing"))
        elif destination.kind == "discord":
            try:
                valid = _official_discord_webhook(address)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                issues.append((destination.address_env, "invalid Discord webhook URL"))
        elif any(ord(char) < 32 or ord(char) == 127 for char in address):
            issues.append((destination.address_env, "invalid Telegram address"))
        if destination.kind == "telegram":
            if not destination.token_env:
                issues.append(("token_env", "missing Telegram token reference"))
                continue
            token = credential_env.get(destination.token_env, "")
            if not isinstance(token, str) or not token.strip():
                issues.append((destination.token_env, "missing"))
            elif any(ord(char) < 32 or ord(char) == 127 for char in token):
                issues.append((destination.token_env, "invalid Telegram token"))
    return len(active), tuple(issues)
