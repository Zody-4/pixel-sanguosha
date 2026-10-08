"""Bounded local session records and thread snapshots; never alter game decisions."""
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

from xssgkpz.persistence import data_directory

_session = None


class Session:
    def __init__(self):
        root = data_directory() / 'diagnostics'
        root.mkdir(parents=True, exist_ok=True)
        name = time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid())
        self.folder = root / name
        self.folder.mkdir()
        # Each session is bounded by time/count; keep six prior sessions.
        def owned(path):
            parts = path.name.split('-')
            return (path.is_dir() and path != self.folder and path.resolve().parent == root.resolve()
                    and len(parts) == 3 and all(part.isdigit() for part in parts)
                    and len(parts[0]) == 8 and len(parts[1]) == 6)
        for old in sorted((p for p in root.iterdir() if owned(p)),
                          key=lambda p: p.name, reverse=True)[6:]:
            for filename in ('events.jsonl', 'threads.log'):
                (old / filename).unlink(missing_ok=True)
            try:
                old.rmdir()
            except OSError:
                pass
        self.events = (self.folder / 'events.jsonl').open('a', encoding='utf-8', buffering=1)
        self.threads = (self.folder / 'threads.log').open('a', encoding='utf-8', buffering=1)
        self.lock = threading.RLock()
        self.last_tick = time.monotonic()
        self.last_record = 0.0
        self.stage = 'startup'
        self.context = {}
        self.count = 0
        self.stop_event = threading.Event()
        self.native_enabled = False
        self.write('session_start', python=sys.version, pygame=__import__('pygame').version.ver,
                   build='pc-diagnostics-01', frozen=bool(getattr(sys, 'frozen', False)))
        try:
            faulthandler.enable(file=self.threads, all_threads=True)
            # Independent native watchdog also captures C calls holding the GIL.
            # These periodic snapshots alone do not imply a hang.
            faulthandler.dump_traceback_later(60, repeat=True, file=self.threads)
            self.native_enabled = True
        except (RuntimeError, OSError):
            self.write('native_watchdog_unavailable')
        self.worker = threading.Thread(target=self.watch, name='game-diagnostics', daemon=True)
        self.worker.start()
        self.write('watchdog_ready', native=self.native_enabled, stall_seconds=8, periodic_seconds=60)

    def write(self, kind, **values):
        try:
            with self.lock:
                if self.count >= 50000:
                    return
                self.count += 1
                row = dict(time=time.strftime('%Y-%m-%d %H:%M:%S'),
                           monotonic=round(time.monotonic(), 3), event=kind, **values)
                self.events.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        except Exception:
            pass

    def watch(self):
        last_dump = 0.0
        while not self.stop_event.wait(1):
            now = time.monotonic()
            if now - self.last_tick >= 8 and now - last_dump >= 30:
                last_dump = now
                self.write('suspected_stall', seconds=round(now-self.last_tick, 1),
                           stage=self.stage, context=self.context)
                try:
                    with self.lock:
                        self.threads.write('\nSuspected stall: ' + self.stage + '\n')
                        self.threads.flush()
                        faulthandler.dump_traceback(file=self.threads, all_threads=True)
                except Exception:
                    pass

    def close(self):
        self.stop_event.set()
        self.worker.join(timeout=2)
        self.write('session_end')
        if self.native_enabled:
            faulthandler.cancel_dump_traceback_later()
            faulthandler.disable()
        with self.lock:
            self.events.close()
            self.threads.close()


def start():
    global _session
    try:
        _session = Session()
    except Exception:
        _session = None  # An unavailable log directory must not prevent play.


def stop():
    global _session
    session, _session = _session, None
    if session:
        try:
            session.close()
        except Exception:
            pass


def heartbeat(app, stage):
    session = _session
    if session is None:
        return
    now = time.monotonic()
    session.last_tick = now
    session.stage = stage
    if now - session.last_record < 1:
        return
    session.last_record = now
    try:
        engine = app.engine
        state = getattr(engine, 'state', None)
        session.context = dict(page=app.page, pause=app.pause_open,
                               seed=getattr(app, 'setup_seed', None),
                               mode=getattr(state, 'mode_id', None),
                               turn=getattr(state, 'turn_number', None),
                               player=getattr(state, 'current_player_id', None),
                               phase=str(getattr(state, 'phase', '')),
                               request=str(getattr(getattr(engine, 'pending_request', None), 'kind', '')))
        session.write('heartbeat', stage=stage, context=session.context)
    except Exception:
        pass


def action(app, value):
    if _session:
        _session.last_record = 0
        heartbeat(app, 'action')
        _session.write('action', action=value, context=_session.context)


def exception():
    if _session:
        _session.write('exception', traceback=traceback.format_exc(),
                       stage=_session.stage, context=_session.context)
