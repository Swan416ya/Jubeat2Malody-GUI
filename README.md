# Jubeat2Malody 成品谱面库

本分支 **仅存放** 已转换好的 Malody `.mcz` 文件，与 `master` 上的源代码完全分离。

- 仓库：[Swan416ya/Jubeat2Malody-GUI](https://github.com/Swan416ya/Jubeat2Malody-GUI)
- 分支：`mcz-releases`
- 转换工具：请使用 `master` 分支的 [Jubeat2Malody GUI](https://github.com/Swan416ya/Jubeat2Malody-GUI)

---

## 欢迎 Pull Request

**个人精力有限，非常欢迎大家贡献谱面。**

如果你有空，可以：

1. 用本仓库的工具解包 / 转换 `.mcz`
2. 将文件放入下方对应版本文件夹
3. 向 `mcz-releases` 分支发起 **Pull Request**

PR 不限数量，街机各世代、国服曲目都欢迎。合并后即可供他人直接下载。

### PR 基本要求

- `.mcz` 放入**正确的版本目录**（见下表）
- 文件名使用曲名，避免特殊字符导致路径问题
- 同一曲目请勿重复提交；更新谱面请在 PR 说明中注明
- 建议 PR 标题格式：`add: jubeat-clan / 曲名` 或 `add: 音乐魔方 / 曲名`

### Fork 后提交流程（示例）

```bash
# 1. Fork 仓库后 clone，并切换到 mcz-releases
git clone https://github.com/<你的用户名>/Jubeat2Malody-GUI.git
cd Jubeat2Malody-GUI
git checkout mcz-releases

# 2. 放入 .mcz（路径按版本选择）
#    例：jubeat-beyond-ave/ヒトガタ.mcz

git add jubeat-beyond-ave/
git commit -m "add: jubeat-beyond-ave / ヒトガタ"
git push origin mcz-releases

# 3. 在 GitHub 上向 Swan416ya/Jubeat2Malody-GUI 的 mcz-releases 开 PR
```

---

## 目录结构

各文件夹**彼此平行**，按 **Jubeat 街机世代** 或 **国服客户端** 分类：

```
mcz-releases/
├── jubeat/                  # 初代 jubeat
├── jubeat-ripples/          # jubeat ripples
├── jubeat-ripples-append/   # jubeat ripples APPEND
├── jubeat-knit/             # jubeat knit
├── jubeat-copula/           # jubeat copula
├── jubeat-clan/             # jubeat clan
├── jubeat-festo/            # jubeat festo
├── jubeat-ave/              # jubeat ave.
├── jubeat-beyond-ave/       # jubeat beyond ave.
└── 音乐魔方/                 # 国服 PC（Jubeat CN），与街机各版本并列
```

> 曲目归属以**数据来源**为准：从哪一代街机数据解包就放哪一代目录；国服解包统一放 `音乐魔方/`。

### 下载直链（示例）

将 `{版本目录}`、`{文件名}` 替换为实际路径：

```
https://github.com/Swan416ya/Jubeat2Malody-GUI/raw/mcz-releases/{版本目录}/{文件名}.mcz
```

例：

```
https://github.com/Swan416ya/Jubeat2Malody-GUI/raw/mcz-releases/音乐魔方/袖手旁棺.mcz
```

---

## 维护者本地发布（worktree）

维护者本地目录与 `mcz-releases` 通过 git worktree 绑定：

```
E:\Program Files (x86)\Jubeat BeyondAve\Branch
```

```powershell
cd "E:\Program Files (x86)\Jubeat BeyondAve\Branch"
git add jubeat-beyond-ave/   # 或 音乐魔方/ 等
git commit -m "add: jubeat-beyond-ave / 曲名"
git push origin mcz-releases
```

---

## 与代码仓库的关系

| 项目 | 分支 | 内容 |
|------|------|------|
| 源代码 | `master` | GUI、解包与转换逻辑 |
| 成品谱面 | `mcz-releases` | 各版本 `.mcz` 下载包 |

两套内容互不混杂；开发代码请在 `master`，贡献谱面请 PR 到 `mcz-releases`。
