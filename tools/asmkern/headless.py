# SPDX-License-Identifier: MIT
"""Verify a live, privately launched melonDS (never system/shared emulator)."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine_golden as eg

SANDBOX = ['--nosocket=x11', '--nosocket=fallback-x11', '--nosocket=wayland',
           '--nodevice=all', '--env=DISPLAY=', '--env=WAYLAND_DISPLAY=',
           '--env=QT_QPA_PLATFORM=offscreen', '--env=QT_QUICK_BACKEND=software',
           '--env=LIBGL_ALWAYS_SOFTWARE=1']


def verify_live(rom, work):
    pids = eg.owned_pids(Path(rom).resolve())
    assert len(pids) == 1, 'expected exactly one private emulator'
    proc = Path('/proc') / str(pids[0])
    env = dict(x.split(b'=', 1) for x in (proc / 'environ').read_bytes().split(b'\0') if b'=' in x)
    assert env[b'QT_QPA_PLATFORM'] == b'offscreen'
    assert not env.get(b'DISPLAY') and not env.get(b'WAYLAND_DISPLAY')
    assert env[b'XDG_CONFIG_HOME'] == os.fsencode(Path(work).resolve() / 'config')
    assert 'libqoffscreen.so' in (proc / 'maps').read_text()
    for fd in (proc / 'fd').iterdir():
        try:
            assert '/dev/dri' not in os.readlink(fd), 'GPU fd present'
        except FileNotFoundError:
            pass
    result = dict(pid=pids[0], starttime=(proc / 'stat').read_text().split(') ', 1)[1].split()[19],
                  qt_offscreen_plugin_verified=True, display_env_empty=True,
                  private_config_verified=True, gpu_device_denied='--nodevice=all', gpu_fds_absent=True)
    (Path(work) / 'live-headless.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
