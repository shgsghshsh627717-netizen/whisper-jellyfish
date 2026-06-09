"""桌面宠物水母：可拖拽、浮在所有窗口最上层的悬浮水母（图片帧形象）。

形象来自 assets/pet/*.png（粉色水母表情包），跟随录音状态切换表情并轻轻飘动。
拖拽可移动（位置记忆到磁盘），轻点（非拖拽）触发回调（开始/停止录音）。
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Callable, Dict, Optional, Tuple

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSCompositingOperationClear,
    NSEvent,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSMakeRect,
    NSMutableParagraphStyle,
    NSPanel,
    NSParagraphStyleAttributeName,
    NSRectFillUsingOperation,
    NSScreen,
    NSTextAlignmentCenter,
    NSTimer,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSPopUpMenuWindowLevel,
)
from Foundation import NSString
from PyObjCTools import AppHelper

from src.keyboard.inputState import InputState
from src.utils.logger import logger

_PET_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "pet"
)
_POS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", ".pet_position.json"
)

# 状态 -> (图片帧列表, 运动模式)
# 多帧会每隔 _ROTATE_SECONDS 轮换一张
# 运动模式: float(上下飘) / wobble(左右晃) / idle(轻浮)
_IDLE_FRAMES = ["cell_0_1.png", "cell_0_2.png", "cell_2_2.png"]      # 闭眼/趴睡/害羞 轮换
_REC_FRAMES = ["cell_0_0.png", "cell_2_1.png"]                        # 开心冒星/花球欢呼 轮换

_STATE_MAP: Dict[InputState, Tuple[list, str]] = {
    InputState.IDLE: (_IDLE_FRAMES, "idle"),
    InputState.RECORDING: (_REC_FRAMES, "float"),
    InputState.RECORDING_TRANSLATE: (_REC_FRAMES, "float"),
    InputState.RECORDING_KIMI: (_REC_FRAMES, "float"),
    InputState.DOUBAO_STREAMING: (_REC_FRAMES, "float"),
    InputState.PROCESSING: (["cell_1_1.png"], "wobble"),             # 捧爱心
    InputState.PROCESSING_KIMI: (["cell_1_1.png"], "wobble"),
    InputState.TRANSLATING: (["cell_1_1.png"], "wobble"),
    InputState.WARNING: (["cell_1_0.png"], "idle"),                  # 炸毛
    InputState.ERROR: (["cell_2_0.png"], "idle"),                   # 打伞淋雨
}

_MOTION_SPEED = {"float": 0.18, "wobble": 0.16, "idle": 0.08}
_ROTATE_SECONDS = 2.5  # 多帧轮换间隔
_TICK_SECONDS = 0.1

# 录音状态集合：进入这些状态时启动倒计时
_RECORDING_STATES = frozenset({
    InputState.RECORDING,
    InputState.RECORDING_TRANSLATE,
    InputState.RECORDING_KIMI,
    InputState.DOUBAO_STREAMING,
})

_LABEL_H = 20.0          # 水母下方倒计时文字条高度
_WARN_REMAIN = 60.0      # 剩余时间低于此值时倒计时变红提醒


class _JellyView(NSView):
    """显示当前表情图片 + 处理拖拽/点击。"""

    def initWithFrame_owner_(self, frame, owner):
        self = objc.super(_JellyView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._owner = owner
        self._down_origin = None
        return self

    def isOpaque(self):
        return False

    def acceptsFirstMouse_(self, event):
        return True

    def drawRect_(self, rect):
        # 清成透明，避免残影
        NSColor.clearColor().set()
        NSRectFillUsingOperation(self.bounds(), NSCompositingOperationClear)

        owner = self._owner
        img = owner.current_image()
        if img is None:
            return

        b = self.bounds()
        isz = img.size()
        if isz.width <= 0 or isz.height <= 0:
            return

        # 底部预留 _LABEL_H 高的文字条给倒计时，水母画在其上方的方形区域内
        jelly_h = b.size.height - _LABEL_H

        # 等比缩放，留出飘动的余量
        pad = 10.0
        avail = min(b.size.width, jelly_h) - pad * 2
        scale = min(avail / isz.width, avail / isz.height)
        dw = isz.width * scale
        dh = isz.height * scale

        # 飘动位移
        phase = owner.phase
        motion = owner.current_motion()
        ox = oy = 0.0
        amp = 4.0
        if motion == "float":
            oy = amp * math.sin(phase)
        elif motion == "wobble":
            ox = amp * math.sin(phase)
        else:
            oy = (amp * 0.6) * math.sin(phase)

        x = (b.size.width - dw) / 2.0 + ox
        y = _LABEL_H + (jelly_h - dh) / 2.0 + oy
        img.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(x, y, dw, dh), NSMakeRect(0, 0, isz.width, isz.height), 1, 1.0
        )

        # 倒计时（仅录音时显示）
        remaining = owner.countdown_remaining()
        if remaining is not None:
            self._draw_countdown(b, remaining)

    def _draw_countdown(self, bounds, remaining):
        remaining = max(0.0, remaining)
        mm = int(remaining) // 60
        ss = int(remaining) % 60
        text = NSString.stringWithString_(f"{mm}:{ss:02d}")

        warn = remaining <= _WARN_REMAIN
        color = NSColor.systemRedColor() if warn else NSColor.whiteColor()
        para = NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(NSTextAlignmentCenter)
        attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(12.0),
            NSForegroundColorAttributeName: color,
            NSParagraphStyleAttributeName: para,
        }

        tsz = text.sizeWithAttributes_(attrs)
        pill_w = tsz.width + 14.0
        pill_h = _LABEL_H - 2.0
        px = (bounds.size.width - pill_w) / 2.0
        py = 1.0
        pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(px, py, pill_w, pill_h), pill_h / 2.0, pill_h / 2.0
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.55).set()
        pill.fill()

        ty = py + (pill_h - tsz.height) / 2.0
        text.drawInRect_withAttributes_(
            NSMakeRect(px, ty, pill_w, tsz.height), attrs
        )

    # ---- 鼠标：原生背景拖拽由窗口处理；这里只区分"点击 vs 拖拽" ----
    def mouseDown_(self, event):
        win = self.window()
        self._down_origin = (win.frame().origin.x, win.frame().origin.y)

    def mouseUp_(self, event):
        win = self.window()
        if self._down_origin is not None:
            ox, oy = self._down_origin
            now = win.frame().origin
            moved = abs(now.x - ox) > 3 or abs(now.y - oy) > 3
            if moved:
                self._owner.save_position()
            else:
                self._owner.on_click()
        self._down_origin = None


class DesktopPetWindow:
    """可拖拽的桌面水母悬浮窗（图片形象）。"""

    SIZE = 96.0

    def __init__(
        self,
        on_click: Optional[Callable[[], None]] = None,
        max_record_seconds: float = 600.0,
    ) -> None:
        self._panel: Optional[NSPanel] = None
        self._view: Optional[_JellyView] = None
        self._timer = None
        self._state: InputState = InputState.IDLE
        self.phase: float = 0.0
        self._on_click = on_click
        self._images: Dict[str, NSImage] = {}
        self._frame_idx: int = 0          # 当前轮换帧
        self._state_ticks: int = 0        # 进入当前状态后经过的 tick 数
        self._max_record_seconds: float = float(max_record_seconds)
        self._countdown_deadline: Optional[float] = None  # 录音到点的时间戳

    def countdown_remaining(self) -> Optional[float]:
        """录音中返回剩余秒数；否则 None（不显示倒计时）。"""
        if self._countdown_deadline is None:
            return None
        return self._countdown_deadline - time.time()

    # ---- 图片缓存 ----
    def _image(self, filename: str) -> Optional[NSImage]:
        if filename not in self._images:
            path = os.path.abspath(os.path.join(_PET_DIR, filename))
            img = NSImage.alloc().initWithContentsOfFile_(path)
            if img is None:
                logger.warning(f"[DesktopPet] 图片加载失败: {path}")
            self._images[filename] = img
        return self._images[filename]

    def current_image(self) -> Optional[NSImage]:
        frames, _ = _STATE_MAP.get(self._state, _STATE_MAP[InputState.IDLE])
        fname = frames[self._frame_idx % len(frames)]
        return self._image(fname)

    def current_motion(self) -> str:
        _, motion = _STATE_MAP.get(self._state, _STATE_MAP[InputState.IDLE])
        return motion

    # ---- 视图回调 ----
    def on_click(self) -> None:
        if self._on_click is not None:
            try:
                self._on_click()
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[DesktopPet] on_click 出错: {exc}")

    def save_position(self) -> None:
        if self._panel is None:
            return
        o = self._panel.frame().origin
        try:
            with open(os.path.abspath(_POS_FILE), "w") as f:
                json.dump({"x": float(o.x), "y": float(o.y)}, f)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[DesktopPet] 保存位置失败: {exc}")

    def _load_position(self) -> Optional[Tuple[float, float]]:
        try:
            with open(os.path.abspath(_POS_FILE)) as f:
                d = json.load(f)
            return float(d["x"]), float(d["y"])
        except Exception:
            return None

    # ---- 生命周期 ----
    def show(self) -> None:
        AppHelper.callAfter(self._setup)

    def hide(self) -> None:
        def _hide():
            if self._panel is not None:
                self._panel.orderOut_(None)
        AppHelper.callAfter(_hide)

    def update_state(self, state: InputState) -> None:
        def _apply():
            if state != self._state:
                # 进入录音状态：启动倒计时；离开录音状态：清除
                was_recording = self._state in _RECORDING_STATES
                now_recording = state in _RECORDING_STATES
                if now_recording and not was_recording:
                    self._countdown_deadline = time.time() + self._max_record_seconds
                elif not now_recording:
                    self._countdown_deadline = None

                self._state = state
                self._frame_idx = 0       # 切状态时从第一帧开始
                self._state_ticks = 0
            if self._view is not None:
                self._view.setNeedsDisplay_(True)
        AppHelper.callAfter(_apply)

    def _setup(self) -> None:
        if self._panel is not None:
            return
        screen = NSScreen.mainScreen()
        sf = screen.frame()
        size = self.SIZE
        win_h = size + _LABEL_H  # 多出一条放倒计时

        pos = self._load_position()
        if pos is None:
            x = sf.size.width - size - 40
            y = 140
        else:
            x, y = pos
            x = max(0, min(x, sf.size.width - size))
            y = max(0, min(y, sf.size.height - win_h))

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, size, win_h), style, 2, False
        )
        panel.setLevel_(NSPopUpMenuWindowLevel)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setHidesOnDeactivate_(False)
        panel.setCanHide_(False)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setIgnoresMouseEvents_(False)
        panel.setMovableByWindowBackground_(True)  # 原生背景拖拽

        view = _JellyView.alloc().initWithFrame_owner_(
            NSMakeRect(0, 0, size, win_h), self
        )
        panel.setContentView_(view)
        self._panel = panel
        self._view = view

        panel.orderFrontRegardless()

        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.1, True, lambda _t: self._tick()
        )

    def _tick(self) -> None:
        self.phase += _MOTION_SPEED.get(self.current_motion(), 0.1)
        self._state_ticks += 1

        # 多帧状态：每 _ROTATE_SECONDS 轮换一帧
        frames, _ = _STATE_MAP.get(self._state, _STATE_MAP[InputState.IDLE])
        if len(frames) > 1:
            ticks_per_frame = max(1, int(_ROTATE_SECONDS / _TICK_SECONDS))
            new_idx = (self._state_ticks // ticks_per_frame) % len(frames)
            if new_idx != self._frame_idx:
                self._frame_idx = new_idx

        if self._view is not None:
            self._view.setNeedsDisplay_(True)
