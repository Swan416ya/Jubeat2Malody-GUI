#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.song_debut import resolve_debut_folder

tests = [
    "Queen's Paradise [ 2 ]",
    "情熱大陸 [ 2 ]",
    "AIR RAID FROM THA UNDAGROUND [ 2 ]",
    "Queen's Paradise",
    "情熱大陸",
    "隅田川夏恋歌",
    "スペースカーニバル [ 2 ]",
]
for t in tests:
    print(f"{t} -> {resolve_debut_folder(t)}")
