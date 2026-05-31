"""Measure cold-start: window visible vs full engine ready."""
import os
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "venv" / "Lib" / "site-packages"))
sys.path.insert(0, str(root))
os.environ["ARGOS_FAST_STARTUP"] = "1"
os.environ.setdefault("XDG_DATA_HOME", str(root / "data" / "local"))
os.environ.setdefault("XDG_CONFIG_HOME", str(root / "data" / "config"))
os.environ.setdefault("XDG_CACHE_HOME", str(root / "data" / "cache"))

t0 = time.perf_counter()


def lap(label: str) -> None:
    print(f"{label}: {time.perf_counter() - t0:.3f}s")


lap("start")
import argostranslategui.gui as gui_mod

lap("gui module (no ctranslate2 yet)")
from PyQt5.QtWidgets import QApplication

app = QApplication([])
lap("QApplication")
win = gui_mod.GUIWindow()
lap("GUIWindow()")
win.show()
app.processEvents()
lap("window visible (first paint)")
import time

time.sleep(0.35)
app.processEvents()
lap("after 350ms (language load may start)")
