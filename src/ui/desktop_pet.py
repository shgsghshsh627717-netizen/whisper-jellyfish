"""桌面宠物水母：可拖拽、浮在所有窗口最上层的悬浮水母（图片帧形象）。

形象来自 assets/pet/*.png（粉色水母表情包），跟随录音状态切换表情并轻轻飘动。
拖拽可移动（位置记忆到磁盘），轻点（非拖拽）触发回调（开始/停止录音）。
"""

from __future__ import annotations

import json
import math
import os
from typing import Callable, Dict, Optional, Tuple

import objc
from AppKit import (
    NSColor,
    NSCompositingOperationClear,
    NSEvent,
    NSImage,
    NSMakeRect,
    NSPanel,
    NSRectFillUsingOperation,
    NSScreen,
    NSTimer,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSPopUpMenuWindowLevel,
)
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

        # 等比缩放，留出飘动的余量
        pad = 10.0
        avail = min(b.size.width, b.size.height) - pad * 2
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
        y = (b.size.height - dh) / 2.0 + oy
        img.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(x, y, dw, dh), NSMakeRect(0, 0, isz.width, isz.height), 1, 1.0
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

    def __init__(self, on_click: Optional[Callable[[], None]] = None) -> None:
        self._panel: Optional[NSPanel] = None
        self._view: Optional[_JellyView] = None
        self._timer = None
        self._state: InputState = InputState.IDLE
        self.phase: float = 0.0
        self._on_click = on_click
        self._images: Dict[str, NSImage] = {}
        self._frame_idx: int = 0          # 当前轮换帧
        self._state_ticks: int = 0        # 进入当前状态后经过的 tick 数

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

        pos = self._load_position()
        if pos is None:
            x = sf.size.width - size - 40
            y = 140
        else:
            x, y = pos
            x = max(0, min(x, sf.size.width - size))
            y = max(0, min(y, sf.size.height - size))

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, size, size), style, 2, False
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
            NSMakeRect(0, 0, size, size), self
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
