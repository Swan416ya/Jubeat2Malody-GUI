"""
Jubeat 曲名数据库模块

提供 music_id → 曲名 的查询能力，支持:
1. 内置静态数据库 (从公开音游 wiki 整理)
2. 在线查询 (bemani.cc wiki)
3. 本地 music_info.xml 缓存
"""

import json
import re
import threading
from pathlib import Path
from typing import Optional, Dict

# 内置静态数据库: music_id → 曲名 / 曲师
# 数据来源: 公开音游 wiki (bemani.cc, RemyWiki)、bemaniutils jubeat.tsv
_BUILTIN_SONG_DB: Dict[int, str] = {}
_BUILTIN_ARTIST_DB: Dict[int, str] = {}
_REFERENCE_TSV_LOADED = False

_METADATA_TSV = Path(__file__).resolve().parents[2] / "data" / "jubeat_metadata.tsv"


def get_song_artist(music_id: int, local_db: dict = None) -> Optional[str]:
    """查询曲师名（参考库 / music_info 解析结果）"""
    if local_db and music_id in local_db:
        for key in ("artist", "artist_name"):
            artist = (local_db[music_id].get(key) or "").strip()
            if artist and artist.upper() not in ("KONAMI", "UNKNOWN", "COPYRIGHT"):
                return artist

    if music_id in _BUILTIN_ARTIST_DB:
        return _BUILTIN_ARTIST_DB[music_id]

    return None


def get_song_name(music_id: int, local_db: dict = None) -> Optional[str]:
    """查询歌曲名称

    查询优先级:
    1. local_db (music_info.xml 解析结果)
    2. 内置静态数据库
    3. 返回 None (可由调用方触发在线查询)

    Args:
        music_id: 歌曲ID
        local_db: 本地 music_info.xml 解析结果

    Returns:
        歌曲名称，未找到返回 None
    """
    # 1. 本地数据库
    if local_db and music_id in local_db:
        name = local_db[music_id].get("name", "")
        if name and not name.startswith("unknown_"):
            return name

    # 2. 内置数据库
    if music_id in _BUILTIN_SONG_DB:
        return _BUILTIN_SONG_DB[music_id]

    return None


def load_builtin_db(db_path: Path = None) -> int:
    """加载内置歌曲数据库

    Args:
        db_path: 数据库 JSON 文件路径，默认使用内置数据

    Returns:
        加载的歌曲数量
    """
    global _BUILTIN_SONG_DB

    if db_path and db_path.exists():
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _BUILTIN_SONG_DB = {int(k): v for k, v in data.items()}
                return len(_BUILTIN_SONG_DB)
        except Exception:
            pass

    load_reference_tsv()
    return len(_BUILTIN_SONG_DB)


def load_reference_tsv(tsv_path: Path = None) -> int:
    """加载 bemaniutils 参考曲名/曲师表 (music_id\\ttitle\\tartist)"""
    global _BUILTIN_SONG_DB, _BUILTIN_ARTIST_DB, _REFERENCE_TSV_LOADED

    path = tsv_path or _METADATA_TSV
    if tsv_path is None and _REFERENCE_TSV_LOADED:
        return 0
    if not path.exists():
        return 0

    loaded = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
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
                if title and mid not in _BUILTIN_SONG_DB:
                    _BUILTIN_SONG_DB[mid] = title
                    loaded += 1
                if artist and artist.upper() not in ("KONAMI", "COPYRIGHT") and mid not in _BUILTIN_ARTIST_DB:
                    _BUILTIN_ARTIST_DB[mid] = artist
        if tsv_path is None:
            _REFERENCE_TSV_LOADED = True
    except Exception:
        return 0

    return loaded


def save_builtin_db(db_path: Path) -> bool:
    """保存当前数据库到 JSON 文件"""
    try:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(_BUILTIN_SONG_DB, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def fetch_song_names_online(music_ids: list = None, on_result=None) -> None:
    """在线查询歌曲名称 (异步)

    从 bemani.cc wiki 抓取 jubeat 曲目列表，更新内置数据库。
    查询结果通过 on_result 回调返回。

    Args:
        music_ids: 需要查询的 music_id 列表，None 表示查询全部
        on_result: 回调函数，签名 on_result(found: dict, error: str)
    """
    def _fetch():
        found = {}
        error = ""
        try:
            import urllib.request
            import ssl

            # 尝试从 bemani.cc wiki 抓取
            # jubeat 曲目列表页
            url = "https://wiki.bemani.cc/index.php?title=Jubeat%E6%A6%82%E5%86%B5"
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            resp = urllib.request.urlopen(req, timeout=15, context=ctx)
            html = resp.read().decode('utf-8', errors='replace')

            # 从 HTML 中提取曲目信息
            # bemani.cc 的曲目列表通常在表格中
            # 这里用简单的正则匹配，实际可能需要根据页面结构调整
            _update_db_from_html(html, found)

        except Exception as e:
            error = str(e)

        if on_result:
            on_result(found, error)

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()


def _update_db_from_html(html: str, found: dict) -> None:
    """从 HTML 页面中提取曲目信息并更新数据库"""
    global _BUILTIN_SONG_DB

    # 尝试匹配常见的 wiki 表格格式
    # 格式1: | music_id || 曲名 || ...
    pattern1 = re.compile(r'\|\s*(\d{4,8})\s*\|\|.*?\[\[([^\]]+)\]\]', re.DOTALL)
    for m in pattern1.finditer(html):
        try:
            mid = int(m.group(1))
            name = m.group(2).strip()
            # 清理 wiki 链接
            name = re.sub(r'\|.*$', '', name).strip()
            if name and mid not in _BUILTIN_SONG_DB:
                _BUILTIN_SONG_DB[mid] = name
                found[mid] = name
        except (ValueError, IndexError):
            continue

    # 格式2: <td>music_id</td><td>曲名</td>
    pattern2 = re.compile(r'<td[^>]*>\s*(\d{4,8})\s*</td>\s*<td[^>]*>\s*([^<]+)', re.DOTALL)
    for m in pattern2.finditer(html):
        try:
            mid = int(m.group(1))
            name = m.group(2).strip()
            if name and mid not in _BUILTIN_SONG_DB:
                _BUILTIN_SONG_DB[mid] = name
                found[mid] = name
        except (ValueError, IndexError):
            continue


def update_db_from_music_info(music_info: dict) -> int:
    """从 music_info.xml 解析结果更新内置数据库

    Returns:
        新增的歌曲数量
    """
    global _BUILTIN_SONG_DB
    added = 0
    for mid, info in music_info.items():
        name = info.get("name", "")
        if name and not name.startswith("unknown_") and mid not in _BUILTIN_SONG_DB:
            _BUILTIN_SONG_DB[mid] = name
            added += 1
    return added
