# run_daily_pipeline.py
from fake_dungeon import DungeonAutomation

CONFIG_FLOW = [
    "configs/config_Persondaily.json",   # 1. 个人日常
    "configs/config_Teamdaily.json",     # 2. 组队日常
    "configs/config_Mail.json"           # 3. 领邮箱
    "configs/config_roles.json",         # 4.切换角色
   # "configs/config_Boss.json",         # 5. 打 BOSS

]


def run_daily_pipeline(log_func=print, stop_flag=None):
    """
    按顺序依次执行四个配置里的所有 tasks：
    个人日常 -> 组队日常 -> 打 BOSS -> 领邮箱

    对每个配置内部的任务，使用带重试逻辑：
    - 一轮跑完，记录失败任务
    - 下一轮只跑失败的
    - 直到该配置内所有任务成功，才切换到下一个配置
    """
    for cfg in CONFIG_FLOW:
        # 如果外部发出停止信号，则整个流水线提前结束
        if stop_flag is not None and stop_flag.is_set():
            log_func("收到停止信号，终止日常流水线")
            break

        log_func(f"\n========== 使用配置: {cfg} ==========")
        try:
            auto = DungeonAutomation(cfg)

            # 每个大模块开始前尝试回主界面
            auto.try_return_home(log_func=log_func, stop_flag=stop_flag)

            # 带重试执行当前配置里的所有任务
            auto.run_all_tasks_with_retry(
                log_func=log_func,
                stop_flag=stop_flag,
                max_rounds=1   # 0 = 不限制轮数，直到全部成功
            )

        except Exception as e:
            log_func(f"[ERROR] 配置 {cfg} 执行异常: {e}")


if __name__ == "__main__":
    run_daily_pipeline()
