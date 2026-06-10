<div align="center">

# Jubeat2Malody GUI

**将 Jubeat 街机 / 国服 PC 谱面解包、预览，并转换为 Malody V 可导入的 `.mcz`**

<br>

<table>
  <tr>
    <td align="center"><b>街机 IFS / EVE</b><br><sub>contents/data 解包</sub></td>
    <td align="center">➜</td>
    <td align="center"><b>歌曲资源目录</b><br><sub>EVE · MIDI · BGM · 封面</sub></td>
    <td align="center">➜</td>
    <td align="center"><b>Malody .mcz</b><br><sub>含谱师 · 等级 · 曲绘</sub></td>
  </tr>
</table>

<br>

<img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<img src="https://img.shields.io/badge/GUI-PySide6%20Fluent-41CD52?style=flat-square&logo=qt&logoColor=white" alt="PySide6 Fluent">
<img src="https://img.shields.io/badge/License-GPLv3%20(non--commercial)-blue?style=flat-square" alt="License">

</div>

---

## 简介

本项目面向 **Jubeat** 玩家与谱面爱好者，提供一站式桌面工具链：

- 从 **街机数据**（IFS / EVE）或 **国服 PC 客户端**（Unity Bundle / MIDI）提取谱面与音频  
- 在 **4×4 网格** 中预览谱面并与 BGM 同步播放  
- 导出符合 Malody V 规范的谱面包，含难度等级、谱师信息与封面  

无需手动拼 JSON 或处理 Konami 专有音频格式，解包 → 预览 → 转换可在 GUI 内完成；也提供 **CLI** 便于脚本化批量处理。

---

## 功能一览

<table>
  <thead>
    <tr>
      <th width="18%">模块</th>
      <th width="42%">说明</th>
      <th width="40%">入口</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>街机曲库</b></td>
      <td>扫描 <code>contents/data</code>，批量解包 IFS，解析 <code>music_info.xml</code></td>
      <td>GUI → <b>街机曲库</b></td>
    </tr>
    <tr>
      <td><b>国服曲库</b></td>
      <td>扫描国服 HotUpdate Bundle，提取 OGG / MIDI / 封面 / 曲名等级</td>
      <td>GUI → <b>国服曲库</b></td>
    </tr>
    <tr>
      <td><b>谱面预览</b></td>
      <td>4×4 网格动画、难度切换、BGM 同步、变速播放</td>
      <td>GUI → <b>预览</b></td>
    </tr>
    <tr>
      <td><b>格式转换</b></td>
      <td>自动识别 EVE / CN MIDI，输出 <code>.mcz</code>（<code>BSC Lv5</code> 命名）</td>
      <td>GUI → <b>转换</b></td>
    </tr>
    <tr>
      <td><b>命令行</b></td>
      <td>批量转换、国服搜索 / 解包 / 一键出包</td>
      <td><code>scripts/jubeat2malody.py</code></td>
    </tr>
  </tbody>
</table>

<details>
<summary><b>Malody 导出元数据（点击展开）</b></summary>

<br>

| 字段 | 街机 | 国服 |
|------|------|------|
| 谱师 `creator` | `jubeat` | `音乐魔方` |
| 难度 `version` | `BSC Lv5` 等 | 同左 |
| 等级 `level` | 来自 `music_info.xml` | 来自曲库 Protobuf |
| 音频 | WAV 4× 增益 → OGG | OGG 原样复制 |
| BPM | EVE TEMPO | `chart.mid` 内 tempo |

</details>

---

## 快速开始

### 环境要求

- Windows 10/11（主要开发与测试平台）
- Python **3.10+**
- **ffmpeg**（需在 PATH 中，用于 WAV → OGG）

### 安装与运行

```powershell
cd "E:\Python Project\Jubeat2Malody GUI"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 启动 GUI
python -m src.gui.main
```

### CLI 示例

```powershell
# 已解包目录 → .mcz
python scripts/jubeat2malody.py convert "debug_out/某曲目录" -o debug_out/mcz

# 批量转换
python scripts/jubeat2malody.py convert "debug_out/cn_batch" -o debug_out/mcz --batch

# 国服：搜索 / 解包 / 一键出包
python scripts/jubeat2malody.py cn-search 自电感应
python scripts/jubeat2malody.py cn-mcz 995000003 -o debug_out/cn_mcz
```

