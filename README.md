# Jubeat2Malody 成品谱面包

本分支 **仅存放** 已转换好的 Malody `.mcz` 文件，与主分支的源代码完全分离。

- 仓库：`https://github.com/Swan416ya/Jubeat2Malody-GUI`
- 分支：`mcz-releases`
- 本地目录：`E:\Program Files (x86)\Jubeat BeyondAve\Branch`（git worktree）

## 目录结构

```
v{版本号}/
├── arcade/     # 街机 / 日服解包转换
└── cn/         # 国服解包转换
```

示例：`v1.0/arcade/ヒトガタ.mcz`

版本号对应转换工具发布批次（如音频增益、曲绘修复等更新后递增 `v1.1`、`v2.0`）。

## 发布流程

在本目录（worktree）中操作：

```powershell
cd "E:\Program Files (x86)\Jubeat BeyondAve\Branch"

# 1. 将 .mcz 放入对应版本子目录
#    例：v1.0/cn/袖手旁棺.mcz

# 2. 提交并推送
git add v1.0/
git status
git commit -m "release: v1.0 添加国服曲目"
git push origin mcz-releases
```

他人下载单文件（将 `{曲名}`、`{版本}` 替换为实际路径）：

```
https://github.com/Swan416ya/Jubeat2Malody-GUI/raw/mcz-releases/v{版本}/cn/{曲名}.mcz
```

## 与代码仓库的关系

| 项目 | 分支 | 内容 |
|------|------|------|
| 源代码 | `master` | Python GUI / 转换逻辑 |
| 成品谱面 | `mcz-releases` | `.mcz` 下载包 |

主项目目录通过 `git worktree` 绑定本文件夹，切换 `master` 不会影响此处文件。
