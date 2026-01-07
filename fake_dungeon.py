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
        """
        cmd = [self.adb_path]
        if self.device:
            cmd += ["-s", self.device]
        cmd += list(args)
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
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


# ========= 眼睛：TemplateMatcher =========

class TemplateMatcher:
    """基于 OpenCV 的模板匹配"""

    def __init__(self, templates_dir="templates", screenshot_dir="screenshots"):
        self.templates_dir = templates_dir
        self.screenshot_dir = screenshot_dir
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

    def wait_and_click(self, adb: ADBDevice, template_name,
                       timeout=30, interval=1, threshold=0.8):
        """常用模式：等待某个模板出现，然后点击"""
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
                print(f"[wait_and_click] {template_name} at {pos}")
                adb.tap(pos[0], pos[1])
                return True

            time.sleep(interval)

        print(f"[wait_and_click] 等待 {template_name} 超时({timeout}s)")
        return False


# ========= 大脑：DungeonAutomation =========

class DungeonAutomation:
    """
    负责读取 dungeon_config.json，
    按照 tasks/steps 顺序调用 ADBDevice + TemplateMatcher。
    """

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        adb_path = self.config["adb_path"]
        device = self.config["device"]

        if not os.path.isfile(adb_path):
            raise FileNotFoundError(f"配置中的 adb_path 不存在：{adb_path}")

        self.adb = ADBDevice(adb_path, device)
        self.matcher = TemplateMatcher()
        self.adb.connect()

    def run_single_task(self, task_conf: dict, log_func=print, stop_flag=None):
        name = task_conf.get("name", "unnamed_task")
        log_func(f"开始任务: {name}")

        for step in task_conf.get("steps", []):
            if stop_flag is not None and stop_flag.is_set():
                log_func("收到停止信号，中断任务")
                return

            action = step.get("action")
            if action == "wait_and_click":
                tpl = step["template"]
                timeout = step.get("timeout", 30)
                threshold = step.get("threshold", 0.8)
                ok = self.matcher.wait_and_click(
                    self.adb, tpl, timeout=timeout, threshold=threshold
                )
                if not ok:
                    log_func(f"等待并点击 {tpl} 失败，终止任务")
                    return

            elif action == "sleep":
                sec = step.get("seconds", 1)
                log_func(f"等待 {sec} 秒")
                time.sleep(sec)

            else:
                log_func(f"未知动作: {action}")

        log_func(f"任务 {name} 完成")

    def run_all_tasks(self, log_func=print, stop_flag=None):
        """依次执行配置中的所有 tasks"""
        for task in self.config.get("tasks", []):
            if stop_flag is not None and stop_flag.is_set():
                log_func("停止标志已置位，终止所有任务")
                break
            self.run_single_task(task, log_func=log_func, stop_flag=stop_flag)
