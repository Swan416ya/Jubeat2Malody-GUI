"""驱动 rerun_all_mcz_from_extract.py 分段跑完 720 首。

每段 50 首（约 7-8 分钟），确保单次前台调用在 10 分钟超时内完成。
段与段之间是独立的前台调用，不会被父任务超时连累。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rerun_all_mcz_from_extract.py"
LOG = ROOT / "debug_out" / "_rerun_full.log"

BATCH_SIZE = 50
TOTAL = 720  # 已知总数，超出无所谓


def main() -> int:
    start = 0
    seg = 0
    t0 = time.time()
    while start < TOTAL:
        seg += 1
        elapsed = time.time() - t0
        print(f"\n>>> 段 {seg}: start={start}, limit={BATCH_SIZE}  (累计已用 {elapsed:.0f}s)", flush=True)
        cmd = [sys.executable, "-u", str(SCRIPT),
               "--start", str(start), "--limit", str(BATCH_SIZE), "--no-clear"]
        # 首段不清空会保留旧文件，但我们已经清空过了，这里 --no-clear 正确
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"\n>>> 段 {seg}: start={start}\n")
            f.flush()
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                                    cwd=str(ROOT), timeout=590)  # 9.8 分钟超时
        if result.returncode != 0:
            print(f"!!! 段 {seg} 返回码 {result.returncode}", flush=True)
        start += BATCH_SIZE
    print(f"\n=== 全部 {seg} 段完成，总耗时 {time.time()-t0:.0f}s ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
