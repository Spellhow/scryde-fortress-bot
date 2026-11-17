"""Safe legacy state inventory with fabricated private content."""
import contextlib
import copy
import io
import json
import tempfile
from pathlib import Path
import unittest

from community.legacy_preflight import analyze_legacy_state
from scripts.legacy_state_preflight import main


PRIVATE="NEVER-PRINT-CHAT-ID-OR-PRIVATE-API-KEY"


def sample():
    return {
        "fortress":{
            "had":True,"id":116,"name":PRIVATE,
            "objects":{"116":{"had":True,"name":PRIVATE,"id":116}},
        },
        "castle":{"had":False,"objects":{}},
        "our_fortress_attacks":{"another":{"name":PRIVATE,"siege_at":1920000000}},
        "our_castle_attacks":{},
        "news":{
            "last_seen_id":999,"sent_ids":[1,2,3],
            "pending":[
                {"post_id":1,"status":"pending","text":PRIVATE},
                {"post_id":2,"status":"approved","text":PRIVATE},
                {"post_id":3,"status":"published","text":PRIVATE},
                {"post_id":4,"status":"expired","text":PRIVATE},
            ],
        },
        "forum_news":{
            "last_seen_id":100,"sent_ids":[5],
            "pending":[{"post_id":5,"status":"cancelled","text":PRIVATE}],
            "wiki_title":PRIVATE,
        },
        "meta":{"last_alerts":{"fortress:a":1920000000},
                "tg_update_offset":99900000,
                "sensitive_debug_text":PRIVATE},
    }


class LegacyStatePreflightTests(unittest.TestCase):
    def test_report_is_counts_only_and_has_explicit_cutover_blockers(self):
        data=sample()
        before=copy.deepcopy(data)
        report=analyze_legacy_state(data)
        self.assertFalse(report["migration_ready"])
        self.assertEqual(before,data)
        self.assertEqual(1,report["tracked_objects"]["fortress"]["previously_owned"])
        self.assertEqual(1,report["registered_attacks"]["our_fortress_attacks"])
        self.assertEqual(2,report["news_queues"]["news"]["active_moderation"])
        self.assertEqual(1,report["recent_siege_dedupe_keys"])
        self.assertIn("legacy_bsoe_full_parity_not_verified",report["blockers"])
        self.assertIn("pending_moderation_requires_compatible_gateway",report["blockers"])
        self.assertIn("legacy_publication_ids_need_transition_map",report["blockers"])
        self.assertNotIn(PRIVATE,json.dumps(report))
        self.assertNotIn("tg_update_offset",str(report))

    def test_empty_legacy_state_still_does_not_authorize_auto_cutover(self):
        data=sample()
        data["fortress"]={"had":False,"objects":{}}
        data["our_fortress_attacks"]={}
        data["news"]={"last_seen_id":0,"pending":[],"sent_ids":[]}
        data["forum_news"]={"last_seen_id":0,"pending":[],"sent_ids":[]}
        data["meta"]={"last_alerts":{},"tg_update_offset":0}
        report=analyze_legacy_state(data)
        self.assertEqual(["legacy_bsoe_full_parity_not_verified"],report["blockers"])
        self.assertFalse(report["migration_ready"])

    def test_schema_failures_are_handled_and_never_show_source(self):
        for data in ([],{},{"fortress":PRIVATE}):
            with self.subTest(data=type(data).__name__),self.assertRaises(ValueError):
                analyze_legacy_state(data)

    def test_invalid_pending_status_is_anonymized(self):
        data=sample()
        data["news"]["pending"].append({"status":["not-hashable"],"text":PRIVATE})
        report=analyze_legacy_state(data)
        self.assertEqual(1,report["news_queues"]["news"]["other_or_invalid"])
        self.assertNotIn(PRIVATE,str(report))

    def test_cli_dry_run_outputs_only_counts_and_never_edits_source(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"legacy-private.json"
            before=json.dumps(sample(),ensure_ascii=False)
            source.write_text(before,encoding="utf8")
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                result=main(["--source",str(source)])
            self.assertEqual(0,result)
            report=json.loads(out.getvalue())
            self.assertFalse(report["migration_ready"])
            self.assertEqual(before,source.read_text(encoding="utf8"))
            self.assertNotIn(PRIVATE,out.getvalue())
            self.assertNotIn("99900000",out.getvalue())
            self.assertEqual([source.name],list(map(lambda p:p.name,Path(td).iterdir())))

    def test_fail_on_blockers_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"state.json"
            source.write_text(json.dumps(sample()),encoding="utf8")
            with contextlib.redirect_stdout(io.StringIO()):
                rc=main(["--source",str(source),"--fail-on-blockers"])
            self.assertEqual(1,rc)

    def test_cli_malformed_json_does_not_expose_contents(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"state.json"
            source.write_text("{"+PRIVATE,encoding="utf8")
            out=io.StringIO()
            with contextlib.redirect_stderr(out):
                rc=main(["--source",str(source)])
            self.assertEqual(2,rc)
            self.assertNotIn(PRIVATE,out.getvalue())


if __name__=="__main__":
    unittest.main()
