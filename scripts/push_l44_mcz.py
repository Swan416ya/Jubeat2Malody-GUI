"""提交 + 推送 mcz-releases 分支: 新 L44 资源 38 首 MCZ。

git 全局已配置 Clash 代理 (http://127.0.0.1:7890)。
每批 8 个文件, 最多重试 3 次。
"""
import subprocess
import time
from pathlib import Path

BRANCH = Path(r"E:\Program Files (x86)\Jubeat BeyondAve\Branch")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', **kw)


def main() -> int:
    result = run(['git', 'status', '--porcelain', '-z'])
    files = []
    for entry in result.stdout.split('\x00'):
        if not entry:
            continue
        path = entry[3:]  # 去掉 "?? "
        if path.endswith('.mcz'):
            files.append(path)
    if not files:
        print('无变更', flush=True)
        return 0

    print(f'{len(files)} 个文件待提交', flush=True)
    ok = 0
    batch_size = 8
    for i in range(0, len(files), batch_size):
        batch = files[i:i + batch_size]
        batch_no = i // batch_size + 1
        r = run(['git', 'add', '--'] + batch)
        if r.returncode != 0:
            print(f'  批次 {batch_no} add 失败: {r.stderr[-200:]}', flush=True)
            continue
        r = run(['git', 'commit', '-m', f'feat(mcz): L44 资源新增 {len(batch)} 首 MCZ 批次 {batch_no}'])
        if r.returncode != 0:
            print(f'  批次 {batch_no} commit 失败: {r.stderr[-200:]}', flush=True)
            continue

        pushed = False
        for attempt in range(3):
            r = run(['git', 'push', 'origin', 'mcz-releases'])
            if r.returncode == 0:
                print(f'  批次 {batch_no}: OK ({len(batch)} 个)', flush=True)
                pushed = True
                ok += len(batch)
                break
            print(f'  批次 {batch_no} 推送重试 {attempt + 1}: {r.stderr[-150:]}', flush=True)
            time.sleep(5)
        if not pushed:
            print(f'  批次 {batch_no} !!! 推送失败', flush=True)
    print(f'完成: 推送 {ok}/{len(files)}', flush=True)
    return 0 if ok == len(files) else 1


if __name__ == '__main__':
    raise SystemExit(main())
