"""匹克球 (Pickleball) 分組結果 Flex Message 與 Carousel 視覺排版模組。

提供將單輪雙打分組與多輪排程結果，轉化為高質感 LINE Flex 卡片與輪播訊息。
採用對比色塊對戰風格：隊伍 A (清新藍)、隊伍 B (暖橘色)、深色 VS 徽章、底部休息名單與多輪輪播。
嚴格遵守無表情符號規範 (No Emoji Policy)。
"""

from typing import Any, Dict, List, Optional
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexCarousel,
    FlexMessage,
    FlexSeparator,
    FlexText,
    QuickReply,
)


def _build_court_match_box(court: Dict[str, Any], show_court_title: bool = True) -> FlexBox:
    """建構單一場地的對戰牌卡 (隊伍 A vs 隊伍 B)。"""
    c_idx = court.get("court_index", 1)
    team_a = ", ".join(court.get("team_a", []))
    team_b = ", ".join(court.get("team_b", []))

    court_contents: List[Any] = []

    # 場地標籤
    if show_court_title:
        court_contents.append(
            FlexText(
                text=f"第 {c_idx} 場地",
                weight="bold",
                size="xs",
                color="#4B5563",
                margin="sm",
            )
        )

    # 對抗組合色塊盒子
    matchup_box = FlexBox(
        layout="vertical",
        spacing="xs",
        contents=[
            # 隊伍 A (清新藍色塊)
            FlexBox(
                layout="horizontal",
                background_color="#EFF6FF",
                corner_radius="md",
                padding_all="sm",
                contents=[
                    FlexText(
                        text="隊伍 A",
                        weight="bold",
                        size="xs",
                        color="#2563EB",
                        flex=2,
                    ),
                    FlexText(
                        text=team_a,
                        weight="bold",
                        size="sm",
                        color="#1E3A8A",
                        wrap=True,
                        flex=5,
                    ),
                ],
            ),
            # 中央 VS 徽章
            FlexBox(
                layout="horizontal",
                justify_content="center",
                contents=[
                    FlexBox(
                        layout="vertical",
                        background_color="#1F2937",
                        corner_radius="xs",
                        padding_start="sm",
                        padding_end="sm",
                        padding_top="none",
                        padding_bottom="none",
                        contents=[
                            FlexText(
                                text="VS",
                                weight="bold",
                                size="xxs",
                                color="#FFFFFF",
                                align="center",
                            )
                        ],
                    )
                ],
            ),
            # 隊伍 B (暖橘色塊)
            FlexBox(
                layout="horizontal",
                background_color="#FFF7ED",
                corner_radius="md",
                padding_all="sm",
                contents=[
                    FlexText(
                        text="隊伍 B",
                        weight="bold",
                        size="xs",
                        color="#EA580C",
                        flex=2,
                    ),
                    FlexText(
                        text=team_b,
                        weight="bold",
                        size="sm",
                        color="#7C2D12",
                        wrap=True,
                        flex=5,
                    ),
                ],
            ),
        ],
    )
    court_contents.append(matchup_box)

    return FlexBox(
        layout="vertical",
        spacing="xs",
        margin="md",
        contents=court_contents,
    )


def _build_resting_box(resting_players: List[str], label: str = "本輪休息") -> Optional[FlexBox]:
    """建構休息或輪空人員的灰色區塊。"""
    if not resting_players:
        return None

    return FlexBox(
        layout="vertical",
        background_color="#F3F4F6",
        corner_radius="md",
        padding_all="sm",
        margin="md",
        spacing="xs",
        contents=[
            FlexText(
                text=f"{label} ({len(resting_players)} 人)",
                weight="bold",
                size="xs",
                color="#6B7280",
            ),
            FlexText(
                text=", ".join(resting_players),
                size="xs",
                color="#374151",
                wrap=True,
            ),
        ],
    )


