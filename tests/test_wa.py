#!/usr/bin/env python3
"""Tests for bin/wa against a fixture copy of the WhatsApp for Mac schema.

Run: python3 tests/test_wa.py   (stdlib only, Python 3.9+)
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

WA = os.environ.get("WA_BIN", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "bin", "wa"))
EPOCH = 978307200


def load_wa():
    loader = importlib.machinery.SourceFileLoader("wa_mod", WA)
    spec = importlib.util.spec_from_loader("wa_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def ago(seconds):
    return time.time() - seconds - EPOCH


def build_db(path, drop=None):
    """Fixture DB with the columns wa reads. drop='TABLE.COL' leaves one out."""
    wa = load_wa()
    db = sqlite3.connect(path)
    for table, cols in wa.REQUIRED.items():
        cols = [c for c in cols if "%s.%s" % (table, c) != drop]
        db.execute("CREATE TABLE %s (%s)" % (table, ", ".join(
            c + (" INTEGER PRIMARY KEY" if c == "Z_PK" else "") for c in cols)))
    have = lambda t: [c for c in wa.REQUIRED[t] if "%s.%s" % (t, c) != drop]

    def ins(table, **row):
        row = {k: v for k, v in row.items() if k in have(table)}
        db.execute("INSERT INTO %s (%s) VALUES (%s)" % (
            table, ",".join(row), ",".join("?" * len(row))), list(row.values()))

    pinned = ago(-7000 * 31557600)  # WhatsApp pins by dating the chat ~7000 years ahead
    sessions = [  # pk, name, jid, type, last-date, unread, last-message pk
        (1, "Alice Smith", "6611111111@s.whatsapp.net", 0, ago(3600), 2, 3),
        (2, "Team Lunch", "120363000001@g.us", 1, ago(80 * 60), 0, 6),
        (3, "Status", "status@broadcast", 3, ago(60), 0, 7),
        (4, "Alice Wong", "6622222222@s.whatsapp.net", 0, ago(5 * 86400), 0, 8),
        (5, "Bob's Shop", "6633333333@s.whatsapp.net", 0, pinned, 0, 9),
        (6, "Secret", "6699999999@s.whatsapp.net", 0, ago(30), 0, 10),
    ]
    for pk, name, jid, stype, last, unread, lm in sessions:
        ins("ZWACHATSESSION", Z_PK=pk, ZPARTNERNAME=name, ZCONTACTJID=jid, ZSESSIONTYPE=stype,
            ZLASTMESSAGEDATE=last, ZUNREADCOUNT=unread, ZLASTMESSAGE=lm, ZARCHIVED=0,
            ZHIDDEN=1 if name == "Secret" else 0, ZREMOVED=0)
    ins("ZWAGROUPMEMBER", Z_PK=1, ZMEMBERJID="6644@s.whatsapp.net", ZCONTACTNAME="Carol")
    ins("ZWAGROUPMEMBER", Z_PK=2, ZMEMBERJID="6655@s.whatsapp.net")
    ins("ZWAPROFILEPUSHNAME", ZJID="6655@s.whatsapp.net", ZPUSHNAME="Dave P")
    ins("ZWAMEDIAITEM", Z_PK=1, ZTITLE="receipt photo")
    messages = [  # pk, session, me, type, date, text, group member, media
        (1, 1, 0, 0, ago(3 * 86400), "Привет, встреча завтра?", None, None),
        (2, 1, 1, 0, ago(2 * 86400), "Yes, 10am", None, None),
        (3, 1, 0, 1, ago(3600), None, None, 1),
        (4, 2, 0, 0, ago(2 * 3600), "Lunch at Somtam?", 1, None),
        (5, 2, 0, 0, ago(90 * 60), "ok", 2, None),
        (6, 2, 0, 6, ago(80 * 60), '{"event": "joined"}', None, None),
        (7, 3, 0, 0, ago(60), "status text should stay hidden", None, None),
        (8, 4, 0, 8, ago(5 * 86400), "invoice.pdf", None, None),
        (9, 5, 0, 0, ago(10 * 60), "order shipped", None, None),
        (10, 6, 0, 0, ago(30), "hidden chat text", None, None),
    ]
    for pk, sess, me, typ, date, text, gm, media in messages:
        ins("ZWAMESSAGE", Z_PK=pk, ZCHATSESSION=sess, ZISFROMME=me, ZMESSAGETYPE=typ,
            ZMESSAGEDATE=date, ZTEXT=text, ZGROUPMEMBER=gm, ZMEDIAITEM=media)
    db.commit()
    db.close()


class WaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "ChatStorage.sqlite")
        build_db(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_wa(self, *args, db=None, env_extra=None):
        env = dict(os.environ, WA_DB=db or self.db, WA_NOLOG="1")
        env.update(env_extra or {})
        for k in [k for k, v in env.items() if v is None]:
            del env[k]
        cmd = [sys.executable, WA] + list(args)
        return subprocess.run(cmd, env=env, capture_output=True, text=True,
                              cwd=self.tmp.name, timeout=30)

    def json_of(self, *args):
        p = self.run_wa(*args, "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_chats_order_pin_unread_and_skips(self):
        chats = self.json_of("chats")
        names = [c["name"] for c in chats]
        self.assertEqual(names, ["Bob's Shop", "Alice Smith", "Team Lunch", "Alice Wong"])
        bob = chats[0]
        self.assertTrue(bob["pinned"])
        self.assertTrue(bob["last"].startswith(time.strftime("%Y")), bob["last"])
        self.assertEqual(chats[1]["unread"], 2)
        self.assertEqual(chats[1]["preview"], "[image] receipt photo")
        self.assertEqual(chats[2]["preview"], "[system]")
        self.assertEqual([c["name"] for c in self.json_of("chats", "--unread")], ["Alice Smith"])

    def test_read_exact_name_chronological_with_caption(self):
        msgs = self.json_of("read", "alice smith")
        self.assertEqual([m["from"] for m in msgs], ["Alice Smith", "me", "Alice Smith"])
        self.assertEqual(msgs[2]["type"], "image")
        self.assertEqual(msgs[2]["text"], "receipt photo")

    def test_group_senders_and_system_events(self):
        msgs = self.json_of("read", "team")
        self.assertEqual([m["from"] for m in msgs], ["Carol", "Dave P"])
        with_all = self.json_of("read", "team", "--all")
        self.assertEqual(with_all[-1]["type"], "system")

    def test_ambiguous_chat_prints_runnable_commands(self):
        p = self.run_wa("read", "alice")
        self.assertEqual(p.returncode, 2)
        cmds = [l.split("#")[0].strip() for l in p.stderr.splitlines() if l.startswith("  wa read")]
        self.assertEqual(len(cmds), 2, p.stderr)
        argv = shlex.split(cmds[0])
        self.assertEqual(argv[:2], ["wa", "read"])
        rerun = self.run_wa(*argv[1:])
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertTrue(rerun.stdout.strip())

    def test_name_with_quote_and_unknown_chat(self):
        self.assertEqual(self.json_of("read", "bob's")[0]["text"], "order shipped")
        p = self.run_wa("read", "nobody-here")
        self.assertEqual(p.returncode, 2)
        self.assertIn("Try: wa chats -n 100", p.stderr)

    def test_search_any_case_any_script_all_words(self):
        hits = self.json_of("search", "ПРИВЕТ")
        self.assertEqual([h["chat"] for h in hits], ["Alice Smith"])
        self.assertEqual(len(self.json_of("search", "yes", "10AM")), 1)
        self.assertEqual(self.json_of("search", "yes", "lunch"), [])
        self.assertEqual(self.json_of("search", "receipt")[0]["type"], "image")

    def test_status_and_hidden_chats_never_appear(self):
        for args in (["search", "status"], ["search", "hidden"], ["read", "Secret"]):
            p = self.run_wa(*args)
            self.assertNotIn("hidden", p.stdout)
            self.assertNotIn("status text", p.stdout)
        p = self.run_wa("search", "status")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")
        self.assertIn("Searched all messages", p.stderr)
        self.assertIn("Try:", p.stderr)

    def test_recent_since_window(self):
        msgs = self.json_of("recent", "--since", "1d")
        self.assertEqual([m["text"] for m in msgs],
                         ["Lunch at Somtam?", "ok", "receipt photo", "order shipped"])
        p = self.run_wa("recent", "--since", "tomorrow")
        self.assertEqual(p.returncode, 2)

    def test_flags_before_and_after_subcommand(self):
        self.assertEqual(self.json_of("status")["messages"], 10)
        p = self.run_wa("--json", "status")
        self.assertEqual(json.loads(p.stdout)["chats"], 4)

    def test_schema_drift_reds_every_command(self):
        bad = os.path.join(self.tmp.name, "drift.sqlite")
        build_db(bad, drop="ZWAMESSAGE.ZTEXT")
        for args in (["status"], ["chats"], ["search", "x"]):
            p = self.run_wa(*args, db=bad)
            self.assertEqual(p.returncode, 1, args)
            self.assertIn("ZWAMESSAGE.ZTEXT", p.stderr)

    def test_reads_wal_database_after_whatsapp_quits(self):
        # WhatsApp keeps the DB in WAL mode. When it quits, the -shm index is removed,
        # and a plain read-only open then fails with "unable to open database file".
        closed = os.path.join(self.tmp.name, "closed.sqlite")
        build_db(closed)
        con = sqlite3.connect(closed)
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        self.assertFalse(os.path.exists(closed + "-shm"))
        p = self.run_wa("status", "--json", db=closed)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["messages"], 10)
        self.assertFalse(os.path.exists(closed + "-shm"), "wa must not create files")

    def test_missing_database_exits_3(self):
        p = self.run_wa("status", db=os.path.join(self.tmp.name, "nope", "ChatStorage.sqlite"))
        self.assertEqual(p.returncode, 3)
        p = self.run_wa("status", db=os.path.join(self.tmp.name, "ChatStorage-missing.sqlite"))
        self.assertEqual(p.returncode, 3)

    @unittest.skipIf(sys.platform == "darwin", "on a Mac wa reads locally by design")
    def test_off_mac_without_host_says_how_to_connect(self):
        p = self.run_wa("chats", env_extra={"WA_DB": None, "WA_HOST": None, "WA_LOCAL": None})
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("WA_HOST", p.stderr)

    def test_version(self):
        p = self.run_wa("--version")
        self.assertEqual(p.returncode, 0)
        self.assertRegex(p.stdout, r"^wa \d{4}\.\d{1,2}\.\d{1,2}$")

    def test_never_writes(self):
        before = hashlib.sha256(open(self.db, "rb").read()).hexdigest()
        for args in (["chats"], ["read", "team", "--all"], ["search", "ok"], ["recent"], ["status"]):
            self.run_wa(*args)
        self.assertEqual(hashlib.sha256(open(self.db, "rb").read()).hexdigest(), before)
        db = load_wa().connect(self.db)
        with self.assertRaises(sqlite3.Error):
            db.execute("DELETE FROM ZWAMESSAGE")

    def test_remote_command_survives_shell_quoting(self):
        wa = load_wa()
        args = ["search", "it's a \"test\" $(rm -rf ~)", "--chat", "Bob's Shop"]
        cmd = wa.remote_command(args, "my-mac")
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("BatchMode=yes", cmd)
        self.assertEqual(cmd[-3:-1], ["--", "my-mac"])  # a host like -oProxyCommand=x stays a host
        remote = shlex.split(cmd[-1])
        self.assertEqual(remote[:5],
                         ["/usr/bin/env", "WA_LOCAL=1", "WA_NOLOG=1", "/usr/bin/python3", "-"])
        self.assertEqual(remote[5:], args)

    def extra_db(self, name, *sql):
        path = os.path.join(self.tmp.name, name + ".sqlite")
        build_db(path)
        con = sqlite3.connect(path)
        for stmt in sql:
            con.execute(stmt)
        con.commit()
        con.close()
        return path

    def test_bad_date_and_bad_count_are_usage_errors(self):
        self.assertEqual(self.run_wa("read", "team", "--since", "2026-02-30").returncode, 2)
        self.assertEqual(self.run_wa("chats", "-n", "0").returncode, 2)
        self.assertEqual(self.run_wa("chats", "-n", "-1").returncode, 2)

    def test_broken_utf8_message_does_not_stop_listing(self):
        db = self.extra_db("utf8", "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZISFROMME, "
                           "ZMESSAGETYPE, ZMESSAGEDATE, ZTEXT) VALUES (11, 2, 0, 0, %f, "
                           "CAST(x'6f6bff' AS TEXT))" % ago(60))
        p = self.run_wa("read", "team", "--json", db=db)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)[-1]["text"], "ok\ufffd")

    def test_control_characters_never_reach_the_terminal(self):
        db = self.extra_db("ansi", "UPDATE ZWAMESSAGE SET ZTEXT = 'red' || char(27) || "
                           "'[2J' || char(7) WHERE Z_PK = 5",
                           "UPDATE ZWACHATSESSION SET ZPARTNERNAME = 'Team' || char(27) || "
                           "'[31m Lunch' WHERE Z_PK = 2")
        for args in (["read", "team"], ["chats"], ["search", "red"], ["recent"]):
            p = self.run_wa(*args, db=db)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertNotIn("\x1b", p.stdout, args)
            self.assertNotIn("\x07", p.stdout, args)

    def test_chat_lookup_by_name_with_at_sign_and_by_phone(self):
        db = self.extra_db("at", "UPDATE ZWACHATSESSION SET ZPARTNERNAME = 'Ops @ Acme' "
                           "WHERE Z_PK = 2")
        self.assertEqual(self.run_wa("read", "ops @ acme", db=db).returncode, 0)
        self.assertEqual(self.json_of("read", "+66 1111 1111")[0]["chat"], "Alice Smith")
        p = self.run_wa("read", "120363000001")  # a group id is not a phone number
        self.assertEqual(p.returncode, 2)

    def test_pinned_chat_without_last_message_shows_no_far_future_date(self):
        db = self.extra_db("pin", "UPDATE ZWACHATSESSION SET ZLASTMESSAGE = NULL WHERE Z_PK = 5")
        chats = json.loads(self.run_wa("chats", "--json", db=db).stdout)
        bob = [c for c in chats if c["name"] == "Bob's Shop"][0]
        self.assertTrue(bob["pinned"])
        self.assertIsNone(bob["last"])
        self.assertEqual(chats[-1]["name"], "Bob's Shop")
        self.assertNotIn("90", self.run_wa("chats", db=db).stdout.splitlines()[-1][:2])

    def test_live_wal_database_is_read_without_touching_data_files(self):
        live = self.extra_db("live")
        writer = sqlite3.connect(live)  # stands in for WhatsApp holding the database open
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE ZWAMESSAGE SET ZTEXT = 'ok now' WHERE Z_PK = 5")
        writer.commit()
        try:
            self.assertTrue(os.path.exists(live + "-shm"))
            digest = lambda f: hashlib.sha256(open(f, "rb").read()).hexdigest()
            before = (sorted(os.listdir(self.tmp.name)), digest(live), digest(live + "-wal"))
            p = self.run_wa("read", "team", "--json", db=live)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)[-1]["text"], "ok now")  # sees the WAL
            for args in (["chats"], ["search", "ok"], ["recent"], ["status"]):
                self.run_wa(*args, db=live)
            after = (sorted(os.listdir(self.tmp.name)), digest(live), digest(live + "-wal"))
            self.assertEqual(after, before)
        finally:
            writer.close()

    def test_unexpected_error_is_exit_4_not_schema_drift(self):
        wa = load_wa()
        boom = lambda db, a: 1 / 0
        with unittest.mock.patch.dict(os.environ, {"WA_DB": self.db, "WA_NOLOG": "1"}), \
                unittest.mock.patch.dict(wa.COMMANDS, {"status": boom}), \
                unittest.mock.patch("sys.stderr"):
            self.assertEqual(wa.main(["status"]), 4)


if __name__ == "__main__":
    unittest.main(verbosity=1)
