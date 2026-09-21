"""匹克球 (Pickleball) 核心模組。

提供匹克球相關業務邏輯，包括隨機分組、名單解析、賽制排定、快取記憶與 QuickReply 介面。
"""

from pickleball.grouping import (
    clean_player_name,
    format_group_result,
    parse_player_input,
    random_group,
)
from pickleball.constants import (
    DEFAULT_COURT_SIZE,
    DEFAULT_TEAM_SIZE,
    GROUPING_HELP_TEXT,
)
from pickleball.ai_extractor import extract_players_with_ai, standardize_announcement_with_ai
from pickleball.cache import (
    clear_awaiting_pickleball_input,
    clear_group_creation_session,
    clear_pickleball_session,
    get_group_creation_session,
    get_pickleball_session,
    is_awaiting_pickleball_input,
    remove_player_and_promote,
    save_pickleball_session,
    set_awaiting_pickleball_input,
    set_group_creation_session,
)
from pickleball.quick_reply import (
    get_pickleball_cancel_quick_reply,
    get_pickleball_quick_reply,
    get_remove_player_quick_reply,
)
from pickleball.highlights import (
    create_pickleball_highlight_flex,
    get_pickleball_highlight_video,
)
from pickleball.court_finder import (
    COUNTIES,
    create_courts_flex,
    get_county_quick_reply,
    scrape_courts_by_county,
)
from pickleball.flex_formatter import (
    create_pickleball_group_flex,
)
from pickleball.rules import (
    create_pickleball_rules_flex,
)
from pickleball.group_creation import (
    STEP_COURTS,
    STEP_DATE,
    STEP_LEVEL,
    STEP_LOCATION,
    STEP_PLAYERS,
    STEP_SEQUENCE,
    STEP_TIME,
    STEP_TITLE,
    convert_relative_date,
    format_time_input,
    generate_group_announcement,
    get_step_prompt_and_quick_reply,
)

__all__ = [
    "clean_player_name",
    "format_group_result",
    "parse_player_input",
    "random_group",
    "extract_players_with_ai",
    "standardize_announcement_with_ai",
    "remove_player_and_promote",
    "save_pickleball_session",
    "get_pickleball_session",
    "clear_pickleball_session",
    "set_awaiting_pickleball_input",
    "is_awaiting_pickleball_input",
    "clear_awaiting_pickleball_input",
    "set_group_creation_session",
    "get_group_creation_session",
    "clear_group_creation_session",
    "get_pickleball_quick_reply",
    "get_pickleball_cancel_quick_reply",
    "get_remove_player_quick_reply",
    "get_pickleball_highlight_video",
    "create_pickleball_highlight_flex",
    "COUNTIES",
    "scrape_courts_by_county",
    "get_county_quick_reply",
    "create_courts_flex",
    "create_pickleball_group_flex",
    "create_pickleball_rules_flex",
    "get_step_prompt_and_quick_reply",
    "generate_group_announcement",
    "convert_relative_date",
    "format_time_input",
    "STEP_TITLE",
    "STEP_DATE",
    "STEP_TIME",
    "STEP_LOCATION",
    "STEP_COURTS",
    "STEP_PLAYERS",
    "STEP_LEVEL",
    "STEP_SEQUENCE",
    "DEFAULT_COURT_SIZE",
    "DEFAULT_TEAM_SIZE",
    "GROUPING_HELP_TEXT",
]
