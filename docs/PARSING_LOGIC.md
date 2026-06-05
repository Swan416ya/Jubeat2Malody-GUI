# Jubeat2Malody 解析逻辑详解

从 Jubeat 街机游戏文件到 Malody V 可导入格式的完整解析流程，
包括每一步的实现细节、使用的库、参考的仓库，以及设计决策背后的原因。

---

## 整体流程概览

```
Jubeat 游戏数据目录 (contents/data/)
├── ifs_pack/d{X}/
│   ├── {id}_msc.ifs    → 谱面 + 音频
│   └── {id}_jkt.ifs    → 封面图片
├── music_info/music_info.xml  → 歌曲元数据 (曲名/BPM/难度)
└── word_info/word_info.xml    → 补充曲名/艺术家

转换管线:
IFS → ifstools解包 → EVE谱面 + BGM.bin + 纹理PNG
                      ↓
           music_info.xml → 曲名/BPM/难度
           word_info.xml  → 补充曲名
           _jkt.ifs       → 封面图
           BMP解码 → WAV → OGG(ffmpeg)
                      ↓
           EVE解析(jubeatools) → Song对象
                      ↓
           Malody .mc生成 + .mcz打包 → 可导入文件
```

---

## 1. IFS 文件解包

### IFS 是什么

IFS (Image File System) 是 Konami 街机游戏的自定义容器格式，内含带清单(manifest)的虚拟文件系统。每首歌对应两个 IFS：

| 文件 | 内容 |
|---|---|
| `{id}_msc.ifs` | 谱面(bsc.eve/adv.eve/ext.eve) + 音频(bgm.bin/idx.bin) |
| `{id}_jkt.ifs` | 封面图片(纹理) |

### 使用的库：ifstools

