# fake_dungeon.py
import os
import time
import random
import json
import subprocess

import cv2


# ========= 手：ADBDevice =========

class ADBDevice:
    """封装 ADB 基础操作：连接、点击、滑动、截图"""

    def __init__(self, adb_path: str, device: str):
        self.adb_path = adb_path
        self.device = device  # 例如 "127.0.0.1:5555"

    def _adb_cmd(self, *args, **popen_kwargs):
        """
        统一封装 adb 命令调用：
        _adb_cmd("shell", "input", "tap", "500", "600")
        这里不再默认设置 stdout/stderr，由调用者自己决定。
        """
        cmd = [self.adb_path]
        if self.device:
            cmd += ["-s", self.device]
        cmd += list(args)
        return subprocess.run(
            cmd,
            **popen_kwargs
        )


    def connect(self):
        """可选：对某些模拟器先执行 adb connect"""
        try:
            result = subprocess.run(
                [self.adb_path, "connect", self.device],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            print("[ADB connect]", result.stdout.strip(), result.stderr.strip())
        except Exception as e:
            print("[ADB connect] 异常:", e)

        devices = subprocess.run(
            [self.adb_path, "devices"],
            stdout=subprocess.PIPE,
            text=True
        ).stdout
        print("[ADB devices]\n", devices)

    def tap(self, x: int, y: int, delay=(0.3, 0.6)):
        self._adb_cmd("shell", "input", "tap", str(x), str(y))
        time.sleep(random.uniform(*delay))

    def swipe(self, x1, y1, x2, y2, duration_ms=300, delay=(0.3, 0.6)):
        self._adb_cmd(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms)
        )
        time.sleep(random.uniform(*delay))

    def screenshot(self, save_path: str) -> bool:
        """截屏到指定路径，成功返回 True"""
        try:
            with open(save_path, "wb") as f:
                result = self._adb_cmd("exec-out", "screencap", "-p", stdout=f)
            if result.returncode != 0:
                print("[screenshot] adb 错误:", result.stderr)
                return False
            return True
        except Exception as e:
            print("[screenshot] 异常:", e)
            return False

    def keyevent(self, keycode, repeat: int = 1, delay=(0.1, 0.2)):
        """
        发送虚拟按键：
        - keycode 可以是数字(如 111) 或字符串(如 'KEYCODE_ESCAPE')
        - repeat 表示连按次数
        """
        for _ in range(max(1, repeat)):
            self._adb_cmd("shell", "input", "keyevent", str(keycode))
            time.sleep(random.uniform(*delay))

