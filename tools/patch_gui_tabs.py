"""One-off patch: convert GUIWindow to multi-tab layout."""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "venv/Lib/site-packages/argostranslategui/gui.py"
text = p.read_text(encoding="utf-8")

if "    def _REMOVE_OLD_INIT_MARKER" in text:
    start = text.index("    def _REMOVE_OLD_INIT_MARKER")
    end = text.index("    def maybe_open_glossary_on_startup")
    insert = open(Path(__file__).parent / "patch_gui_tabs_insert.txt", encoding="utf-8").read()
    text = text[:start] + insert + text[end:]
    print("removed old init block")

if "    def _apply_language_combos(self" in text:
    s = text.index("    def _apply_language_combos(self")
    e = text.index("    def closeEvent(self, event):")
    mid = (
        "    def load_languages(self):\n"
        "        self.languages = _get_argos_translate().load_installed_languages()\n"
        "        for tab in self._iter_tabs():\n"
        "            tab.apply_language_combos(run_translate=not _fast_startup_enabled())\n\n"
    )
    text = text[:s] + mid + text[e:]
    print("removed apply_language_combos block")

text = text.replace(
    """    def _start_language_load_async(self) -> None:
        self.right_textEdit.setPlaceholderText("正在加载语言包，界面已就绪…")
        self.left_language_combo.setEnabled(False)
        self.right_language_combo.setEnabled(False)""",
    """    def _start_language_load_async(self) -> None:
        for tab in self._iter_tabs():
            tab.right_textEdit.setPlaceholderText("正在加载语言包，界面已就绪…")
            tab.left_language_combo.setEnabled(False)
            tab.right_language_combo.setEnabled(False)""",
)

text = text.replace(
    """    def _on_languages_loaded(self, languages: object) -> None:
        self._lang_load_worker = None
        self.left_language_combo.setEnabled(True)
        self.right_language_combo.setEnabled(True)
        self.languages = list(languages) if languages else []
        self._apply_language_combos(run_translate=False)""",
    """    def _on_languages_loaded(self, languages: object) -> None:
        self._lang_load_worker = None
        self.languages = list(languages) if languages else []
        for tab in self._iter_tabs():
            tab.left_language_combo.setEnabled(True)
            tab.right_language_combo.setEnabled(True)
            tab.apply_language_combos(run_translate=False)""",
)

# load_failed may already be patched or use different format
if "for tab in self._iter_tabs():" not in text.split("_on_languages_load_failed")[1][:400]:
    text = text.replace(
        """    def _on_languages_load_failed(self, msg: str) -> None:
        self.left_language_combo.setEnabled(True)
        self.right_language_combo.setEnabled(True)
        self.right_textEdit.setPlaceholderText""",
        """    def _on_languages_load_failed(self, msg: str) -> None:
        for tab in self._iter_tabs():
            tab.left_language_combo.setEnabled(True)
            tab.right_language_combo.setEnabled(True)
            tab.right_textEdit.setPlaceholderText""",
        1,
    )

text = text.replace(
    """    def closeEvent(self, event):
        w = getattr(self, "_offline_speech_worker", None)
        if w is not None and w.isRunning():
            w.request_stop()
            w.wait(10000)
        super().closeEvent(event)""",
    """    def closeEvent(self, event):
        for tab in self._iter_tabs():
            tab.shutdown()
        super().closeEvent(event)""",
)

# drop duplicate load_languages if any
while text.count("    def load_languages(self):") > 1:
    i = text.index("    def load_languages(self:")
    j = text.index("    def ", i + 10)
    text = text[:i] + text[j:]

p.write_text(text, encoding="utf-8")
print("done", p)
