"""Real local Git bare-repo races; no network, no production state."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from community.state import DeliveryState
from scripts.merge_community_state import merge_states, StateMergeConflict

ROOT=Path(__file__).resolve().parent
EMPTY={"schema_version":1,"delivered":{},"cursors":{}}

def git(path,*args):
    proc=subprocess.run(["git",*args],cwd=path,check=True,capture_output=True,text=True)
    return proc.stdout.strip()

def state(delivered=None,cursors=None):
    return {"schema_version":1,"delivered":delivered or {},"cursors":cursors or {}}


class StateMergeTests(unittest.TestCase):
    def test_different_receipts_are_unioned_without_mutation(self):
        base=state(delivered={"a":1},cursors={"warm:x":"initialized"})
        ours=state(delivered={"a":1,"b":2},cursors={"warm:x":"initialized"})
        theirs=state(delivered={"a":1,"c":3},cursors={"warm:x":"initialized"})
        expected={"a":1,"b":2,"c":3}
        result=merge_states(base,ours,theirs)
        self.assertEqual(expected,result["delivered"])
        self.assertEqual({"a":1},base["delivered"])
        self.assertEqual("initialized",result["cursors"]["warm:x"])

    def test_same_receipt_keeps_latest_ack(self):
        self.assertEqual(10,merge_states(state(),state({"one":5}),state({"one":10}))["delivered"]["one"])

    def test_remote_only_cursor_edit_is_preserved(self):
        merged=merge_states(state(),state({"local":1}),state(cursors={"health:abc":"{safe}"}))
        self.assertEqual("{safe}",merged["cursors"]["health:abc"])

    def test_ambiguous_castle_cursor_changes_fail_closed(self):
        old=state(cursors={"l2dex:castle":"snapshotA"})
        ours=state(cursors={"l2dex:castle":"snapshotB"})
        theirs=state(cursors={"l2dex:castle":"snapshotC"})
        with self.assertRaises(StateMergeConflict):
            merge_states(old,ours,theirs)

    def test_different_cursor_edits_merge(self):
        old=state(cursors={"warm:x":"initialized","health:y":"100"})
        ours=state(cursors={"warm:x":"initialized","health:y":"120"})
        theirs=state(cursors={"warm:x":"initialized","health:y":"100","health:z":"90"})
        result=merge_states(old,ours,theirs)
        self.assertEqual({"warm:x":"initialized","health:y":"120","health:z":"90"},result["cursors"])

    def test_unknown_schema_is_not_silently_merged(self):
        with self.assertRaises(ValueError):
            merge_states({"schema_version":2,"delivered":{},"cursors":{}},state(),state())


class GitStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="l2-state-git-")
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.remote=self.base/"remote.git"
        self.a=self.base/"a"
        self.b=self.base/"b"
        git(self.base,"init","--bare","--initial-branch=master",str(self.remote))
        git(self.base,"clone",str(self.remote),str(self.a))
        git(self.a,"checkout","-b","master")
        for working in (self.a,):
            git(working,"config","user.email","test@example.invalid")
            git(working,"config","user.name","Unit Test")
        for relative in ("ops/persist_community_state.sh","scripts/merge_community_state.py"):
            target=self.a/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/relative,target)
        (self.a/"README").write_text("base\n",encoding="utf8")
        (self.a/"community_deliveries.json").write_text(json.dumps(EMPTY),encoding="utf8")
        git(self.a,"add",".")
        git(self.a,"commit","-m","initial")
        git(self.a,"push","-u","origin","master")
        git(self.base,"clone",str(self.remote),str(self.b))
        git(self.b,"config","user.email","test@example.invalid")
        git(self.b,"config","user.name","Unit Test")

    def save(self,working,contents):
        (working/"community_deliveries.json").write_text(json.dumps(contents)+"\n",encoding="utf8")

    def update_remote(self,contents,README=None):
        self.save(self.b,contents)
        if README:
            (self.b/"README").write_text(README,encoding="utf8")
        git(self.b,"add",".")
        git(self.b,"commit","-m","external change")
        git(self.b,"push","origin","master")

    def persist(self):
        env=dict(os.environ,STATE_PUSH_MAX_ATTEMPTS="1",PYTHONPATH=str(ROOT))
        return subprocess.run(
            ["bash","ops/persist_community_state.sh"],cwd=self.a,
            capture_output=True,text=True,env=env
        )

    def remote_state(self):
        git(self.a,"fetch","origin","master")
        return json.loads(git(self.a,"show","origin/master:community_deliveries.json"))

    def test_concurrent_distinct_receipts_and_unrelated_code_update(self):
        self.save(self.a,state(delivered={"receiptA":111}))
        self.update_remote(state(delivered={"receiptB":222}),README="remote code update\n")
        result=self.persist()
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertEqual({"receiptA":111,"receiptB":222},self.remote_state()["delivered"])
        self.assertEqual("remote code update",git(self.a,"show","origin/master:README"))
        self.assertEqual("community_deliveries.json",git(self.a,"diff-tree","--no-commit-id","--name-only","-r","origin/master"))

    def test_same_cursor_remote_conflict_refuses_commit(self):
        before=state(cursors={"l2dex-castles:abc":"snapshotA"})
        self.save(self.a,state(cursors={"l2dex-castles:abc":"snapshotB"}))
        self.update_remote(state(cursors={"l2dex-castles:abc":"snapshotC"}))
        # Force baseline itself to contain snapshotA, not default empty.
        # Worktree checkout originally held empty, so both values differ from
        # empty and still represent ambiguous concurrent changes.
        result=self.persist()
        self.assertNotEqual(0,result.returncode)
        self.assertIn("nothing pushed",result.stderr)
        self.assertEqual("snapshotC",self.remote_state()["cursors"]["l2dex-castles:abc"])

    def test_no_change_does_not_create_commit(self):
        before=git(self.a,"rev-parse","HEAD")
        result=self.persist()
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertIn("No community state changes",result.stdout)
        self.assertEqual(before,git(self.a,"rev-parse","HEAD"))

    def test_untracked_state_from_fresh_template_is_committed(self):
        git(self.a,"rm","community_deliveries.json")
        git(self.a,"commit","-m","remove state for fresh copy")
        git(self.a,"push","origin","master")
        self.save(self.a,state(delivered={"first":5}))
        result=self.persist()
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertEqual(5,self.remote_state()["delivered"]["first"])


if __name__=="__main__":
    unittest.main()
