# worker_thread.py
import threading
from typing import Callable
from fake_dungeon import DungeonAutomation


class DungeonWorker(threading.Thread):
    """在后台线程中执行 DungeonAutomation.run_all_tasks"""

    def __init__(self, config_path: str,
                 log_func: Callable[[str], None] = print):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.log_func = log_func
        self.stop_event = threading.Event()

    def run(self):
        try:
            auto = DungeonAutomation(self.config_path)
            auto.run_all_tasks(log_func=self.log_func, stop_flag=self.stop_event)
        except Exception as e:
            self.log_func(f"[Worker] 发生异常: {e}")

    def stop(self):
        self.log_func("[Worker] 收到停止请求")
        self.stop_event.set()
