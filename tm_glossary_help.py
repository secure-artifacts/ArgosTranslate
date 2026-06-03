"""术语库与翻译记忆（TM）的用户说明。"""
from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox

HELP_TITLE = "术语库与 TM 的区别"

HELP_TEXT = """【术语库】记的是词语、专名、固定说法。
例如：把「联合国」固定译成「ООН」。
机器翻译完成后，程序会把译文里对应的词换成你设的译法。
在窗口顶部点「术语库」即可编辑。

【翻译记忆 TM】记的是整句原文和整句译文。
例如：整句「欢迎来华访问」配整句译文。
下次遇到相同原文，直接采用你保存的整句，不再机器翻译。
在译文下方点「采纳为 TM」可保存当前句对；分句稿件模式下每行右侧也可采纳。
导入、导出等在本页「查看 TM」窗口。

怎么选？
· 只想统一某个词、专名的译法 → 用语术语库
· 某整句已经翻好、希望下次直接用 → 用 TM

可以一起用：先查 TM，没有命中再机器翻译，术语库再修正用词。"""


def show_tm_glossary_help(parent=None) -> None:
    QMessageBox.information(parent, HELP_TITLE, HELP_TEXT)