- **仓库**: [mon/ifstools](https://github.com/mon/ifstools)
- **选择原因**: 唯一能正确解包 Konami IFS 的 Python 库。核心能力：
  1. 解析 IFS 的**二进制 XML manifest**（Konami 自定义格式，非标准 XML）
  2. 提取内部文件到磁盘
  3. **自动将纹理转换为 PNG** — 获取封面图的关键

### 实现要点

```python
# unpacker.py — extract_ifs()
ifs = ifstools.IFS(str(ifs_path))
ifs.extract(path=str(output_dir))          # 解包所有文件
extracted = [f.name for f in ifs.tree.all_files]
ifs.close()
```

**加密检测**: manifest 含 `dummy_Edat` 表示加密，ifstools 无法解包，需提前跳过。

**目录修正**: ifstools 会创建 `{stem}_ifs/` 子目录，需将文件移到上层保持扁平结构。

### 为什么不用其他方案

| 方案 | 问题 |
|---|---|
| 手写 IFS 解析器 | 二进制 XML + 多种压缩，工程量巨大 |
| QuickBMS 脚本 | 需外部工具，不适合 Python 集成 |
| 硬编码偏移读取 | 文件偏移由 manifest 动态计算 |

---

## 2. 元数据解析（曲名 / BPM / 难度）

### music_info.xml 结构

```xml
<music_info><body><data>
  <music_id>10000001</music_id>
  <title_name>Twinkle☆Star</title_name>                    <!-- 可读曲名 -->
  <ascii_name>8389828d838e839382c581998358837b</ascii_name> <!-- Shift-JIS hex -->
  <name_string>837483878393838282c581998358837b</name_string><!-- 日文名 hex -->
  <copyright_name>KONAMI</copyright_name>
  <bpm_min>3000000</bpm_min>   <!-- 微秒/拍 -->
  <bpm_max>3000000</bpm_max>
  <level_bsc>3</level_bsc>
  <detail_level_bsc>3.0</detail_level_bsc>
</data></body></music_info>
```

### 曲名解码：Shift-JIS 十六进制

`ascii_name` / `name_string` 是 Shift-JIS 编码的十六进制字符串。
Konami 用 hex 编码可能是为了避免 XML 特殊字符问题。

实现采用**多编码回退**（`unpacker.py — decode_name_string()`）：

```python
raw = bytes.fromhex(encoded)
for encoding in ("shift_jis", "cp932", "euc_jp", "utf-8"):
    try:
        result = raw.decode(encoding)
        # 验证无控制字符
        if result and not any(ord(c) < 0x20 and c not in "\n\r\t" for c in result):
            return result
    except (UnicodeDecodeError, ValueError):
        continue
```

多编码回退的原因：不同版本 Jubeat 可能使用不同编码，Shift-JIS 最常见但 CP932/EUC-JP 也有可能。

### 曲名优先级

```
title_name > ascii_name > name_string > copyright_name > "unknown_{id}"
```

| 字段 | 说明 | 可靠性 |
|---|---|---|
| `title_name` | 明文曲名，部分版本直接包含 | **最高** |
| `ascii_name` | 罗马音/英文 (Shift-JIS hex) | 高 |
| `name_string` | 日文名 (Shift-JIS hex) | 中 |
| `copyright_name` | 版权信息 | 低 |

`title_name` 优先是因为无需编码转换，最不易出错。此字段的发现参考了 **jubeat_patcher** 的 `music_db.cc` 源码。

### BPM 转换

XML 中 BPM 使用**微秒/拍**单位，需转换为标准 BPM：

```python
bpm = 60_000_000 / raw_value    # 微秒/拍 → BPM
```

代码同时处理两种格式：`raw_value > 1000` 视为微秒/拍，否则视为直接 BPM 值，兼容不同版本。

### word_info.xml 补充

`word_info.xml` 可能包含更完整的标题/艺术家信息，但结构不固定。
通过模糊匹配 `title`+`name` / `artist`+`name` 关键词提取。

---

## 3. 封面图片提取

### 封面图的两种来源

1. **`_msc.ifs` 中的纹理**: ifstools 解包时自动将纹理转 PNG（部分版本内嵌封面）
2. **`_jkt.ifs` 专用封面包**: 大部分歌曲的封面存储在独立文件中

### 提取流程

```
1. 检查 _msc.ifs 解包后是否有 PNG → ifstools 自动转换纹理
2. 没有则查找 _jkt.ifs / _ifs.ifs（在 ifs_dir 及 d{X}/ 子目录中搜索）
3. 解包 _jkt.ifs 到临时目录
4. 从候选图片中选最佳封面
```

### ifstools 为什么能自动提取纹理

ifstools 内部实现了 Konami 纹理格式解析器，读取 manifest 中声明的纹理资源（如 `<texture format="argb8888">`）后直接输出 PNG。这是它相比其他 IFS 工具的核心优势。

### 封面选择策略 (`_pick_best_jacket`)

```
1. 最优: 文件名含 jkt/jacket/cover + music_id
2. 次优: 文件名含 jkt/jacket/cover
3. 兜底: 最大的图片文件
```

`jkt` 是 Konami 内部对 jacket（封面）的缩写。IFS 解包后可能产生多张 PNG（按钮纹理、背景等），需通过关键词筛选。

---

## 4. BMP 音频解码

### Konami BMP 格式（非标准 BMP 图片）

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0x00 | 4 | 魔数 | `BMP\x00` |
| 0x04 | 4 | data_size | 大端序 |
| 0x10 | 2 | channels | 声道数 (1/2) |
| 0x12 | 2 | bits | 位深 (16) |
| 0x14 | 4 | sample_rate | 采样率 |
| 0x20 | - | PCM data | 原始采样数据 |

**混合字节序问题**: 部分文件的 channels/bits/sample_rate 使用小端序，代码做了大端→小端回退：

```python
# 先尝试大端
channels = struct.unpack(">H", data[16:18])[0]
# 失败则回退小端
if channels not in (1, 2):
    channels = struct.unpack("<H", data[16:18])[0]
```

### 转换链路

```
bgm.bin (Konami BMP) → bgm.wav (标准 WAV) → bgm.ogg (OGG Vorbis, ffmpeg)
```

WAV→OGG 使用 ffmpeg：`ffmpeg -i bgm.wav -c:a libvorbis -q:a 4 bgm.ogg`

如果 ffmpeg 不可用，回退使用 WAV 文件（Malody 也支持 WAV）。

---

## 5. EVE 谱面解析

### EVE 格式

纯文本，每行 `tick, COMMAND, value`：

```
0, HAKU, 1          # 节拍标记
0, TEMPO, 3000000   # BPM变化 (微秒/拍)
480, PLAY, 5        # 点击音符 (位置5)
960, LONG, ...      # 长按音符 (编码复杂)
```

| 命令 | 说明 |
|---|---|
| `HAKU` | 节拍标记，间隔 = ticks_per_beat |
| `TEMPO` | BPM 变化，value = 微秒/拍 |
| `PLAY` | 点击音符，value = 位置 (0-15, 4×4网格) |
| `LONG` | 长按音符，编码复杂 |

### 使用的库：jubeatools

- **仓库**: [Stepland/jubeatools](https://github.com/Stepland/jubeatools)
- **选择原因**: 最完整的 Jubeat 格式工具箱，正确处理：
  1. tick→beat 转换（通过 TimeMap）
  2. TEMPO→BPM 转换（微秒/拍 → BPM）
  3. **长按音符解码**（EveLong 的 position/direction/duration 编码，这是最难的部分）
  4. Malody 格式导出

### 实现要点

```python
# eve_parser.py
from jubeatools.formats.konami.eve.load import iter_events, load_file
from jubeatools.formats.konami.load_tools import make_chart_from_events

lines = load_file(eve_path)                    # 读取 EVE 文件
events = list(iter_events(lines))               # 解析事件列表
chart = make_chart_from_events(events, beat_snap=240)  # 生成 Chart 对象
```

`beat_snap=240` 表示 1/240 拍的量化精度，足以处理绝大多数谱面。

### 为什么不自己写 EVE 解析器

长按音符(LONG)的编码非常复杂——一个 LONG 事件需要结合 position、direction、duration 三个维度解码出起始位置、结束位置和时长。jubeatools 已经完整实现了这套逻辑，且经过社区验证。

---

## 6. Malody .mc 格式生成

### .mc 格式结构 (JSON)

```json
{
  "meta": {
    "song": "曲名", "artist": "Konami",
    "mode": "key", "mode_ext": {},     // Malody V 必需
    "audio": "bgm.ogg", "version": 2
  },
  "time": [{"beat": [0,0,1], "bpm": 120.0}],
  "note": [
    {"beat": [0,0,1], "index": 0, "type": 0},        // tap
    {"beat": [1,0,1], "index": 5, "type": 1,          // long/hold
     "endbeat": [2,0,1], "endindex": 5}
  ],
  "extra": {"BSC": {"divide":4,"speed":100,...}}       // Malody V 必需
}
```

- **beat 格式**: `[measure, numerator, denominator]` = measure + numerator/denominator 拍
- **type**: 0=tap, 1=hold/long
- **mode_ext**: 16键模式 (4×4 网格)

### 使用的库：jubeatools (Malody 导出)

```python
from jubeatools.formats.malody.dump import dump_malody_chart
from jubeatools.formats.malody import schema as malody

malody_chart = dump_malody_chart(metadata, diff_name, chart, timing)
json_chart = malody.CHART_SCHEMA.dump(malody_chart)
```

### 补全的必需字段

jubeatools 生成的 JSON 缺少 Malody V 导入必需的两个字段，需要手动补全：

```python
# 1. meta.mode_ext — 模式扩展参数
json_chart["meta"]["mode_ext"] = {}

# 2. extra — 编辑器附加信息
json_chart["extra"] = {diff_name: {"divide": 4, "speed": 100, "save": 0, "lock": 0, "edit_mode": 0}}
```

**发现过程**: 通过对比 Malody V 导出的真实谱面文件，发现这两个字段是导入时的硬性要求。
缺少 `mode_ext` 会导致 Malody 无法识别谱面模式；缺少 `extra` 会导致导入后只显示条目但无谱面数据。

### 音频文件名修正

如果 WAV→OGG 转换失败回退到 WAV，需要同步更新 .mc 中 Sound 事件的音频路径：

```python
if audio_filename:
    for note in json_chart.get("note", []):
        if note.get("type") == 1 and "sound" in note:
            note["sound"] = audio_filename
```

---

## 7. .mcz 打包

### .mcz 格式

标准 ZIP 文件，内部结构：

```
0/                    ← 必须在 0/ 目录下
├── songname_bsc.mc   ← 谱面文件
├── songname_adv.mc
├── songname_ext.mc
├── bgm.ogg           ← 音频文件
└── jkt_10000001.png  ← 封面图(可选)
```

**`0/` 目录前缀**: Malody V 导入要求文件在 `0/` 子目录下，这是 Malody 的多难度组织约定。

### 实现要点

```python
with zipfile.ZipFile(mcz_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for mc_fn, mc_path in mc_files:
        zf.write(mc_path, f"0/{mc_fn}")        # 谱面
    zf.write(audio_path, f"0/{audio_filename}") # 音频
    if img_path:
        zf.write(img_path, f"0/{img_filename}") # 封面
```

---

## 8. 曲名在线查询机制

### 问题

部分版本的 `music_info.xml` 不包含 `title_name`，且 `ascii_name`/`name_string` 解码后可能乱码，导致曲名显示为 `unknown_{id}`。

### 方案：song_database.py

提供三级查询：

```
1. 本地 music_info.xml 解析结果 (最可靠)
2. 内置静态数据库 (从公开 wiki 整理)
3. 在线查询 bemani.cc wiki (异步线程)
```

### 在线数据源

- **bemani.cc wiki**: 社区维护的 BEMANI 系列游戏曲目数据库
- **参考项目**: [zetaraku/arcade-songs-fetch](https://github.com/zetaraku/arcade-songs-fetch) — 从 Konami e-amusement 站点抓取曲目数据

当前实现在线爬虫使用简单正则匹配，可能需要根据实际页面结构调整。

---

## 9. 参考项目与致谢

| 项目 | 用途 | 参考价值 |
|---|---|---|
| [Stepland/jubeatools](https://github.com/Stepland/jubeatools) | EVE 解析 + Malody 导出 | **核心依赖** — 谱面解析、长按处理、格式导出 |
| [mon/ifstools](https://github.com/mon/ifstools) | IFS 解包 | **核心依赖** — 容器解包、纹理转 PNG |
| [chestnutcase/jubeatnet](https://github.com/chestnutcase/jubeatnet) | 谱面分析/可视化 | 数据结构设计、`title_name` 字段发现 |
| [zetaraku/arcade-songs-fetch](https://github.com/zetaraku/arcade-songs-fetch) | 在线曲目数据抓取 | wiki 爬虫思路参考 |
| [kangalio/malody-convert](https://github.com/kangalio/malody-convert) | Malody 格式转换 | .mc 格式解析参考 |
| [LuiCat/mc2tja](https://github.com/LuiCat/mc2tja) | Malody → TJA | beat 精度处理、BPM 变化处理参考 |
