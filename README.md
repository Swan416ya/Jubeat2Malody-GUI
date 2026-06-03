# Jubeat2Malody GUI

将 Jubeat 街机游戏的谱面文件转换为 Malody V 可导入的格式，并提供可视化预览功能。

## 功能

- **解包** — 从 Jubeat 游戏文件 (IFS) 中提取谱面 (EVE)、音频 (BGM) 和元数据
- **预览** — 4×4 网格可视化谱面，支持播放动画
- **转换** — EVE ↔ Malody .mc/.mcz 互转，批量/单文件
- **管理** — 歌曲列表、封面缩略图、难度标签

## 技术栈

- **语言**: Python 3.10+
- **GUI**: PySide6 + QFluentWidgets (Fluent Design 风格)
- **核心库**:
  - `jubeatools` — EVE 谱面解析 & Malody 格式导出
  - `ifstools` — Konami IFS 文件解包
  - `ffmpeg` — 音频格式转换 (WAV → OGG)

## 项目结构

```
Jubeat2Malody GUI/
├── src/
│   ├── core/                    # 核心业务逻辑
│   │   ├── unpacker.py          # IFS 解包 & 音频转换
│   │   ├── eve_parser.py        # EVE 谱面解析
│   │   └── malody_writer.py     # Malody .mc/.mcz 生成
│   ├── gui/                     # GUI 界面
│   │   ├── main.py              # 主窗口 (FluentWindow + 导航)
│   │   ├── common/              # 公共模块
│   │   │   ├── config.py        # 全局配置 (QSettings 持久化)
│   │   │   └── signal_bus.py    # 全局信号总线 (跨组件通信)
│   │   └── pages/               # 子页面
│   │       ├── unpack_page.py   # 解包页 — IFS 批量解包
│   │       ├── preview_page.py  # 预览页 — 4×4 网格可视化 + 动画
│   │       ├── convert_page.py  # 转换页 — EVE → Malody 批量转换
│   │       └── manage_page.py   # 管理页 — 歌曲列表/搜索/筛选
│   └── resources/               # 资源文件
├── docs/
│   └── NOTES.md                 # 项目核心要点文档
├── requirements.txt
└── .gitignore
```

## 开发环境设置

```powershell
cd "E:\Python Project\Jubeat2Malody GUI"
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

```powershell
python -m src.gui.main
```

## 参考项目

### 核心格式解析

| 项目 | 说明 | 参考价值 |
|---|---|---|
| [Stepland/jubeatools](https://github.com/Stepland/jubeatools) | Jubeat 文件格式工具箱，支持 EVE/MA2 解析与 Malody 等多格式导出 | **核心依赖** — EVE 谱面解析、长按音符处理、Malody 格式导出的参考实现 |
| [mon/ifstools](https://github.com/mon/ifstools) | Konami IFS 文件解包/打包工具 | **核心依赖** — IFS 容器解包的参考实现，支持二进制 XML 转文本 |
| [chestnutcase/jubeatnet](https://github.com/chestnutcase/jubeatnet) | Jubeat 谱面分析、建模与可视化，含指法分析 | 谱面数据结构设计、4×4 网格可视化、指法模式分析的参考 |

### 谱面格式转换

| 项目 | 说明 | 参考价值 |
|---|---|---|
| [kangalio/malody-convert](https://github.com/kangalio/malody-convert) | Malody .mc → .sm 格式转换 | Malody .mc 格式解析的参考，beat/note 数据结构处理 |
| [Jakads/malody2osu](https://github.com/Jakads/malody2osu) | Malody 谱面 → osu!mania 转换 | .mc/.mcz 文件读取、批量拖拽转换的交互参考 |
| [LuiCat/mc2tja](https://github.com/LuiCat/mc2tja) | Malody → 太鼓次郎 TJA 格式转换 | Malody 格式深度解析、BPM 变化处理、beat 精度处理参考 |
| [rmstZ](https://github.com/rmstZ) | 多格式音游转谱工具，支持 imd/mc/aff/osu 等互转 | 多格式统一抽象层设计、谱面包 (.mcz/.osz) 处理参考 |

### GUI 框架

| 项目 | 说明 | 参考价值 |
|---|---|---|
| [zhiyiYo/PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) | Fluent Design 风格 PyQt/PySide 组件库 | **核心依赖** — GUI 组件库，含导航、卡片、表格等 Fluent Design 控件 |
| [mcpsde/mcz-spectral-tool](https://gitee.com/mcpsde/mcz-spectral-tool) | Python+Tkinter 的 Malody 谱面剪辑拼接工具 | .mcz 打包/解包、谱面编辑 GUI 交互的参考 |

## 许可证

GPLv3 (非商用) — 与 QFluentWidgets 开源许可一致
