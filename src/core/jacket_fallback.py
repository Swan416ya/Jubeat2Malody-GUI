"""
曲绘回退：本地提取失败时从 Konami eagate / zetaraku 数据匹配并下载。

zetaraku 公开数据见 https://arcade-songs.zetaraku.dev/jubeat/
图片实际托管于 eagate.573.jp（与 arcade-songs-fetch 一致）。
"""

from __future__ import annotations

import html
import json
import re
import ssl
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

_CACHE_DIR = Path.home() / ".jubeat2malody"
_EAGATE_INDEX_CACHE = _CACHE_DIR / "eagate_jacket_index.json"
_ZETARAKU_DATA_URL = "https://dp4p6x0xfi5o9.cloudfront.net/jubeat/data.json"
_EAGATE_LIST_URL = "https://p.eagate.573.jp/game/jubeat/beyond/music/{list_id}.html"
_EAGATE_BASE = "https://p.eagate.573.jp/"

_eagate_index: Dict[str, Tuple[str, str]] = {}
_eagate_loaded = False


def _normalize_title(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s*\[\s*2\s*\]\s*$", "", text)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _reading_keywords(reading: str) -> List[str]:
    """从片假名读法提取用于消歧的关键词。"""
    reading = (reading or "").strip()
    keywords: List[str] = []
    patterns = [
        ("チヨコ", "チョコ"), ("チョコ", "チョコ"), ("マホウ", "魔法"),
        ("ギザバ", "ギザバ"), ("カイブン", "怪文"), ("モウジョ", "少女"),
    ]
    for needle, token in patterns:
        if needle in reading and token not in keywords:
            keywords.append(token)
    if len(reading) >= 4 and not keywords:
        keywords.append(reading[:4])
    return keywords


def _title_match_score(
    query_titles: List[str],
    query_reading: str,
    candidate_title: str,
) -> int:
    norm_candidate = _normalize_title(candidate_title)
    score = 0
    for query in query_titles:
        if not query:
            continue
        norm_query = _normalize_title(query)
        if norm_query and norm_query == norm_candidate:
            score += 100
        elif norm_query and norm_query in norm_candidate:
            score += 60
        elif norm_query and norm_candidate in norm_query:
            score += 40
    for kw in _reading_keywords(query_reading):
        if kw in candidate_title:
            score += 30
    return score


def _fetch_text(url: str, timeout: int = 30) -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Jubeat2Malody)"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_eagate_page(html_text: str) -> List[Tuple[str, str, str]]:
    """解析一页 eagate 曲库列表 → [(title, artist, image_url)]"""
    rows: List[Tuple[str, str, str]] = []
    for block in re.findall(
        r'<div class="list_data">\s*<p><img[^>]+src="([^"]+)"[^>]*></p>\s*<ul>(.*?)</ul>\s*</div>',
        html_text,
        re.S,
    ):
        img_src, ul_body = block
        lis = [html.unescape(x.strip()) for x in re.findall(r"<li>([^<]+)</li>", ul_body)]
        if not lis:
            continue
        title, artist = lis[0], lis[1] if len(lis) > 1 else ""
        image_url = urljoin(_EAGATE_BASE, img_src)
        rows.append((title, artist, image_url))
    return rows


def _load_eagate_index(force_refresh: bool = False) -> Dict[str, Tuple[str, str]]:
    """构建曲名 → (显示标题, 曲绘 URL) 索引（带缓存）。"""
    global _eagate_index, _eagate_loaded

    if _eagate_loaded and not force_refresh:
        return _eagate_index

    if not force_refresh and _EAGATE_INDEX_CACHE.is_file():
        try:
            payload = json.loads(_EAGATE_INDEX_CACHE.read_text(encoding="utf-8"))
            raw = payload.get("titles", {})
            _eagate_index = {
                k: (v["title"], v["url"]) if isinstance(v, dict) else (k, v)
                for k, v in raw.items()
            }
            _eagate_loaded = True
            if _eagate_index:
                return _eagate_index
        except Exception:
            pass

    index: Dict[str, Tuple[str, str]] = {}
    for list_id in ("index", "original"):
        page = 1
        while page <= 50:
            url = _EAGATE_LIST_URL.format(list_id=list_id)
            if page > 1:
                url += f"?page={page}"
            try:
                text = _fetch_text(url)
            except Exception:
                break
            rows = _parse_eagate_page(text)
            if not rows:
                break
            for title, _artist, image_url in rows:
                index[_normalize_title(title)] = (title, image_url)
            has_next = 'class="next"' in text and 'href="?page=' in text
            if not has_next:
                break
            page += 1
            time.sleep(0.35)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _EAGATE_INDEX_CACHE.write_text(
        json.dumps(
            {
                "titles": {k: {"title": v[0], "url": v[1]} for k, v in index.items()},
                "count": len(index),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _eagate_index = index
    _eagate_loaded = True
    return _eagate_index


def _find_eagate_image_url(
    titles: List[str],
    reading: str = "",
    artist: str = "",
) -> Optional[str]:
    index = _load_eagate_index()
    if not index:
        return None

    best_url = ""
    best_score = 0
    for norm_title, (display_title, url) in index.items():
        score = _title_match_score(titles, reading, display_title)
        if artist and artist in display_title:
            score += 5
        if score > best_score:
            best_score = score
            best_url = url

    for query in titles:
        norm = _normalize_title(query)
        if norm in index:
            return index[norm][1]

    return best_url if best_score >= 30 else None


def _download_image(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Jubeat2Malody)"})
        data = urllib.request.urlopen(req, timeout=30).read()
        if len(data) < 256:
            return False
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def _to_png_if_needed(path: Path) -> Path:
    """GIF 曲绘转为 PNG，Malody 更兼容。"""
    if path.suffix.lower() == ".png":
        return path
    try:
        from PIL import Image

        png_path = path.with_suffix(".png")
        with Image.open(path) as img:
            img.convert("RGBA").save(png_path, "PNG")
        if png_path.is_file():
            path.unlink(missing_ok=True)
            return png_path
    except Exception:
        pass
    return path


def fetch_jacket_fallback(
    song_dir: Path,
    info: dict,
    music_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    下载远程曲绘到歌曲目录。

    Returns:
        (成功与否, 文件名)
    """
    mid = music_id or info.get("music_id") or 0
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        mid = 0

    titles = [
        info.get("title_name") or "",
        info.get("name") or "",
        info.get("japanese_name") or "",
    ]
    reading = info.get("reading_name") or info.get("name") or ""
    artist = info.get("artist") or info.get("artist_name") or ""

    image_url = _find_eagate_image_url(titles, reading=reading, artist=artist)
    if not image_url:
        return False, ""

    suffix = Path(image_url).suffix.lower() or ".gif"
    filename = f"jkt_{mid}{suffix}" if mid else f"jkt_remote{suffix}"
    dest = song_dir / filename
    if not _download_image(image_url, dest):
        return False, ""

    final = _to_png_if_needed(dest)
    if mid and final.name != f"jkt_{mid}.png":
        target = song_dir / f"jkt_{mid}.png"
        if final != target:
            target.write_bytes(final.read_bytes())
            final.unlink(missing_ok=True)
        final = target
    return True, final.name


def ensure_song_jacket(song_dir: Path, info: dict) -> Tuple[bool, str]:
    """若目录无曲绘则尝试远程回退。"""
    from .malody_writer import _find_image

    _, existing = _find_image(song_dir, info)
    if existing and existing.is_file():
        return True, existing.name
    return fetch_jacket_fallback(song_dir, info)
