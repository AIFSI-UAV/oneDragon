# run_multirole_pipeline.py
from typing import Callable

from fake_dungeon import DungeonAutomation
from run_daily_pipeline import run_daily_pipeline

# 专门用于“切换角色”的配置
ROLE_CONFIG = "configs/config_roles.json"

# 你有几个角色，就在这里配几个
ROLES = [
    {"name": "角色1", "switch_macro": "switch_role_1"},
    {"name": "角色2", "switch_macro": "switch_role_2"},
    {"name": "角色1", "switch_macro": "switch_role_3"},
    {"name": "角色2", "switch_macro": "switch_role_4"},
    {"name": "角色2", "switch_macro": "switch_role_5"},
    # {"name": "角色3", "switch_macro": "switch_role_3"},
]

# 切换角色的最大重试次数（可以自己调）
SWITCH_MAX_RETRY = 2


def run_multi_role_pipeline(log_func: Callable[[str], None] = print, stop_flag=None):
    """
    多角色日常流水线：

      1) 默认当前已经登录的是 ROLES[0]（第一个角色）：
         - 不执行切换宏
         - 直接跑该角色的完整日常流水线

      2) 对 ROLES[1:], ROLES[2:], ... 这些角色：
         - 最多尝试 SWITCH_MAX_RETRY 次切换（失败则 return_to_main 重试）
         - 切换成功后跑完整日常流水线
         - 多次切换失败则跳过该角色
    """
    # 先初始化“角色切换专用”的 DungeonAutomation
    try:
        role_auto = DungeonAutomation(ROLE_CONFIG)
    except Exception as e:
        log_func(f"[multi-role] 初始化角色切换配置失败: {e}")
        return

    for idx, role in enumerate(ROLES):
        if stop_flag is not None and stop_flag.is_set():
            log_func("[multi-role] 收到停止信号，终止多角色流水线")
            break

        name = role["name"]
        macro_name = role["switch_macro"]

        # ======================================================
        # 第一位角色：默认已在该角色下，不执行切换，直接跑日常
        # ======================================================
        if idx == 0:
            log_func(
                f"\n========== 当前已是第一个角色 {name}，跳过切换，直接执行日常流水线 =========="
            )
            run_daily_pipeline(log_func=log_func, stop_flag=stop_flag)
            log_func(f"[multi-role] {name} 的日常流水线完成")
            continue

        # ======================================================
        # 后续角色：执行“多次切换 + 失败回主界面重试”的逻辑
        # ======================================================
        switched = False
        for attempt in range(1, SWITCH_MAX_RETRY + 1):
            if stop_flag is not None and stop_flag.is_set():
                log_func("[multi-role] 收到停止信号，中断当前角色切换")
                return

            log_func(
                f"\n========== 切换到 {name}（第 {attempt}/{SWITCH_MAX_RETRY} 次尝试） =========="
            )

            ok = role_auto.run_macro_by_name(
                macro_name,
                log_func=log_func,
                stop_flag=stop_flag,
            )

            if ok:
                log_func(f"[multi-role] 切换到 {name} 成功")
                switched = True
                break

            # 切换失败：尝试返回主界面，再准备下一次重试
            log_func(
                f"[multi-role] 切换到 {name} 失败，第 {attempt} 次尝试结束，执行 return_to_main 后重试"
            )
            role_auto.try_return_home(log_func=log_func, stop_flag=stop_flag)

        if not switched:
            log_func(
                f"[multi-role] 多次尝试后仍无法切换到 {name}，跳过该角色，继续下一个角色"
            )
            continue

        # 切换成功后，执行该角色的完整日常流水线
        log_func(f"[multi-role] 开始执行 {name} 的完整日常流水线")
        run_daily_pipeline(log_func=log_func, stop_flag=stop_flag)
        log_func(f"[multi-role] {name} 的日常流水线完成")


if __name__ == "__main__":
    run_multi_role_pipeline()
