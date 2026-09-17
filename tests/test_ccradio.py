#!/usr/bin/env python3
"""Tests for ccradio. No mpv, no network, no speakers required.

Run:  python3 tests/test_ccradio.py
"""

import json
import os
import shutil
import socket
import tempfile
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
        base = {"volume": 70.0, "pause": False, "idle-active": False, "path": ""}
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


class TestDuck(Base):
    def test_duck_lowers_and_unduck_restores_exactly(self):
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state()
        s["volume"] = 80
        self.cc.save_state(s)

        self.cc.cmd_duck([])
        self.assertEqual(m.props["volume"], 20, "80 * 0.25")
        self.assertTrue(self.cc.load_state()["ducked"])

        self.cc.cmd_unduck([])
        self.assertEqual(m.props["volume"], 80)
        self.assertFalse(self.cc.load_state()["ducked"])

    def test_duck_respects_floor_at_low_volume(self):
        m = self.start_mpv(volume=8.0)
        s = self.cc.load_state()
        s["volume"] = 8
        self.cc.save_state(s)
        self.cc.cmd_duck([])
        self.assertEqual(m.props["volume"], self.cc.DUCK_FLOOR, "never below the floor")

    def test_double_duck_does_not_stack(self):
        m = self.start_mpv(volume=80.0)
        s = self.cc.load_state()
        s["volume"] = 80
        self.cc.save_state(s)
        self.cc.cmd_duck([])
        self.cc.cmd_duck([])
        self.cc.cmd_unduck([])
        self.assertEqual(m.props["volume"], 80, "two ducks then one unduck must restore")

    def test_unduck_without_duck_is_a_noop(self):
        m = self.start_mpv(volume=80.0)
        self.cc.cmd_unduck([])
        self.assertEqual(m.props["volume"], 80)

    def test_duck_with_no_daemon_does_not_raise_or_set_flag(self):
        self.cc.cmd_duck([])
        self.assertFalse(self.cc.load_state()["ducked"])


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


class TestSessionRefcount(Base):
    def test_counts_up_and_down(self):
        self.start_mpv()
        for _ in range(3):
            self.cc.cmd_session(["start"])
        self.assertEqual(self.cc.load_state()["sessions"], 3)
        self.cc.cmd_session(["end"])
        self.assertEqual(self.cc.load_state()["sessions"], 2)

    def test_never_goes_negative(self):
        self.cc.cmd_session(["end"])
        self.cc.cmd_session(["end"])
        self.assertEqual(self.cc.load_state()["sessions"], 0)

    def test_last_session_out_stops_daemon(self):
        m = self.start_mpv()
        self.cc.cmd_session(["start"])
        self.cc.cmd_session(["end"])
        self.assertIn(["quit"], m.seen, "daemon must be told to quit at zero sessions")

    def test_daemon_survives_while_another_session_lives(self):
        m = self.start_mpv()
        self.cc.cmd_session(["start"])
        self.cc.cmd_session(["start"])
        self.cc.cmd_session(["end"])
        self.assertNotIn(["quit"], m.seen, "music must survive one window closing")


