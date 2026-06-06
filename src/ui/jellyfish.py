"""共享的水母绘制逻辑：菜单栏图标和桌面宠物都用它。"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from Cocoa import (
    NSBezierPath,
    NSColor,
    NSImage,
    NSMakePoint,
    NSMakeRect,
)

# 运动模式 -> 推进速度
MOTION_SPEED = {
    "float": 0.55,   # 录音：上下飘
    "wobble": 0.42,  # 处理：左右晃
    "alert": 0.30,   # 警告/错误
    "idle": 0.18,    # 空闲
}


def draw_jellyfish(
    size: float,
    phase: float,
    motion: str,
    color: Optional[Tuple[float, float, float]],
    alpha: float = 1.0,
) -> NSImage:
    """绘制一帧水母。

    Args:
        size: 画布边长（点）。基准设计在 22pt，其余按比例缩放。
        phase: 动画相位（弧度累加值）。
        motion: "float" / "wobble" / "alert" / "idle"。
        color: (r,g,b) 0..1；None 表示填黑（菜单栏 template 模式会被系统替换）。
        alpha: 整体不透明度。
    """
    W = H = size
    s = size / 22.0  # 缩放因子

    img = NSImage.alloc().initWithSize_((W, H))
    img.lockFocus()

    # 整体位移与触手摆幅（按运动模式）
    body_x = 0.0
    body_y = 0.0
    if motion == "float":
        body_y = 1.6 * s * math.sin(phase)
        sway_amp = 1.9 * s
    elif motion == "wobble":
        body_x = 1.8 * s * math.sin(phase)
        sway_amp = 1.2 * s
    elif motion == "alert":
        body_x = 0.8 * s * math.sin(phase * 2.0)
        sway_amp = 0.6 * s
    else:  # idle
        body_y = 0.6 * s * math.sin(phase)
        sway_amp = 0.8 * s

    if color is None:
        fill = NSColor.colorWithWhite_alpha_(0.0, alpha)
    else:
        r, g, b = color
        fill = NSColor.colorWithRed_green_blue_alpha_(r, g, b, alpha)
    fill.set()

    cx = W / 2.0 + body_x
    base_y = H * 0.54 + body_y
    bw = 6.6 * s
    bh = 5.4 * s

    # 钟罩穹顶（∩ 形 + 底缘三个浅扇贝）
    bell = NSBezierPath.bezierPath()
    bell.moveToPoint_(NSMakePoint(cx - bw, base_y))
    bell.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(cx, base_y + bh),
        NSMakePoint(cx - bw, base_y + bh * 0.95),
        NSMakePoint(cx - bw * 0.45, base_y + bh),
    )
    bell.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(cx + bw, base_y),
        NSMakePoint(cx + bw * 0.45, base_y + bh),
        NSMakePoint(cx + bw, base_y + bh * 0.95),
    )
    dip = 1.0 * s
    bell.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(cx + bw / 3.0, base_y),
        NSMakePoint(cx + bw * 0.78, base_y - dip),
        NSMakePoint(cx + bw * 0.55, base_y - dip),
    )
    bell.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(cx - bw / 3.0, base_y),
        NSMakePoint(cx + bw / 6.0, base_y - dip),
        NSMakePoint(cx - bw / 6.0, base_y - dip),
    )
    bell.curveToPoint_controlPoint1_controlPoint2_(
        NSMakePoint(cx - bw, base_y),
        NSMakePoint(cx - bw * 0.55, base_y - dip),
        NSMakePoint(cx - bw * 0.78, base_y - dip),
    )
    bell.closePath()
    bell.fill()

    # 触手：4 条，每条 3 颗小圆球，随相位摆动
    n_tent = 4
    for i in range(n_tent):
        tx = cx - bw * 0.58 + i * (bw * 1.16 / (n_tent - 1))
        for k in range(3):
            depth = k + 1
            yy = base_y - 1.6 * s - k * 2.6 * s
            sway = sway_amp * math.sin(phase * 1.3 + k * 0.85 + i * 0.7) * (depth / 3.0)
            xx = tx + sway
            rad = (1.3 - k * 0.27) * s
            dot = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(xx - rad, yy - rad, rad * 2, rad * 2)
            )
            dot.fill()

    img.unlockFocus()
    return img
