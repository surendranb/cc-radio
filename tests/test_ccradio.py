#!/usr/bin/env python3
"""Tests for ccradio. No mpv, no network, no speakers required.

Run:  python3 tests/test_ccradio.py
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import time
import threading
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_cli(state_dir, sock):
    os.environ["CCRADIO_STATE_DIR"] = state_dir
    os.environ["CCRADIO_SOCK"] = sock
    return SourceFileLoader("ccradio_mod", os.path.join(ROOT, "bin", "ccradio")).load_module()


class FakeMpv:
    """Minimal mpv IPC stand-in: records commands, replies with canned data."""

    def __init__(self, path, props=None):
        self.path = path
        self.props = props or {}
        self.seen = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(8)
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
                    elif cmd[0] == "cycle" and cmd[1] == "pause":
                        self.props["pause"] = not self.props.get("pause", False)
                    conn.sendall((json.dumps(
                        {"request_id": msg["request_id"], "error": "success",
                         "data": out}) + "\n").encode())
            except Exception:
                pass
            finally:
                conn.close()

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

    def tearDown(self):
        if self.mpv:
            self.mpv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start_mpv(self, **props):
        base = {"volume": 70.0, "pause": False, "idle-active": True, "path": ""}
        base.update(props)
        self.mpv = FakeMpv(self.sock, base)
        return self.mpv


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

    def test_fallback_used_when_curated_missing(self):
        self.cc.CURATED = os.path.join(self.tmp, "gone.json")
        self.assertEqual(len(self.cc.stations()), len(self.cc.FALLBACK))

    def test_fallback_used_when_curated_corrupt(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as fh:
            fh.write("{not json")
        self.cc.CURATED = bad
        self.assertEqual(len(self.cc.stations()), len(self.cc.FALLBACK))


class TestOrder(Base):
    def test_order_repairs_when_stations_change_underneath(self):
        live = [s["id"] for s in self.cc.stations()]
        s = {"order": ["deleted-station", live[2], live[0]]}
        order = self.cc.order_ids(s)
        self.assertNotIn("deleted-station", order)
        self.assertEqual(sorted(order), sorted(live), "every live station must appear once")
        self.assertEqual(order[:2], [live[2], live[0]], "existing order preserved")

    def test_empty_order_falls_back_to_full_list(self):
        live = [s["id"] for s in self.cc.stations()]
        self.assertEqual(self.cc.order_ids({"order": []}), live)


class TestState(Base):
    def test_roundtrip_and_defaults(self):
        s = self.cc.load_state()
        self.assertEqual(s["volume"], 70)
        s["volume"] = 42
        self.cc.save_state(s)
        self.assertEqual(self.cc.load_state()["volume"], 42)

    def test_corrupt_state_falls_back_to_defaults(self):
        with open(self.cc.state_path(), "w") as fh:
            fh.write("{{{garbage")
        self.assertEqual(self.cc.load_state()["volume"], 70)

    def test_save_leaves_no_temp_files(self):
        self.cc.save_state(self.cc.load_state())
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TestIPC(Base):
    def test_not_running_raises_when_no_socket(self):
        with self.assertRaises(self.cc.NotRunning):
            self.cc.ipc("get_property", "volume")

    def test_alive_false_without_daemon(self):
        self.assertFalse(self.cc.alive())

    def test_alive_true_with_daemon(self):
        self.start_mpv()
        self.assertTrue(self.cc.alive())

    def test_set_volume_sends_exact_command_and_clamps(self):
        m = self.start_mpv()
        self.assertEqual(self.cc.set_volume(55), 55)
        self.assertIn(["set_property", "volume", 55], m.seen)
        self.assertEqual(self.cc.set_volume(-20), 0, "clamps at floor")
        self.assertEqual(self.cc.set_volume(9999), self.cc.VOL_MAX, "clamps at ceiling")

    def test_volume_persists_when_daemon_is_down(self):
        self.assertEqual(self.cc.set_volume(33), 33)
        self.assertEqual(self.cc.load_state()["volume"], 33)


class TestNowPlaying(Base):
    def test_returns_icy_title(self):
        self.start_mpv(**{"metadata/by-key/icy-title": "Artist - Track",
                          "path": "https://ice2.somafm.com/lush-128-mp3"})
        self.assertEqual(self.cc.now_playing(), "Artist - Track")

    def test_suppresses_url_basename_placeholder(self):
        self.start_mpv(**{"media-title": "lush-128-mp3",
                          "path": "https://ice2.somafm.com/lush-128-mp3"})
        self.assertIsNone(self.cc.now_playing(), "stream filename is not a track name")

    def test_suppresses_raw_url(self):
        self.start_mpv(**{"media-title": "https://ice2.somafm.com/lush-128-mp3",
                          "path": "https://ice2.somafm.com/lush-128-mp3"})
        self.assertIsNone(self.cc.now_playing())

    def test_handles_missing_metadata(self):
        self.start_mpv(path="https://ice2.somafm.com/lush-128-mp3")
        self.assertIsNone(self.cc.now_playing())


class TestWorkingSignal(Base):
    """Music plays while ANY tab is working, and only then."""

    A = '{"session_id":"tab-A"}'
    B = '{"session_id":"tab-B"}'

    def _as(self, payload, fn):
        """Run a hook command as if it came from that tab."""
        import io
        real, sys.stdin = sys.stdin, io.StringIO(payload)
        try:
            sys.stdin.isatty = lambda: False
            fn([])
        finally:
            sys.stdin = real

    def test_quick_turn_stays_silent(self):
        self.start_mpv()
        self.cc.START_DELAY = 0.4
        self._as(self.A, self.cc.cmd_arm)
        self._as(self.A, self.cc.cmd_disarm)
        time.sleep(0.9)
        self.assertEqual([c for c in self.mpv.seen if c and c[0] == "loadfile"], [],
                         "a two-second answer must not trigger music")

    def test_long_turn_starts_music(self):
        self.start_mpv()
        self.cc.START_DELAY = 0.3
        self._as(self.A, self.cc.cmd_arm)
        time.sleep(1.4)
        self.assertTrue([c for c in self.mpv.seen if c and c[0] == "loadfile"])

    def test_second_tab_does_not_stomp_the_station(self):
        self.start_mpv()
        self.cc.START_DELAY = 0.3
        self._as(self.A, self.cc.cmd_arm)
        time.sleep(1.2)
        before = len([c for c in self.mpv.seen if c and c[0] == "loadfile"])
        self._as(self.B, self.cc.cmd_arm)
        time.sleep(1.2)
        after = len([c for c in self.mpv.seen if c and c[0] == "loadfile"])
        self.assertEqual(before, after,
                         "a second tab joining must not change the station")

    def test_one_tab_finishing_keeps_music_for_the_others(self):
        self._as(self.A, self.cc.cmd_arm)
        self._as(self.B, self.cc.cmd_arm)
        m = self.start_mpv()
        self._as(self.A, self.cc.cmd_disarm)
        self.assertNotIn(["quit"], m.seen,
                         "tab A finishing must not silence tab B's music")
        self.assertIn("tab-B", self.cc.read_working())

    def test_music_stops_only_when_every_tab_is_done(self):
        self._as(self.A, self.cc.cmd_arm)
        self._as(self.B, self.cc.cmd_arm)
        m = self.start_mpv()
        self._as(self.A, self.cc.cmd_disarm)
        self._as(self.B, self.cc.cmd_disarm)
        self.assertIn(["quit"], m.seen)
        self.assertEqual(self.cc.read_working(), {})

    def test_repeated_disarm_is_harmless(self):
        self._as(self.A, self.cc.cmd_arm)
        self._as(self.A, self.cc.cmd_disarm)
        self._as(self.A, self.cc.cmd_disarm)
        self.assertEqual(self.cc.read_working(), {})

    def test_stale_tabs_are_forgotten(self):
        self.cc.write_working({"crashed-tab": time.time() - self.cc.STALE_AFTER - 10,
                               "live-tab": time.time()})
        self.assertEqual(list(self.cc.read_working()), ["live-tab"],
                         "a tab that never reported finishing must not wedge the radio on")

    def test_sessions_are_told_apart(self):
        self._as(self.A, self.cc.cmd_arm)
        self._as(self.B, self.cc.cmd_arm)
        self.assertEqual(sorted(self.cc.read_working()), ["tab-A", "tab-B"])


class TestDuckSignal(Base):
    def _as(self, sid, fn):
        import io
        real, sys.stdin = sys.stdin, io.StringIO('{"session_id":"%s"}' % sid)
        try:
            sys.stdin.isatty = lambda: False
            fn([])
        finally:
            sys.stdin = real

    def _tab_is_working(self, sid="tab-A"):
        self.cc.write_working({sid: time.time()})

    def test_subagent_notification_does_not_duck(self):
        """A subagent going idle must not dip a real tab's music."""
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state(); s["volume"] = 80; self.cc.save_state(s)
        self._tab_is_working("tab-A")
        self._as("some-subagent-session", self.cc.cmd_duck)
        self.assertEqual(m.props["volume"], 80, "subagent idle must not duck")
        self.assertFalse(self.cc.load_state()["ducked"])

    def test_real_tab_notification_still_ducks(self):
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state(); s["volume"] = 80; self.cc.save_state(s)
        self._tab_is_working("tab-A")
        self._as("tab-A", self.cc.cmd_duck)
        self.assertEqual(m.props["volume"], 20)

    def test_duck_and_restore(self):
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state(); s["volume"] = 80; self.cc.save_state(s)
        self._tab_is_working("tab-A")
        self._as("tab-A", self.cc.cmd_duck)
        self.assertEqual(m.props["volume"], 20)
        self.cc.cmd_unduck([])
        self.assertEqual(m.props["volume"], 80)

    def test_duck_respects_floor(self):
        m = self.start_mpv(volume=8.0)
        s = self.cc.load_state(); s["volume"] = 8; self.cc.save_state(s)
        self._tab_is_working("tab-A")
        self._as("tab-A", self.cc.cmd_duck)
        self.assertEqual(m.props["volume"], self.cc.DUCK_FLOOR)

    def test_double_duck_does_not_stack(self):
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state(); s["volume"] = 80; self.cc.save_state(s)
        self._tab_is_working("tab-A")
        self._as("tab-A", self.cc.cmd_duck)
        self._as("tab-A", self.cc.cmd_duck)
        self.cc.cmd_unduck([])
        self.assertEqual(m.props["volume"], 80)

    def test_duck_without_daemon_is_harmless(self):
        self._tab_is_working("tab-A")
        self._as("tab-A", self.cc.cmd_duck)
        self.assertFalse(self.cc.load_state()["ducked"])

    def test_replying_lifts_the_duck(self):
        """The duck means Claude is waiting on you. Replying means it is not."""
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state(); s["volume"] = 80; self.cc.save_state(s)
        self._tab_is_working("tab-A")
        self._as("tab-A", self.cc.cmd_duck)
        self.assertEqual(m.props["volume"], 20)
        self._as("tab-A", self.cc.cmd_arm)
        self.assertEqual(m.props["volume"], 80,
                         "answering the prompt must bring the volume back")
        self.assertFalse(self.cc.load_state()["ducked"])

    def test_duck_lifts_even_while_another_tab_works(self):
        """cmd_arm returns early when another tab is already working, so an
        unduck placed after that return would never run for a second tab."""
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state(); s["volume"] = 80; self.cc.save_state(s)
        self.cc.write_working({"tab-A": time.time(), "tab-B": time.time()})
        self._as("tab-A", self.cc.cmd_duck)
        self.assertEqual(m.props["volume"], 20)
        self._as("tab-B", self.cc.cmd_arm)
        self.assertEqual(m.props["volume"], 80)

    def test_stale_duck_flag_clears_without_a_daemon(self):
        """A duck left saved by a session that ended must not quietly hold the
        next session's music at a quarter volume."""
        s = self.cc.load_state()
        s.update(ducked=True, preduck=70, volume=70)
        self.cc.save_state(s)
        self._as("tab-A", self.cc.cmd_arm)
        self.assertFalse(self.cc.load_state()["ducked"])


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

    def test_all_four_hooks_declared(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as fh:
            hooks = json.load(fh)["hooks"]
        wiring = {ev: v[0]["hooks"][0]["command"].rsplit('"', 1)[-1].strip()
                  for ev, v in hooks.items()}
        self.assertEqual(wiring, {
            "UserPromptSubmit": "arm",      # Claude starts working -> music
            "Stop": "disarm",               # Claude finishes -> silence
            "Notification": "duck",         # Claude needs you -> quiet
            "PermissionRequest": "duck",
            "SessionEnd": "disarm",
        })

    def test_executables_are_executable(self):
        for p in ("bin/ccradio", "hooks/hook.sh"):
            self.assertTrue(os.access(os.path.join(ROOT, p), os.X_OK), p)

    def test_every_command_in_usage_is_dispatchable(self):
        cc = SourceFileLoader("m", os.path.join(ROOT, "bin", "ccradio")).load_module()
        for line in cc.USAGE.splitlines():
            line = line.strip()
            if not line.startswith(("play", "next", "shuffle", "pause", "vol",
                                    "now", "status", "stations", "search", "stop")):
                continue
            verb = line.split()[0].split("/")[0]
            self.assertIn(verb, cc.COMMANDS, "USAGE lists '%s' but it is not wired up" % verb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