class TestIdlePause(Base):
    """Stop hook pauses; UserPromptSubmit resumes. Manual intent always wins."""

    def _busy(self, n):
        s = self.cc.load_state()
        s["sessions"] = n
        s["busy"] = n
        self.cc.save_state(s)

    def test_pauses_when_the_only_session_goes_idle(self):
        m = self.start_mpv(pause=False)
        self._busy(1)
        self.cc.cmd_idle([])
        self.assertTrue(m.props["pause"], "music must stop when Claude waits on you")
        self.assertTrue(self.cc.load_state()["autopaused"])

    def test_resumes_on_next_prompt(self):
        m = self.start_mpv(pause=False)
        self._busy(1)
        self.cc.cmd_idle([])
        self.cc.cmd_active([])
        self.assertFalse(m.props["pause"])
        self.assertFalse(self.cc.load_state()["autopaused"])

    def test_keeps_playing_while_another_window_is_still_working(self):
        m = self.start_mpv(pause=False)
        self._busy(2)
        self.cc.cmd_idle([])
        self.assertFalse(m.props["pause"], "one window idle, another working - keep playing")
        self.cc.cmd_idle([])
        self.assertTrue(m.props["pause"], "now every window is idle")

    def test_does_not_resume_music_you_paused_by_hand(self):
        m = self.start_mpv(pause=False)
        self._busy(1)
        self.cc.cmd_pause([])                    # you hit pause
        self.assertTrue(m.props["pause"])
        self.cc.cmd_idle([])
        self.cc.cmd_active([])                   # you send a prompt
        self.assertTrue(m.props["pause"], "your pause must survive the hooks")

    def test_hand_pause_during_autopause_sticks(self):
        m = self.start_mpv(pause=False)
        self._busy(1)
        self.cc.cmd_idle([])                     # hooks pause it
        self.cc.cmd_pause([])                    # you resume by hand
        self.assertFalse(m.props["pause"])
        self.cc.cmd_active([])
        self.assertFalse(m.props["pause"], "still playing, not re-paused")

    def test_busy_never_goes_negative_when_hooks_are_missed(self):
        self.start_mpv(pause=False)
        for _ in range(5):
            self.cc.cmd_idle([])
        self.assertEqual(self.cc.load_state()["busy"], 0)

    def test_busy_is_capped_at_session_count(self):
        self.start_mpv(pause=False)
        s = self.cc.load_state()
        s["sessions"] = 2
        self.cc.save_state(s)
        for _ in range(6):
            self.cc.cmd_active([])
        self.assertLessEqual(self.cc.load_state()["busy"], 2)

    def test_idle_with_no_daemon_is_harmless(self):
        self.cc.cmd_idle([])
        self.assertFalse(self.cc.load_state()["autopaused"])


class TestAutoResume(Base):
    def test_remembers_it_was_playing_when_last_window_closed(self):
        self.start_mpv(pause=False)
        self.cc.cmd_session(["start"])
        self.cc.cmd_session(["end"])
        self.assertTrue(self.cc.load_state()["was_playing"])

    def test_remembers_silence_when_you_stopped_it(self):
        self.start_mpv(pause=False)
        self.cc.cmd_session(["start"])
        self.cc.cmd_stop([])
        self.cc.cmd_session(["end"])
        self.assertFalse(self.cc.load_state()["was_playing"],
                         "stopping by hand must not auto-resume next time")

    def test_paused_at_shutdown_counts_as_not_playing(self):
        self.start_mpv(pause=True)
        self.cc.cmd_session(["start"])
        self.cc.cmd_session(["end"])
        self.assertFalse(self.cc.load_state()["was_playing"])

    def test_first_session_resumes_previous_station(self):
        m = self.start_mpv(pause=False)
        s = self.cc.load_state()
        s["was_playing"] = True
        s["station"] = "soma-dronezone"
        s["sessions"] = 0
        self.cc.save_state(s)
        self.cc.cmd_session(["start"])
        loads = [c for c in m.seen if c and c[0] == "loadfile"]
        self.assertTrue(loads, "should have resumed playback")
        self.assertIn("dronezone", loads[0][1])

    def test_second_window_does_not_restart_playback(self):
        m = self.start_mpv(pause=False)
        s = self.cc.load_state()
        s["was_playing"] = True
        s["station"] = "soma-dronezone"
        s["sessions"] = 1
        self.cc.save_state(s)
        self.cc.cmd_session(["start"])
        self.assertEqual([c for c in m.seen if c and c[0] == "loadfile"], [],
                         "opening a second window must not restart the stream")

    def test_no_resume_when_it_was_not_playing(self):
        m = self.start_mpv(pause=False)
        s = self.cc.load_state()
        s["was_playing"] = False
        s["station"] = "soma-dronezone"
        s["sessions"] = 0
        self.cc.save_state(s)
        self.cc.cmd_session(["start"])
        self.assertEqual([c for c in m.seen if c and c[0] == "loadfile"], [])


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
        self.assertEqual(sorted(hooks),
                         ["SessionEnd", "SessionStart", "Stop", "UserPromptSubmit"])
        wiring = {ev: v[0]["hooks"][0]["command"].rsplit('"', 1)[-1].strip()
                  for ev, v in hooks.items()}
        self.assertEqual(wiring["Stop"], "idle")
        self.assertEqual(wiring["UserPromptSubmit"], "active")
        self.assertEqual(wiring["SessionStart"], "session start")
        self.assertEqual(wiring["SessionEnd"], "session end")

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
