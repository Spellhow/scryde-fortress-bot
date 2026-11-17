"""Privacy-preserving readiness audit for tracked legacy BSOE state.

Counts and named migration blockers only. No content bodies, chat identifiers,
tokens, URLs, clan names or usernames ever appear in a report.
This does not migrate or rewrite any files.
"""
from collections import Counter
import json


SECTIONS = ("fortress", "castle", "our_fortress_attacks", "our_castle_attacks",
            "news", "forum_news", "meta")
ACTIVE_MODERATION = {"pending", "approved"}


def _state_dict(data, key):
    section=data.get(key)
    if not isinstance(section, dict):
        raise ValueError("legacy state has missing or invalid sections")
    return section


def analyze_legacy_state(data):
    if not isinstance(data, dict):
        raise ValueError("legacy state must be a JSON object")
    sections={name:_state_dict(data,name) for name in SECTIONS}
    result={
        "format": "legacy-bsoe-read-only-preflight-v1",
        "tracked_objects": {},
        "registered_attacks": {},
        "news_queues": {},
        "recent_siege_dedupe_keys": 0,
        "telegram_callback_offset_present": False,
        "migration_ready": False,
        "blockers": [],
    }
    for name in ("fortress","castle"):
        section=sections[name]
        tracked=section.get("objects",{})
        if not isinstance(tracked,dict):
            raise ValueError("malformed legacy object index")
        active=sum(1 for item in tracked.values() if isinstance(item,dict) and item.get("had") is True)
        malformed=sum(1 for item in tracked.values() if not isinstance(item,dict))
        result["tracked_objects"][name]={
            "entries":len(tracked),
            "previously_owned":active,
            "invalid_entries":malformed,
        }
        if malformed:
            result["blockers"].append("invalid_rank_tracking_data")
        if section.get("had") is True and not tracked:
            result["blockers"].append("legacy_flat_object_state_requires_import")
    for name in ("our_fortress_attacks","our_castle_attacks"):
        result["registered_attacks"][name]=len(sections[name])
    for name in ("news","forum_news"):
        section=sections[name]
        pending=section.get("pending",[])
        sent_ids=section.get("sent_ids",[])
        if not isinstance(pending,list) or not isinstance(sent_ids,list):
            raise ValueError("legacy news queues must be arrays")
        counts=Counter(
            (item.get("status", "unknown")
             if isinstance(item.get("status", "unknown"), str) else "invalid")
            if isinstance(item, dict) else "invalid"
            for item in pending
        )
        result["news_queues"][name]={
            "items":len(pending),
            "active_moderation":sum(counts.get(status,0) for status in ACTIVE_MODERATION),
            "previously_published":counts.get("published",0),
            "expired":counts.get("expired",0),
            "other_or_invalid":sum(value for status,value in counts.items()
                                   if status not in (ACTIVE_MODERATION|{"published","expired"})),
            "sent_source_ids":len(sent_ids),
            "has_last_seen_cursor":type(section.get("last_seen_id")) is int,
        }
        if any(status in ACTIVE_MODERATION for status in counts):
            result["blockers"].append("pending_moderation_requires_compatible_gateway")
        if sent_ids or section.get("last_seen_id"):
            result["blockers"].append("legacy_publication_ids_need_transition_map")
    meta=sections["meta"]
    alerts=meta.get("last_alerts",{})
    if not isinstance(alerts,dict):
        raise ValueError("malformed legacy deduplication cache")
    result["recent_siege_dedupe_keys"]=len(alerts)
    result["telegram_callback_offset_present"]=bool(meta.get("tg_update_offset"))
    if result["telegram_callback_offset_present"]:
        result["blockers"].append("callback_offset_requires_moderation_compatibility")
    if result["registered_attacks"]["our_fortress_attacks"] or result["registered_attacks"]["our_castle_attacks"]:
        result["blockers"].append("tracked_outbound_attacks_require_exact_timers")
    if sum(item["previously_owned"] for item in result["tracked_objects"].values()):
        result["blockers"].append("active_ownership_requires_side_by_side_replay")
    # The current Community Bot lacks the full legacy moderation/event state
    # machine; a silent state import would risk duplicate messages or loss.
    result["blockers"].append("legacy_bsoe_full_parity_not_verified")
    result["blockers"]=sorted(set(result["blockers"]))
    return result
