"""征途坦荡挂机 (TankIdleTask) 插件发行版: 对局内零输入挂机拿完成奖励。

本文件是 ok-nte 征途坦荡挂机任务的 .okscript 插件发行版, 参照物流中心插件
(tank-battle-notes 8 / logistics-notes 2.5.2) 的打包约定:
- 自包含模板: 活动入口/活动标题/开始匹配三个模板由插件自带 assets/images
  加载并按捕获宽度缩放, 通过 find_one(template=...) 匹配, 不依赖宿主
  FeatureSet 裸名 (正式版会把 ok_import 插件特征挂 "<插件名>/" 命名空间,
  且旧宿主构建可能没有 tank_* 特征)。
- 依赖宿主稳定接口: src.tasks.BaseNTETask / NTEOneTimeTask /
  src.Labels (仅 login_setting, 宿主核心特征)。
- 同步源: src/tasks/TankIdleTask.py (标定与逻辑以仓库任务为准,
  修改后需同步本文件并升级 manifest.json 的 version)。
"""

import os
import re

import cv2 as cv
import numpy as np
from ok import TaskDisabledException

from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.ui.task_icons import Icon

# ── 插件自带模板加载 (同 logistics_center 插件, assets 裁自 1920x1080) ──
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "images")
_TEMPLATE_CACHE = {}


def _plugin_template(name, frame_width):
    """加载插件自带模板并缩放到当前捕获宽度 (模板源图裁自 1920x1080)。"""
    key = (name, int(frame_width))
    if key not in _TEMPLATE_CACHE:
        path = os.path.join(_TEMPLATE_DIR, f"{name}.png")
        img = cv.imdecode(np.fromfile(path, dtype=np.uint8), cv.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"plugin template missing: {path}")
        ratio = frame_width / 1920.0
        if abs(ratio - 1.0) > 0.01:
            img = cv.resize(img, (max(1, int(img.shape[1] * ratio)),
                                  max(1, int(img.shape[0] * ratio))))
        _TEMPLATE_CACHE[key] = img
    return _TEMPLATE_CACHE[key]

# ── 标定 (1920x1080 画布像素, 与 TankIdleTask/TankBattleTask 同源, notes 7/9) ──
# 对局 HUD 底部道具槽栏第一个槽位的粉色描边: 仅对局内存在, 用作对局判定。
SLOT_PINK_BOX = (730 / 1920, 985 / 1080, 800 / 1920, 1060 / 1080)
# 活动页侧栏区域 (滚动后「征途坦荡」入口的搜索范围; 上缘扩到 0.22 覆盖
# 任意滚动位置, notes 9)。
SIDEBAR_BOX = (0.02, 0.22, 0.17, 0.95)
# 活动页侧栏滚动位置 (滚轮作用点)。
SIDEBAR_WHEEL_POS = (157, 700)
# 入口身份验证: OCR 命中即认 (拨号礼遇等四字按钮与入口模板结构相似,
# 纯模板 0.75 阈值假阳性 conf 0.80, notes 9); 模板兜底要高分。
RE_SIDEBAR_ENTRY = re.compile(r"征途坦荡")
SIDEBAR_TEMPLATE_HIGH_CONF = 0.9
# 活动页 "已获得 N/上限" 计数条 (金币+数字胶囊, y 901-949, 140/147 双帧标定 notes 7)。
EARNED_BOX = (1645 / 1920, 893 / 1080, 1880 / 1920, 958 / 1080)

RE_EARNED = re.compile(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)")


def parse_earned(text):
    """从 OCR 文本解析 "已获得 N/上限", 返回 (earned, cap) 或 None。

    两组数字都可能带千分位逗号 (1,250/1,250, notes 5.1); 第一组不含逗号的旧
    正则会把 1,250 解析成 250, 满上限时止损失效 (notes 7)。
    """
    if not text:
        return None
    match = RE_EARNED.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))
    except ValueError:
        return None


class RoundAbort(Exception):
    """单轮中止: 由 do_run 记为失败轮次并停止任务。"""


