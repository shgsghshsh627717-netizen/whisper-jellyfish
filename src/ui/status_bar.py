"""macOS 状态栏控制器，显示 Whisper-Input 的运行状态（动画水母图标）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from AppKit import NSImageOnly, NSImageScaleProportionallyDown
from Cocoa import (
    NSApplication,
    NSApplicationActivationPolicyProhibited,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSTimer,
    NSVariableStatusItemLength,
)
from PyObjCTools import AppHelper

from src.keyboard.inputState import InputState
from src.ui.jellyfish import MOTION_SPEED, draw_jellyfish


@dataclass(frozen=True)
class _StateVisual:
    description: str
    # 运动模式: "float"(上下飘) / "wobble"(左右晃) / "idle"(轻微) / "alert"
    motion: str
    # 颜色: None 表示用 template(跟随菜单栏明暗)，否则用指定 RGB
    color: Optional[Tuple[float, float, float]]


_STATE_VISUALS = {
    InputState.IDLE: _StateVisual("空闲", "idle", None),
    InputState.RECORDING: _StateVisual("录音中", "float", (0.95, 0.27, 0.27)),
    InputState.RECORDING_TRANSLATE: _StateVisual("录音中 (翻译)", "float", (0.95, 0.27, 0.27)),
    InputState.RECORDING_KIMI: _StateVisual("录音中 (本地)", "float", (0.95, 0.45, 0.13)),
    InputState.DOUBAO_STREAMING: _StateVisual("流式识别中", "float", (0.20, 0.70, 0.40)),
    InputState.PROCESSING: _StateVisual("转录处理中", "wobble", (0.23, 0.51, 0.96)),
    InputState.PROCESSING_KIMI: _StateVisual("转录处理中", "wobble", (0.23, 0.51, 0.96)),
    InputState.TRANSLATING: _StateVisual("翻译中", "wobble", (0.95, 0.77, 0.20)),
    InputState.WARNING: _StateVisual("警告", "alert", (0.95, 0.60, 0.10)),
    InputState.ERROR: _StateVisual("错误", "alert", (0.90, 0.20, 0.20)),
}


class StatusBarController:
    """管理状态栏图标和提示信息，绘制会飘动的水母。"""

    CANVAS = 22.0  # 绘制画布尺寸（点）

    def __init__(self) -> None:
        self._status_item = None
        self._menu = None
        self._current_state: InputState = InputState.IDLE
        self._queue_length: int = 0
        self._phase: float = 0.0
        self._timer = None
        self._custom_icons: Dict[str, NSImage] = {}

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动状态栏控件并进入事件循环。"""
        AppHelper.callAfter(self._setup)
        AppHelper.runConsoleEventLoop()

    def update_state(self, state: InputState, *, queue_length: int = 0) -> None:
        queue_length = max(0, queue_length)

        def _apply() -> None:
            self._current_state = state
            self._queue_length = queue_length
            self._refresh()

        AppHelper.callAfter(_apply)

    def show_error(self, message: str = "错误") -> None:
        """显示错误状态（main.py 会调用）。"""
        def _apply() -> None:
            self._current_state = InputState.ERROR
            self._refresh()

        AppHelper.callAfter(_apply)

    # ------------------------------------------------------------------
    # 初始化与事件循环
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)

        status_bar = NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)

        button = self._status_item.button()
        if button is not None:
            button.setToolTip_("Whisper-Input - 空闲")

        self._menu = NSMenu.alloc().init()
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "退出语音输入", "terminate:", ""
        )
        self._menu.addItem_(quit_item)
        self._status_item.setMenu_(self._menu)

        # 动画定时器：~10fps，持续推进相位重绘水母
        self._timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.1, True, lambda _timer: self._tick()
        )

        self._refresh()

    def _tick(self) -> None:
        visual = _STATE_VISUALS.get(self._current_state, _STATE_VISUALS[InputState.IDLE])
        self._phase += MOTION_SPEED.get(visual.motion, 0.2)
        self._refresh()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._status_item is None:
            return
        button = self._status_item.button()
        if button is None:
            return

        visual = _STATE_VISUALS.get(self._current_state, _STATE_VISUALS[InputState.IDLE])
        image = draw_jellyfish(self.CANVAS, self._phase, visual.motion, visual.color)
        image.setSize_((self.CANVAS, self.CANVAS))
        # template=True 让 macOS 按菜单栏明暗自动着色（空闲态用）
        image.setTemplate_(visual.color is None)

        button.setImage_(image)
        button.setImageScaling_(NSImageScaleProportionallyDown)
        button.setImagePosition_(NSImageOnly)

        # 排队数量显示为标题
        if self._queue_length:
            button.setTitle_(f" {self._queue_length if self._queue_length < 10 else '*'}")
            button.setImagePosition_(2)  # NSImageLeft
        else:
            button.setTitle_("")
            button.setImagePosition_(NSImageOnly)

        tooltip = f"Whisper-Input - {visual.description}"
        if self._queue_length:
            tooltip += f" | 待处理 {self._queue_length}"
        button.setToolTip_(tooltip)

