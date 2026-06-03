# 项目核心要点文档

## 1. 项目目标

将 Jubeat 街机游戏的谱面文件 (EVE) 转换为 Malody V 音游模拟器可导入的格式 (.mc/.mcz)，
并提供 GUI 界面支持解包、预览和批量转换。

## 2. 文件格式说明

### Jubeat 游戏文件结构
```
contents/data/
├── ifs_pack/                    # 谱面包目录
│   └── dXXXXXXXX/               # 按ID范围分组
│       └── XXXXXXXXX_msc.ifs    # 单曲IFS包(含谱面+音频)
└── music_info/
    └── music_info.xml           # 歌曲元数据(名称/BPM/难度)
```

### IFS 文件 (Konami 容器格式)
- 用 `ifstools` 解包 (pip install ifstools)
- 内含: `bsc.eve`, `adv.eve`, `ext.eve` (三个难度谱面), `bgm.bin`, `idx.bin` (音频)
- 部分文件加密 (含 `dummy_Edat`)，无法解包

### EVE 谱面格式
- 纯文本，每行格式: `tick, COMMAND, value`
- 关键命令:
  - `HAKU` — 节拍标记，间隔 = ticks_per_beat
  - `TEMPO` — BPM 变化，value/1000.0 = BPM
  - `PLAY` — 点击音符，value = 位置 (0-15, 4×4 网格)
  - `LONG` — 长按音符，编码较复杂，用 jubeatools 解析

### BMP 音频格式 (Konami 自有)
- 文件头 `BMP\x00`，混合字节序
- 头部 32 字节含: data_size(大端), channels(大端), bits(大端), sample_rate(大端)
- 偏移 32 字节后为 PCM 数据
- 需转换为标准 WAV 后再转 OGG

### Malody .mc 格式 (JSON)
```json
{
  "meta": {
    "song": "曲名", "artist": "艺术家", "charter": "制谱者",
    "bpm": 120.0, "mode": "key", "mode_ext": 16,
    "version": 2, "difficulty": 0, "level": "5",
    "audio": "bgm.ogg", "offset": 0
  },
  "time": [{"beat": [0,0,1], "bpm": 120.0}],
  "note": [
    {"beat": [0,0,1], "index": 0, "type": 0},           // tap
    {"beat": [1,0,1], "index": 5, "type": 1,             // long
     "endbeat": [2,0,1], "endindex": 5}
  ]
}
```
- beat 格式: `[measure, numerator, denominator]` = measure + numerator/denominator 拍
- type: 0=tap, 1=hold/long
- mode_ext=16 表示 16 键 (对应 jubeat 4×4 网格)

### .mcz 格式
- 标准 ZIP 文件，内含 .mc 文件 + 音频文件
- Malody V 直接导入此格式

## 3. 核心依赖

| 库 | 用途 | 安装 |
|---|---|---|
| `jubeatools` | EVE 解析 + Malody 导出 + 长按音符解析 | pip install jubeatools |
| `ifstools` | Konami IFS 文件解包 | pip install ifstools |
| `PySide6-Fluent-Widgets` | Fluent Design 风格 GUI | pip install PySide6-Fluent-Widgets |
| `ffmpeg` | WAV→OGG 音频转换 (系统需安装) | 外部依赖 |

## 4. 转换流程

```
IFS 文件
  → ifstools 解包 → EVE + BGM.bin + 元数据
  → EVE 解析 (jubeatools + 自定义解析器)
  → BGM.bin → WAV (内置 BMP 解码器) → OGG (ffmpeg)
  → 生成 .mc (JSON) + 打包 .mcz (ZIP)
```

## 5. jubeatools 关键接口

```python
from jubeatools.formats.konami.eve.load import load_eve
from jubeatools.formats.malody.dump import dump_malody_chart

# 加载 EVE
song = load_eve(Path("bsc.eve"))  # 返回 Song 对象
# song.charts: {Difficulty: Chart}
# Chart.notes: List[Union[TapNote, LongNote]]

# 导出 Malody
malody_dict = dump_malody_chart(chart, song_metadata)
```

## 6. GUI 架构规划

- **框架**: PySide6 + QFluentWidgets (Fluent Design / WinUI 风格)
- **许可**: GPLv3 (非商用免费，与 QFluentWidgets 开源版一致)
- **主要页面**:
  1. 解包页 — 选择游戏目录 → 批量解包 IFS
  2. 预览页 — 4×4 网格可视化谱面 + 播放动画
  3. 转换页 — EVE → Malody 批量/单文件转换
  4. 管理页 — 歌曲列表、搜索、筛选

## 7. 已验证的可行性

- ✅ ifstools 可解包 Jubeat BeyondAve 的 IFS 文件
- ✅ EVE 谱面可被 jubeatools 正确解析 (含长按音符)
- ✅ 转换后的 .mc 文件格式正确，Malody V 可导入
- ✅ BMP→WAV 转换正常，ffmpeg WAV→OGG 正常
- ✅ .mcz 打包格式正确
- ⚠️ 部分 IFS 文件加密 (dummy_Edat)，无法解包
