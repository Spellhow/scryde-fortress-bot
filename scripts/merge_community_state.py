#!/usr/bin/env python3
"""Conservative, offline three-way merge of public Community Bot state."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from community.state import DeliveryState, MAX_DELIVERIES, SCHEMA_VERSION

class StateMergeConflict(ValueError):
    """Ambiguous concurrent source-cursor edits. Never guess a siege state."""

_MISSING = object()

def merge_states(base, ours, theirs):
    base = DeliveryState.from_dict(base)
    ours = DeliveryState.from_dict(ours)
    theirs = DeliveryState.from_dict(theirs)
    delivered = dict(base.delivered)
    for state in (ours, theirs):
        for key, at in state.delivered.items():
            if not isinstance(key, str) or not key:
                raise ValueError("invalid delivery ID")
            delivered[key] = max(delivered.get(key, at), at)
    if len(delivered) > MAX_DELIVERIES:
        delivered = dict(sorted(delivered.items(), key=lambda pair: (pair[1], pair[0]))[-MAX_DELIVERIES:])
    cursors = {}
    for key in base.cursors.keys() | ours.cursors.keys() | theirs.cursors.keys():
        old = base.cursors.get(key, _MISSING)
        local = ours.cursors.get(key, _MISSING)
        remote = theirs.cursors.get(key, _MISSING)
        if local == remote:
            merged = local
        elif local == old:
            merged = remote
        elif remote == old:
            merged = local
        else:
            raise StateMergeConflict("conflicting source cursors")
        if merged is not _MISSING:
            cursors[key] = merged
    return {"schema_version": SCHEMA_VERSION, "delivered": delivered, "cursors": cursors}

def main():
    parser = argparse.ArgumentParser()
    for name in ("base", "ours", "theirs", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = merge_states(*(json.loads(getattr(args, name).read_text(encoding="utf8")) for name in ("base", "ours", "theirs")))
        args.output.write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False)+"\n", encoding="utf8")
    except (ValueError, TypeError, OSError) as exc:
        print("Community state merge refused ({})".format(type(exc).__name__),file=sys.stderr)
        return 1
    print("Community state reconciled")
    return 0

if __name__ == "__main__":
    sys.exit(main())