def _build_round_bubble(
    round_item: Dict[str, Any],
    total_players: int,
    court_count: int,
    total_rounds: int,
) -> FlexBubble:
    """建構多輪賽程中單一輪次的卡片 (Bubble)。"""
    r_idx = round_item.get("round_index", 1)
    courts = round_item.get("courts", [])
    resting = round_item.get("resting", [])

    body_contents: List[Any] = []

    # 垂直堆疊所有場地對戰牌卡
    show_court_title = len(courts) > 1 or court_count > 1
    for c in courts:
        body_contents.append(_build_court_match_box(c, show_court_title=show_court_title))

    # 本輪休息人員
    resting_box = _build_resting_box(resting, label="本輪休息")
    if resting_box:
        body_contents.append(resting_box)

    return FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#CCFF00",
            padding_all="md",
            contents=[
                FlexText(
                    text=f"第 {r_idx} 輪賽程 (Round {r_idx})",
                    weight="bold",
                    size="lg",
                    color="#1F2937",
                ),
                FlexText(
                    text=f"正選 {total_players} 人 | {court_count} 面場地 | 共 {total_rounds} 輪",
                    size="xs",
                    color="#4B5563",
                    margin="xs",
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=body_contents,
        ),
    )


def _build_statistics_bubble(
    play_counts: Dict[str, int],
    waitlist: List[str],
    total_players: int,
    court_count: int,
    total_rounds: int,
) -> FlexBubble:
    """建構多輪賽程最後一張統計與候補總結卡片 (Bubble)。"""
    body_contents: List[Any] = []

    # 出賽次數分析
    unique_counts = set(play_counts.values()) if play_counts else set()
    is_fair = len(unique_counts) == 1 and len(play_counts) > 0

    if is_fair:
        common_count = list(unique_counts)[0]
        body_contents.append(
            FlexBox(
                layout="vertical",
                background_color="#F0FDF4",
                corner_radius="md",
                padding_all="sm",
                contents=[
                    FlexText(
                        text="出賽統計: 完全公平輪替",
                        weight="bold",
                        size="sm",
                        color="#16A34A",
                    ),
                    FlexText(
                        text=f"全員 {total_players} 人每人出賽 {common_count} 次，輪空休息完全均等。",
                        size="xs",
                        color="#15803D",
                        wrap=True,
                        margin="xs",
                    ),
                ],
            )
        )
    else:
        # 非完全均等時，列出出賽明細
        stats_list = [f"{p}: {cnt}次" for p, cnt in play_counts.items()]
        body_contents.append(
            FlexBox(
                layout="vertical",
                background_color="#F8FAFC",
                corner_radius="md",
                padding_all="sm",
                spacing="xs",
                contents=[
                    FlexText(
                        text="出賽次數統計",
                        weight="bold",
                        size="xs",
                        color="#475569",
                    ),
                    FlexText(
                        text=", ".join(stats_list),
                        size="xs",
                        color="#334155",
                        wrap=True,
                    ),
                ],
            )
        )

    # 活動候補名單
    if waitlist:
        body_contents.append(
            FlexBox(
                layout="vertical",
                background_color="#FFFBEB",
                corner_radius="md",
                padding_all="sm",
                margin="md",
                spacing="xs",
                contents=[
                    FlexText(
                        text=f"活動候補名單 ({len(waitlist)} 人)",
                        weight="bold",
                        size="xs",
                        color="#D97706",
                    ),
                    FlexText(
                        text=", ".join(waitlist),
                        size="xs",
                        color="#B45309",
                        wrap=True,
                    ),
                ],
            )
        )

    return FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#1F2937",
            padding_all="md",
            contents=[
                FlexText(
                    text="出賽統計與候補名單",
                    weight="bold",
                    size="lg",
                    color="#FFFFFF",
                ),
                FlexText(
                    text="多輪公平輪替總結",
                    size="xs",
                    color="#9CA3AF",
                    margin="xs",
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=body_contents,
        ),
    )


def _build_single_round_bubble(group_result: Dict[str, Any]) -> FlexBubble:
    """建構單輪雙打分組結果的單張卡片 (Bubble)。"""
    total = group_result.get("total", 0)
    courts = group_result.get("courts", [])
    waiting = group_result.get("waiting", [])
    waitlist = group_result.get("waitlist", [])
    court_count = len(courts)

    body_contents: List[Any] = []

    # 各場地對戰牌卡
    show_court_title = court_count > 1
    for c in courts:
        body_contents.append(_build_court_match_box(c, show_court_title=show_court_title))

    # 本輪輪空名單
    if waiting:
        waiting_box = _build_resting_box(waiting, label="輪空 / 候補")
        if waiting_box:
            body_contents.append(waiting_box)

    # 活動候補名單
    if waitlist:
        body_contents.append(
            FlexBox(
                layout="vertical",
                background_color="#FFFBEB",
                corner_radius="md",
                padding_all="sm",
                margin="md",
                spacing="xs",
                contents=[
                    FlexText(
                        text=f"活動候補名單 ({len(waitlist)} 人)",
                        weight="bold",
                        size="xs",
                        color="#D97706",
                    ),
                    FlexText(
                        text=", ".join(waitlist),
                        size="xs",
                        color="#B45309",
                        wrap=True,
                    ),
                ],
            )
        )

    return FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#CCFF00",
            padding_all="md",
            contents=[
                FlexText(
                    text="匹克球隨機分組結果",
                    weight="bold",
                    size="lg",
                    color="#1F2937",
                ),
                FlexText(
                    text=f"正選總人數: {total} 人 | 使用場地數: {court_count} 面",
                    size="xs",
                    color="#4B5563",
                    margin="xs",
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="sm",
            contents=body_contents,
        ),
    )


