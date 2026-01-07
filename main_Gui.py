# main_Gui.py
import tkinter as tk
from tkinter import scrolledtext, filedialog

from worker_thread import DungeonWorker


class DungeonGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("App 自动化 Demo")

        self.worker = None

        # 单配置模式下使用的配置文件
        #（默认给一个合理值，你也可以改成 configs/config_Boss.json 或别的）
        self.config_path_var = tk.StringVar(value="configs/config_Boss.json")

        # 模式选择：multi_role / pipeline / single
        # 默认：多角色日常
        self.mode_var = tk.StringVar(value="multi_role")

        # 顶部：配置文件（仅“单配置调试”模式真正使用）
        frame_top = tk.Frame(root)
        frame_top.pack(fill="x", padx=10, pady=5)

        tk.Label(frame_top, text="配置文件(仅单配置调试模式有效):").pack(side="left")
        tk.Entry(frame_top, textvariable=self.config_path_var, width=40).pack(
            side="left", padx=5
        )
        tk.Button(frame_top, text="浏览", command=self.choose_config).pack(side="left")

        # 中间：模式选择 + 控制按钮
        frame_btn = tk.Frame(root)
        frame_btn.pack(fill="x", padx=10, pady=5)

        # 模式单选按钮
        tk.Label(frame_btn, text="运行模式:").pack(side="left")

        tk.Radiobutton(
            frame_btn,
            text="多角色日常（所有角色）",
            variable=self.mode_var,
            value="multi_role",
        ).pack(side="left", padx=5)

        tk.Radiobutton(
            frame_btn,
            text="单角色日常流水线",
            variable=self.mode_var,
            value="pipeline",
        ).pack(side="left", padx=5)

        tk.Radiobutton(
            frame_btn,
            text="单配置调试",
            variable=self.mode_var,
            value="single",
        ).pack(side="left", padx=5)

        # 控制按钮
        tk.Button(frame_btn, text="开始任务", command=self.start_tasks).pack(
            side="left", padx=10
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
        """仅在【单配置调试】模式下真正有意义，但其它模式下也不会出错。"""
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
        # 防止重复启动
        if self.worker is not None and self.worker.is_alive():
            self.log("任务仍在运行中，请先停止")
            return

        mode = self.mode_var.get()
        config_path = self.config_path_var.get()

        if mode == "multi_role":
            self.log("准备以『多角色日常』模式启动")
            self.worker = DungeonWorker(
                config_path="",   # 对 multi_role 模式无实际意义
                log_func=self.log,
                mode="multi_role",
            )

        elif mode == "pipeline":
            self.log("准备以『单角色日常流水线』模式启动")
            self.worker = DungeonWorker(
                config_path="",   # 对 pipeline 模式也无实际意义
                log_func=self.log,
                mode="pipeline",
            )

        else:  # "single"
            self.log(f"准备以『单配置调试』模式启动，配置文件: {config_path}")
            self.worker = DungeonWorker(
                config_path=config_path,
                log_func=self.log,
                mode="single",
            )

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
