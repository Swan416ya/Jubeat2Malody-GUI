# AI 自动抄谱方案（视频 → Jubeat 谱面）

> 状态：**方案阶段，尚未实现**  
> 参考项目：[HachimiDX / HachimiDX-Convert](https://github.com/ck2739046/HachimiDX)（舞萌 DX 视频抄谱）  
> 关联文档：[PARSING_LOGIC.md](./PARSING_LOGIC.md)、[NOTES.md](./NOTES.md)

---

## 1. 目标与边界

### 1.1 要做什么

输入一段 **Jubeat 游玩/确认视频**（街机录屏、国服 PC 客户端、模拟器回放等），自动输出：

- 中间产物：`ChartInfo` / `jubeatools.song.Chart`（与现有预览页一致）
- 终态产物：`.mc` / `.mcz`（复用 `malody_writer.py`）

### 1.2 不做什么（至少 v1 不做）

| 能力 | 说明 |
|------|------|
| 替代现有解包管线 | 已有 IFS / 国服 Bundle 时，**解包仍优先**，抄谱是补充路径 |
| 全皮肤全版本一次搞定 | 街机世代皮肤差异大，需分阶段覆盖 |
| 100% 无人工 | 与 HachimiDX 一样，**抄谱 + 校对** 才是现实工作流 |
| 复杂演出特效 | 烟花、镜头晃动、UI 遮挡等先当噪声处理 |

### 1.3 与 HachimiDX 的差异（决定工作量）

| 维度 | 舞萌 (HachimiDX) | Jubeat (本项目) |
|------|------------------|-----------------|
| 布局 | 圆形轨道 + Slide/Touch 多类型 | **4×4 固定网格**，类型少 |
| 音符类型 | tap / hold / slide / touch / … | **tap + long**（长按带尾键方向） |
| 轨迹 | Slide 需 OBB 角度模型 | 无 slide，**检测更简单** |
| BPM | v1 仅固定 BPM | 官方谱面常有 **TEMPO 变速**，难度更高 |
| 训练标注 | Mod 内存 Dump + 自动 YOLO 标注 | **无公开 Mod**，需自建合成数据 |
| 输出格式 | simai (`maidata.txt`) | EVE / Malody `.mc`（已有转换器） |

**结论**：Jubeat 的 **视觉检测比舞萌简单**，但 **时序/BPM/长按尾键** 和 **训练数据获取** 是主要难点。

---

## 2. 参考：HachimiDX 架构摘要

```
视频 → 帧提取(OpenCV) → YOLO 检测/分类 → 多目标跟踪(BOTSORT/OCSORT)
     → 音符事件序列(位置/类型/出现帧) → 音频对齐 → 时值推理 → simai 文本
```

三层结构（值得照搬）：

1. **UI 层** — 任务配置、进度、结果预览、人工修正入口  
2. **Services 层** — 任务队列、子进程推理、参数校验  
3. **Core 层** — CV + 跟踪 + 时序推理 + 格式导出  

训练数据（其核心优势）：

- 游戏 Mod **直接 Dump 音符坐标与类型** → 脚本自动生成 YOLO 标注  
- **三个专用模型**：`detect`（位置）、`obb`（slide 角）、`classify`（ex/break 变体）  

已知限制（README 自述）：固定 BPM、实拍画质影响分类、部分重叠音符不支持。

---

## 3. 推荐技术栈

### 3.1 核心算法

| 模块 | 推荐技术 | 备选 | 说明 |
|------|----------|------|------|
| 视频 I/O | **OpenCV** + **ffmpeg** | PyAV | 抽帧、裁剪 UI 区域、转码；项目已有 ffmpeg 依赖 |
| 目标检测 | **Ultralytics YOLOv8/v11** | RT-DETR | 与 HachimiDX 同路线；16 格面板 + note 精灵检测 |
| 多目标跟踪 | **ByteTrack / BoT-SORT** | OC-SORT | 跨帧关联同一 note，推断 hold 持续时间 |
| 面板定位 | 传统 CV（透视变换）+ 轻量检测 | 纯端到端 | 先裁出 4×4 区域，降低检测难度 |
| 音频对齐 | **librosa** / **aubio** onset | 互相关 | 将帧时间轴映射到 beat；BPM 估计 |
| BPM/节拍 | **madmom** 或自研 beat tracker | — | 无 ground truth 时的 fallback |
| 推理后端 | PyTorch → **ONNX** → TensorRT/DirectML | — | 与 HachimiDX 一致，兼顾 NVIDIA / 核显 |
| 数据结构 | **jubeatools `song.Chart`** | 自研 | 与 `eve_parser` / `malody_writer` 统一 |
| 参数校验 | **pydantic v2** | dataclass | 任务配置、检测阈值 |

### 3.2 训练与标注

| 模块 | 推荐技术 | 说明 |
|------|----------|------|
| 标注格式 | **YOLO txt**（detect） | 类别：`tap_appear` / `hold_head` / `hold_tail` / `panel_cell` 等 |
| 合成数据 | **自研 Renderer** | 用已知 EVE/CN MIDI 渲染假 UI 画面（**主路线**） |
| 标注工具 | **CVAT** / **Label Studio** | 仅用于实拍视频微调、困难样本 |
| 实验跟踪 | **MLflow** 或简单 CSV | 模型版本、mAP、抄谱准确率 |
| 增强 | Albumentations | 亮度、模糊、压缩伪影、皮肤色偏 |

### 3.3 应用与集成（沿用本项目）

| 模块 | 技术 | 说明 |
|------|------|------|
| GUI | **PySide6 + QFluentWidgets** | 新增「AI 抄谱」页，风格与现有一致 |
| 预览 | 复用 `preview_page.ChartGridWidget` | 抄谱结果与 EVE 预览同一组件 |
| 导出 | `malody_writer.convert_song` | 抄谱结果落盘后走现有转换 |
| CLI | 扩展 `scripts/jubeat2malody.py` | `video-chart` 子命令 |
| 任务队列 | `QThread` / `QProcess` | 推理放子进程，避免 GUI 卡死 |

### 3.4 可选依赖隔离

CV/深度学习包（`torch`, `ultralytics`, `opencv-python`）体积大，建议：

```
requirements.txt          # 现有轻量依赖
requirements-ai.txt       # 可选 AI 抄谱依赖
```

GUI 检测不到 AI 依赖时，隐藏相关 Tab 并提示安装。

---

## 4. 端到端管线设计

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│ 输入视频     │ → │ 预处理        │ → │ 视觉推理     │ → │ 事件重建      │
│ mp4/mkv/... │    │ 裁 UI / 去畸变 │    │ 检测 + 跟踪  │    │ tap/long 序列 │
└─────────────┘    └──────────────┘    └─────────────┘    └──────┬───────┘
                                                                  │
┌─────────────┐    ┌──────────────┐    ┌─────────────┐           │
│ .mcz 导出    │ ← │ malody_writer│ ← │ 时序量化      │ ←─────────┘
│ (现有)       │    │ + song_info  │    │ beat + BPM   │
└─────────────┘    └──────────────┘    └──────────────┘
                         ↑
                   ┌──────────────┐
                   │ 人工校对 GUI  │  （可选但强烈建议）
                   └──────────────┘
```

### 4.1 预处理

1. **检测游玩区域**：国服 PC 布局固定，可模板匹配；街机需四角点 + 透视变换。  
2. **帧率归一**：统一 30/60 fps 时间戳。  
3. **跳过非游玩段**：标题 / RESULT / 空白段可用 UI 分类器或场景切换检测剔除。  
4. **（可选）从视频轨提取音频**，用于 beat 对齐。

### 4.2 视觉推理（Jubeat 特化）

**类别设计（v1 最小集）**

| class_id | 含义 |
|----------|------|
| `tap` | 单击 note 出现帧 |
| `hold_start` | 长按头 |
| `hold_body` | 长按体（可选，用于跟踪） |
| `hold_end` | 长按尾（**位置 index 关键**） |

面板格可不单独检测：note 中心点投影到 4×4 网格（与 `preview_page` 的 index 0–15 一致）。

**跟踪逻辑**

- 同一格短时间内重复的 `tap` → 去重（判定线扫过动画）  
- `hold_start` → 跟踪至 `hold_end` 或体消失 → 计算 `duration`（帧）  
- 尾键方向：取 `hold_end` 所在格 index 作为 `tail_tip`

### 4.3 时序与 BPM

分两级策略：

| 级别 | 条件 | 方法 |
|------|------|------|
| A（优先） | 视频含清晰 BPM 显示 / 固定 BPM 曲 | OCR BPM 或用户输入 → 帧→beat 线性映射 |
| B | 有 BGM（视频音轨或外挂） | onset + beat tracking → 对齐检测事件 |
| C（v2+） | 变速曲 | 分段 BPM 或从预览 UI 的 BPM 数字 OCR |

帧时间 → beat：

```
beat = (timestamp_sec - offset_sec) * bpm / 60
```

量化到 `MALODY_BEAT_SNAP = 4`（与 `malody_writer` 一致）。

### 4.4 输出对接（本项目）

新增 `src/core/video_chart/`（建议目录）：

```
video_chart/
  __init__.py
  pipeline.py          # 总编排
  preprocess.py        # 裁切、抽帧
  detector.py          # YOLO 封装
  tracker.py           # 跟踪 + 事件合并
  timing.py            # 帧→beat、BPM
  chart_builder.py     # → ChartInfo / song.Chart
```

`chart_builder` 输出对接：

```python
# 与 eve_parser.ChartInfo 相同结构，预览页零改动
ChartInfo(
    bpms=[(0.0, 120.0)],
    tap_notes=[(beat, panel_index), ...],
    long_notes=[(start_beat, pos, end_beat, tail_index), ...],
)
```

导出时写入临时目录：

```
ai_out/{曲名}/
  song_info.txt      # BPM、曲名（用户填或 OCR）
  chart_ai.json      # 原始检测日志（便于调试）
  bgm.wav            # 从视频提取
  → malody_writer.convert_song(...)
```

---

## 5. 是否需要打标？—— 需要，但主路线是「自动打标」

### 5.1 结论

| 方式 | 必要性 | 用途 |
|------|--------|------|
| **合成自动标注** | ✅ 必须（主数据集） | 用已有 EVE/CN 谱面渲染画面，自动生成 YOLO 框 |
| **游戏内 Dump** | ⭐ 理想但难 | Jubeat 无公开 Mod；国服 Unity 逆向成本高 |
| **人工标注实拍** | ⚠️ 少量即可 | 覆盖合成域差距（实拍模糊、反光） |
| **人工校对抄谱结果** | ✅ 必须（产品流程） | 类似 HachimiDX 内嵌编辑器，而非纯标注 |

**不建议**从零手工标上千段实拍视频——性价比远低于「合成 + 少量实拍微调」。

### 5.2 推荐数据集构建（三阶段）

#### 阶段 A：合成数据（80%+ 样本）

利用本项目**已有资产**：

- 街机：`debug_out` / 解包得到的 `*.eve`（500+ 首国服 + 街机曲库）
- 国服：`cn_midi` + `chart.mid`

流程：

1. 用 Malody 或自写 **离线 Renderer**，按已知谱面生成「假游玩画面」序列图  
2. 叠加不同皮肤贴图、note 皮肤、分辨率（720p/1080p）  
3. 每帧从 ground truth 直接写出 YOLO 标签（中心格 + 类型）  
4. 随机 UI 噪声（MISS、连击数、透明度）

**优点**：标签 100% 准、可无限扩量、可控制困难样本（满屏 note、同时长按）。  
**缺点**：与真实录屏有 domain gap，需阶段 B 补足。

#### 阶段 B：实拍微调（10–20%）

- 来源：B 站确认视频、自建国服 PC 录屏、街机拍摄  
- 工具：CVAT / Label Studio，只标 **困难帧**（遮挡、低亮度、hold 尾部）  
- 目标：提升实拍泛化，而非从头标全集

#### 阶段 C：抄谱结果校对（产品数据飞轮）

- GUI 中「删除误检 note / 补 tap / 拉 hold」→ 导出修正后的 `ChartInfo`  
- 可选：把修正前后 diff 回灌为 hard negative 样本  

### 5.3 模型拆分建议（参考 HachimiDX，按 Jubeat 简化）

| 模型 | 任务 | v1 是否必要 |
|------|------|-------------|
| `jubeat_detect` | note 出现 + 类型（tap/hold 头尾） | ✅ |
| `jubeat_panel` | 4×4 面板区域定位 | ✅（或传统 CV 即可） |
| `jubeat_classify` | ex/break 等变体 | ❌ v2（festo+ 才有丰富变体） |
| `jubeat_scene` | 游玩中 / 结算 / 标题 | ⚠️ 规则够用则不上模型 |

舞萌需要 3 个模型 partly 因为 slide 角度；Jubeat **v1 一个 detect 模型 + 网格投影** 可能够用。

---

## 6. 与现有项目的集成方案

### 6.1 模块关系

```
                    ┌─────────────────────────────────────┐
                    │           Jubeat2Malody GUI           │
                    │  街机曲库 │ 国服曲库 │ 预览 │ 转换    │
                    └───────────────┬─────────────────────┘
                                    │ 新增
                              ┌─────▼─────┐
                              │ AI 抄谱页  │
                              └─────┬─────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
  video_chart/*              eve_parser.ChartInfo        malody_writer
  (新模块)                    (复用)                      (复用)
```

### 6.2 GUI 功能草案

**AI 抄谱页** 子流程：

1. 选择视频文件  
2. 参数：来源类型（国服 PC / 街机 / 自动）、BPM（自动/手动）、难度名  
3. 运行 → 进度条（抽帧 / 推理 / 对齐 / 导出）  
4. 跳转 **预览页** 对照检查（已有 4×4 动画 + 音频）  
5. 一键 **转换 .mcz** 或保存中间 `chart_ai.json`

### 6.3 CLI 扩展

```powershell
# 方案态命令设计（尚未实现）
python scripts/jubeat2malody.py video-chart input.mp4 -o debug_out/ai_chart --bpm auto
python scripts/jubeat2malody.py video-chart input.mp4 --dry-run   # 只出 ChartInfo JSON
```

### 6.4 与解包管线的关系

| 场景 | 推荐路径 |
|------|----------|
| 有游戏文件 | 解包 → 转换（现有） |
| 只有确认视频 / 他人录屏 | AI 抄谱 → 校对 → 转换 |
| 有视频想交叉验证解包 | 两者并行，diff `ChartInfo`（可复用 `cn_midi_study` 思路） |

---

## 7. 分阶段实施路线图

### Phase 0 — 可行性验证（1–2 周）

- [ ] 收集 10 段国服 PC + 10 段街机录屏样本  
- [ ] 手工标注 100 帧，测试「网格投影 + 亮度阈值」能否检出 tap  
- [ ] 验证帧→beat 误差（固定 BPM 曲）是否 < 1/8 拍  
- **交付物**：Jupyter/脚本 demo + Go/No-Go 结论  

### Phase 1 — MVP（4–6 周）

- [ ] 合成数据 Renderer + 自动 YOLO 标注流水线  
- [ ] 训练 `jubeat_detect` v1  
- [ ] `video_chart` 核心：固定 BPM、仅 tap、国服 PC 布局  
- [ ] 输出 `ChartInfo` + 预览页联调  
- **交付物**：CLI `video-chart`，无 GUI  

### Phase 2 — 可实用（4–6 周）

- [ ] hold 头尾检测 + 跟踪  
- [ ] 音频 beat 对齐；BPM 自动估计  
- [ ] 实拍数据微调 + 人工校对最小 UI  
- [ ] 导出 `.mcz`（`BSC Lv?` 命名规则沿用）  
- **交付物**：GUI「AI 抄谱」Tab  

### Phase 3 — 增强（长期）

- [ ] 街机多皮肤适配  
- [ ] 变速 BPM（OCR 或分段）  
- [ ] 与解包谱面 auto-diff 质量评分  
- [ ] TensorRT 加速、批量抄谱  

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 合成与实拍域差距大 | 实拍准确率低 | 少量实拍微调 + 用户校对；优先国服 PC（UI 统一） |
| 长按尾键识别错 | 谱面不可用 | 跟踪 + 尾帧单独 class；校对 UI 重点修 long |
| BPM 变速 | 后半段漂移 | v1 声明仅支持固定 BPM；v2 OCR / 分段 |
| 依赖过重 | 用户不愿装 torch | `requirements-ai.txt` 可选；核心解包功能不受影响 |
| 法律/版权 | 传播录屏谱面 | 工具仅供个人学习；文档声明不鼓励商用传播 |

---

## 9. 验收指标（建议）

| 指标 | Phase 1 目标 | Phase 2 目标 |
|------|--------------|--------------|
| Tap 位置准确率 | ≥ 90%（合成测试集） | ≥ 85%（实拍） |
| Tap 时间误差 | ≤ 1/4 拍（固定 BPM） | ≤ 1/8 拍（对齐后） |
| Hold 识别率 | 不考核 | ≥ 75% |
| 人工校对耗时 | — | < 5 min / 首（2 分钟内歌曲） |

对比基准：与 ground truth EVE/CN MIDI 做 note 匹配（可扩展 `cn_midi_study.py`）。

---

## 10. 待决问题（实现前需确认）

1. **首要视频来源**：国服 PC only，还是必须街机实拍？  
2. **目标输出**：仅 Malody，还是也要写回 `.eve`？  
3. **是否投入 Renderer**：用 Malody 画面录屏，还是自绘简化 UI？  
4. **GPU 要求**：是否接受「无独显仅能 CPU 推理（慢）」？  
5. **是否做训练工具链**：仅推理预训练模型，还是完整开源训练脚本？

---

## 11. 参考链接

- [HachimiDX-Convert](https://github.com/ck2739046/HachimiDX-Convert) — 舞萌抄谱主参考（YOLO + 跟踪 + simai）  
- [HachimiDX 中文 README（训练数据说明）](https://github.com/ck2739046/HachimiDX/blob/main/readme_zh_cn.md)  
- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)  
- 本项目：`src/core/eve_parser.py`、`src/gui/pages/preview_page.py`、`src/core/malody_writer.py`、`src/core/cn_midi_study.py`（谱面对比）

---

*文档版本：2026-06-09 · 随实现进展更新*
