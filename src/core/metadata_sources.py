"""
外部 / 辅助曲名曲师数据源。

- 本地 ID 表：data/jubeat_metadata.tsv
- 定数指纹表：data/level_fingerprint.tsv（来自 atwiki sonicy_memo）
- 在线刷新：atwiki pages/4.html（curl 回退）
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_CACHE_DIR = Path.home() / ".jubeat2malody"
_ATWIKI_CACHE = _CACHE_DIR / "atwiki_sonicy.html"
_ATWIKI_URL = "https://w.atwiki.jp/sonicy_memo/pages/4.html"
_BUNDLED_FINGERPRINT = Path(__file__).resolve().parents[2] / "data" / "level_fingerprint.tsv"

_LEVEL_ROW = re.compile(
    r"^\|(?:\s*(?:[OHP通+]+\s*\|))*\s*(?P<title>[^|]+?)\s*\|"
    r"\s*(?P<artist>[^|]+?)\s*\|"
    r"\s*(?P<bpm>[\d.]+(?:-[\d.]+)?)\s*\|"
    r"\s*Lv\s*(?P<bsc>[\d.]+)\s*\|"
    r"\s*Lv\s*(?P<adv>[\d.]+)\s*\|"
    r"\s*Lv\s*(?P<ext>[\d.]+)\s*\|?\s*$"
)

_atwiki_index: Dict[Tuple[float, float, float, float], List[Tuple[str, str]]] = {}
_atwiki_loaded = False


@dataclass
class LevelSignature:
    bpm: float
    bsc: float
    adv: float
    ext: float

    @classmethod
    def from_song_info(cls, info: dict) -> Optional["LevelSignature"]:
        bpm = float(info.get("bpm_max") or info.get("bpm") or 0)
        if bpm <= 0:
            return None
        levels = info.get("levels") or {}
        bsc = _level_detail(levels, "bsc")
        adv = _level_detail(levels, "adv")
        ext = _level_detail(levels, "ext")
        if bsc is None or adv is None or ext is None:
            return None
        return cls(bpm=bpm, bsc=bsc, adv=adv, ext=ext)

    def key(self) -> Tuple[float, float, float, float]:
        return (self.bpm, self.bsc, self.adv, self.ext)


def _level_detail(levels: dict, diff: str) -> Optional[float]:
    raw = levels.get(diff) or levels.get(diff.upper())
    if raw is None:
        return None
    if isinstance(raw, dict):
        detail = raw.get("detail")
        if detail is not None:
            return float(detail)
        level = raw.get("level")
        return float(level) if level is not None else None
    text = str(raw).strip()
    match = re.search(r"\(([\d.]+)\)", text)
    if match:
        return float(match.group(1))
    try:
        return float(text)
    except ValueError:
        return None


def _parse_bpm_value(text: str) -> float:
    text = text.strip()
    if "-" in text:
        text = text.split("-", 1)[0].strip()
    return float(text)


def _strip_html_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _parse_level_cell(text: str) -> Optional[float]:
    match = re.search(r"([\d.]+)", text)
    return float(match.group(1)) if match else None


def _index_put(
    index: Dict[Tuple[float, float, float, float], List[Tuple[str, str]]],
    key: Tuple[float, float, float, float],
    value: Tuple[str, str],
) -> None:
    bucket = index.setdefault(key, [])
    if value not in bucket:
        bucket.append(value)


def parse_atwiki_html_table(html_text: str) -> Dict[Tuple[float, float, float, float], List[Tuple[str, str]]]:
    """解析 atwiki HTML 表格为 (bpm,bsc,adv,ext) → [(title, artist)]。"""
    index: Dict[Tuple[float, float, float, float], List[Tuple[str, str]]] = {}
    skip_titles = {"Music", "BASIC", "ADVANCED", "EXTREME"}

    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 9:
            continue
        title = _strip_html_tags(cells[3])
        artist = _strip_html_tags(cells[4])
        if not title or title in skip_titles:
            continue
        if "jubeat" in title.lower() and "ave" in title.lower():
            continue
        try:
            key = (
                _parse_bpm_value(_strip_html_tags(cells[5])),
                _parse_level_cell(_strip_html_tags(cells[6])),
                _parse_level_cell(_strip_html_tags(cells[7])),
                _parse_level_cell(_strip_html_tags(cells[8])),
            )
        except (TypeError, ValueError):
            continue
        if any(part is None for part in key):
            continue
        if artist.startswith("(") and artist.endswith(")"):
            artist = artist[1:-1].strip()
        _index_put(index, key, (title, artist))
    return index


def parse_atwiki_sonicy_table(text: str) -> Dict[Tuple[float, float, float, float], List[Tuple[str, str]]]:
    """解析 atwiki 管道符表格文本。"""
    if "<tr" in text:
        return parse_atwiki_html_table(text)

    index: Dict[Tuple[float, float, float, float], List[Tuple[str, str]]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "Music | Artist | BPM" in line:
            continue
        match = _LEVEL_ROW.match(line)
        if not match:
            continue
        title = match.group("title").strip()
        artist = match.group("artist").strip()
        if not title or title in ("Music", "jubeat beyond the Ave.", "jubeat Ave."):
            continue
        if artist.startswith("(") and artist.endswith(")"):
            artist = artist[1:-1].strip()
        try:
            key = (
                _parse_bpm_value(match.group("bpm")),
                float(match.group("bsc")),
                float(match.group("adv")),
                float(match.group("ext")),
            )
        except ValueError:
            continue
        _index_put(index, key, (title, artist))
    return index


def load_level_fingerprint_tsv(path: Path) -> Dict[Tuple[float, float, float, float], List[Tuple[str, str]]]:
    index: Dict[Tuple[float, float, float, float], List[Tuple[str, str]]] = {}
    if not path.is_file():
        return index
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        try:
            key = tuple(float(parts[i]) for i in range(4))  # type: ignore[assignment]
        except ValueError:
            continue
        _index_put(index, key, (parts[4].strip(), parts[5].strip()))
    return index


def _fetch_url_curl(url: str) -> str:
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("curl not found")
    result = subprocess.run(
        [curl, "-sL", "-A", "Mozilla/5.0 (Jubeat2Malody)", url],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"curl failed ({result.returncode})")
    return result.stdout.decode("utf-8", errors="replace")


def _fetch_atwiki_html(force_refresh: bool = False) -> str:
    if not force_refresh and _ATWIKI_CACHE.is_file():
        return _ATWIKI_CACHE.read_text(encoding="utf-8", errors="replace")

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            _ATWIKI_URL,
            headers={"User-Agent": "Mozilla/5.0 (Jubeat2Malody metadata sync)"},
        )
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            html_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        html_text = _fetch_url_curl(_ATWIKI_URL)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _ATWIKI_CACHE.write_text(html_text, encoding="utf-8")
    return html_text


def load_atwiki_index(force_refresh: bool = False) -> int:
    """加载定数指纹索引，返回条目数。"""
    global _atwiki_index, _atwiki_loaded

    if _atwiki_loaded and not force_refresh:
        return len(_atwiki_index)

    _atwiki_index = load_level_fingerprint_tsv(_BUNDLED_FINGERPRINT)

    try:
        if force_refresh and _ATWIKI_CACHE.is_file():
            _ATWIKI_CACHE.unlink()
        html_text = _fetch_atwiki_html(force_refresh=force_refresh)
        online = parse_atwiki_html_table(html_text)
        if online:
            for key, values in online.items():
                for value in values:
                    _index_put(_atwiki_index, key, value)
    except Exception:
        if _ATWIKI_CACHE.is_file():
            try:
                cached = parse_atwiki_sonicy_table(
                    _ATWIKI_CACHE.read_text(encoding="utf-8", errors="replace")
                )
                for key, values in cached.items():
                    for value in values:
                        _index_put(_atwiki_index, key, value)
            except Exception:
                pass

    _atwiki_loaded = True
    return len(_atwiki_index)


def _reading_keywords(reading: str) -> List[str]:
    reading = (reading or "").strip()
    keywords: List[str] = []
    patterns = [
        ("チヨコ", "チョコ"), ("チョコ", "チョコ"), ("マホウ", "魔法"),
        ("ギザバ", "ギザバ"), ("カイブン", "怪文"), ("モウジョ", "少女"),
        ("ハレル", "Ha"), ("ヒトガタ", "ヒト"),
    ]
    for needle, token in patterns:
        if needle in reading and token not in keywords:
            keywords.append(token)
    return keywords


def _pick_best_fingerprint_match(
    candidates: List[Tuple[str, str]],
    info: dict,
) -> Optional[Tuple[str, str]]:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    reading = info.get("reading_name") or info.get("name") or ""
    keywords = _reading_keywords(reading)
    best = candidates[0]
    best_score = -1
    for title, artist in candidates:
        score = 0
        for kw in keywords:
            if kw in title:
                score += 10
        if reading and _normalize_title_for_match(reading) == _normalize_title_for_match(title):
            score += 100
        if score > best_score:
            best_score = score
            best = (title, artist)
    return best if best_score > 0 else candidates[0]


def _normalize_title_for_match(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def lookup_atwiki_by_levels(info: dict) -> Optional[Tuple[str, str]]:
    """用 BPM + 三难度定数匹配曲名/曲师（同指纹多曲时按读法消歧）。"""
    sig = LevelSignature.from_song_info(info)
    if not sig:
        return None
    load_atwiki_index()
    candidates = _atwiki_index.get(sig.key(), [])
    return _pick_best_fingerprint_match(candidates, info)


def load_user_metadata_tsv() -> Tuple[Dict[int, str], Dict[int, str]]:
    """读取用户可编辑补充表：music_id\\ttitle\\tartist"""
    titles: Dict[int, str] = {}
    artists: Dict[int, str] = {}
    paths = [
        Path(__file__).resolve().parents[2] / "data" / "user_metadata.tsv",
        _CACHE_DIR / "user_metadata.tsv",
    ]
    for path in paths:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                try:
                    mid = int(parts[0])
                except ValueError:
                    continue
                title = parts[1].strip()
                artist = parts[2].strip() if len(parts) > 2 else ""
                if title:
                    titles[mid] = title
                if artist:
                    artists[mid] = artist
        except OSError:
            continue
    return titles, artists

