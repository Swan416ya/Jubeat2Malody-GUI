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
│   ├── core/               # 核心业务逻辑
│   │   ├── unpacker.py     # IFS 解包 & 音频转换
│   │   ├── eve_parser.py   # EVE 谱面解析
│   │   └── malody_writer.py # Malody .mc/.mcz 生成
│   ├── gui/                # GUI 界面
│   └── resources/          # 资源文件
├── venv/                   # 虚拟环境
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

## 许可证

GPLv3 (非商用) — 与 QFluentWidgets 开源许可一致
