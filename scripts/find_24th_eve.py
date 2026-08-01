"""扫描所有 .eve，找出含有非 1/4 拍整数倍位置音符的谱面。

1 拍 = 240 tick，1/4 拍 = 60 tick。
任何 PLAY 事件 tick % 60 != 0 都说明该谱面有比 1/4 拍更细的分割
(1/8=30, 1/12=20, 1/16=15, 1/24=10, 1/32=7.5 不可能, 1/48=5 ...)。

专门挑含 24 分（tick % 10 == 0 且 tick % 30 != 0）的谱面做验证。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

EVE_RE = re.compile(r"^\s*(\d+)\s*,\s*(\w+)\s*,\s*(-?\d+)")


def scan(eve_path: Path) -> dict:
    ticks = []
    for line in eve_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = EVE_RE.match(line)
        if not m:
            continue
        tick, ev, _ = int(m.group(1)), m.group(2), int(m.group(3))
        if ev == "PLAY":
            ticks.append(tick)
    if not ticks:
        return {"has_24": False, "has_sub_quarter": False, "max_denom": 0, "ticks": []}

    # 量化到 1/4 拍（60 tick）看是否丢精度
    sub_quarter = [t for t in ticks if t % 60 != 0]
    # 24 分特征：tick 能被 10 整除但不能被 30 整除（即 1/12 拍 = 20tick 也是 24 分系列的倍数）
    has_24 = any(t % 10 == 0 and t % 30 != 0 for t in ticks)
    # 最大分母（相对 1 拍 = 240）
    denoms = Counter()
    for t in ticks:
        local = t % 240
        if local == 0:
            continue
        # 找最小分母 d 使 local * d % 240 == 0
        for d in (2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 96, 192, 240):
            if (local * d) % 240 == 0:
                denoms[d] += 1
                break
    return {
        "has_24": has_24,
        "has_sub_quarter": bool(sub_quarter),
        "max_denom": max(denoms) if denoms else 0,
        "denom_counts": dict(denoms),
        "n_notes": len(ticks),
        "n_sub_quarter": len(sub_quarter),
    }


def main():
    base = Path("debug_out")
    candidates = []
    for eve in base.rglob("*.eve"):
        info = scan(eve)
        if info["has_24"]:
            candidates.append((eve, info))

    candidates.sort(key=lambda x: -x[1]["n_sub_quarter"])
    print(f"含 24 分音符的 EVE 谱面共 {len(candidates)} 张：\n")
    for eve, info in candidates[:20]:
        rel = eve.relative_to(base)
        print(f"{rel}")
        print(f"  总音符 {info['n_notes']}，非 1/4 拍位置 {info['n_sub_quarter']}")
        print(f"  分母分布: {info['denom_counts']}")
        print()


if __name__ == "__main__":
    main()