---

## 文档索引

<div align="center">

| | 文档 | 适合阅读对象 |
|:---:|:---|:---|
| 📋 | [**项目核心要点**](./docs/NOTES.md) | 想快速了解格式、依赖与转换流程 |
| 🔧 | [**解析逻辑详解**](./docs/PARSING_LOGIC.md) | 需要深入 IFS / EVE / Malody 实现细节 |
| 🛠️ | [**解包诊断脚本**](./scripts/debug_unpack_one.py) | 街机单曲解包排错（命令行） |
| ⌨️ | [**CLI 工具**](./scripts/jubeat2malody.py) | 批量转换与国服操作（命令行） |

</div>

<br>

<table>
  <tr>
    <td width="50%" valign="top">

### 📋 [NOTES.md](./docs/NOTES.md)

项目速查手册：文件格式、目录结构、核心依赖、Malody `.mc` 字段约定。

</td>
    <td width="50%" valign="top">

### 🔧 [PARSING_LOGIC.md](./docs/PARSING_LOGIC.md)

端到端解析管线：IFS 解包、元数据、BMP 音频、EVE→Song、国服 MIDI、`.mcz` 打包与设计取舍。

</td>
  </tr>
</table>

---

## 项目结构

```
Jubeat2Malody GUI/
├── src/
│   ├── core/
│   │   ├── unpacker.py          # 街机 IFS 解包 · 元数据 · 音频
│   │   ├── cn_bundles.py        # 国服 Unity Bundle 解包
│   │   ├── cn_midi.py           # 国服 MIDI → jubeatools Chart
│   │   ├── eve_parser.py        # EVE 谱面加载
│   │   ├── malody_writer.py     # Malody .mc / .mcz 生成
│   │   └── song_pack.py         # 街机 / 国服自动识别
│   ├── gui/
│   │   ├── main.py              # Fluent 主窗口
│   │   └── pages/               # 街机曲库 · 国服曲库 · 预览 · 转换
│   └── ...
├── scripts/
│   ├── jubeat2malody.py         # CLI
│   └── debug_unpack_one.py      # 单曲解包诊断
├── docs/
│   ├── NOTES.md
│   └── PARSING_LOGIC.md
├── data/                        # 曲名 / 元数据参考表
└── requirements.txt
```

---

## 技术栈

<table>
  <tr>
    <td><b>GUI</b></td>
    <td>PySide6 · <a href="https://github.com/zhiyiYo/PyQt-Fluent-Widgets">QFluentWidgets</a>（Fluent Design）</td>
  </tr>
  <tr>
    <td><b>谱面</b></td>
    <td><a href="https://github.com/Stepland/jubeatools">jubeatools</a> — EVE / Malody 互转</td>
  </tr>
  <tr>
    <td><b>解包</b></td>
    <td><a href="https://github.com/mon/ifstools">ifstools</a> · UnityPy（国服）· mido（MIDI）</td>
  </tr>
  <tr>
    <td><b>媒体</b></td>
    <td>ffmpeg · 内置 Konami BMP 解码与导出增益</td>
  </tr>
</table>

---

## 参考项目

<details>
<summary><b>格式解析 · 转换 · GUI（点击展开）</b></summary>

| 项目 | 说明 |
|------|------|
| [Stepland/jubeatools](https://github.com/Stepland/jubeatools) | EVE 解析、Malody 导出（**核心依赖**） |
| [mon/ifstools](https://github.com/mon/ifstools) | Konami IFS 解包（**核心依赖**） |
| [chestnutcase/jubeatnet](https://github.com/chestnutcase/jubeatnet) | 4×4 网格与谱面结构参考 |
| [kangalio/malody-convert](https://github.com/kangalio/malody-convert) | Malody `.mc` 格式参考 |
| [zhiyiYo/PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) | Fluent GUI 组件（**核心依赖**） |

</details>

---

<div align="center">

<br>

<sub>

<b>许可证</b> · GPLv3（非商用）— 与 QFluentWidgets 开源许可一致

<br><br>

如果本项目对你有帮助，欢迎 Star ⭐

</sub>

</div>
