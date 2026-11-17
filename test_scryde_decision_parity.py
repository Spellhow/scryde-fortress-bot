"""Read-only Scryde candidate decisions vs actual offline legacy sends.

NO real Telegram, browsers, state files or Gemini.
"""
from collections import Counter
import copy
import unittest
from unittest.mock import patch

import github_runner as bot
from community.adapters.scryde_decisions import project_scryde_decisions

NOW=1800000000
OBJECT_ID=116
URL="https://ua.scryde.game/rankings/1000/fortresses"


def row(owner="BSOE", attackers=(), siege_at=NOW+3600, valid=True):
    output={
        "id":OBJECT_ID, "name":"Antharas Fortress",
        "owner":{"name":owner} if owner is not None else None,
        "siege_at":siege_at,
        "siege_sides":{"attackers":[{"name":name} for name in attackers]},
    }
    if not valid:
        output["owner"]="invalid-owner"
    return output


def defence(had=True, notified_siege=False, attackers=(), first=0,
            siege_at=0, notified_reminder=False):
    obj=bot.default_object_state()
    obj.update({
        "had":had, "id":OBJECT_ID, "name":"Antharas Fortress",
        "notified_siege":notified_siege,
        "last_attackers":[{"name":n} for n in attackers],
        "last_siege_at":siege_at,
        "siege_first_notify":first,
        "notified_reminder":notified_reminder,
    })
    section=dict(obj)
    section["objects"]={str(OBJECT_ID):dict(obj)}
    return section


def classify(text):
    if "УВАГА! Атакують" in text:
        return "defence_attack"
    if "Облога нашу фортецю через" in text:
        return "defence_reminder"
    if "Атака на нашу фортецю відмінена" in text:
        return "defence_cancelled"
    if "втрачено!" in text:
        return "ownership_lost"
    if "Наш клан атакує" in text:
        return "our_attack"
    if "Наша облога через" in text:
        return "our_attack_reminder"
    if "Наш клан знявся з реєстрації" in text:
        return "our_attack_cancelled"
    raise AssertionError("Unexpected BSOE notification category")


class LegacyDecisionParity(unittest.TestCase):
    def compare(self, rows, section=None, attacks=None, recent=None, now=NOW):
        section=copy.deepcopy(section if section is not None else defence(had=False))
        attacks=copy.deepcopy(attacks if attacks is not None else {})
        recent=copy.deepcopy(recent or {})
        frozen_section=copy.deepcopy(section)
        frozen_attacks=copy.deepcopy(attacks)
        predicted=project_scryde_decisions(
            rows,clan="BSOE",object_type="fortress",
            defence_state=section,attack_state=attacks,now=now,recent_alerts=recent,
        )
        self.assertEqual(section,frozen_section)
        self.assertEqual(attacks,frozen_attacks)
        sent=[]
        def capture(text,*args,**kwargs):
            sent.append(classify(text))
            return True
        live=copy.deepcopy(section)
        live["_root_state"]={"meta":{"last_alerts":copy.deepcopy(recent)}}
        with patch.object(bot,"send_notification",side_effect=capture),\
             patch.object(bot,"send_telegram",side_effect=capture),\
             patch.object(bot,"build_event_card",return_value=None),\
             patch.object(bot.time,"time",return_value=now):
            bot.process_defence(live,rows,"fortress",URL)
            bot.process_our_attacks(copy.deepcopy(attacks),rows,"fortress",URL)
        self.assertEqual(
            Counter(d.kind for d in predicted.decisions),
            Counter(sent), "candidate projection diverged from legacy outbound attempts",
        )
        return predicted

    def test_initial_defence_attack(self):
        self.compare([row(attackers=("Enemy",))],defence(had=True))

    def test_unchanged_siege_has_no_alert(self):
        self.compare([row(attackers=("Enemy",))],
                     defence(had=True,notified_siege=True,
                             attackers=("Enemy",),siege_at=NOW+3600,first=NOW-100))

    def test_cancel_defence_registration_before_siege(self):
        self.compare([row(attackers=())],
                     defence(had=True,notified_siege=True,
                             attackers=("Enemy",),siege_at=NOW+3600))

    def test_completed_siege_does_not_generate_late_cancel(self):
        self.compare([row(attackers=())],
                     defence(had=True,notified_siege=True,
                             attackers=("Enemy",),siege_at=NOW-300))

    def test_verified_loss(self):
        self.compare([row(owner="Enemy")],defence(had=True))

    def test_missing_or_invalid_owner_never_proves_loss(self):
        report=self.compare([],defence(had=True))
        self.assertEqual(1,report.missing_owned_rows)
        self.compare([row(owner="Enemy",valid=False)],defence(had=True))

    def test_new_our_attack(self):
        self.compare([row(owner="Enemy",attackers=("BSOE",))],
                     defence(had=False))

    def test_our_attack_reminder(self):
        previous={"116":{
            "notified":True,"siege_at":NOW+1200,
            "notified_at":NOW-1900,"notified_reminder":False,
            "name":"Antharas Fortress",
        }}
        self.compare([row(owner="Enemy",attackers=("BSOE",),siege_at=NOW+1200)],
                     defence(had=False),previous)

    def test_our_attack_cancel(self):
        previous={"116":{
            "notified":True,"siege_at":NOW+1200,
            "notified_at":NOW-2000,"notified_reminder":False,
            "name":"Antharas Fortress",
        }}
        self.compare([row(owner="Enemy",attackers=())],defence(had=False),previous)

    def test_malformed_snapshot_deferred_cancel(self):
        previous={"116":{
            "notified":True,"siege_at":NOW+1200,
            "notified_at":NOW-2000,"notified_reminder":False,
            "name":"Antharas Fortress",
        }}
        projected=self.compare([row(owner="Enemy",valid=False)],
                               defence(had=False),previous)
        self.assertEqual(1,projected.malformed_rows)

    def test_duplicates_quarantined(self):
        self.compare([row(owner="Enemy"),row(owner="BSOE")],defence(had=True))

    def test_recent_alert_dedup(self):
        key=bot.build_siege_alert_key("fortress",OBJECT_ID,NOW+3600,["Enemy"])
        self.compare([row(attackers=("Enemy",))],defence(had=True),
                     recent={key:NOW-30})

    def test_late_defence_reminder(self):
        self.compare([row(attackers=("Enemy",),siege_at=NOW+1200)],
                     defence(had=True,notified_siege=True,
                             attackers=("Enemy",),first=NOW-7200,
                             siege_at=NOW+1200))


if __name__=="__main__":
    unittest.main()
