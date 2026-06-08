import os
import sys
import tkinter as tk

from core.ui.ui_main import MainUI


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    root = tk.Tk()
    root.minsize(1200, 640)
    MainUI(root, base_dir=get_base_dir())
    root.mainloop()


if __name__ == "__main__":
    main()
