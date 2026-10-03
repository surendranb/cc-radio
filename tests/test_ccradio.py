#!/usr/bin/env python3
"""Tests for scripts/ccradio. No mpv, no network, no speakers required.

Run:  python3 tests/test_ccradio.py

The mod (hooks/register.js) is a sensor; its pure part has its own tests in
tests/radio-tab.test.mjs. Everything that decides and plays lives here.
"""

import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import importlib.machinery
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "scripts", "ccradio")
DELAY = 0.3


def load_cli(state_dir, sock):
    os.environ["CCRADIO_STATE_DIR"] = state_dir
    os.environ["CCRADIO_SOCK"] = sock
    os.environ["CCRADIO_SYNC"] = "1"                 # no forked reconcilers in tests
    os.environ["CCRADIO_NO_WATCHDOG"] = "1"
    os.environ["CCRADIO_START_DELAY"] = str(DELAY)
    return load_module("ccradio_mod")


def load_module(name):
    spec = importlib.util.spec_from_loader(
        name, importlib.machinery.SourceFileLoader(name, EXE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeMpv:
    """Minimal mpv IPC stand-in: records commands, replies with canned data."""

    def __init__(self, path, props=None):
        self.path = path
        self.props = props or {}
        self.seen = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(16)
        self.stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                data = conn.recv(65536).decode()
                for line in data.splitlines():
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    cmd = msg["command"]
                    self.seen.append(cmd)
                    out = None
                    if cmd[0] == "get_property":
                        out = self.props.get(cmd[1])
                    elif cmd[0] == "set_property":
                        self.props[cmd[1]] = cmd[2]
                    elif cmd[0] == "loadfile":
                        self.props["idle-active"] = False
                        self.props["path"] = cmd[1]
                    elif cmd[0] == "stop":
                        self.props["idle-active"] = True
                        self.props["path"] = ""
                    elif cmd[0] == "cycle" and cmd[1] == "pause":
                        self.props["pause"] = not self.props.get("pause", False)
                    conn.sendall((json.dumps(
                        {"request_id": msg["request_id"], "error": "success",
                         "data": out}) + "\n").encode())
            except Exception:
                pass
            finally:
                conn.close()

    def loads(self):
        return [c[1] for c in self.seen if c and c[0] == "loadfile"]

    def sent(self, verb):
        return any(c and c[0] == verb for c in self.seen)

    def close(self):
        self.stop = True
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            os.unlink(self.path)
        except OSError:
            pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sock = os.path.join(self.tmp, "s.sock")
        self.cc = load_cli(self.tmp, self.sock)
        self.mpv = None
        # No test may ever launch a real player: in-process, the daemon is a stub...
        self.cc.start_daemon = lambda s=None: (s or self.cc.load_state()) if self.cc.alive() \
            else self.cc.die("no fake mpv in this test")

    def tearDown(self):
        if self.mpv:
            self.mpv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        # ...and a subprocess that reached one is a test bug, not a feature.
        stray = subprocess.run(["pgrep", "-f", "input-ipc-server=%s" % self.sock],
                               capture_output=True, text=True).stdout.strip()
        if stray:
            subprocess.run(["pkill", "-f", "input-ipc-server=%s" % self.sock])
            self.fail("a test launched a real mpv (pid %s)" % stray)

    def start_mpv(self, **props):
        base = {"volume": 70.0, "pause": False, "idle-active": True, "path": ""}
        base.update(props)
        self.mpv = FakeMpv(self.sock, base)
        return self.mpv

    def quietly(self, fn, *a):
        """Run a command without its chatter landing in the test output."""
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return fn(*a)

    # The mod's verb, as it arrives: one tab's record, then a reconcile.
    def tab(self, sid, turn=None, waiting=None, agents=None, gone=False):
        args = [sid]
        if turn is not None:
            args.append("turn=%d" % turn)
        if waiting is not None:
            args.append("waiting=%d" % waiting)
        if agents is not None:
            args.append("agents=%d" % agents)
        if gone:
            args.append("gone")
        self.quietly(self.cc.cmd_report, args)


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------

class TestDecide(Base):
    def rec(self, **kw):
        base = {"turn": False, "waiting": False, "agents": 0, "at": 1000.0}
        base.update(kw)
        return base

    def test_no_tabs_means_silence(self):
        self.assertEqual(self.cc.decide({}, 1000.0)[:2], (False, "none"))

    def test_idle_tabs_mean_silence(self):
        self.assertEqual(self.cc.decide({"a": self.rec()}, 1000.0)[:2], (False, "idle"))

    def test_one_working_tab_means_music(self):
        tabs = {"a": self.rec(), "b": self.rec(turn=True)}
        self.assertEqual(self.cc.decide(tabs, 1000.0)[:2], (True, "working"))

    def test_you_win_over_the_machine(self):
        """A tab waiting on you pauses the music even while another tab works."""
        tabs = {"a": self.rec(turn=True), "b": self.rec(turn=True, waiting=True)}
        self.assertEqual(self.cc.decide(tabs, 1000.0)[:2], (False, "waiting"))

    def test_background_agents_keep_a_tab_working_after_its_turn(self):
        tabs = {"a": self.rec(turn=False, agents=2, agents_at=1000.0)}
        self.assertEqual(self.cc.decide(tabs, 1000.0)[:2], (True, "working"))

    def test_an_agent_count_nobody_refreshes_goes_stale(self):
        tabs = {"a": self.rec(agents=2, agents_at=1000.0 - self.cc.AGENTS_STALE - 1)}
        self.assertEqual(self.cc.decide(tabs, 1000.0)[:2], (False, "idle"))

    def test_a_heartbeat_with_the_same_agent_count_does_not_reset_the_clock(self):
        """The old bug: every heartbeat refreshed agents_at, so a leaked agent counted forever."""
        self.cc.report("A", {"turn": False, "agents": 1})
        first = self.cc.read_tabs()["A"]["agents_at"]
        time.sleep(0.05)
        self.cc.report("A", {"turn": False, "agents": 1})      # the heartbeat
        self.assertEqual(self.cc.read_tabs()["A"]["agents_at"], first)
        self.cc.report("A", {"turn": False, "agents": 2})      # a real change
        self.assertGreater(self.cc.read_tabs()["A"]["agents_at"], first)

    def test_tabs_that_stop_reporting_are_forgotten(self):
        self.cc.write_tabs({
            "dead": {"turn": True, "at": time.time() - self.cc.FRESH_AFTER - 1},
            "live": {"turn": False, "at": time.time()},
        })
        self.assertEqual(list(self.cc.read_tabs()), ["live"],
                         "a tab that crashed mid-turn must not wedge the radio on")


# --------------------------------------------------------------------------
# the player follows the tabs
# --------------------------------------------------------------------------

class TestReconcile(Base):
    def test_a_quick_answer_stays_silent(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        # reconcile waited out the delay inline; the tab finished first? No -
        # with CCRADIO_SYNC the delay is served inside cmd_report, so simulate
        # the quick turn by reporting the end before the delay would elapse.
        self.cc.report("A", {"turn": False})
        self.cc.reconcile()
        # Music that started during the delay window is stopped again at once.
        self.assertTrue(m.props["idle-active"], "nothing should be loaded after a quick turn")

    def test_music_starts_after_the_delay(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.assertEqual(len(m.loads()), 1)
        self.assertIn(m.loads()[0], [s["url"] for s in self.cc.stations()])

    def test_a_second_tab_keeps_the_station(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.tab("B", turn=1)
        self.assertEqual(len(m.loads()), 1, "a second tab joining must not change the station")

    def test_the_tab_that_started_it_can_leave_and_music_goes_on(self):
        """The old bug: the starter was bound to its own tab, so B worked in silence."""
        m = self.start_mpv()
        self.cc.report("A", {"turn": True})
        self.cc.report("B", {"turn": True})
        self.cc.report("A", {"turn": False})
        self.cc.reconcile()
        self.assertEqual(len(m.loads()), 1, "B is working, so music must start")
        self.assertFalse(m.props["idle-active"])

    def test_one_tab_finishing_keeps_music_for_the_others(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.tab("B", turn=1)
        self.tab("A", turn=0)
        self.assertFalse(m.sent("stop"), "tab A finishing must not silence tab B's music")

    def test_music_pauses_when_every_tab_is_done(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.tab("B", turn=1)
        self.tab("A", turn=0)
        self.tab("B", turn=0)
        self.assertTrue(m.sent("stop"))
        self.assertTrue(m.props["idle-active"])
        self.assertFalse(m.sent("quit"), "tabs are still open, so the daemon stays warm")

    def test_daemon_goes_down_when_the_last_tab_closes(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.tab("A", gone=True)
        self.assertTrue(m.sent("quit"))

    def test_a_question_pauses_and_the_answer_resumes_at_once(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.assertEqual(len(m.loads()), 1)
        self.tab("A", waiting=1)
        self.assertTrue(m.props["idle-active"], "waiting on you means silence")
        t0 = time.time()
        self.tab("A", waiting=0)
        self.assertEqual(len(m.loads()), 2, "the answer brings the music back")
        self.assertLess(time.time() - t0, DELAY, "no second start delay after a question")

    def test_a_permission_prompt_before_the_music_starts_is_honoured(self):
        """The old bug: a duck that landed before the player existed was lost."""
        m = self.start_mpv()
        self.cc.report("A", {"turn": True})
        self.cc.report("A", {"waiting": True})
        self.cc.reconcile()
        self.assertEqual(m.loads(), [], "a dialog is up - nothing may start")

    def test_subagents_keep_the_music_after_the_turn(self):
        m = self.start_mpv()
        self.tab("A", turn=1, agents=1)
        self.tab("A", turn=0)
        self.assertFalse(m.sent("stop"), "a background agent is still working")
        self.tab("A", agents=0)
        self.assertTrue(m.sent("stop"))

    def test_an_interrupted_turn_pauses(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.tab("A", turn=0)          # Escape: the mod reports the turn ended
        self.assertTrue(m.props["idle-active"])

    def test_reconcile_is_idempotent(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        for _ in range(3):
            self.cc.reconcile()
        self.assertEqual(len(m.loads()), 1, "repeating the question must not restart the stream")

    def test_each_run_avoids_the_last_station(self):
        m = self.start_mpv()
        for i in range(6):
            self.tab("A", turn=1)
            self.tab("A", turn=0)
        loads = m.loads()
        self.assertGreaterEqual(len(loads), 6)
        self.assertTrue(all(a != b for a, b in zip(loads, loads[1:])),
                        "two runs in a row must not land on the same station")


class TestWatchdog(Base):
    def test_a_dead_last_tab_cannot_leave_music_playing(self):
        """The old gap: with one tab gone without a word, nobody ever reconciled."""
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.assertEqual(len(m.loads()), 1)
        # The tab dies: its record goes stale, and nobody reports any more.
        self.cc.write_tabs({"A": {"turn": True, "at": time.time() - self.cc.FRESH_AFTER - 1}})
        self.cc._reconcile_once()          # what the watchdog runs every few seconds
        self.assertTrue(m.sent("quit"), "no live tab means the daemon goes down")

    def test_only_one_watchdog_runs(self):
        import fcntl
        fh = open(os.path.join(self.tmp, "watchdog.lock"), "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            t0 = time.time()
            self.cc.cmd_watchdog([])       # a second one must stand down at once
            self.assertLess(time.time() - t0, 1.0)
        finally:
            fh.close()


class TestModes(Base):
    def test_play_while_nothing_works_is_yours(self):
        m = self.start_mpv()
        self.quietly(self.cc.cmd_play, ["soma-groovesalad"])
        self.assertEqual(self.cc.load_state()["mode"], "manual")
        self.tab("A", turn=1)
        self.tab("A", turn=0)
        self.assertFalse(m.sent("stop"), "music you started must survive the tabs going idle")

    def test_play_while_a_tab_works_just_changes_the_station(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.cmd_play, ["soma-dronezone"])
        self.assertEqual(self.cc.load_state()["mode"], "auto")
        self.tab("A", turn=0)
        self.assertTrue(m.sent("stop"), "changing the station must not take the radio away from the tabs")

    def test_next_during_automatic_music_keeps_it_automatic(self):
        """The old bug: next/prev/shuffle flipped ownership and the hooks never stopped it."""
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.cmd_next, [])
        self.assertEqual(self.cc.load_state()["mode"], "auto")
        self.tab("A", turn=0)
        self.assertTrue(m.sent("stop"))

    def test_pause_is_an_off_switch_the_tabs_respect(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.cmd_off, [])
        self.assertTrue(m.props["idle-active"])
        self.tab("A", turn=0)
        self.tab("A", turn=1)
        self.assertEqual(len(m.loads()), 1, "off means the tabs start nothing")

    def test_auto_hands_the_radio_back(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.cmd_off, [])
        self.quietly(self.cc.cmd_auto, [])
        self.assertEqual(len(m.loads()), 2, "auto reconciles at once: the tab is working")

    def test_resume_is_auto_not_a_toggle(self):
        """The old bug: `resume` was the pause toggle, so resume while playing paused."""
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.COMMANDS["resume"], [])
        self.assertFalse(m.props["idle-active"])
        self.assertEqual(self.cc.load_state()["mode"], "auto")

    def test_stop_takes_the_daemon_down_and_stays_off(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.cmd_stop, [])
        self.assertTrue(m.sent("quit"))
        self.assertEqual(self.cc.load_state()["mode"], "off")

    def test_off_with_no_tabs_lets_the_daemon_go(self):
        m = self.start_mpv()
        self.quietly(self.cc.cmd_off, [])
        self.tab("A", gone=True)
        self.assertTrue(m.sent("quit"))


# --------------------------------------------------------------------------
# stations, state, search
# --------------------------------------------------------------------------

class TestStations(Base):
    def test_curated_list_loads_and_is_wellformed(self):
        st = self.cc.stations()
        self.assertGreaterEqual(len(st), 10)
        for s in st:
            for key in ("id", "name", "url"):
                self.assertTrue(s.get(key), "%s missing %s" % (s.get("id"), key))
            self.assertTrue(s["url"].startswith("http"), s["url"])
        self.assertEqual(len({s["id"] for s in st}), len(st), "duplicate ids")

    def test_find_by_exact_id_partial_and_name(self):
        self.assertEqual(self.cc.find_station("soma-groovesalad")["id"], "soma-groovesalad")
        self.assertEqual(self.cc.find_station("groovesalad")["id"], "soma-groovesalad")
        self.assertEqual(self.cc.find_station("Drone Zone")["id"], "soma-dronezone")
        self.assertIsNone(self.cc.find_station("no-such-station-xyz"))
        self.assertIsNone(self.cc.find_station(None), "no station is not a crash")

    def test_fallback_used_when_curated_missing(self):
        self.cc.CURATED = os.path.join(self.tmp, "gone.json")
        self.assertEqual(len(self.cc.stations()), len(self.cc.FALLBACK))

    def test_fallback_used_when_curated_corrupt(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as fh:
            fh.write("{not json")
        self.cc.CURATED = bad
        self.assertEqual(len(self.cc.stations()), len(self.cc.FALLBACK))

    def test_only_http_streams_reach_the_player(self):
        """mpv opens far more than http. A directory record must not be able to point it elsewhere."""
        self.assertFalse(self.cc.safe_url("file:///etc/passwd"))
        self.assertFalse(self.cc.safe_url("ytdl://something"))
        self.assertTrue(self.cc.safe_url("https://example.test/x.mp3"))
        self.cc.write_pool("genre: x", [
            {"id": "bad", "name": "Bad", "url": "file:///tmp/x", "genre": ""},
            {"id": "ok", "name": "Ok", "url": "https://example.test/ok", "genre": ""}])
        self.assertEqual([s["id"] for s in self.cc.stations()], ["ok"])
        with self.assertRaises(SystemExit):
            self.cc.play({"id": "bad", "name": "Bad", "url": "file:///tmp/x"})

    def test_order_repairs_when_stations_change_underneath(self):
        live = [s["id"] for s in self.cc.stations()]
        s = {"order": ["deleted-station", live[2], live[0]]}
        order = self.cc.order_ids(s)
        self.assertNotIn("deleted-station", order)
        self.assertEqual(sorted(order), sorted(live))
        self.assertEqual(order[:2], [live[2], live[0]])


class TestGenrePools(Base):
    POOL = [
        {"id": "a-station", "name": "A Station", "genre": "lofi",
         "url": "https://example.test/a.mp3", "source": "Radio Browser"},
        {"id": "b-station", "name": "B Station", "genre": "lofi",
         "url": "https://example.test/b.mp3", "source": "Radio Browser"},
    ]

    def fake_fetch(self, sts):
        self.cc.rb_fetch = lambda field, term, limit=30: list(sts)

    def test_pool_replaces_the_builtin_stations(self):
        self.cc.write_pool("genre: lofi", self.POOL)
        self.assertEqual([s["id"] for s in self.cc.stations()], ["a-station", "b-station"])

    def test_corrupt_or_empty_pool_falls_back_to_builtins(self):
        with open(self.cc.pool_path(), "w") as fh:
            fh.write("{not json")
        self.assertGreaterEqual(len(self.cc.stations()), 10)
        self.cc.write_pool("genre: nothing", [])
        self.assertGreaterEqual(len(self.cc.stations()), 10)

    def test_ids_stay_unique_when_names_repeat(self):
        taken = set()
        ids = [self.cc.pool_id("Lofi Radio", taken) for _ in range(3)]
        self.assertEqual(ids, ["lofi-radio", "lofi-radio-2", "lofi-radio-3"])

    def test_resolved_url_wins_and_tags_become_genre(self):
        st = self.cc.as_station(
            {"name": " Chill FM ", "url": "https://example.test/redirect",
             "url_resolved": "https://example.test/real.mp3", "tags": "lofi,chill"}, set())
        self.assertEqual(st["url"], "https://example.test/real.mp3")
        self.assertEqual(st["name"], "Chill FM")
        self.assertEqual(st["genre"], "lofi, chill")

    def test_off_restores_the_builtins(self):
        self.cc.write_pool("genre: lofi", self.POOL)
        self.quietly(self.cc.cmd_genre, ["off"])
        self.assertGreaterEqual(len(self.cc.stations()), 10)
        self.assertIsNone(self.cc.read_pool())

    def test_a_genre_is_a_preference_not_a_play_button(self):
        """Picking a genre while nothing works must not start music the tabs then own."""
        m = self.start_mpv()
        self.fake_fetch(self.POOL)
        self.quietly(self.cc.cmd_genre, ["lofi"])
        self.assertEqual(self.cc.read_pool()["label"], "genre: lofi")
        self.assertEqual(m.loads(), [])
        self.assertEqual(self.cc.load_state()["mode"], "auto")

    def test_a_genre_switches_music_that_is_already_playing(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.fake_fetch(self.POOL)
        self.quietly(self.cc.cmd_genre, ["lofi"])
        self.assertIn(m.loads()[-1], [s["url"] for s in self.POOL])

    def test_automatic_music_draws_from_the_pool(self):
        m = self.start_mpv()
        self.cc.write_pool("genre: lofi", self.POOL)
        self.tab("A", turn=1)
        for url in m.loads():
            self.assertIn(url, [s["url"] for s in self.POOL], "automatic music escaped the pool")

    def test_directory_down_is_one_clear_line(self):
        self.cc.rb_query = lambda params: (_ for _ in ()).throw(self.cc.DirectoryDown())
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                self.cc.cmd_genre(["jazz"])
            with self.assertRaises(SystemExit):
                self.cc.cmd_search(["jazz"])
        self.assertIn("Radio Browser is unreachable", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_language_pool_is_labelled_as_a_language(self):
        self.fake_fetch(self.POOL)
        self.quietly(self.cc.cmd_language, ["tamil"])
        self.assertEqual(self.cc.read_pool()["label"], "language: tamil")


class TestState(Base):
    def test_roundtrip_and_defaults(self):
        s = self.cc.load_state()
        self.assertEqual(s["volume"], 70)
        self.assertEqual(s["mode"], "auto")
        s["volume"] = 42
        self.cc.save_state(s)
        self.assertEqual(self.cc.load_state()["volume"], 42)

    def test_corrupt_state_falls_back_to_defaults(self):
        with open(self.cc.state_path(), "w") as fh:
            fh.write("{{{garbage")
        self.assertEqual(self.cc.load_state()["volume"], 70)
        with open(self.cc.state_path(), "w") as fh:
            fh.write("[1, 2]")
        self.assertEqual(self.cc.load_state()["mode"], "auto")

    def test_unknown_mode_is_auto(self):
        s = self.cc.load_state()
        s["mode"] = "sideways"
        self.cc.save_state(s)
        self.assertEqual(self.cc.load_state()["mode"], "auto")

    def test_save_leaves_no_temp_files(self):
        self.cc.save_state(self.cc.load_state())
        self.cc.write_tabs({})
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TestIPC(Base):
    def test_not_running_raises_when_no_socket(self):
        with self.assertRaises(self.cc.NotRunning):
            self.cc.ipc("get_property", "volume")

    def test_alive_and_loaded(self):
        self.assertFalse(self.cc.alive())
        self.assertFalse(self.cc.loaded())
        m = self.start_mpv()
        self.assertTrue(self.cc.alive())
        self.assertFalse(self.cc.loaded(), "idle is not loaded")
        m.props["idle-active"] = False
        self.assertTrue(self.cc.loaded())

    def test_set_volume_sends_exact_command_and_clamps(self):
        m = self.start_mpv()
        self.assertEqual(self.cc.set_volume(55), 55)
        self.assertIn(["set_property", "volume", 55], m.seen)
        self.assertEqual(self.cc.set_volume(-20), 0)
        self.assertEqual(self.cc.set_volume(9999), self.cc.VOL_MAX)

    def test_volume_persists_when_daemon_is_down(self):
        self.assertEqual(self.cc.set_volume(33), 33)
        self.assertEqual(self.cc.load_state()["volume"], 33)

    def test_stop_daemon_never_signals_a_stranger(self):
        """The old bug: a stale pid after a reboot belongs to someone else."""
        bystander = subprocess.Popen(["sleep", "30"])
        try:
            s = self.cc.load_state()
            s["pid"] = bystander.pid
            self.cc.save_state(s)
            self.cc.stop_daemon()
            time.sleep(0.2)
            self.assertIsNone(bystander.poll(), "a process that is not our mpv must not be killed")
            self.assertIsNone(self.cc.load_state()["pid"])
        finally:
            bystander.kill()
            bystander.wait()


class TestUntrustedText(Base):
    def test_control_characters_never_reach_the_terminal(self):
        """A station operator writes the ICY title; it must not be able to recolour the band."""
        self.assertEqual(self.cc.clean("\x1b[31mRED\x1b[0m title\x07"), "RED title")
        self.assertEqual(self.cc.clean("x" * 500), "x" * 120)
        self.assertEqual(self.cc.clean(None), "")
        self.start_mpv(**{"metadata/by-key/icy-title": "\x1b]0;evil\x07Artist - Track",
                          "path": "https://ice2.somafm.com/lush-128-mp3", "idle-active": False})
        self.assertEqual(self.cc.now_playing(), "Artist - Track")
        st = self.cc.as_station({"name": "Bad\x1b[2JName", "url": "https://x.test/a",
                                 "tags": "a,\x00b"}, set())
        self.assertEqual(st["name"], "BadName")
        self.assertEqual(st["genre"], "a, b")


class TestNowPlaying(Base):
    def test_returns_icy_title(self):
        self.start_mpv(**{"metadata/by-key/icy-title": "Artist - Track",
                          "path": "https://ice2.somafm.com/lush-128-mp3", "idle-active": False})
        self.assertEqual(self.cc.now_playing(), "Artist - Track")

    def test_suppresses_url_basename_placeholder_and_raw_url(self):
        self.start_mpv(**{"media-title": "lush-128-mp3",
                          "path": "https://ice2.somafm.com/lush-128-mp3"})
        self.assertIsNone(self.cc.now_playing())
        self.mpv.props["media-title"] = "https://ice2.somafm.com/lush-128-mp3"
        self.assertIsNone(self.cc.now_playing())

    def test_handles_missing_metadata(self):
        self.start_mpv(path="https://ice2.somafm.com/lush-128-mp3")
        self.assertIsNone(self.cc.now_playing())


class TestCommands(Base):
    def test_now_with_nothing_loaded_dies_cleanly(self):
        """The old bug: an AttributeError traceback when no station was stored."""
        self.start_mpv()
        with self.assertRaises(SystemExit):
            self.quietly(self.cc.cmd_now, [])

    def test_play_with_no_args_survives_a_vanished_station(self):
        """The old bug: a TypeError when the last station was a search result that is gone."""
        m = self.start_mpv()
        s = self.cc.load_state()
        s["station"] = "rb-deadbeef"
        self.cc.save_state(s)
        self.quietly(self.cc.cmd_play, [])
        self.assertEqual(len(m.loads()), 1)

    def test_play_a_search_result_with_a_bad_scheme_dies(self):
        self.start_mpv()
        self.cc.save_found([{"stationuuid": "abc", "name": "Evil", "url": "file:///x"}])
        with self.assertRaises(SystemExit):
            self.quietly(self.cc.cmd_play, ["1"])

    def test_no_arguments_means_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cc.main([])
        self.assertIn("stopped", out.getvalue())

    def test_statusline_is_empty_when_silent_and_short_when_playing(self):
        m = self.start_mpv()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cc.cmd_statusline([])
        self.assertEqual(out.getvalue(), "", "an idle player shows nothing")
        self.tab("A", turn=1)
        m.props["metadata/by-key/icy-title"] = "x" * 100
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cc.cmd_statusline([])
        self.assertTrue(out.getvalue().startswith("♪ "))
        self.assertLessEqual(len(out.getvalue().strip()), 46)

    def test_working_explains_the_decision(self):
        self.tab("A", turn=1, waiting=1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.cc.cmd_working([])
        self.assertIn("waiting on you", out.getvalue())
        self.assertIn("-> silence", out.getvalue())

    def test_report_rejects_nonsense(self):
        with self.assertRaises(SystemExit):
            self.quietly(self.cc.cmd_report, ["A", "colour=blue"])
        with self.assertRaises(SystemExit):
            self.quietly(self.cc.cmd_report, [])

    def test_any_crash_is_one_line_not_a_traceback(self):
        self.cc.COMMANDS["boom"] = lambda a: (_ for _ in ()).throw(RuntimeError("kaput"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                self.cc.main(["boom"])
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(err.getvalue().count("\n"), 1)
        self.assertIn("kaput", err.getvalue())

    def test_missing_mpv_shows_an_install_hint_in_the_band(self):
        """A first-time user without mpv must see why nothing plays."""
        real = self.cc.find_mpv
        self.cc.find_mpv = lambda: None
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.cc.cmd_report(["A", "turn=1"])
            self.assertIn("install mpv", out.getvalue())
        finally:
            self.cc.find_mpv = real

    def test_auto_does_not_wait_out_a_fresh_start_delay(self):
        m = self.start_mpv()
        self.tab("A", turn=1)
        self.quietly(self.cc.cmd_off, [])
        t0 = time.time()
        self.quietly(self.cc.cmd_auto, [])
        self.assertLess(time.time() - t0, DELAY, "you asked for music: no delay")
        self.assertEqual(len(m.loads()), 2)

    def test_missing_mpv_is_reported_not_silent(self):
        real = self.cc.find_mpv
        self.cc.find_mpv = lambda: None
        try:
            self.assertIn("mpv is not installed", self.cc.describe())
        finally:
            self.cc.find_mpv = real


class TestConcurrency(Base):
    """Many tabs report at once. Nothing is lost, and nothing is left running."""

    def test_off_during_a_start_is_not_lost(self):
        """The old race: the reconciler saved mode=auto over your pause."""
        import threading
        m = self.start_mpv()
        gate = threading.Event()
        real_play = self.cc.play
        def slow_play(st, s=None):
            gate.set()
            time.sleep(0.4)                # the stream is starting...
            return real_play(st, s)
        self.cc.play = slow_play
        self.cc.report("A", {"turn": True})
        t = threading.Thread(target=self.cc.reconcile)
        t.start()
        gate.wait(2)
        env = dict(os.environ, CCRADIO_STATE_DIR=self.tmp, CCRADIO_SOCK=self.sock)
        subprocess.run([EXE, "off"], env=env, capture_output=True, timeout=10)   # ...you press pause
        t.join(5)
        self.assertEqual(self.cc.load_state()["mode"], "off", "your off must survive the start")
        self.cc.play = real_play

    def run_many(self, verb_args):
        if not self.mpv:
            self.start_mpv()           # subprocesses talk to the fake, never a real mpv
        env = dict(os.environ, CCRADIO_STATE_DIR=self.tmp, CCRADIO_SOCK=self.sock,
                   CCRADIO_SYNC="1", CCRADIO_START_DELAY="0")
        procs = [subprocess.Popen([EXE] + a, env=env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL) for a in verb_args]
        for p in procs:
            p.wait(timeout=30)
        return procs

    def test_concurrent_reports_do_not_lose_tabs(self):
        self.run_many([["report", "tab-%d" % i, "turn=1"] for i in range(12)])
        self.assertEqual(len(self.cc.read_tabs()), 12,
                         "a tab lost here is a tab that works while the music is off")

    def test_concurrent_ends_drain_the_set(self):
        self.start_mpv()
        self.run_many([["report", "tab-%d" % i, "turn=1"] for i in range(12)])
        self.run_many([["report", "tab-%d" % i, "turn=0"] for i in range(12)])
        self.assertFalse(any(r.get("turn") for r in self.cc.read_tabs().values()))
        self.assertTrue(self.mpv.props["idle-active"], "everything finished: silence")

    def test_only_one_stream_starts_when_tabs_race(self):
        m = self.start_mpv()
        self.run_many([["report", "tab-%d" % i, "turn=1"] for i in range(8)])
        self.assertEqual(len(m.loads()), 1, "eight tabs racing must start one stream, not eight")

    def test_the_hook_path_leaves_no_process_behind(self):
        """With forking on, the child must detach from our pipes and exit on its own."""
        self.start_mpv()               # or the child would start a real mpv
        env = dict(os.environ, CCRADIO_STATE_DIR=self.tmp, CCRADIO_SOCK=self.sock,
                   CCRADIO_START_DELAY="0.2")
        env.pop("CCRADIO_SYNC", None)
        t0 = time.time()
        r = subprocess.run([EXE, "report", "A", "turn=1"], env=env, capture_output=True,
                           timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.time() - t0, 1.5, "the hook must return before the start delay")
        time.sleep(0.8)
        left = subprocess.run(["pgrep", "-f", "%s report A" % EXE], capture_output=True, text=True)
        self.assertEqual(left.stdout.strip(), "", "the reconciler child must have exited")


class TestDebugLog(Base):
    def test_silent_and_writes_nothing_when_off(self):
        os.environ.pop("CCRADIO_DEBUG", None)
        self.cc.log("should not appear")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "debug.log")))

    def test_records_when_on(self):
        os.environ["CCRADIO_DEBUG"] = "1"
        try:
            self.cc.log("hello %s", "world")
            with open(os.path.join(self.tmp, "debug.log")) as fh:
                self.assertIn("hello world", fh.read())
        finally:
            os.environ.pop("CCRADIO_DEBUG", None)

    def test_never_raises_even_when_unwritable(self):
        os.environ["CCRADIO_DEBUG"] = "1"
        try:
            os.environ["CCRADIO_STATE_DIR"] = "/proc/nonexistent/nope"
            self.cc.log("must not raise")
        finally:
            os.environ["CCRADIO_STATE_DIR"] = self.tmp
            os.environ.pop("CCRADIO_DEBUG", None)

    def test_rotates_instead_of_growing_forever(self):
        os.environ["CCRADIO_DEBUG"] = "1"
        try:
            path = os.path.join(self.tmp, "debug.log")
            with open(path, "w") as fh:
                fh.write("x" * (self.cc.LOG_MAX + 1))
            self.cc.log("after rotation")
            self.assertTrue(os.path.exists(path + ".1"))
            self.assertLess(os.path.getsize(path), 200)
        finally:
            os.environ.pop("CCRADIO_DEBUG", None)

    def test_the_trace_explains_every_decision(self):
        os.environ["CCRADIO_DEBUG"] = "1"
        try:
            self.start_mpv()
            self.tab("A", turn=1)
            self.tab("A", waiting=1)
            self.tab("A", turn=0, waiting=0)
            with open(os.path.join(self.tmp, "debug.log")) as fh:
                trace = fh.read()
            for needle in ("report A", "reconcile: play", "reconcile: pause", "waiting on you"):
                self.assertIn(needle, trace)
        finally:
            os.environ.pop("CCRADIO_DEBUG", None)


class TestPlaylistResolution(Base):
    def test_direct_stream_url_passes_through_untouched(self):
        u = "https://ice2.somafm.com/groovesalad-256-mp3"
        self.assertEqual(self.cc.resolve_pls(u), u)

    def test_hls_passes_through(self):
        u = "https://example.com/live.m3u8"
        self.assertEqual(self.cc.resolve_pls(u), u)


class TestPlugin(unittest.TestCase):
    """The plugin wrapper must stay valid and consistent."""

    def test_manifests_parse(self):
        for p in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                  "hooks/hooks.json", "stations/curated.json"):
            with open(os.path.join(ROOT, p)) as fh:
                json.load(fh)

    def test_the_mod_is_wired(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as fh:
            hooks = json.load(fh)
        self.assertEqual(hooks.get("modules"), ["./register.js"])
        self.assertTrue(os.path.exists(os.path.join(ROOT, "hooks", "register.js")))
        self.assertNotIn("hooks", hooks, "settings hooks would double-drive the player")

    def test_the_mod_reports_through_the_one_verb(self):
        """Every path from the mod into scripts/ccradio is a command this file dispatches."""
        with open(os.path.join(ROOT, "hooks", "register.js")) as fh:
            src = fh.read()
        cc = load_module("m")
        import re
        for verb in re.findall(r'run\(\$, \["(\w+)"', src):
            self.assertIn(verb, cc.COMMANDS, "the mod calls '%s' but it is not wired up" % verb)
        self.assertIn("reportArgs(", src)

    def test_the_mod_only_watches_events_that_exist(self):
        """A misspelled event is a hook that never runs. Pin the spellings."""
        with open(os.path.join(ROOT, "hooks", "register.js")) as fh:
            src = fh.read()
        import re
        known = {
            "session.start", "session.end", "turn.start", "turn.complete",
            "agent.spawn", "tool.check", "tool.call", "command.run", "ui.render",
        }
        used = set(re.findall(r'on\("([a-zA-Z.]+)"', src))
        self.assertTrue(used, "no hooks found")
        self.assertEqual(used - known, set(), "unknown event names")
        self.assertFalse([e for e in used if e.startswith("classic.")],
                         "classic.* hooks are bypassed for a user mod under the built-in guard")

    def test_version_strings_agree(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            v = json.load(fh)["version"]
        cc = load_module("m2")
        self.assertEqual(cc.VERSION, v)

    def test_executables_are_executable(self):
        self.assertTrue(os.access(EXE, os.X_OK))

    def test_every_command_in_usage_is_dispatchable(self):
        cc = load_module("m3")
        for line in cc.USAGE.splitlines()[2:]:
            line = line.strip()
            if not line:
                continue
            for verb in line.split()[0:1] + [w for w in line.split()[1:3] if w in cc.COMMANDS]:
                verb = verb.strip("/")
                if verb in ("/", "|"):
                    continue
                self.assertIn(verb, cc.COMMANDS, "USAGE lists '%s' but it is not wired up" % verb)


if __name__ == "__main__":
    unittest.main(verbosity=1)