class TankIdleTask(NTEOneTimeTask, BaseNTETask):
    """征途坦荡挂机: 匹配进图后零输入挂机到对局结束, 只拿保底完成奖励"""

    CONF_IGNORE_CAP = "无视代币上限(调试)"

    MATCH_LOAD_TIMEOUT = 150.0
    PLAY_MAX_SECONDS = 11 * 60.0
    RECOVER_SECONDS = 60.0
    END_CHECKS = 30
    END_GIVEUP_CHECKS = 55
    END_CHECK_INTERVAL = 0.8
    STEP_TIMEOUT = 30.0
    # 侧栏条目随活动轮换增删 (2026-11-16 改版后征途坦荡前面多了 5 个活动,
    # 固定 3 次滚动不够, notes 9): 下滑扫描上限 + 回顶重扫轮数。
    SIDEBAR_SCROLL_MAX = 8
    SIDEBAR_SCROLL_TOP_RESET = 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "征途坦荡挂机"
        self.group_name = "活动"
        self.group_icon = Icon.GAME
        self.description = (
            "自动进入征途坦荡坦克大战对局, 对局内不驾驶不开炮, 挂机到对局结束拿完成奖励"
        )
        self.instructions = (
            "任务会打开活动页的征途坦荡并自动匹配对局, 对局约 8 分钟, 期间不做任何游戏输入, "
            "只等待对局结束领取保底完成奖励。不含拾取、开炮与纪念商店购买, "
            "需要这些能力请使用「征途坦荡」完整任务。"
        )
        self.add_rounds_config()
        self.default_config.update(
            {
                self.CONF_IGNORE_CAP: False,
            }
        )
        self.config_description.update(
            {
                self.CONF_IGNORE_CAP: "TX 纪念币达到上限后仍继续进对局 (调试用)",
            }
        )

    def configured_rounds(self, default=0):
        """环境变量 TANK_ROUNDS 覆盖轮次 (headless 验证用), 其余同 RoundMixin。"""
        env = os.environ.get("TANK_ROUNDS")
        if env is not None:
            try:
                return max(0, int(env))
            except ValueError:
                pass
        return super().configured_rounds(default)

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            raise
        except RoundAbort as e:
            self.log_warning(f"征途坦荡挂机轮次中止: {e}")
        except Exception as e:
            self.log_error("征途坦荡挂机任务出错", e, notify=True)
            raise

    def do_run(self):
        """轮次循环: 匹配对局并挂机到结算。"""
        self.start_rounds()
        completed = 0
        self._recover_after_match()
        self._warm_ocr()
        try:
            while self.begin_round():
                try:
                    if not self._run_round():
                        self.stop_rounds("代币已到上限")
                        break
                    self.add_success()
                    completed += 1
                except RoundAbort as e:
                    self.add_failed(str(e) or "轮次中止")
                    break
        finally:
            self.finish_rounds()
        try:
            self.ensure_main()
        except Exception as e:
            self.log_warning(f"收尾回到主界面失败: {e}")
        self.log_info(f"征途坦荡挂机任务完成, 共 {completed} 局")
        return True

    def _run_round(self) -> bool:
        self.ensure_main(in_world=True)
        self._open_event_page()
        nocap = self.config.get(self.CONF_IGNORE_CAP, False) or os.environ.get("TANK_NOCAP") == "1"
        if not nocap:
            earned = self._read_earned()
            if earned is not None:
                self.log_info(f"代币进度 {earned[0]}/{earned[1]} (上限逐日刷新, 动态读取)")
                if earned[0] >= earned[1]:
                    self.log_info(
                        f"TX 纪念币已到上限 ({earned[0]}/{earned[1]}), 对局不再产出, 跳过"
                    )
                    self.stop_rounds("代币上限")
                    return False
        if self._in_match():
            self.log_info("检测到已在对局中, 直接继续本局")
        else:
            self._start_match()
        self._idle_match()
        self._recover_after_match()
        return True

    def _warm_ocr(self) -> None:
        """预热 OCR 引擎: 首次调用同步加载模型, 冷启动可达数十秒,
        不预热会让首个 OCR 步骤 (代币上限检查) 静默超时 (notes 3.18)。"""
        try:
            self.ocr(box=self.box_of_screen(0.3, 0.4, 0.7, 0.6, name="ocr_warmup"))
        except Exception as e:
            self.log_warning(f"OCR 预热失败: {e}")

    def _recover_after_match(self) -> None:
        """对局结束后的恢复: 结算弹窗/误按 esc 的退出确认框都会挡住主界面。

        循环点确认按钮 + 间隔按 esc, 直到确认框消失 (notes 3.13)。
        """
        timer = self.clock.timer(timeout=self.RECOVER_SECONDS)
        last_esc = 0.0
        while not timer.expired():
            if self._in_match():
                return
            clicked = self.wait_click_confirm(time_out=1.5, raise_if_not_found=False)
            if clicked:
                self.log_round_info("点击确认弹窗")
                continue
            if self.is_in_team():
                return
            if self.clock.now() - last_esc > 4:
                last_esc = self.clock.now()
                self.send_key("esc", after_sleep=1)
            self.sleep(0.5)

    # ── 对局状态检测 ─────────────────────────────────────────────────

    def _in_match(self, frame=None):
        """道具槽粉色描边存在即在对局内 (大世界没有该面板)。"""
        frame = self.frame if frame is None else frame
        if frame is None:
            return False
        mask = self._color_mask(frame, SLOT_PINK_BOX, (160, 100, 200), (176, 255, 255))
        return int(cv.countNonZero(mask)) > 100

    def _color_mask(self, frame, rel_box, hsv_low, hsv_high):
        box = self.box_of_screen(*rel_box, name="tank_idle_hud")
        cropped = box.crop_frame(frame)
        hsv = cv.cvtColor(cropped, cv.COLOR_BGR2HSV)
        return cv.inRange(hsv, np.array(hsv_low), np.array(hsv_high))

    # ── 入口: 大世界 → 活动页 → 征途坦荡 ─────────────────────────────

    def _open_event_page(self) -> None:
        def action():
            self.ensure_main(in_world=True)
            self.send_key("f4", after_sleep=2)
            entry = self._find_sidebar_entry()
            if entry is None:
                # F4 记住上次滚动位置, 起点可能在列表底部: 回顶再扫一轮 (notes 9)。
                self._wheel_sidebar_top()
                entry = self._find_sidebar_entry()
            if entry is None:
                return False
            self.sleep(0.8)
            self.operate_click(entry, after_sleep=2)
            title = self.wait_until(
                lambda: self.find_one(
                    template=_plugin_template("tank_event_title", self.width),
                    box=self.box_of_screen(0.75, 0.1, 0.99, 0.22, name="event_title"),
                    threshold=0.7,
                ),
                time_out=8,
                raise_if_not_found=False,
                settle_time=0.5,
            )
            return title is not None

        if bool(self.retry_on_action(action, self.ensure_main, attempt=2)):
            return
        self.log_error("无法打开征途坦荡活动页", notify=True)
        raise RoundAbort("event page")

    def _find_sidebar_entry(self):
        """侧栏条目随活动轮换增删, 征途坦荡屏位不固定 (notes 9): 逐屏下滑,
        每屏先 OCR 找「征途坦荡」文字 (身份验证, 排除拨号礼遇等相似按钮的
        模板假阳性), OCR 未读出再用插件自带入口模板高分 (>=0.9) 兜底。"""
        for _ in range(self.SIDEBAR_SCROLL_MAX):
            hit = self._ocr_sidebar_entry()
            if hit is not None:
                return hit
            hit = self.find_one(
                template=_plugin_template("tank_event_entry", self.width),
                box=self.box_of_screen(*SIDEBAR_BOX, name="sidebar"),
                threshold=SIDEBAR_TEMPLATE_HIGH_CONF,
            )
            if hit is not None:
                return hit
            self._wheel_sidebar()
        return None

    def _ocr_sidebar_entry(self):
        """OCR 侧栏区域找「征途坦荡」文字框 (返回绝对坐标 Box 或 None)。"""
        texts = self.ocr(
            box=self.box_of_screen(*SIDEBAR_BOX, name="sidebar"),
            match=RE_SIDEBAR_ENTRY,
        )
        if not texts:
            return None
        return texts[0]

    def _wheel_sidebar_top(self):
        for _ in range(self.SIDEBAR_SCROLL_TOP_RESET):
            self.operate(
                lambda: self.scroll(SIDEBAR_WHEEL_POS[0], SIDEBAR_WHEEL_POS[1], count=3),
                block=True, restore_cursor=False,
            )
            self.sleep(0.6)

    def _wheel_sidebar(self):
        x = int(SIDEBAR_WHEEL_POS[0])
        y = int(SIDEBAR_WHEEL_POS[1])
        self.operate(lambda: self.scroll(x, y, count=-3), block=True, restore_cursor=False)
        self.sleep(1.2)

    # ── 匹配 ────────────────────────────────────────────────────────

    def _start_match(self) -> None:
        button = self.wait_until(
            lambda: self.find_one(
                template=_plugin_template("tank_start_match", self.width),
                box=self.box_of_screen(0.75, 0.88, 0.99, 0.99, name="start_match"),
                threshold=0.75,
            ),
            time_out=self.STEP_TIMEOUT,
            raise_if_not_found=False,
        )
        if button is None:
            self.log_error("未找到开始匹配按钮", notify=True)
            raise RoundAbort("start button")
        self.operate_click(button, after_sleep=2)
        self.log_info("已点击开始匹配, 等待载入")
        if not self._wait_in_match(self.MATCH_LOAD_TIMEOUT):
            self.log_error("超时未进入对局", notify=True)
            raise RoundAbort("match load")

    def _wait_in_match(self, time_out: float) -> bool:
        timer = self.clock.timer(timeout=time_out)
        while not timer.expired():
            if self._in_match():
                self.sleep(2)
                return True
            self.sleep(1)
        return False

    # ── 对局挂机 ─────────────────────────────────────────────────────

    def _idle_match(self) -> None:
        """对局挂机: 不做任何游戏输入, 只等对局结束 (只拿完成奖励, notes 3.20)。

        结束判定与 TankBattleTask._play_match 相同: 道具栏消失 + 世界队伍确认。
        保留两条兜底: 月卡弹窗可能在对局中弹出 (notes 3.40), 挡住屏幕且对局会
        超时被踢; 被踢到登录界面时复用 check_login 登回 (notes 3.12)。
        """
        self.log_round_info("对局挂机模式, 等待对局结束")
        timer = self.clock.timer(timeout=self.PLAY_MAX_SECONDS)
        end_checks = 0
        while not timer.expired():
            if self.find_monthly_card() is not None:
                self.log_round_info("月卡弹窗, 处理领取")
                self.handle_monthly_card(log=False)
            if not self._in_match():
                end_checks += 1
                if end_checks >= self.END_CHECKS and self.is_in_team():
                    self.log_round_info("对局结束 (挂机完成, 已回大世界)")
                    return
                if end_checks > self.END_GIVEUP_CHECKS:
                    self.log_round_info("对局状态未知超时, 按结束处理")
                    return
                if self.find_one(Labels.login_setting, threshold=0.7) is not None:
                    self.log_round_info("检测到被踢到登录界面, 自动登录")
                    self.check_login()
                    end_checks = 0
                self.sleep(self.END_CHECK_INTERVAL)
                continue
            end_checks = 0
            self.sleep(1)

    # ── 代币上限 ─────────────────────────────────────────────────────

    def _read_earned(self):
        """活动页 '已获得 N/上限' OCR, 返回 (earned, cap) 或 None。

        上限逐日递增 (1000 -> 1250 -> 1500, notes 5.1), 每轮动态读取,
        不得用固定值缓存。target_height 绝不可加: 框架按全帧高算缩放,
        48/1080 会把裁剪区缩成 8x2px, OCR 全毁 (notes 3.45)。
        """
        result = None

        def read():
            nonlocal result
            text = self.ocr(
                box=self.box_of_screen(*EARNED_BOX, name="earned"),
                match=RE_EARNED,
            )
            if text:
                result = parse_earned("".join(item.name for item in text))
            return result

        found = self.wait_until(read, time_out=6, raise_if_not_found=False, settle_time=0.3)
        if found is None:
            self.log_info("代币计数 OCR 未读出 (可能不在活动页或数字过小)")
        return found
