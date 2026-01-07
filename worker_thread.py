# worker_thread.py
import threading
from typing import Callable

from fake_dungeon import DungeonAutomation
from run_daily_pipeline import run_daily_pipeline
from run_multirole_pipeline import run_multi_role_pipeline


class DungeonWorker(threading.Thread):
    """
    在后台线程中执行任务：

    mode = "multi_role" : 多角色日常流水线
                          （使用 run_multi_role_pipeline）
    mode = "pipeline"   : 单角色日常流水线
                          （使用 run_daily_pipeline）
    mode = "single"     : 单配置调试
                          （直接用 DungeonAutomation(config_path)）
    """

    def __init__(
        self,
        config_path: str,
        log_func: Callable[[str], None] = print,
        mode: str = "multi_role",   # 默认就跑多角色日常
    ):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.log_func = log_func
        self.stop_event = threading.Event()
        self.mode = mode

    def run(self):
        try:
            if self.mode == "multi_role":
                self.log_func("以『多角色日常』模式启动（config_roles + 各 config_*.json）")
                run_multi_role_pipeline(
                    log_func=self.log_func,
                    stop_flag=self.stop_event
                )

            elif self.mode == "pipeline":
                self.log_func("以『单角色日常流水线』模式启动")
                run_daily_pipeline(
                    log_func=self.log_func,
                    stop_flag=self.stop_event
                )

            else:  # "single"
                self.log_func(f"以『单配置调试』模式启动，配置文件: {self.config_path}")
                auto = DungeonAutomation(self.config_path)
                # 如果你已经实现了 run_all_tasks_with_retry，这里可以换成更智能的重试版
                auto.run_all_tasks(
                    log_func=self.log_func,
                    stop_flag=self.stop_event
                )

        except Exception as e:
            self.log_func(f"[Worker] 发生异常: {e}")

    def stop(self):
        self.log_func("[Worker] 收到停止请求")
        self.stop_event.set()
