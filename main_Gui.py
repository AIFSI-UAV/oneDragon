# main_Gui.py
import tkinter as tk
from tkinter import scrolledtext, filedialog

from worker_thread import DungeonWorker


class DungeonGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("App 自动化 Demo")

        self.worker = None
        self.config_path_var = tk.StringVar(value="dungeon_config.json")

        # 顶部：配置文件
        frame_top = tk.Frame(root)
        frame_top.pack(fill="x", padx=10, pady=5)

        tk.Label(frame_top, text="配置文件:").pack(side="left")
        tk.Entry(frame_top, textvariable=self.config_path_var, width=40).pack(
            side="left", padx=5
        )
        tk.Button(frame_top, text="浏览", command=self.choose_config).pack(side="left")

        # 中间：控制按钮
        frame_btn = tk.Frame(root)
        frame_btn.pack(fill="x", padx=10, pady=5)

        tk.Button(frame_btn, text="开始任务", command=self.start_tasks).pack(
            side="left", padx=5
        )
        tk.Button(frame_btn, text="停止任务", command=self.stop_tasks).pack(
            side="left", padx=5
        )

        # 下方：日志窗口
        self.log_box = scrolledtext.ScrolledText(
            root, width=80, height=25, state="disabled"
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=5)

    def choose_config(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.config_path_var.set(path)

    def log(self, text: str):
        """线程安全地向文本框追加日志"""
        def append():
            self.log_box.configure(state="normal")
            self.log_box.insert(tk.END, text + "\n")
            self.log_box.see(tk.END)
            self.log_box.configure(state="disabled")

        self.root.after(0, append)

    def start_tasks(self):
        if self.worker is not None and self.worker.is_alive():
            self.log("任务仍在运行中，请先停止")
            return

        config_path = self.config_path_var.get()
        self.log(f"使用配置: {config_path}")
        self.worker = DungeonWorker(config_path, log_func=self.log)
        self.worker.start()

    def stop_tasks(self):
        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
        else:
            self.log("当前没有运行中的任务")


def main():
    root = tk.Tk()
    gui = DungeonGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
