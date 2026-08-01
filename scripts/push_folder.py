"""分批 commit + push 一个版本文件夹，处理含空格/特殊字符的文件名。

每次 8 个文件，最多重试 3 次。
"""
import subprocess
import sys
import time
from pathlib import Path

def push_folder(folder: str, batch_size: int = 8) -> int:
    # 用 -z 输出 null 分隔
    result = subprocess.run(
        ['git', 'status', '--porcelain', '-z', f'{folder}/'],
        capture_output=True
    )
    files = []
    for entry in result.stdout.split(b'\x00'):
        if not entry:
            continue
        path = entry[3:].decode('utf-8')
        if path.endswith('.mcz'):
            files.append(path)

    if not files:
        print(f'[{folder}] 无变更', flush=True)
        return 0

    print(f'[{folder}] {len(files)} 个文件待提交，分 {(len(files)+batch_size-1)//batch_size} 批', flush=True)
    ok = 0
    for i in range(0, len(files), batch_size):
        batch = files[i:i+batch_size]
        batch_no = i // batch_size + 1
        try:
            subprocess.run(['git', 'add', '--'] + batch, check=True)
            subprocess.run(['git', 'commit', '-m', f'fix(24分): 重生 {folder} 批次 {batch_no} (issue #1)'],
                           check=True, capture_output=True, encoding='utf-8')
        except subprocess.CalledProcessError as e:
            print(f'  [{folder}] 批次 {batch_no} commit 失败: {e}', flush=True)
            continue

        pushed = False
        for attempt in range(3):
            r = subprocess.run(['git', 'push', 'origin', 'mcz-releases'],
                               capture_output=True, text=True, encoding='utf-8')
            if r.returncode == 0:
                print(f'  [{folder}] 批次 {batch_no}: OK ({len(batch)} 个)', flush=True)
                pushed = True
                ok += len(batch)
                break
            print(f'  [{folder}] 批次 {batch_no} 重试 {attempt+1}...', flush=True)
            time.sleep(5)
        if not pushed:
            print(f'  [{folder}] 批次 {batch_no} !!! 推送失败: {r.stderr[-150:]}', flush=True)
    print(f'[{folder}] 完成: 推送 {ok}/{len(files)}', flush=True)
    return ok


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python push_folder.py <folder> [batch_size]')
        sys.exit(1)
    folder = sys.argv[1]
    bs = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    push_folder(folder, bs)
