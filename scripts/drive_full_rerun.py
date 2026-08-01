"""全量重跑协调器：每跑够 ~100 首就 commit + push 一次。

调用 rerun_all_mcz_from_extract.py 分段跑（每段 35 首，10 分钟内完成），
累积到 batch_size 首时统一 commit + push。
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RERUN_SCRIPT = ROOT / "scripts" / "rerun_all_mcz_from_extract.py"
BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")

BATCH_SIZE = 35      # 每段跑多少首（10 分钟内）
COMMIT_THRESHOLD = 100  # 累积多少首后 commit + push


def run_segment(start: int, limit: int) -> tuple[int, int]:
    """跑一段，返回 (ok, fail)。"""
    cmd = [sys.executable, "-u", str(RERUN_SCRIPT),
           "--start", str(start), "--limit", str(limit), "--no-clear"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                            cwd=str(ROOT), timeout=590)
    # 从输出解析 ok/fail
    ok = fail = 0
    for line in result.stdout.splitlines():
        if "完成:" in line:
            # 格式: 完成: 成功 40 | 失败 0 | 耗时 414.7s
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "成功":
                    ok = int(parts[i+1])
                elif p == "失败":
                    fail = int(parts[i+1])
    if ok == 0 and fail == 0:
        print(f"  !!! 无法解析输出, 最后 200 字: {result.stdout[-200:]}", flush=True)
    return ok, fail


def commit_and_push(batch_no: int, total_ok: int) -> bool:
    """commit + push 当前所有变更。"""
    # git add -A
    subprocess.run(["git", "add", "-A"], cwd=str(BRANCH), check=True)
    msg = f"重生{total_ok}首谱面"
    subprocess.run(["git", "commit", "-m", msg], cwd=str(BRANCH),
                   capture_output=True, encoding='utf-8')
    # push，最多重试 3 次
    for attempt in range(3):
        r = subprocess.run(["git", "push", "origin", "mcz-releases"],
                           cwd=str(BRANCH), capture_output=True, text=True, encoding='utf-8')
        if r.returncode == 0:
            print(f"  >>> 批次 {batch_no}: commit '{msg}' 推送成功 (累计 {total_ok} 首)", flush=True)
            return True
        print(f"  >>> 批次 {batch_no}: push 重试 {attempt+1}...", flush=True)
        time.sleep(5)
    print(f"  >>> 批次 {batch_no}: !!! push 失败: {r.stderr[-150:]}", flush=True)
    return False


def main():
    TOTAL = 1063
    total_ok = 0
    total_fail = 0
    since_last_commit = 0
    batch_no = 0
    t0 = time.time()

    start = 0
    while start < TOTAL:
        ok, fail = run_segment(start, BATCH_SIZE)
        total_ok += ok
        total_fail += fail
        since_last_commit += ok + fail
        start += BATCH_SIZE
        elapsed = time.time() - t0
        print(f"  已跑 {start}/{TOTAL}, 累计 OK {total_ok} FAIL {total_fail}, "
              f"距上次 commit {since_last_commit} 首, 已用 {elapsed:.0f}s", flush=True)

        if since_last_commit >= COMMIT_THRESHOLD or start >= TOTAL:
            batch_no += 1
            commit_and_push(batch_no, total_ok)
            since_last_commit = 0

    print(f"\n=== 全部完成: OK {total_ok} | FAIL {total_fail} | {batch_no} 批 | "
          f"总耗时 {time.time()-t0:.0f}s ===", flush=True)


if __name__ == "__main__":
    main()
