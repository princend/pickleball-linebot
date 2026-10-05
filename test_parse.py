import os
import sys
from pickleball.grouping import parse_player_input

raw_text = """1.ouo
2.新
3.芸
4.翔
5.玫
6.玫老公
7.喬伊
8.蔡喬喬
--- 以下候補 ---
1.
2."""

players, court_limit, rounds, group_count, per_group, mode, waitlist = parse_player_input(raw_text)
print(f"players={players}")
print(f"court_limit={court_limit}")
print(f"rounds={rounds}")
print(f"mode={mode}")