def create_pickleball_group_flex(
    group_result: Dict[str, Any],
    quick_reply: Optional[QuickReply] = None,
) -> FlexMessage:
    """將匹克球分組運算結果封裝為高質感的 Flex Message (單輪為單張 Bubble，多輪為 Carousel 輪播)。"""
    mode = group_result.get("mode", "doubles")

    if mode == "multi_round":
        schedule = group_result.get("schedule", [])
        total_players = group_result.get("total", 0)
        court_count = group_result.get("court_count", 1)
        total_rounds = group_result.get("rounds", len(schedule))
        play_counts = group_result.get("play_counts", {})
        waitlist = group_result.get("waitlist", [])

        bubbles: List[FlexBubble] = []

        # 1. 每一輪的專屬卡片 (Round 1, Round 2...)
        for r_item in schedule:
            bubbles.append(
                _build_round_bubble(
                    round_item=r_item,
                    total_players=total_players,
                    court_count=court_count,
                    total_rounds=total_rounds,
                )
            )

        # 2. 最後一張出賽統計卡片
        bubbles.append(
            _build_statistics_bubble(
                play_counts=play_counts,
                waitlist=waitlist,
                total_players=total_players,
                court_count=court_count,
                total_rounds=total_rounds,
            )
        )

        carousel = FlexCarousel(contents=bubbles)
        alt_text = f"匹克球多輪賽程對戰表 ({total_rounds} 輪 | {court_count} 面場)"
        return FlexMessage(
            alt_text=alt_text,
            contents=carousel,
            quick_reply=quick_reply,
        )

    # 單輪雙打分組
    bubble = _build_single_round_bubble(group_result)
    total = group_result.get("total", 0)
    alt_text = f"匹克球隨機分組結果 (共 {total} 人)"
    return FlexMessage(
        alt_text=alt_text,
        contents=bubble,
        quick_reply=quick_reply,
    )

from linebot.v3.messaging import FlexButton, MessageAction

def create_menu_flex(quick_reply: Optional[QuickReply] = None) -> FlexMessage:
    """建立匹克球功能選單面板。"""
    bubble = FlexBubble(
        size="mega",
        header=FlexBox(
            layout="vertical",
            background_color="#CCFF00",
            padding_all="lg",
            contents=[
                FlexText(
                    text="匹克球專區",
                    weight="bold",
                    size="xl",
                    color="#1E3A8A",
                    align="center",
                ),
            ],
        ),
        body=FlexBox(
            layout="vertical",
            padding_all="md",
            spacing="md",
            contents=[
                # Row 1
                FlexBox(
                    layout="horizontal",
                    spacing="md",
                    contents=[
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=MessageAction(label="開團文生產", text="!開團"),
                        ),
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=MessageAction(label="分組", text="!分組"),
                        ),
                    ]
                ),
                # Row 2
                FlexBox(
                    layout="horizontal",
                    spacing="md",
                    contents=[
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=MessageAction(label="賽事精華", text="!匹克球精華"),
                        ),
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=MessageAction(label="匹克球規則", text="!匹克球規則"),
                        ),
                    ]
                ),
                # Row 3
                FlexBox(
                    layout="horizontal",
                    spacing="md",
                    contents=[
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=MessageAction(label="查球場", text="!查球場"),
                        ),
                        FlexButton(
                            style="secondary",
                            height="sm",
                            action=MessageAction(label="分組說明", text="!分組說明"),
                        ),
                    ]
                ),
            ],
        ),
    )
    return FlexMessage(
        alt_text="匹克球專區功能選單",
        contents=bubble,
        quick_reply=quick_reply,
    )
