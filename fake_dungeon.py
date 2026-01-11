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
    """基于 OpenCV 的模板匹配 + 模板缓存 + 灰度截图复用 + 可选 ROI"""

    def __init__(self, templates_dir="templates", screenshot_dir="screenshots"):
        # 基于 fake_dungeon.py 文件所在目录，构造绝对路径
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # 支持从 config 传入类似 "templates/Mail" 的子目录
        self.templates_dir = os.path.join(base_dir, templates_dir)
        self.screenshot_dir = os.path.join(base_dir, screenshot_dir)

        os.makedirs(self.templates_dir, exist_ok=True)
        os.makedirs(self.screenshot_dir, exist_ok=True)

        # 模板缓存：key=模板绝对路径, value=灰度模板 ndarray
        self._template_cache = {}

    # ---------------- 模板缓存 ----------------

    def _get_gray_template(self, template_name: str):
        """
        从缓存中获取灰度模板；若缓存未命中，则从磁盘读取并转灰度后缓存。
        失败时返回 None。
        """
        template_path = os.path.join(self.templates_dir, template_name)

        # 1) 先查缓存
        cached = self._template_cache.get(template_path)
        if cached is not None:
            return cached

        # 2) 缓存中没有，读文件
        template = cv2.imread(template_path)
        if template is None:
            print(f"[模板缺失] {template_path}")
            return None

        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        self._template_cache[template_path] = gray_template
        return gray_template

    # ---------------- ROI 工具 ----------------

    @staticmethod
    def _apply_roi(gray_screen, roi, roi_mode: str = "abs"):
        """
        根据 ROI 和 roi_mode 截取区域：
        - roi_mode = "abs": roi = [x1, y1, x2, y2] 像素坐标
        - roi_mode = "rel": roi = [x1r, y1r, x2r, y2r]，0~1 之间比例坐标
        返回: (gray_region, offset_x, offset_y)
        """
        if roi is None:
            return gray_screen, 0, 0

        h, w = gray_screen.shape[:2]

        # 1) 先转换成像素坐标
        if roi_mode == "rel":
            x1r, y1r, x2r, y2r = roi
            x1 = int(x1r * w)
            x2 = int(x2r * w)
            y1 = int(y1r * h)
            y2 = int(y2r * h)
        else:  # "abs" 或其它默认走绝对坐标
            x1, y1, x2, y2 = roi

        # 2) 边界截断，防止越界
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))

        # 3) ROI 非法则退化为整图
        if x2 <= x1 or y2 <= y1:
            return gray_screen, 0, 0

        region = gray_screen[y1:y2, x1:x2]
        return region, x1, y1

    # ---------------- 灰度截图上的匹配核心 ----------------

    def _find_template_in_gray(
            self,
            gray_screen,
            template_name: str,
            threshold: float = 0.8,
            roi=None,
            roi_mode: str = "abs"
    ):
        """
        在灰度截图 gray_screen 中匹配单个模板，支持 ROI。
        """
        gray_template = self._get_gray_template(template_name)
        if gray_template is None:
            return None

        # 先对灰度图应用 ROI
        region, offset_x, offset_y = self._apply_roi(gray_screen, roi, roi_mode)

        if region.shape[0] < gray_template.shape[0] or region.shape[1] < gray_template.shape[1]:
            print(f"[模板尺寸异常] {template_name} 在 ROI 内无效")
            return None

        result = cv2.matchTemplate(region, gray_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = gray_template.shape
            cx = max_loc[0] + w // 2 + offset_x
            cy = max_loc[1] + h // 2 + offset_y
            return cx, cy

        return None

    # ---------------- 兼容老接口：彩色图直接匹配 ----------------

    def find_template_in_image(
            self,
            image,
            template_name: str,
            threshold: float = 0.8,
            roi=None,
            roi_mode: str = "abs"
    ):
        """
        在给定 image 中查找单个模板 template_name，返回中心坐标或 None。

        - image: 可以是 BGR 彩图或灰度图
        - roi:    可选，[x1, y1, x2, y2]（abs）或 [x1r, y1r, x2r, y2r]（rel）
        - roi_mode: "abs" 或 "rel"
        """
        # 1) 统一转灰度
        if len(image.shape) == 3:
            gray_screen = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray_screen = image

        # 2) 先应用 ROI（内部会做 abs/rel 的判断和裁剪）
        region, offset_x, offset_y = self._apply_roi(gray_screen, roi, roi_mode)

        # 3) 获取灰度模板（用缓存）
        gray_template = self._get_gray_template(template_name)
        if gray_template is None:
            return None

        # 4) 尺寸检查
        if region.shape[0] < gray_template.shape[0] or region.shape[1] < gray_template.shape[1]:
            print(f"[模板尺寸异常] {template_name} 在 ROI 内无效")
            return None

        result = cv2.matchTemplate(region, gray_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            h, w = gray_template.shape
            cx = max_loc[0] + w // 2 + offset_x
            cy = max_loc[1] + h // 2 + offset_y
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
        roi=None,
        roi_mode: str = "abs",
    ) -> bool:
        """
        常用模式：等待某个模板出现，然后点击（可多次点击）。
        - 支持 ROI / roi_mode
        - 返回 True 表示点击成功，False 表示超时未检测到
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

            gray_screen = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            pos = self._find_template_in_gray(
                gray_screen,
                template_name,
                threshold=threshold,
                roi=roi,
                roi_mode=roi_mode,
            )

            if pos:
                print(
                    f"[wait_and_click] {template_name} at {pos}, "
                    f"click_times={click_times}"
                )
                for _ in range(max(1, click_times)):
                    adb.tap(pos[0], pos[1])
                return True

            time.sleep(interval)

        print(f"[wait_and_click] 等待 {template_name} 超时({timeout}s)")
        return False

    # ---------------- wait_for_template：支持 ROI ----------------
    def wait_for_template(
        self,
        adb: "ADBDevice",
        template_name: str,
        timeout: float = 30,
        interval: float = 1.0,
        threshold: float = 0.8,
        roi=None,
        roi_mode: str = "abs",
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

            gray_screen = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            pos = self._find_template_in_gray(
            gray_screen,
            template_name,
            threshold = threshold,
            roi = roi,
            roi_mode = roi_mode,)

            if pos:
                print(f"[wait_for_template] 检测到 {template_name} at {pos}")
                return True

            time.sleep(interval)

        print(f"[wait_for_template] 等待 {template_name} 超时({timeout}s)")
        return False

    # ---------------- 多模板：命中任意一个就点击（支持 ROI） ----------------

    def wait_and_click_any(
        self,
        adb: "ADBDevice",
        templates,
        timeout: float = 30,
        interval: float = 1.0,
        threshold: float = 0.8,
        click_times: int = 1,
        roi=None,
        roi_mode: str = "abs",
    ):
        """
        在给定的 templates 列表中，谁先匹配成功就点谁。
        返回 (ok, hit_template_name)
        """
        if not templates or not isinstance(templates, list):
            print(f"[wait_and_click_any] 非法的 templates 参数: {templates}")
            return False, None

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

            gray_screen = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 统一对灰度图应用 ROI
            region, offset_x, offset_y = self._apply_roi(gray_screen, roi, roi_mode)

            best_name = None
            best_pos = None
            best_val = -1.0
            best_w = 0
            best_h = 0

            h_region, w_region = region.shape[:2]

            for name in templates:
                gray_template = self._get_gray_template(name)
                if gray_template is None:
                    continue

                h, w = gray_template.shape
                if h_region < h or w_region < w:
                    print(f"[模板尺寸异常] {name}")
                    continue

                result = cv2.matchTemplate(region, gray_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                if max_val > best_val:
                    best_val = max_val
                    best_name = name
                    best_pos = max_loc
                    best_w = w
                    best_h = h

            if best_name is not None and best_val >= threshold:
                cx = best_pos[0] + best_w // 2 + offset_x
                cy = best_pos[1] + best_h // 2 + offset_y
                print(
                    f"[wait_and_click_any] 命中 {best_name} at ({cx}, {cy}), "
                    f"score={best_val:.3f}, click_times={click_times}"
                )
                for _ in range(max(1, click_times)):
                    adb.tap(cx, cy)
                return True, best_name

            time.sleep(interval)

        print(f"[wait_and_click_any] 在 {timeout}s 内未检测到 {templates}")
        return False, None

# ========= 大脑：DungeonAutomation =========

class DungeonAutomation:
    """
    负责读取 readm.txt，
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

        self._in_return_home = False

        # 2）读取 macros & 预展开 tasks
        self.macros = self.config.get("macros", {})  # 可能没有，就给个空 dict
        raw_tasks = self.config.get("tasks", [])
        self.tasks = self._expand_tasks_with_macros(raw_tasks)

        # 3）动作分发表：action -> 处理函数
        self._action_handlers = {
            "wait_and_click": self._handle_wait_and_click,
            "sleep": self._handle_sleep,
            "wait_and_click_loop": self._handle_wait_and_click_loop,
            "wait_and_click_or":  self._handle_wait_and_click_or,
            "wait_and_click_yes": self._handle_wait_and_click_yes,
            "wait_and_click_no": self._handle_wait_and_click_no,  # ★ 新增
            "wait_and_click_any": self._handle_wait_and_click_any,
            "click_while_exists": self._handle_click_while_exists,
            "click_any_while_exists": self._handle_click_any_while_exists,
            "keyevent": self._handle_keyevent,
            "wait_for_template": self._handle_wait_for_template,
        }

    # ----------------------------------------------------------------------
    # 配置解析：展开 tasks 中的 use_macro（老逻辑保留）
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # 通用 steps 执行：给宏用（run_macro_by_name / return_to_main）
    # 保持原有行为，不动。
    # ----------------------------------------------------------------------
    def _run_steps(self, steps, log_func=print, stop_flag=None) -> bool:
        """
        执行一组 steps（支持：
        - use_macro：宏中调用其他宏
        - 以及所有在 self._action_handlers 里注册过的 action
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

            # 2) 通过统一分发表调用各 action 的 handler
            action = step.get("action")
            handler = self._action_handlers.get(action)

            if handler is None:
                log_func(f"[宏步骤] 未知动作: {action}，跳过本步骤")
                # 出于安全也可以 return False，看你是要“严”还是“宽”
                continue

            ok = handler(step, log_func, stop_flag)
            if not ok:
                # handler 内部已经按需要处理了 try_return_home 等逻辑
                log_func(f"[宏步骤] 动作 {action} 执行失败，终止当前步骤序列")
                return False

        # 全部 steps 执行完毕
        return True

    # ----------------------------------------------------------------------
    # 任务失败后的安全回主界面
    # ----------------------------------------------------------------------
    def try_return_home(self, log_func=print, stop_flag=None):
        # 如果已经在回主界面流程里，就不要再嵌套调用
        if self._in_return_home:
            log_func("当前已经在 'return_to_main' 宏中，忽略再次 try_return_home 调用")
            return

        home_steps = self.macros.get("return_to_main")
        if not home_steps:
            log_func("未配置宏 'return_to_main'，无法自动返回主界面")
            return

        log_func("任务失败，执行宏 'return_to_main' 尝试返回主界面")

        old_flag = self._in_return_home
        self._in_return_home = True
        try:
            self._run_steps(home_steps, log_func=log_func, stop_flag=stop_flag)
        finally:
            self._in_return_home = old_flag

    # ----------------------------------------------------------------------
    # 各 action 的 handler（小函数）
    # ----------------------------------------------------------------------
    def _handle_wait_and_click(self, step, log_func, stop_flag) -> bool:
        tpl = step["template"]
        timeout = step.get("timeout", 30)
        threshold = step.get("threshold", 0.8)
        click_times = step.get("click_times", 1)
        roi = step.get("roi")
        roi_mode = step.get("roi_mode", "abs")

        ok = self.matcher.wait_and_click(
            self.adb,
            tpl,
            timeout=timeout,
            threshold=threshold,
            click_times=click_times,
            roi=roi,  # ★ 传 ROI
            roi_mode=roi_mode,
        )
        if not ok:
            log_func(f"等待并点击 {tpl} 失败，任务提前结束")
            self.try_return_home(log_func=log_func, stop_flag=stop_flag)
            return False
        return True

    def _handle_sleep(self, step, log_func, stop_flag) -> bool:
        sec = step.get("seconds", 1)
        log_func(f"等待 {sec} 秒")
        time.sleep(sec)
        return True

    def _handle_wait_and_click_loop(self, step, log_func, stop_flag) -> bool:
        tpl = step["template"]
        per_timeout = step.get("per_timeout", 60)  # 每一轮内部等待时间
        threshold = step.get("threshold", 0.8)
        max_wait = step.get("max_wait", 0)        # 总等待上限（秒），0 表示无限等待
        click_times = step.get("click_times", 1)  # 每次检测到时点击次数
        roi = step.get("roi")
        roi_mode = step.get("roi_mode", "abs")

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
                roi=roi,
                roi_mode=roi_mode,
            )
            if ok:
                log_func(f"循环等待中检测到 {tpl}，已点击 {click_times} 次")
                break

            # 检查总等待时间是否超限
            if max_wait > 0 and (time.time() - start_all) >= max_wait:
                log_func(
                    f"wait_and_click_loop 超过最大等待时间 {max_wait} 秒，任务提前结束"
                )
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False

            log_func(f"{tpl} 本轮 {per_timeout}s 内未出现，继续下一轮等待...")
        return True

    def _handle_conditional_click(self, step, log_func, stop_flag, mode: str) -> bool:
        """
        统一处理:
          - mode = "or"
          - mode = "yes"
          - mode = "no"
        """

        primary = step.get("primary_template")
        fallback = step.get("fallback_template")
        pt = step.get("primary_timeout", 3)
        ft = step.get("fallback_timeout", 20)
        thr = step.get("threshold", 0.8)
        clicks = step.get("click_times", 1)
        ignore_fallback_fail = step.get("ignore_fallback_fail", False)
        roi = step.get("roi")
        roi_mode = step.get("roi_mode", "abs")

        if not primary or not fallback:
            log_func(f"[conditional_click/{mode}] primary 或 fallback 缺失，跳过本步骤")
            return True

        # 统一先看 primary 出没
        log_func(
            f"[conditional_click/{mode}] primary={primary}, fallback={fallback}, "
            f"pt={pt}, ft={ft}, thr={thr}, clicks={clicks}"
        )

        # 先检测 primary 是否出现
        has_primary = self.matcher.wait_for_template(
            self.adb, primary, timeout=pt, threshold=thr,
            roi = roi, roi_mode = roi_mode
        )

        if mode == "or":
            # 逻辑: 先点 primary，如果不出现，再去点 fallback
            if has_primary:
                log_func(f"[conditional_click/or] 检测到 {primary}，尝试点击它")
                ok = self.matcher.wait_and_click(
                    self.adb, primary, timeout=ft, threshold=thr, click_times=clicks,
                    roi=roi, roi_mode=roi_mode
                )
            else:
                log_func(f"[conditional_click/or] 未检测到 {primary}，尝试点击 {fallback}")
                ok = self.matcher.wait_and_click(
                    self.adb, fallback, timeout=ft, threshold=thr, click_times=clicks,
                    roi=roi, roi_mode=roi_mode
                )

            if not ok:
                if ignore_fallback_fail:
                    log_func("[conditional_click/or] 点击失败但 ignore_fallback_fail=True，继续后续任务")
                    return True
                log_func("[conditional_click/or] 点击失败，任务提前结束")
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False
            return True

        elif mode == "yes":
            # 逻辑: 有 primary 才点击 fallback；否则直接跳过
            if not has_primary:
                log_func(
                    f"[conditional_click/yes] 未在 {pt}s 内检测到 {primary}，跳过本步骤"
                )
                return True

            log_func(
                f"[conditional_click/yes] 检测到 {primary}，尝试点击 {fallback}"
            )
            ok = self.matcher.wait_and_click(
                self.adb, fallback, timeout=ft, threshold=thr, click_times=clicks,
                roi = roi, roi_mode = roi_mode
            )
            if not ok:
                if ignore_fallback_fail:
                    log_func(
                        f"[conditional_click/yes] 未成功点击 {fallback}，但 ignore_fallback_fail=True，继续后续任务"
                    )
                    return True
                log_func("[conditional_click/yes] 点击失败，任务提前结束")
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False
            return True

        elif mode == "no":
            # 逻辑: 有 primary 就什么都不做；没 primary 才点击 fallback
            if has_primary:
                log_func(
                    f"[conditional_click/no] 检测到 {primary}，跳过点击 {fallback}"
                )
                return True

            log_func(
                f"[conditional_click/no] 在 {pt}s 内未检测到 {primary}，尝试点击 {fallback}"
            )
            ok = self.matcher.wait_and_click(
                self.adb, fallback, timeout=ft, threshold=thr, click_times=clicks,
                roi = roi, roi_mode = roi_mode
            )
            if not ok:
                if ignore_fallback_fail:
                    log_func(
                        f"[conditional_click/no] 未成功点击 {fallback}，"
                        f"但 ignore_fallback_fail=True，继续后续任务"
                    )
                    return True
                log_func("[conditional_click/no] 点击失败，任务提前结束")
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False
            return True

        else:
            log_func(f"[conditional_click] 未知 mode: {mode}，跳过本步骤")
            return True

    def _handle_wait_and_click_or(self, step, log_func, stop_flag) -> bool:
        return self._handle_conditional_click(step, log_func, stop_flag, mode="or")

    def _handle_wait_and_click_yes(self, step, log_func, stop_flag) -> bool:
        return self._handle_conditional_click(step, log_func, stop_flag, mode="yes")

    def _handle_wait_and_click_no(self, step, log_func, stop_flag) -> bool:
        return self._handle_conditional_click(step, log_func, stop_flag, mode="no")

    def _handle_wait_and_click_any(self, step, log_func, stop_flag) -> bool:
        templates = step.get("templates")  # 必须是列表
        if not templates or not isinstance(templates, list):
            log_func(f"wait_and_click_any 缺少有效的 templates 列表: {templates}")
            self.try_return_home(log_func=log_func, stop_flag=stop_flag)
            return False

        timeout = step.get("timeout", 30)
        threshold = step.get("threshold", 0.8)
        click_times = step.get("click_times", 1)
        roi = step.get("roi")
        roi_mode = step.get("roi_mode", "abs")

        ok, hit_tpl = self.matcher.wait_and_click_any(
            self.adb,
            templates,
            timeout=timeout,
            threshold=threshold,
            click_times=click_times,
            roi=roi,
            roi_mode=roi_mode,
        )
        if not ok:
            log_func(
                f"wait_and_click_any 在 {timeout}s 内未检测到 {templates}，任务提前结束"
            )
            self.try_return_home(log_func=log_func, stop_flag=stop_flag)
            return False

        log_func(f"wait_and_click_any 命中模板: {hit_tpl}")
        return True

    def _handle_click_while_exists(self, step, log_func, stop_flag) -> bool:
        tpl = step["template"]
        per_timeout = step.get("per_timeout", 5)      # 每一轮查找的时间窗
        threshold = step.get("threshold", 0.8)
        click_times = step.get("click_times", 1)      # 每次找到后点几下
        max_clicks = step.get("max_clicks", 100)      # 总点击上限（防止死循环）
        max_duration = step.get("max_duration", 0)    # 总时间上限，0 = 不限制
        roi = step.get("roi")  # ★ 新增
        roi_mode = step.get("roi_mode", "abs")

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
                roi=roi,
                roi_mode=roi_mode,
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
                    f"click_while_exists: 点击次数已达上限 {max_clicks}，"
                    f"仍可能存在 {tpl}，任务提前结束"
                )
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False

            # 安全保护：总时间太长
            if max_duration > 0 and (time.time() - start_all) >= max_duration:
                log_func(
                    f"click_while_exists: 总等待时间超过 {max_duration}s，"
                    f"仍可能存在 {tpl}，任务提前结束"
                )
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False

            time.sleep(step.get("interval", 0.2))

        return True

    def _handle_click_any_while_exists(self, step, log_func, stop_flag) -> bool:
        """
        多模板版 click_while_exists：
        只要屏幕上还存在 templates 列表中任意一个模板，就继续：
        - wait_and_click_any 一轮
        - 点击
        直到连续一轮 per_timeout 内都没找到任何一个模板，才结束当前 action。
        """

        templates = step.get("templates")
        if not templates or not isinstance(templates, list):
            log_func(f"click_any_while_exists 缺少有效的 templates 列表: {templates}")
            self.try_return_home(log_func=log_func, stop_flag=stop_flag)
            return False

        per_timeout = step.get("per_timeout", 5)  # 每一轮内部查找时间窗（秒）
        threshold = step.get("threshold", 0.8)
        click_times = step.get("click_times", 1)  # 每次命中后的点击次数
        max_clicks = step.get("max_clicks", 100)  # 总点击上限（防止死循环）
        max_duration = step.get("max_duration", 0)  # 总时间上限，0 = 不限制
        roi = step.get("roi")  # ★ 新增
        roi_mode = step.get("roi_mode", "abs")

        start_all = time.time()
        total_clicks = 0

        log_func(
            f"开始 click_any_while_exists: 模板={templates}, "
            f"per_timeout={per_timeout}, threshold={threshold}, "
            f"click_times={click_times}, max_clicks={max_clicks}, "
            f"max_duration={max_duration}"
        )

        while True:
            if stop_flag is not None and stop_flag.is_set():
                log_func("收到停止信号，中断 click_any_while_exists")
                return False

            # 在 per_timeout 内，尝试命中任意一个模板
            ok, hit_tpl = self.matcher.wait_and_click_any(
                self.adb,
                templates,
                timeout=per_timeout,
                threshold=threshold,
                click_times=click_times,
                roi=roi,  # ★ 传 ROI
                roi_mode=roi_mode,
            )

            if not ok:
                # 当前这一轮找不到任何一个模板，认为已经清空
                log_func(
                    f"在 {per_timeout}s 内未再检测到 {templates} 中任意模板，"
                    f"认为已清空，共点击 {total_clicks} 次"
                )
                break

            total_clicks += click_times
            log_func(
                f"检测到 {hit_tpl}，本轮点击 {click_times} 次，"
                f"累计点击 {total_clicks} 次"
            )

            # 安全保护：点击次数太多
            if max_clicks > 0 and total_clicks >= max_clicks:
                log_func(
                    f"click_any_while_exists: 点击次数达到上限 {max_clicks}，"
                    f"仍可能存在 {templates}，任务提前结束"
                )
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False

            # 安全保护：总时间过长
            if max_duration > 0 and (time.time() - start_all) >= max_duration:
                log_func(
                    f"click_any_while_exists: 总时长超过 {max_duration}s，"
                    f"仍可能存在 {templates}，任务提前结束"
                )
                self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                return False

            # 每轮之间小睡一下，避免过于频繁截图
            time.sleep(step.get("interval", 0.2))

        return True

    def _handle_keyevent(self, step, log_func, stop_flag) -> bool:
        keycode = step.get("keycode")
        repeat = step.get("repeat", 1)
        if keycode is None:
            log_func("[keyevent] 缺少 keycode，跳过本步骤")
            return True

        log_func(f"[keyevent] 发送按键 keycode={keycode}, repeat={repeat}")
        self.adb.keyevent(keycode, repeat=repeat)
        return True

    def _handle_wait_for_template(self, step, log_func, stop_flag) -> bool:
        tpl = step["template"]
        timeout = step.get("timeout", 15)
        threshold = step.get("threshold", 0.8)
        interval = step.get("interval", 1.0)
        roi = step.get("roi")  # ★ 新增
        roi_mode = step.get("roi_mode", "abs")

        log_func(
            f"[wait_for_template] 开始等待模板 {tpl} 出现，"
            f"timeout={timeout}, threshold={threshold}"
        )
        ok = self.matcher.wait_for_template(
            self.adb,
            tpl,
            timeout=timeout,
            interval=interval,
            threshold=threshold,
            roi=roi,  # ★ 传 ROI
            roi_mode=roi_mode,
        )
        if not ok:
            log_func(
                f"[wait_for_template] 在 {timeout}s 内未检测到 {tpl}，任务提前结束"
            )
            self.try_return_home(log_func=log_func, stop_flag=stop_flag)
            return False
        return True

    # ----------------------------------------------------------------------
    # 对外：执行一个任务 / 所有任务 / 带重试 / 执行宏
    # ----------------------------------------------------------------------
    def run_single_task(self, task_conf: dict, log_func=print, stop_flag=None) -> bool:
        name = task_conf.get("name", "unnamed_task")
        log_func(f"开始任务: {name}")

        for step in task_conf.get("steps", []):
            if stop_flag is not None and stop_flag.is_set():
                log_func("收到停止信号，中断任务")
                return False

            # 可选：在 task 里直接嵌套 use_macro（大多数时候已经在 _expand_single_task 展开了）
            if "use_macro" in step:
                macro_name = step["use_macro"]
                sub_steps = self.macros.get(macro_name)
                if not sub_steps:
                    log_func(f"任务步骤中引用了未定义宏: {macro_name}")
                    self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                    return False

                log_func(f"任务内执行子宏: {macro_name}")
                ok = self._run_steps(sub_steps, log_func=log_func, stop_flag=stop_flag)
                if not ok:
                    log_func(f"子宏 {macro_name} 执行失败，任务提前结束")
                    self.try_return_home(log_func=log_func, stop_flag=stop_flag)
                    return False
                continue

            action = step.get("action")
            handler = self._action_handlers.get(action)

            if handler is None:
                log_func(f"未知动作: {action}")
                # 为了兼容旧行为，这里选择“跳过继续”，也可以改成 return False
                continue

            ok = handler(step, log_func, stop_flag)
            if not ok:
                # handler 内部已经根据需要调用了 try_return_home
                return False

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

            log_func(
                f"\n---- 第 {round_idx} 轮任务执行，剩余任务数: {len(remaining)} ----"
            )
            failed = []

            for task in remaining:
                if stop_flag is not None and stop_flag.is_set():
                    log_func("收到停止信号，中断当前轮任务")
                    return False

                ok = self.run_single_task(
                    task,
                    log_func=log_func,
                    stop_flag=stop_flag
                )
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

    # 转灰度，然后走统一的灰度匹配接口
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pos = auto.matcher._find_template_in_gray(gray, template_name,
                                              threshold=threshold,
                                              roi=None,         # 调试时可以手工改
                                              roi_mode="abs"
                                              )
    print(f"[DEBUG] 模板 {template_name} 匹配结果:", pos)

if __name__ == "__main__":
    # 这里可以改成你想测试的模板名称&阈值
    debug_find_template("dungeon_config.json", "btn_menu.png", threshold=0.7)
