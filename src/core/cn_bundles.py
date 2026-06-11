"""
国服 (Jubeat CN PC) Unity YooAsset 资源解包。

国服客户端不使用街机 IFS，曲库在 HotUpdate 目录下的 Unity AssetBundle 中：
- 音频: assets_bundles_sound_songs_{id}bgm_* / {id}idx_*
- 封面: assets_bundles_textures_songjackets_id{id}_*
- 谱面: assets_bundles_sound_charts_* (TextAsset，内容为标准 MIDI，含 bsc/adv/ext 轨道)
- 曲库: assets_bundles_config_* 内的 JBTSongListConfigCategory (Protobuf)
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

try:
    import UnityPy
except ImportError:  # pragma: no cover
    UnityPy = None  # type: ignore

ProgressReporter = Callable[[str, int], None]

DEFAULT_CN_HOTUPDATE = Path(
    r"E:\Program Files (x86)\Jubeat CN\jubeat-file\jubeat-file"
    r"\HotUpdate\JBT_Download\PC\100"
)

_BGM_RE = re.compile(r"assets_bundles_sound_songs_(\d+)bgm_")
_IDX_RE = re.compile(r"assets_bundles_sound_songs_(\d+)idx_")
_JACKET_RE = re.compile(r"assets_bundles_textures_songjackets_id(\d+)_")


def _require_unitypy() -> None:
    if UnityPy is None:
        raise ImportError("国服解包需要 UnityPy，请执行: pip install UnityPy")


def _to_bytes(data) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    if isinstance(data, list):
        return bytes(data)
    if isinstance(data, str):
        return data.encode("utf-8", errors="surrogateescape")
    return bytes(data)


def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
    return result, pos


def _format_jbt_level(raw: int) -> str:
    """JBTSongList field 11：等级 ×10 存储，如 50→5、91→9.1。"""
    if raw <= 0:
        return ""
    if raw % 10 == 0:
        return str(raw // 10)
    return f"{raw / 10:.1f}".rstrip("0").rstrip(".")


def parse_jbt_song_list(blob: bytes) -> Dict[int, dict]:
    """解析 JBTSongListConfigCategory Protobuf，返回 music_id -> 元数据。"""
    songs: Dict[int, dict] = {}
    pos = 0
    while pos < len(blob):
        if blob[pos] != 0x0A:
            pos += 1
            continue
        pos += 1
        length, pos = _read_varint(blob, pos)
        chunk = blob[pos : pos + length]
        pos += length

        cp = 0
        song_id: Optional[int] = None
        title = ""
        artist = ""
        bpm_val: Optional[int] = None
        level_raw: List[int] = []
        while cp < len(chunk):
            tag = chunk[cp]
            cp += 1
            field_id = tag >> 3
            wire = tag & 7
            if wire == 0:
                value, cp = _read_varint(chunk, cp)
                if field_id == 1:
                    song_id = value
                elif field_id == 9:
                    bpm_val = value
                elif field_id == 10:
                    if bpm_val is None and 40 <= value <= 300:
                        bpm_val = value
                elif field_id == 11:
                    level_raw.append(value)
            elif wire == 2:
                ln, cp = _read_varint(chunk, cp)
                text = chunk[cp : cp + ln].decode("utf-8", errors="replace")
                cp += ln
                if field_id == 2:
                    title = text
                elif field_id == 3:
                    artist = text
            else:
                break

        levels: Dict[str, str] = {}
        lv = [x for x in level_raw if x > 0]
        for diff, val in zip(("BSC", "ADV", "EXT"), lv[:3]):
            levels[diff.lower()] = _format_jbt_level(val)

        if song_id is not None:
            entry = {
                "music_id": song_id,
                "name": title or str(song_id),
                "title_name": title,
                "artist_name": artist,
                "levels": levels,
            }
            if bpm_val:
                entry["bpm_max"] = bpm_val
                entry["bpm_min"] = bpm_val
            songs[song_id] = entry
    return songs


def _iter_bundle_objects(bundle_path: Path):
    _require_unitypy()
    env = UnityPy.load(str(bundle_path))
    yield from env.objects


def _extract_mono_source(bundle_path: Path) -> Optional[bytes]:
    for obj in _iter_bundle_objects(bundle_path):
        if obj.type.name != "MonoBehaviour":
            continue
        source = obj.read_typetree().get("_source")
        if isinstance(source, list):
            return bytes(source)
    return None


def _extract_text_asset(bundle_path: Path, asset_name: str) -> Optional[bytes]:
    for obj in _iter_bundle_objects(bundle_path):
        if obj.type.name != "TextAsset":
            continue
        data = obj.read()
        if data.m_Name == asset_name:
            return _to_bytes(data.m_Script)
    return None


def _extract_jacket_png(bundle_path: Path, dest: Path) -> bool:
    for obj in _iter_bundle_objects(bundle_path):
        if obj.type.name != "Texture2D":
            continue
        texture = obj.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        texture.image.save(dest)
        return True
    return False


def _find_largest_song_list_blob(root: Path) -> Optional[bytes]:
    best: Optional[bytes] = None
    for bundle in root.glob("assets_bundles_config_*"):
        for obj in _iter_bundle_objects(bundle):
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            if data.m_Name != "JBTSongListConfigCategory":
                continue
            blob = _to_bytes(data.m_Script)
            if best is None or len(blob) > len(best):
                best = blob
    return best


@dataclass
class CnBundleIndex:
    """国服 HotUpdate 目录索引（按 music_id 查找 bundle 路径）。"""

    root: Path
    bgm: Dict[int, Path] = field(default_factory=dict)
    idx: Dict[int, Path] = field(default_factory=dict)
    jackets: Dict[int, Path] = field(default_factory=dict)
    chart_bundle_by_id: Dict[int, Path] = field(default_factory=dict)
    song_list: Dict[int, dict] = field(default_factory=dict)

    @classmethod
    def scan(
        cls,
        root: Path,
        *,
        build_chart_index: bool = True,
        load_song_list: bool = True,
        progress: Optional[ProgressReporter] = None,
    ) -> "CnBundleIndex":
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"国服资源目录不存在: {root}")

        index = cls(root=root)

        def report(msg: str, pct: int) -> None:
            if progress:
                progress(msg, pct)

        report("索引音频 bundle...", 5)
        for path in root.glob("assets_bundles_sound_songs_*"):
            name = path.name
            if m := _BGM_RE.search(name):
                index.bgm[int(m.group(1))] = path
            elif m := _IDX_RE.search(name):
                index.idx[int(m.group(1))] = path

        report("索引封面 bundle...", 20)
        for path in root.glob("assets_bundles_textures_songjackets_id*_*"):
            if m := _JACKET_RE.search(path.name):
                index.jackets[int(m.group(1))] = path

        if build_chart_index:
            report("索引谱面 bundle...", 40)
            chart_bundles = sorted(root.glob("assets_bundles_sound_charts_*"))
            for i, bundle in enumerate(chart_bundles):
                pct = 40 + int(40 * (i + 1) / max(len(chart_bundles), 1))
                report(f"扫描谱面 {i + 1}/{len(chart_bundles)}...", pct)
                for obj in _iter_bundle_objects(bundle):
                    if obj.type.name != "TextAsset":
                        continue
                    music_id = int(obj.read().m_Name)
                    index.chart_bundle_by_id[music_id] = bundle

        if load_song_list:
            report("读取曲库配置...", 90)
            blob = _find_largest_song_list_blob(root)
            if blob:
                index.song_list = parse_jbt_song_list(blob)

        report("索引完成", 100)
        return index

    @property
    def music_ids(self) -> List[int]:
        ids = set(self.bgm) | set(self.chart_bundle_by_id) | set(self.jackets)
        return sorted(ids)

    def get_song_info(self, music_id: int) -> dict:
        info = dict(self.song_list.get(music_id, {}))
        info.setdefault("music_id", music_id)
        info.setdefault("name", str(music_id))
        info.setdefault("title_name", info.get("name", ""))
        info.setdefault("artist_name", info.get("artist_name", ""))
        return info


def extract_cn_song(
    index: CnBundleIndex,
    music_id: int,
    output_base: Path,
    *,
    include_preview: bool = False,
    progress: Optional[ProgressReporter] = None,
) -> Optional[Path]:
    """
    解包国服单首歌曲，输出结构与街机解包尽量一致：
    - bgm.ogg（完整 BGM，Ogg Vorbis）
    - bsc.mid / adv.mid / ext.mid（从 MIDI 拆出的难度轨）
    - chart.mid（完整 MIDI 备份）
    - jkt_{id}.png
    - song_info.txt
    """
    def report(msg: str, pct: int) -> None:
        if progress:
            progress(msg, pct)

    song_info = index.get_song_info(music_id)
    safe_name = "".join(
        c if c.isalnum() or c in " _-()（）" else "_" for c in song_info.get("name", str(music_id))
    ) or str(music_id)
    song_dir = Path(output_base) / f"{music_id}_{safe_name}"
    song_dir.mkdir(parents=True, exist_ok=True)

    report("提取 BGM...", 15)
    bgm_path = index.bgm.get(music_id)
    if not bgm_path:
        return None
    bgm_bytes = _extract_mono_source(bgm_path)
    if not bgm_bytes or not bgm_bytes.startswith(b"OggS"):
        return None
    (song_dir / "bgm.ogg").write_bytes(bgm_bytes)

    if include_preview:
        idx_path = index.idx.get(music_id)
        if idx_path:
            idx_bytes = _extract_mono_source(idx_path)
            if idx_bytes and idx_bytes.startswith(b"OggS"):
                (song_dir / "preview.ogg").write_bytes(idx_bytes)

    report("提取谱面...", 45)
    chart_bundle = index.chart_bundle_by_id.get(music_id)
    if chart_bundle:
        midi_bytes = _extract_text_asset(chart_bundle, str(music_id))
        if midi_bytes and midi_bytes.startswith(b"MThd"):
            (song_dir / "chart.mid").write_bytes(midi_bytes)
            _split_midi_difficulties(midi_bytes, song_dir)

    report("提取封面...", 70)
    jacket_bundle = index.jackets.get(music_id)
    jacket_name = f"jkt_{music_id}.png"
    jacket_ok = False
    if jacket_bundle:
        jacket_ok = _extract_jacket_png(jacket_bundle, song_dir / jacket_name)

    report("写入歌曲信息...", 90)
    info_path = song_dir / "song_info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"Music ID: {music_id}\n")
        f.write(f"Name: {song_info.get('name', '')}\n")
        title = song_info.get("title_name", "")
        if title:
            f.write(f"Title: {title}\n")
        artist = song_info.get("artist_name", "")
        if artist:
            f.write(f"Artist: {artist}\n")
        bpm_val = song_info.get("bpm_max") or song_info.get("bpm_min")
        if bpm_val:
            f.write(f"BPM: {bpm_val}\n")
        for diff in ("BSC", "ADV", "EXT"):
            lv = song_info.get("levels", {}).get(diff.lower()) or song_info.get("levels", {}).get(diff)
            if lv:
                f.write(f"Level {diff}: {lv}\n")
        if jacket_ok:
            f.write(f"Jacket: {jacket_name}\n")
        f.write(f"CN HotUpdate: {index.root}\n")
        f.write("Source: Jubeat CN (Unity Bundle)\n")
        f.write("Chart Format: MIDI\n")

    report("完成", 100)
    return song_dir


def _split_midi_difficulties(midi_bytes: bytes, song_dir: Path) -> None:
    """将含 bsc/adv/ext 轨道的 MIDI 拆成独立 .mid 文件。"""
    try:
        import io

        import mido
    except ImportError:
        return

    src = mido.MidiFile(file=io.BytesIO(midi_bytes))
    for track in src.tracks:
        track_name = ""
        for msg in track:
            if msg.type == "track_name":
                track_name = msg.name.strip("\x00").lower()
                break
        if track_name not in ("bsc", "adv", "ext"):
            continue

        out = mido.MidiFile(ticks_per_beat=src.ticks_per_beat)
        out_track = mido.MidiTrack()
        out_track.append(mido.MetaMessage("track_name", name=track_name, time=0))
        for msg in track:
            if msg.type != "track_name":
                out_track.append(msg.copy())
        out.tracks.append(out_track)
        out.save(str(song_dir / f"{track_name}.mid"))


def find_jacket_bundle(root: Path, music_id: int) -> Optional[Path]:
    """在 HotUpdate 目录中定位单曲曲绘 bundle。"""
    root = Path(root)
    if not root.is_dir():
        return None
    matches = sorted(root.glob(f"assets_bundles_textures_songjackets_id{music_id}_*"))
    return matches[0] if matches else None


def _local_jacket_path(song_dir: Path, info: Optional[dict] = None) -> Optional[Path]:
    if info and info.get("jacket"):
        candidate = song_dir / info["jacket"]
        if candidate.is_file():
            return candidate
    for pattern in (f"jkt_{info.get('music_id')}.png" if info and info.get("music_id") else "", "jkt*.png"):
        if not pattern:
            continue
        matches = sorted(song_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def _resolve_cn_hotupdate(info: dict) -> Optional[Path]:
    for key in ("cn_hotupdate", "cn_data_dir"):
        raw = (info.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if is_cn_hotupdate_dir(path):
            return path
        found = find_cn_hotupdate_dir(path)
        if found:
            return found
    if DEFAULT_CN_HOTUPDATE.is_dir() and is_cn_hotupdate_dir(DEFAULT_CN_HOTUPDATE):
        return DEFAULT_CN_HOTUPDATE
    return None


def _upsert_song_info_line(song_dir: Path, key: str, value: str) -> None:
    info_path = song_dir / "song_info.txt"
    if not info_path.is_file():
        return
    prefix = f"{key}:"
    lines = info_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = f"{key}: {value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}: {value}")
    info_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_cn_jacket(song_dir: Path, info: dict) -> Tuple[bool, str]:
    """国服曲目：本地无曲绘时从 HotUpdate bundle 补提取。"""
    existing = _local_jacket_path(song_dir, info)
    if existing and existing.is_file():
        return True, existing.name

    try:
        music_id = int(info.get("music_id") or 0)
    except (TypeError, ValueError):
        return False, ""

    if music_id <= 0:
        return False, ""

    hotupdate = _resolve_cn_hotupdate(info)
    if not hotupdate:
        return False, ""

    bundle = find_jacket_bundle(hotupdate, music_id)
    if not bundle:
        return False, ""

    dest = song_dir / f"jkt_{music_id}.png"
    if not _extract_jacket_png(bundle, dest):
        return False, ""

    _upsert_song_info_line(song_dir, "Jacket", dest.name)
    _upsert_song_info_line(song_dir, "CN HotUpdate", str(hotupdate))
    return True, dest.name


def is_cn_hotupdate_dir(path: Path) -> bool:
    """判断目录是否为国服 HotUpdate 曲库根目录。"""
    path = Path(path)
    if not path.is_dir():
        return False
    return any(path.glob("assets_bundles_sound_songs_*bgm_*"))


def find_cn_hotupdate_dir(base: Path) -> Optional[Path]:
    """在国服安装目录下自动定位 HotUpdate 曲库路径。"""
    base = Path(base)
    candidates = [
        base / "HotUpdate" / "JBT_Download" / "PC" / "100",
        base / "jubeat-file" / "jubeat-file" / "HotUpdate" / "JBT_Download" / "PC" / "100",
    ]
    for candidate in candidates:
        if is_cn_hotupdate_dir(candidate):
            return candidate
    for candidate in base.rglob("JBT_Download/PC/100"):
        if is_cn_hotupdate_dir(candidate):
            return candidate
    return None