# ========= 眼睛：TemplateMatcher =========
class TemplateMatcher:
    """基于 OpenCV 的模板匹配"""

    def __init__(self, templates_dir="templates", screenshot_dir="screenshots"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.templates_dir = os.path.join(base_dir, templates_dir)
        self.screenshot_dir = os.path.join(base_dir, screenshot_dir)
        os.makedirs(self.templates_dir, exist_ok=True)
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def find_template_in_image(self, image, template_name, threshold=0.8):
        template_path = os.path.join(self.templates_dir, template_name)
        template = cv2.imread(template_path)
        if template is None:
            print(f"[模板缺失] {template_path}")
            return None

        gray_screen = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        if (gray_screen.shape[0] < gray_template.shape[0] or
                gray_screen.shape[1] < gray_template.shape[1]):
            print(f"[模板尺寸异常] {template_name}")
            return None

        result = cv2.matchTemplate(gray_screen, gray_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = gray_template.shape
            cx = max_loc[0] + w // 2
            cy = max_loc[1] + h // 2
            return cx, cy
        return None

    def wait_and_click(
        self,
        adb: "ADBDevice",
        template_name: str,
        timeout: float = 30,
        interval: float = 1.0,
        threshold: float = 0.8,
        click_times: int = 1,
    ) -> bool:
        """
        等待某个模板在屏幕上出现，然后点击（可以点击多次）。
        click_times: 点击次数，默认为 1；比如 Leave 可以设为 2。
        """
        start = time.time()
        shot_path = os.path.join(self.screenshot_dir, "screen.png")

        while time.time() - start < timeout:
            if not adb.screenshot(shot_path):
                time.sleep(interval)
                continue

            img = cv2.imread(shot_path)
            if img is None:
                time.sleep(interval)
                continue

            pos = self.find_template_in_image(img, template_name, threshold)
            if pos:
                print(f"[wait_and_click] {template_name} at {pos}, click_times={click_times}")
                for _ in range(max(1, click_times)):
                    adb.tap(pos[0], pos[1])
                    time.sleep(0.15)  # 双击之间短暂停顿
                return True

            time.sleep(interval)

        print(f"[wait_and_click] 等待 {template_name} 超时({timeout}s)")
        return False

    def find_any_template_in_image(self, image, template_names, threshold=0.8):
        """
        在同一张截图里，尝试匹配多个模板，只要有一个达到阈值就返回：
        返回值: (命中的模板文件名, (cx, cy)) 或 (None, None)
        """
        best_tpl = None
        best_pos = None
        best_val = 0.0

        gray_screen = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        for tpl_name in template_names:
            template_path = os.path.join(self.templates_dir, tpl_name)
            template = cv2.imread(template_path)
            if template is None:
                print(f"[模板缺失] {template_path}")
                continue

            gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            if (gray_screen.shape[0] < gray_template.shape[0] or
                    gray_screen.shape[1] < gray_template.shape[1]):
                print(f"[模板尺寸异常] {tpl_name}")
                continue

            result = cv2.matchTemplate(gray_screen, gray_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val >= threshold and max_val > best_val:
                h, w = gray_template.shape
                cx = max_loc[0] + w // 2
                cy = max_loc[1] + h // 2
                best_val = max_val
                best_tpl = tpl_name
                best_pos = (cx, cy)

        return best_tpl, best_pos

    def wait_and_click_any(
            self,
            adb: "ADBDevice",
            template_names,
            timeout: float = 30,
            interval: float = 1.0,
            threshold: float = 0.8,
            click_times: int = 1,
    ):
        """
        在多个模板中只要识别到任意一个就点击。
        返回: (True, 命中的模板名) 或 (False, None)
        """
        start = time.time()
        shot_path = os.path.join(self.screenshot_dir, "screen_any.png")

        while time.time() - start < timeout:
            if not adb.screenshot(shot_path):
                time.sleep(interval)
                continue

            img = cv2.imread(shot_path)
            if img is None:
                time.sleep(interval)
                continue

            hit_tpl, pos = self.find_any_template_in_image(img, template_names, threshold)
            if hit_tpl is not None and pos is not None:
                print(f"[wait_and_click_any] 命中 {hit_tpl} at {pos}, click_times={click_times}")
                for _ in range(click_times):
                    adb.tap(pos[0], pos[1])
                    time.sleep(0.1)
                return True, hit_tpl

            time.sleep(interval)

        print(f"[wait_and_click_any] 在 {timeout}s 内未检测到 {template_names}")
        return False, None

    def exists_on_screen(
        self,
        adb: "ADBDevice",
        template_name: str,
        threshold: float = 0.8,
    ) -> bool:
        """
        截一张当前屏幕，检查 template 是否存在（只检查一次，不点击）。
        返回 True 表示仍然能看到该模板，False 表示没找到。
        """
        shot_path = os.path.join(self.screenshot_dir, "verify_screen.png")
        if not adb.screenshot(shot_path):
            print("[exists_on_screen] 截图失败")
            return False

        img = cv2.imread(shot_path)
        if img is None:
            print("[exists_on_screen] 读取截图失败")
            return False

        pos = self.find_template_in_image(img, template_name, threshold)
        return pos is not None

    def wait_for_template(
        self,
        adb: "ADBDevice",
        template_name: str,
        timeout: float = 30,
        interval: float = 1.0,
        threshold: float = 0.8,
    ) -> bool:
        """
        只等待某个模板出现，不点击。
        - 返回 True: 在 timeout 内检测到 template_name
        - 返回 False: 超时仍未检测到
        """
        start = time.time()
        shot_path = os.path.join(self.screenshot_dir, "wait_only.png")

        while time.time() - start < timeout:
            if not adb.screenshot(shot_path):
                time.sleep(interval)
                continue

            img = cv2.imread(shot_path)
            if img is None:
                time.sleep(interval)
                continue

            pos = self.find_template_in_image(img, template_name, threshold)
            if pos:
                print(f"[wait_for_template] 检测到 {template_name} at {pos}")
                return True

            time.sleep(interval)

        print(f"[wait_for_template] 等待 {template_name} 超时({timeout}s)")
        return False

# ========= 大脑：DungeonAutomation =========
class DungeonAutomation:
    """
    负责读取 dungeon_config.json，
    按照 tasks/steps 顺序调用 ADBDevice + TemplateMatcher。
    """

    def __init__(self, config_path: str):
        # 如果传的是相对路径，就拼到 fake_dungeon.py 所在目录下
        if not os.path.isabs(config_path):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(base_dir, config_path)

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        adb_path = self.config["adb_path"]
        device = self.config["device"]

        if not os.path.isfile(adb_path):
            raise FileNotFoundError(f"配置中的 adb_path 不存在：{adb_path}")

        # 从配置里读取 templates_dir（可选），默认 "templates"
        templates_dir = self.config.get("templates_dir", "templates")

        self.adb = ADBDevice(adb_path, device)
        # ★ 把 templates_dir 传给 TemplateMatcher
        self.matcher = TemplateMatcher(templates_dir=templates_dir)
        self.adb.connect()

        # 2）读取 macros & 预展开 tasks
        self.macros = self.config.get("macros", {})  # 可能没有，就给个空 dict
        raw_tasks = self.config.get("tasks", [])
        self.tasks = self._expand_tasks_with_macros(raw_tasks)

    def _expand_tasks_with_macros(self, tasks_conf):
        """对 tasks 列表中的每个 task 展开宏"""
        expanded = []
        for task in tasks_conf:
            expanded.append(self._expand_single_task(task))
        return expanded

    def _expand_single_task(self, task_conf):
        """对单个 task 的 steps 展开其中的 use_macro"""
        steps = []
        for step in task_conf.get("steps", []):
            if "use_macro" in step:
                macro_name = step["use_macro"]
                if macro_name not in self.macros:
                    raise ValueError(f"未定义宏: {macro_name}")
                macro_steps = self.macros[macro_name]
                # 为避免后续修改原数据，这里浅拷贝一份
                steps.extend(macro_steps)
            else:
                steps.append(step)
        new_task = dict(task_conf)
        new_task["steps"] = steps
        return new_task

        # 新增：复用单步执行逻辑的内部工具

    def _run_steps(self, steps, log_func=print, stop_flag=None) -> bool:
        """
        执行一组 steps（支持：
          - use_macro：宏中调用其他宏
          - wait_and_click
          - sleep
          - keyevent
          - wait_for_template：只确认图片是否出现
        ）
        返回 True 表示整个序列执行完成，False 表示中途失败/中断。
        """
        for step in steps:
            if stop_flag is not None and stop_flag.is_set():
                log_func("收到停止信号，中断当前步骤序列")
                return False

            # 1) 先处理 use_macro（宏里嵌套宏）
            if "use_macro" in step:
                macro_name = step["use_macro"]
                sub_steps = self.macros.get(macro_name)
                if not sub_steps:
                    log_func(f"[宏步骤] 未找到被引用的宏: {macro_name}")
                    return False

                log_func(f"[宏步骤] 执行子宏: {macro_name}")
                ok = self._run_steps(sub_steps, log_func=log_func, stop_flag=stop_flag)
                if not ok:
                    log_func(f"[宏步骤] 子宏 {macro_name} 执行失败，终止当前步骤序列")
                    return False
                continue

            # 2) 普通 action
            action = step.get("action")

            if action == "wait_and_click":
                tpl = step["template"]
                timeout = step.get("timeout", 30)
                threshold = step.get("threshold", 0.8)
                click_times = step.get("click_times", 1)

                ok = self.matcher.wait_and_click(
                    self.adb,
                    tpl,
                    timeout=timeout,
                    threshold=threshold,
                    click_times=click_times,
                )
                if not ok:
                    log_func(f"[宏步骤] 等待并点击 {tpl} 失败（宏执行中止）")
                    return False

            elif action == "sleep":
                sec = step.get("seconds", 1)
                log_func(f"[宏步骤] 等待 {sec} 秒")
                time.sleep(sec)

            elif action == "keyevent":
                keycode = step.get("keycode")
                repeat = step.get("repeat", 1)
                if keycode is None:
                    log_func("[宏步骤] keyevent 缺少 keycode，跳过此步")
                    continue
                log_func(f"[宏步骤] 发送按键 keycode={keycode}, repeat={repeat}")
                self.adb.keyevent(keycode, repeat=repeat)

            elif action == "wait_for_template":
                tpl = step["template"]
                timeout = step.get("timeout", 15)
                threshold = step.get("threshold", 0.8)
                interval = step.get("interval", 1.0)

                log_func(
                    f"[宏步骤] 开始等待模板 {tpl} 出现，timeout={timeout}, threshold={threshold}"
                )
                ok = self.matcher.wait_for_template(
                    self.adb,
                    tpl,
                    timeout=timeout,
                    interval=interval,
                    threshold=threshold,
                )
                if not ok:
                    log_func(f"[宏步骤] 在 {timeout}s 内未检测到 {tpl}，视为失败")
                    return False

            else:
                log_func(f"[宏步骤] 未知动作: {action}")
                # 这里既可以继续，也可以视为失败。为了安全，你也可以改成 return False。

        # 全部 steps 执行完毕
        return True

    def try_return_home(self, log_func=print, stop_flag=None):
        """
        任务失败时尝试执行 'return_to_main' 宏：
        - 如果宏不存在，只打印提示
        - 存在则按宏的 steps 执行
        """
        home_steps = self.macros.get("return_to_main")
        if not home_steps:
            log_func("未配置宏 'return_to_main'，无法自动返回主界面")
            return

        log_func("任务失败，执行宏 'return_to_main' 尝试返回主界面")
        self._run_steps(home_steps, log_func=log_func, stop_flag=stop_flag)

    def run_single_task(self, task_conf: dict, log_func=print, stop_flag=None) -> bool:
        name = task_conf.get("name", "unnamed_task")
        log_func(f"开始任务: {name}")

        for step in task_conf.get("steps", []):
            if stop_flag is not None and stop_flag.is_set():
                log_func("收到停止信号，中断任务")
                return False

            action = step.get("action")

            # ------- 普通等待并点击 -------
            if action == "wait_and_click":
                tpl = step["template"]
                timeout = step.get("timeout", 30)
                threshold = step.get("threshold", 0.8)
                click_times = step.get("click_times", 1)

                ok = self.matcher.wait_and_click(
                    self.adb,
                    tpl,
                    timeout=timeout,
                    threshold=threshold,
                    click_times=click_times,
                )
                if not ok:
                    log_func(f"等待并点击 {tpl} 失败，任务提前结束")
                    # 这里尝试自动回主界面
                    self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                    return False

            # ------- 简单 sleep -------
            elif action == "sleep":
                sec = step.get("seconds", 1)
                log_func(f"等待 {sec} 秒")
                time.sleep(sec)

            # ------- 循环等待直到出现（支持 click_times） -------
            elif action == "wait_and_click_loop":
                tpl = step["template"]
                per_timeout = step.get("per_timeout", 60)  # 每一轮内部等待时间
                threshold = step.get("threshold", 0.8)
                max_wait = step.get("max_wait", 0)  # 总等待上限（秒），0 表示无限等待
                click_times = step.get("click_times", 1)  # 每次检测到时点击次数

                start_all = time.time()
                log_func(
                    f"开始循环等待 {tpl}，每轮 {per_timeout}s，"
                    f"max_wait={max_wait}, click_times={click_times}"
                )

                while True:
                    if stop_flag is not None and stop_flag.is_set():
                        log_func("收到停止信号，中断 wait_and_click_loop")
                        return False

                    ok = self.matcher.wait_and_click(
                        self.adb,
                        tpl,
                        timeout=per_timeout,
                        threshold=threshold,
                        click_times=click_times,
                    )
                    if ok:
                        log_func(f"循环等待中检测到 {tpl}，已点击 {click_times} 次")
                        break

                    # 检查总等待时间是否超限
                    if max_wait > 0 and (time.time() - start_all) >= max_wait:
                        log_func(
                            f"wait_and_click_loop 超过最大等待时间 {max_wait} 秒，任务提前结束"
                        )
                        # 和普通失败一样，尝试回主界面
                        self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                        return False

                    log_func(f"{tpl} 本轮 {per_timeout}s 内未出现，继续下一轮等待...")

                    # ------- 新增：优先点 primary_template，失败再点 fallback_template -------
            elif action == "wait_and_click_or":
                primary_tpl = step["primary_template"]
                fallback_tpl = step["fallback_template"]

                threshold = step.get("threshold", 0.8)
                click_times = step.get("click_times", 1)

                primary_timeout = step.get("primary_timeout", 3)
                fallback_timeout = step.get("fallback_timeout", 20)

                log_func(
                    f"wait_and_click_or: 优先尝试 {primary_tpl}({primary_timeout}s)，"
                    f"失败则尝试 {fallback_tpl}({fallback_timeout}s)"
                )

                # 先尝试 primary
                ok_primary = self.matcher.wait_and_click(
                    self.adb,
                    primary_tpl,
                    timeout=primary_timeout,
                    threshold=threshold,
                    click_times=click_times,
                )

                if ok_primary:
                    log_func(f"优先模板 {primary_tpl} 点击成功")
                else:
                    log_func(f"未检测到 {primary_tpl}，尝试备用模板 {fallback_tpl}")

                    ok_fallback = self.matcher.wait_and_click(
                        self.adb,
                        fallback_tpl,
                        timeout=fallback_timeout,
                        threshold=threshold,
                        click_times=click_times,
                    )

                    if not ok_fallback:
                        log_func(
                            f"备用模板 {fallback_tpl} 在 {fallback_timeout}s 内也未检测到，任务提前结束"
                        )
                        self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                        return False
                    else:
                        log_func(f"备用模板 {fallback_tpl} 点击成功")

            # ------- 新增：出现 primary_template 就去点击 fallback_template -------
            elif action == "wait_and_click_yes":
                primary_tpl = step["primary_template"]
                fallback_tpl = step["fallback_template"]

                primary_timeout = step.get("primary_timeout", 3)  # 检测 primary 的时间
                fallback_timeout = step.get("fallback_timeout", 20)
                threshold = step.get("threshold", 0.8)
                click_times = step.get("click_times", 1)

                log_func(
                    f"wait_and_click_yes: 如检测到 {primary_tpl} 则点击 {fallback_tpl}，"
                    f"primary_timeout={primary_timeout}, fallback_timeout={fallback_timeout}"
                )

                # 1）先只检测 primary_template，不点击
                yes = self.matcher.wait_for_template(
                    self.adb,
                    primary_tpl,
                    timeout=primary_timeout,
                    threshold=threshold,
                )

                if not yes:
                    # 没检测到 primary，安静跳过本 step，不算失败
                    log_func(f"未在 {primary_timeout}s 内检测到 {primary_tpl}，跳过本步骤")
                    continue  # 进入下一个 step

                # 2）检测到 primary，再去点击 fallback_template
                log_func(f"检测到 {primary_tpl}，尝试点击 {fallback_tpl}")
                ok = self.matcher.wait_and_click(
                    self.adb,
                    fallback_tpl,
                    timeout=fallback_timeout,
                    threshold=threshold,
                    click_times=click_times,
                )

                if not ok:
                    log_func(f"检测到 {primary_tpl} 但点击 {fallback_tpl} 失败，任务提前结束")
                    self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                    return False

            # ------- 多模板：任意一个出现就点击 -------
            elif action == "wait_and_click_any":
                templates = step.get("templates")  # 必须是列表
                if not templates or not isinstance(templates, list):
                    log_func(f"wait_and_click_any 缺少有效的 templates 列表: {templates}")
                    self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                    return False

                timeout = step.get("timeout", 30)
                threshold = step.get("threshold", 0.8)
                click_times = step.get("click_times", 1)

                ok, hit_tpl = self.matcher.wait_and_click_any(
                    self.adb,
                    templates,
                    timeout=timeout,
                    threshold=threshold,
                    click_times=click_times,
                )
                if not ok:
                    log_func(f"wait_and_click_any 在 {timeout}s 内未检测到 {templates}，任务提前结束")
                    self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                    return False
                else:
                    log_func(f"wait_and_click_any 命中模板: {hit_tpl}")

            # ------- 新增：检测有就一直点，直到消失 -------
            elif action == "click_while_exists":
                tpl = step["template"]
                per_timeout = step.get("per_timeout", 5)  # 每一轮查找的时间窗
                threshold = step.get("threshold", 0.8)
                click_times = step.get("click_times", 1)  # 每次找到后点几下
                max_clicks = step.get("max_clicks", 100)  # 总点击上限（防止死循环）
                max_duration = step.get("max_duration", 0)  # 总时间上限，0 = 不限制

                start_all = time.time()
                total_clicks = 0
                log_func(
                    f"开始 click_while_exists: 模板={tpl}, "
                    f"per_timeout={per_timeout}, threshold={threshold}, "
                    f"max_clicks={max_clicks}, max_duration={max_duration}"
                )

                while True:
                    if stop_flag is not None and stop_flag.is_set():
                        log_func("收到停止信号，中断 click_while_exists")
                        return False

                    # 在 per_timeout 内找一次，有就点（可能连点多下）
                    ok = self.matcher.wait_and_click(
                        self.adb,
                        tpl,
                        timeout=per_timeout,
                        threshold=threshold,
                        click_times=click_times,
                    )
                    if not ok:
                        # 本轮找不到，认为已经没有这个图标了，结束循环
                        log_func(
                            f"在 {per_timeout}s 内未再检测到 {tpl}，认为已清空，共点击 {total_clicks} 次"
                        )
                        break

                    total_clicks += click_times
                    log_func(f"检测到 {tpl}，已累计点击 {total_clicks} 次")

                    # 安全保护：次数太多
                    if max_clicks > 0 and total_clicks >= max_clicks:
                        log_func(
                            f"click_while_exists: 点击次数已达上限 {max_clicks}，仍可能存在 {tpl}，任务提前结束"
                        )
                        self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                        return False

                    # 安全保护：总时间太长
                    if max_duration > 0 and (time.time() - start_all) >= max_duration:
                        log_func(
                            f"click_while_exists: 总等待时间超过 {max_duration}s，仍可能存在 {tpl}，任务提前结束"
                        )
                        self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                        return False

                    time.sleep(step.get("interval", 0.2))

            # ------- 未知动作 -------
            else:
                log_func(f"未知动作: {action}")

        log_func(f"任务 {name} 完成")
        return True

    def run_all_tasks(self, log_func=print, stop_flag=None):
        """依次执行展开后的所有 tasks"""
        for task in self.tasks:
            if stop_flag is not None and stop_flag.is_set():
                log_func("停止标志已置位，终止所有任务")
                break

            ok = self.run_single_task(task, log_func=log_func, stop_flag=stop_flag)
            if not ok:
                name = task.get("name", "unnamed_task")
                log_func(f"任务 {name} 未完成，已尝试返回主界面，继续下一个任务")
                # 不 break，继续下一个 task
                continue

    def run_all_tasks_with_retry(
            self,
            log_func=print,
            stop_flag=None,
            max_rounds: int = 0
    ) -> bool:
        """
        带重试的任务执行：
        - 第一轮执行 self.tasks 中的所有任务；
        - 记录失败的任务，作为下一轮的执行列表；
        - 如此循环，直到所有任务成功，或者达到 max_rounds 限制，或者收到 stop_flag。

        参数：
        - max_rounds = 0 表示“不限制轮数，一直重试直到全部成功或 stop_flag 置位”
        - 返回 True 表示最终全部成功；False 表示还有未完成任务就退出（轮数用完或被停止）
        """
        # 初始剩余任务：所有任务
        remaining = list(self.tasks)
        if not remaining:
            log_func("当前配置中没有任务可执行")
            return True

        round_idx = 1

        while True:
            # 外部请求停止，直接结束
            if stop_flag is not None and stop_flag.is_set():
                log_func("收到停止信号，终止带重试的任务执行")
                return False

            log_func(f"\n---- 第 {round_idx} 轮任务执行，剩余任务数: {len(remaining)} ----")

            failed = []

            for task in remaining:
                if stop_flag is not None and stop_flag.is_set():
                    log_func("收到停止信号，中断当前轮任务")
                    return False

                ok = self.run_single_task(task, log_func=log_func, stop_flag=stop_flag)
                if not ok:
                    failed.append(task)

            # 本轮全部成功
            if not failed:
                log_func(f"第 {round_idx} 轮结束，所有任务已成功完成。")
                return True

            # 还有失败任务，记录名称以便查看
            failed_names = [t.get("name", "unnamed_task") for t in failed]
            log_func(
                f"第 {round_idx} 轮结束，以下任务未完成，将在下一轮重试："
                f"{', '.join(failed_names)}"
            )

            # 如果设置了最大轮数，并且已经到达上限，则停止重试
            if max_rounds > 0 and round_idx >= max_rounds:
                log_func(
                    f"已达到最大轮数 {max_rounds}，仍有任务未完成，停止重试。"
                )
                return False

            # 否则继续下一轮，只对失败任务重试
            remaining = failed
            round_idx += 1

    def run_macro_by_name(self, macro_name: str, log_func=print, stop_flag=None) -> bool:
        """
        执行当前配置中的某个宏（macros 里定义的步骤序列）。
        返回 True 表示宏正常跑完，False 表示执行失败或宏不存在。
        """
        steps = self.macros.get(macro_name)
        if not steps:
            log_func(f"[run_macro_by_name] 未找到宏: {macro_name}")
            return False

        log_func(f"[run_macro_by_name] 开始执行宏: {macro_name}")
        ok = self._run_steps(steps, log_func=log_func, stop_flag=stop_flag)
        log_func(f"[run_macro_by_name] 宏 {macro_name} 执行结束，结果: {ok}")
        return bool(ok)


def debug_find_template(config_path: str, template_name: str, threshold: float = 0.7):
    """
    单步调试：
    1. 初始化 DungeonAutomation
    2. 截一张图到 screenshots/debug_screen.png
    3. 在这张图里找 template_name
    """
    auto = DungeonAutomation(config_path)
    shot_path = os.path.join(auto.matcher.screenshot_dir, "debug_screen.png")

    print("[DEBUG] 截图到", shot_path)
    if not auto.adb.screenshot(shot_path):
        print("[DEBUG] 截图失败")
        return

    img = cv2.imread(shot_path)
    if img is None:
        print("[DEBUG] 读取截图失败")
        return

    pos = auto.matcher.find_template_in_image(img, template_name, threshold=threshold)
    print(f"[DEBUG] 模板 {template_name} 匹配结果:", pos)

if __name__ == "__main__":
            # 这里可以改成你想测试的模板名称&阈值
    debug_find_template("dungeon_config.json", "btn_menu.png", threshold=0.7)
