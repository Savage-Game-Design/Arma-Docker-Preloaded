"""Generates an Arma 3 server.cfg from ARMA_CFG_* environment variables.

Values are resolved in this order:
  1. Environment variable ARMA_CFG_<NAME>
  2. Environment variable ARMA_CFG_<NAME>_FILE (path to a file holding the value)
  3. The defaults file (KEY=VALUE lines using the same ARMA_CFG_<NAME> keys)
  4. Omitted from the generated cfg entirely

The literal value "null" omits a key even when the defaults file sets it.
An empty value emits an empty string ("") or an empty array ({}).

Lists use "|" between items. Nested lists use "|" between rows and "," between
fields. Any list also accepts a JSON array when the value starts with "[".

Flags accept only 0 or 1. Bools accept only true or false (case-insensitive).

Missions are indexed from 1 and must be contiguous:
  ARMA_CFG_MISSION_1_TEMPLATE    (required, creates the mission)
  ARMA_CFG_MISSION_1_DIFFICULTY  (required)
  ARMA_CFG_MISSION_1_NAME        (optional class name, default mission_1)
  ARMA_CFG_MISSION_1_PARAMS      (optional, key=value|key=value, values emitted as written)

ARMA_CFG_EXTRA is appended verbatim at the end of the file.

ARMA_DIFFICULTY_* variables follow the same rules and render the CustomDifficulty class of
the server's <name>.Arma3Profile. The profile is only written when at least one is set.

Unknown ARMA_CFG_* or ARMA_DIFFICULTY_* variables are a fatal error.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ENV_PREFIX = "ARMA_CFG_"
DIFFICULTY_PREFIX = "ARMA_DIFFICULTY_"
PREFIXES = (ENV_PREFIX, DIFFICULTY_PREFIX)
FILE_SUFFIX = "_FILE"
NULL_VALUE = "null"
LIST_SEPARATOR = "|"
FIELD_SEPARATOR = ","
DEFAULT_DEFAULTS_FILE = Path(__file__).parent / "defaults.env"


class ConfigError(Exception):
    def __init__(self, variable: str, message: str):
        self.variable = variable
        super().__init__(f"{variable}: {message}")


# --------------------------------------------------------------------------- #
# Value parsing and rendering
# --------------------------------------------------------------------------- #

def quote(value: str) -> str:
    """Quotes a string for an Arma config. Embedded quotes are doubled."""
    return '"' + value.replace('"', '""') + '"'


def parse_number(variable: str, raw: str) -> str:
    """Accepts integers and decimals. Arma stores many numeric settings as floats, and the
    wiki does not state engine types, so no distinction is enforced."""
    raw = raw.strip()
    if not re.fullmatch(r"-?(\d+(\.\d*)?|\.\d+)", raw):
        raise ConfigError(variable, f"expected a number, got '{raw}'")
    return raw


def parse_flag(variable: str, raw: str) -> str:
    raw = raw.strip()
    if raw not in ("0", "1"):
        raise ConfigError(variable, f"expected 0 or 1, got '{raw}'")
    return raw


def parse_bool(variable: str, raw: str) -> str:
    lowered = raw.strip().lower()
    if lowered not in ("true", "false"):
        raise ConfigError(variable, f"expected true or false, got '{raw}'")
    return lowered


def parse_string(variable: str, raw: str) -> str:
    return quote(raw)


def split_list(variable: str, raw: str) -> list:
    """Splits a list value. Returns a list of strings, or of lists for JSON nested arrays."""
    if raw == "":
        return []
    if raw.lstrip().startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError(variable, f"invalid JSON array: {e}") from e
        if not isinstance(parsed, list):
            raise ConfigError(variable, "JSON value must be an array")
        return [_json_item_to_fields(variable, item) for item in parsed]
    return [item.strip() for item in raw.split(LIST_SEPARATOR)]


def _json_item_to_fields(variable: str, item):
    if isinstance(item, list):
        return [_json_scalar(variable, x) for x in item]
    return _json_scalar(variable, item)


def _json_scalar(variable: str, value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    raise ConfigError(variable, f"unsupported JSON value: {value!r}")


def render_array(items: list) -> str:
    if not items:
        return "{}"
    return "{ " + ", ".join(items) + " }"


def make_string_list_parser() -> Callable[[str, str], str]:
    def parse(variable: str, raw: str) -> str:
        items = split_list(variable, raw)
        rendered = []
        for item in items:
            if isinstance(item, list):
                raise ConfigError(variable, "expected a flat list of strings")
            rendered.append(quote(item))
        return render_array(rendered)
    return parse


def make_number_list_parser(length: Optional[int] = None) -> Callable[[str, str], str]:
    def parse(variable: str, raw: str) -> str:
        items = split_list(variable, raw)
        if length is not None and len(items) != length:
            raise ConfigError(variable, f"expected exactly {length} numbers, got {len(items)}")
        rendered = []
        for item in items:
            if isinstance(item, list):
                raise ConfigError(variable, "expected a flat list of numbers")
            rendered.append(parse_number(variable, item))
        return render_array(rendered)
    return parse


@dataclass
class Column:
    parser: Callable[[str, str], str]
    name: str


def make_rows_parser(columns: list, min_fields: int) -> Callable[[str, str], str]:
    """Parses rows of fields. Each row must have between min_fields and len(columns) fields."""
    def parse(variable: str, raw: str) -> str:
        rows = split_list(variable, raw)
        rendered_rows = []
        for row_index, row in enumerate(rows, start=1):
            if isinstance(row, list):
                fields = row
            else:
                fields = [f.strip() for f in row.split(FIELD_SEPARATOR)]
            if len(fields) < min_fields or len(fields) > len(columns):
                allowed = str(min_fields) if min_fields == len(columns) else f"{min_fields} to {len(columns)}"
                raise ConfigError(variable, f"row {row_index}: expected {allowed} fields, got {len(fields)}")
            rendered_fields = []
            for column, value in zip(columns, fields):
                rendered_fields.append(column.parser(f"{variable} (row {row_index}, {column.name})", value))
            rendered_rows.append(render_array(rendered_fields))
        return render_array(rendered_rows)
    return parse


# --------------------------------------------------------------------------- #
# Setting definitions
# --------------------------------------------------------------------------- #

class Kind:
    STRING = "string"
    NUMBER = "number"
    FLAG = "flag"
    BOOL = "bool"
    STRING_LIST = "string list"
    NUMBER_LIST = "number list"
    TIMEOUT = "timeout"
    ROWS = "rows"
    RAW = "raw"


class Target:
    SERVER_CFG = "server.cfg"
    PROFILE = "profile"


@dataclass
class Setting:
    name: str                 # <prefix><name>
    key: str                  # cfg key as written by Arma
    kind: str
    parser: Callable[[str, str], str]
    engine_default: str       # documented engine default, for the template only
    is_array: bool = False    # emit as key[] = ...
    cls: Optional[str] = None # containing class, e.g. AdvancedOptions
    section: str = ""
    target: str = Target.SERVER_CFG

    @property
    def prefix(self) -> str:
        return DIFFICULTY_PREFIX if self.target == Target.PROFILE else ENV_PREFIX

    @property
    def variable(self) -> str:
        return self.prefix + self.name


def parse_timeout(variable: str, raw: str):
    """One number emits a scalar, two emit a { ready, notReady } array."""
    items = split_list(variable, raw)
    if len(items) == 1:
        return ("scalar", parse_number(variable, items[0]))
    if len(items) == 2:
        return ("array", render_array([parse_number(variable, i) for i in items]))
    raise ConfigError(variable, f"expected one or two numbers, got {len(items)}")


STRING_LIST = make_string_list_parser()
NUMBER_COLUMN = Column(parse_number, "number")
BOOL_COLUMN = Column(parse_bool, "bool")
STRING_COLUMN = Column(parse_string, "string")


def S(name, key, kind, engine_default, parser=None, **kwargs) -> Setting:
    default_parsers = {
        Kind.STRING: parse_string,
        Kind.NUMBER: parse_number,
        Kind.FLAG: parse_flag,
        Kind.BOOL: parse_bool,
        Kind.STRING_LIST: STRING_LIST,
        Kind.TIMEOUT: parse_timeout,
    }
    parser = parser or default_parsers[kind]
    if kind in (Kind.STRING_LIST, Kind.NUMBER_LIST, Kind.ROWS):
        kwargs.setdefault("is_array", True)
    return Setting(name=name, key=key, kind=kind, parser=parser, engine_default=engine_default, **kwargs)


SETTINGS: list = []


def section(title: str, settings: list, target: str = Target.SERVER_CFG):
    for s in settings:
        s.section = title
        s.target = target
    SETTINGS.extend(settings)


section("SERVER IDENTITY AND ACCESS", [
    S("HOSTNAME", "hostname", Kind.STRING, "local machine name"),
    S("PASSWORD", "password", Kind.STRING, '""'),
    S("PASSWORD_ADMIN", "passwordAdmin", Kind.STRING, '""'),
    S("SERVER_COMMAND_PASSWORD", "serverCommandPassword", Kind.STRING, '""'),
    S("MAX_PLAYERS", "maxPlayers", Kind.NUMBER, "64"),
    S("ADMINS", "admins", Kind.STRING_LIST, "{}"),
    S("HEADLESS_CLIENTS", "headlessClients", Kind.STRING_LIST, "{}"),
    S("LOCAL_CLIENT", "localClient", Kind.STRING_LIST, "{}"),
    S("FILE_PATCHING_EXCEPTIONS", "filePatchingExceptions", Kind.STRING_LIST, "{}"),
    S("LOOPBACK", "loopback", Kind.BOOL, "false"),
    S("UPNP", "upnp", Kind.BOOL, "false"),
    S("REQUIRED_BUILD", "requiredBuild", Kind.NUMBER, "0"),
    S("KICK_DUPLICATE", "kickDuplicate", Kind.FLAG, "0"),
])

section("MESSAGE OF THE DAY", [
    S("MOTD", "motd", Kind.STRING_LIST, "{}"),
    S("MOTD_INTERVAL", "motdInterval", Kind.NUMBER, "5"),
])

section("SECURITY", [
    S("BATTLEYE", "BattlEye", Kind.FLAG, "1"),
    S("VERIFY_SIGNATURES", "verifySignatures", Kind.NUMBER, "2"),
    S("EQUAL_MOD_REQUIRED", "equalModRequired", Kind.FLAG, "0"),
    S("ALLOWED_FILE_PATCHING", "allowedFilePatching", Kind.NUMBER, "0"),
    S("ALLOWED_LOAD_FILE_EXTENSIONS", "allowedLoadFileExtensions", Kind.STRING_LIST, "undefined (everything allowed)"),
    S("ALLOWED_PREPROCESS_FILE_EXTENSIONS", "allowedPreprocessFileExtensions", Kind.STRING_LIST, "undefined (everything allowed)"),
    S("ALLOWED_HTML_LOAD_EXTENSIONS", "allowedHTMLLoadExtensions", Kind.STRING_LIST, "undefined (everything allowed)"),
    S("ALLOWED_HTML_LOAD_URIS", "allowedHTMLLoadURIs", Kind.STRING_LIST, "undefined (everything allowed)"),
    S("ZEUS_COMPOSITION_SCRIPT_LEVEL", "zeusCompositionScriptLevel", Kind.NUMBER, "1"),
])

section("VOTING", [
    S("VOTE_THRESHOLD", "voteThreshold", Kind.NUMBER, "0.5"),
    S("VOTE_MISSION_PLAYERS", "voteMissionPlayers", Kind.NUMBER, "1"),
    S("ALLOWED_VOTE_CMDS", "allowedVoteCmds", Kind.ROWS, "{}",
      parser=make_rows_parser([STRING_COLUMN, BOOL_COLUMN, BOOL_COLUMN, NUMBER_COLUMN], min_fields=3)),
    S("ALLOWED_VOTED_ADMIN_CMDS", "allowedVotedAdminCmds", Kind.ROWS, "{}",
      parser=make_rows_parser([STRING_COLUMN, BOOL_COLUMN, BOOL_COLUMN], min_fields=3)),
])

section("NETWORK QUALITY", [
    S("MAX_PING", "maxPing", Kind.NUMBER, "-1"),
    S("MAX_PACKET_LOSS", "maxPacketLoss", Kind.NUMBER, "-1"),
    S("MAX_DESYNC", "maxDesync", Kind.NUMBER, "-1"),
    S("DISCONNECT_TIMEOUT", "disconnectTimeout", Kind.NUMBER, "15"),
    S("KICK_CLIENTS_ON_SLOW_NETWORK", "kickClientsOnSlowNetwork", Kind.NUMBER_LIST, "{ 1, 1, 1, 1 }",
      parser=make_number_list_parser(length=4)),
    S("ENABLE_PLAYER_DIAG", "enablePlayerDiag", Kind.FLAG, "0"),
    S("CALL_EXT_REPORT_LIMIT", "callExtReportLimit", Kind.NUMBER, "1000"),
    S("STEAM_PROTOCOL_MAX_DATA_SIZE", "steamProtocolMaxDataSize", Kind.NUMBER, "1024"),
    S("ARMA_UNITS_TIMEOUT", "armaUnitsTimeout", Kind.NUMBER, "30"),
])

section("KICKS AND TIMEOUTS", [
    S("KICK_TIMEOUT", "kickTimeout", Kind.ROWS, "{ { 0, 60 }, { 1, 60 }, { 2, 60 }, { 3, 60 } }",
      parser=make_rows_parser([NUMBER_COLUMN, NUMBER_COLUMN], min_fields=2)),
    S("VOTING_TIME_OUT", "votingTimeOut", Kind.TIMEOUT, "60 or { 60, 90 }"),
    S("ROLE_TIME_OUT", "roleTimeOut", Kind.TIMEOUT, "90 or { 90, 120 }"),
    S("BRIEFING_TIME_OUT", "briefingTimeOut", Kind.TIMEOUT, "60 or { 60, 90 }"),
    S("DEBRIEFING_TIME_OUT", "debriefingTimeOut", Kind.TIMEOUT, "45 or { 45, 60 }"),
    S("LOBBY_IDLE_TIMEOUT", "lobbyIdleTimeout", Kind.NUMBER, "0"),
])

section("MISSION CYCLE", [
    S("MISSIONS_TO_SERVER_RESTART", "missionsToServerRestart", Kind.NUMBER, "0"),
    S("MISSIONS_TO_SHUTDOWN", "missionsToShutdown", Kind.NUMBER, "0"),
    S("AUTO_SELECT_MISSION", "autoSelectMission", Kind.BOOL, "false"),
    S("RANDOM_MISSION_ORDER", "randomMissionOrder", Kind.BOOL, "false"),
    S("PERSISTENT", "persistent", Kind.FLAG, "0"),
    S("FORCED_DIFFICULTY", "forcedDifficulty", Kind.STRING, '""'),
    S("MISSION_WHITELIST", "missionWhitelist", Kind.STRING_LIST, "{}"),
    S("MISSION_HTTP_DOWNLOAD_BASE_URL", "missionHTTPDownloadBaseURL", Kind.STRING, '""'),
])

section("IN-GAME", [
    S("DISABLE_VON", "disableVoN", Kind.FLAG, "0"),
    S("VON_CODEC", "vonCodec", Kind.NUMBER, "1"),
    S("VON_CODEC_QUALITY", "vonCodecQuality", Kind.NUMBER, "3"),
    S("DISABLE_CHANNELS", "disableChannels", Kind.ROWS, "{}",
      parser=make_rows_parser([NUMBER_COLUMN, BOOL_COLUMN, BOOL_COLUMN, BOOL_COLUMN, BOOL_COLUMN], min_fields=3)),
    S("DRAWING_IN_MAP", "drawingInMap", Kind.BOOL, "true"),
    S("SKIP_LOBBY", "skipLobby", Kind.BOOL, "false"),
    S("ALLOW_PROFILE_GLASSES", "allowProfileGlasses", Kind.BOOL, "true"),
    S("FORCE_ROTOR_LIB_SIMULATION", "forceRotorLibSimulation", Kind.NUMBER, "0"),
    S("OVERRIDE_HAZE_QUALITY", "overrideHazeQuality", Kind.NUMBER, "-1"),
    S("IDLE_FPS_LIMIT", "idleFPSLimit", Kind.NUMBER, "30"),
])

section("LOGGING AND ANALYTICS", [
    S("LOG_FILE", "logFile", Kind.STRING, '""'),
    S("TIME_STAMP_FORMAT", "timeStampFormat", Kind.STRING, '"short"'),
    S("TIME_STAMP_FORMAT_CONSOLE", "timeStampFormatConsole", Kind.STRING, '"short"'),
    S("STATISTICS_ENABLED", "statisticsEnabled", Kind.FLAG, "1"),
])

section("SERVER-SIDE SCRIPTING EVENT HANDLERS", [
    S("DOUBLE_ID_DETECTED", "doubleIdDetected", Kind.STRING, '""'),
    S("ON_USER_CONNECTED", "onUserConnected", Kind.STRING, '""'),
    S("ON_USER_DISCONNECTED", "onUserDisconnected", Kind.STRING, '""'),
    S("ON_USER_KICKED", "onUserKicked", Kind.STRING, '""'),
    S("ON_HACKED_DATA", "onHackedData", Kind.STRING, '""'),
    S("ON_DIFFERENT_DATA", "onDifferentData", Kind.STRING, '""'),
    S("ON_UNSIGNED_DATA", "onUnsignedData", Kind.STRING, '""'),
    S("REGULAR_CHECK", "regularCheck", Kind.STRING, '""'),
])

section("class AdvancedOptions", [
    S("ADVANCED_OPTIONS_LOG_OBJECT_NOT_FOUND", "logObjectNotFound", Kind.FLAG, "1", cls="AdvancedOptions"),
    S("ADVANCED_OPTIONS_SKIP_DESCRIPTION_PARSING", "skipDescriptionParsing", Kind.FLAG, "0", cls="AdvancedOptions"),
    S("ADVANCED_OPTIONS_IGNORE_MISSION_LOAD_ERRORS", "ignoreMissionLoadErrors", Kind.FLAG, "0", cls="AdvancedOptions"),
    S("ADVANCED_OPTIONS_QUEUE_SIZE_LOG_G", "queueSizeLogG", Kind.NUMBER, "0", cls="AdvancedOptions"),
])

section("class AntiFlood", [
    S("ANTI_FLOOD_CYCLE_TIME", "cycleTime", Kind.NUMBER, "0.5", cls="AntiFlood"),
    S("ANTI_FLOOD_CYCLE_LIMIT", "cycleLimit", Kind.NUMBER, "400", cls="AntiFlood"),
    S("ANTI_FLOOD_CYCLE_HARD_LIMIT", "cycleHardLimit", Kind.NUMBER, "4000", cls="AntiFlood"),
    S("ANTI_FLOOD_ENABLE_KICK", "enableKick", Kind.FLAG, "0", cls="AntiFlood"),
])

# Profile: class DifficultyPresets / class CustomDifficulty in <name>.Arma3Profile.
# Documented values are for reference; all are accepted as numbers so a new engine value
# never needs a rebuild. Keys marked "unverified" come from memory of the Difficulty Settings
# wiki page rather than from a profile the engine has written back.
DIFFICULTY_OPTIONS_CLASS = "Options"
DIFFICULTY_AI_CLASS = "CustomAILevel"

section("DIFFICULTY OPTIONS", [
    S("REDUCED_DAMAGE", "reducedDamage", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("GROUP_INDICATORS", "groupIndicators", Kind.NUMBER, "0 never, 1 limited distance, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("FRIENDLY_TAGS", "friendlyTags", Kind.NUMBER, "0 never, 1 limited distance, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("ENEMY_TAGS", "enemyTags", Kind.NUMBER, "0 never, 1 limited distance, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("DETECTED_MINES", "detectedMines", Kind.NUMBER, "0 never, 1 limited distance, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("COMMANDS", "commands", Kind.NUMBER, "0 never, 1 fade out, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("WAYPOINTS", "waypoints", Kind.NUMBER, "0 never, 1 fade out, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("TACTICAL_PING", "tacticalPing", Kind.NUMBER, "0 or 1 (unverified key)", cls=DIFFICULTY_OPTIONS_CLASS),
    S("WEAPON_INFO", "weaponInfo", Kind.NUMBER, "0 never, 1 fade out, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("STANCE_INDICATOR", "stanceIndicator", Kind.NUMBER, "0 never, 1 fade out, 2 always", cls=DIFFICULTY_OPTIONS_CLASS),
    S("STAMINA_BAR", "staminaBar", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("WEAPON_CROSSHAIR", "weaponCrosshair", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("VISION_AID", "visionAid", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("THIRD_PERSON_VIEW", "thirdPersonView", Kind.NUMBER, "0 off, 1 on, 2 vehicles only", cls=DIFFICULTY_OPTIONS_CLASS),
    S("CAMERA_SHAKE", "cameraShake", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("SCORE_TABLE", "scoreTable", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("DEATH_MESSAGES", "deathMessages", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("VON_ID", "vonID", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("MAP_CONTENT", "mapContent", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("MAP_CONTENT_FRIENDLY", "mapContentFriendly", Kind.NUMBER, "0 or 1 (unverified key)", cls=DIFFICULTY_OPTIONS_CLASS),
    S("MAP_CONTENT_ENEMY", "mapContentEnemy", Kind.NUMBER, "0 or 1 (unverified key)", cls=DIFFICULTY_OPTIONS_CLASS),
    S("MAP_CONTENT_MINES", "mapContentMines", Kind.NUMBER, "0 or 1 (unverified key)", cls=DIFFICULTY_OPTIONS_CLASS),
    S("AUTO_REPORT", "autoReport", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
    S("MULTIPLE_SAVES", "multipleSaves", Kind.NUMBER, "0 or 1", cls=DIFFICULTY_OPTIONS_CLASS),
], target=Target.PROFILE)

section("DIFFICULTY AI", [
    S("AI_LEVEL_PRESET", "aiLevelPreset", Kind.NUMBER, "0 low, 1 normal, 2 high, 3 custom"),
    S("AI_SKILL", "skillAI", Kind.NUMBER, "0.0 to 1.0, used when preset is 3", cls=DIFFICULTY_AI_CLASS),
    S("AI_PRECISION", "precisionAI", Kind.NUMBER, "0.0 to 1.0, used when preset is 3", cls=DIFFICULTY_AI_CLASS),
], target=Target.PROFILE)

EXTRA_NAME = "EXTRA"
EXTRA_VARIABLE = ENV_PREFIX + EXTRA_NAME

MISSION_PATTERN = re.compile(r"^" + ENV_PREFIX + r"MISSION_(\d+)_(TEMPLATE|DIFFICULTY|NAME|PARAMS)$")
MISSION_CLASS_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SETTINGS_BY_VARIABLE = {s.variable: s for s in SETTINGS}
SERVER_CFG_SETTINGS = [s for s in SETTINGS if s.target == Target.SERVER_CFG]
PROFILE_SETTINGS = [s for s in SETTINGS if s.target == Target.PROFILE]


# --------------------------------------------------------------------------- #
# Loading values
# --------------------------------------------------------------------------- #

def load_defaults_file(path: Path) -> dict:
    """Parses KEY=VALUE lines. '#' comments and blank lines are ignored."""
    values = {}
    if not path.exists():
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                raise ConfigError(str(path), f"line {line_number}: expected KEY=VALUE")
            key, value = line.rstrip("\r\n").split("=", 1)
            key = key.strip()
            if not key.startswith(PREFIXES):
                raise ConfigError(str(path), f"line {line_number}: key '{key}' must start with one of {', '.join(PREFIXES)}")
            values[key] = value
    return values


def is_known_variable(variable: str) -> bool:
    return (variable in SETTINGS_BY_VARIABLE
            or variable == EXTRA_VARIABLE
            or MISSION_PATTERN.match(variable) is not None)


def collect_values(environ: dict, defaults: dict) -> dict:
    """Merges environment over defaults. Returns {variable: raw value}, with null entries removed.

    Both sources are checked for unknown variables, and *_FILE variants are resolved.
    """
    merged = {}

    for source_label, source in (("defaults file", defaults), ("environment", environ)):
        plain = {}
        from_file = {}
        for variable, raw in source.items():
            if not variable.startswith(PREFIXES):
                continue
            if variable.endswith(FILE_SUFFIX) and is_known_variable(variable[:-len(FILE_SUFFIX)]):
                from_file[variable[:-len(FILE_SUFFIX)]] = raw
            elif is_known_variable(variable):
                plain[variable] = raw
            else:
                raise ConfigError(variable, f"unknown variable in {source_label}")

        for variable, path in from_file.items():
            if variable in plain:
                print(f"Warning: {variable} and {variable}{FILE_SUFFIX} are both set, using {variable}", file=sys.stderr)
                continue
            try:
                with open(path.strip(), "r", encoding="utf-8") as f:
                    plain[variable] = f.read().rstrip("\r\n")
            except OSError as e:
                raise ConfigError(f"{variable}{FILE_SUFFIX}", f"cannot read '{path}': {e}") from e

        merged.update(plain)

    return {variable: raw for variable, raw in merged.items() if raw.strip() != NULL_VALUE}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_setting(setting: Setting, raw: str) -> str:
    if setting.kind == Kind.TIMEOUT:
        form, value = setting.parser(setting.variable, raw)
        suffix = "[]" if form == "array" else ""
        return f"{setting.key}{suffix} = {value};"
    value = setting.parser(setting.variable, raw)
    suffix = "[]" if setting.is_array else ""
    return f"{setting.key}{suffix} = {value};"


def render_missions(values: dict) -> list:
    """Builds the class Missions block. Returns [] when no missions are defined."""
    missions = {}
    for variable, raw in values.items():
        match = MISSION_PATTERN.match(variable)
        if match:
            index = int(match.group(1))
            missions.setdefault(index, {})[match.group(2)] = raw

    if not missions:
        return []

    expected = list(range(1, len(missions) + 1))
    if sorted(missions) != expected:
        raise ConfigError(f"{ENV_PREFIX}MISSION_N_*",
                          f"mission indices must be contiguous from 1, got {sorted(missions)}")

    lines = ["class Missions", "{"]
    for index in expected:
        fields = missions[index]
        prefix = f"{ENV_PREFIX}MISSION_{index}_"
        if "TEMPLATE" not in fields:
            raise ConfigError(prefix + "TEMPLATE", "is required when defining a mission")
        if "DIFFICULTY" not in fields:
            raise ConfigError(prefix + "DIFFICULTY", "is required when defining a mission")
        class_name = fields.get("NAME", f"mission_{index}").strip()
        if not MISSION_CLASS_NAME_PATTERN.match(class_name):
            raise ConfigError(prefix + "NAME", f"'{class_name}' is not a valid class name (letters, digits, underscore)")

        lines.append(f"\tclass {class_name}")
        lines.append("\t{")
        lines.append(f"\t\ttemplate = {quote(fields['TEMPLATE'])};")
        lines.append(f"\t\tdifficulty = {quote(fields['DIFFICULTY'])};")
        params_raw = fields.get("PARAMS")
        if params_raw is not None:
            lines.append("\t\tclass Params")
            lines.append("\t\t{")
            for item in split_list(prefix + "PARAMS", params_raw):
                if isinstance(item, list) or "=" not in item:
                    raise ConfigError(prefix + "PARAMS", f"expected key=value, got '{item}'")
                key, value = item.split("=", 1)
                key = key.strip()
                if not MISSION_CLASS_NAME_PATTERN.match(key):
                    raise ConfigError(prefix + "PARAMS", f"'{key}' is not a valid parameter name")
                lines.append(f"\t\t\t{key} = {value.strip()};")
            lines.append("\t\t};")
        lines.append("\t};")
    lines.append("};")
    return lines


def render_config(values: dict) -> str:
    lines = [
        "// Generated by server_config_generator/generate_server_config.py from ARMA_CFG_* variables.",
        "// Edit the environment or defaults.env, not this file.",
    ]

    # Top-level settings, grouped by section in definition order.
    current_section = None
    for setting in SERVER_CFG_SETTINGS:
        if setting.cls is not None or setting.variable not in values:
            continue
        if setting.section != current_section:
            current_section = setting.section
            lines.append("")
            lines.append(f"// {current_section}")
        lines.append(render_setting(setting, values[setting.variable]))

    # Classes, emitted only when at least one member is set.
    classes = {}
    for setting in SERVER_CFG_SETTINGS:
        if setting.cls is not None and setting.variable in values:
            classes.setdefault(setting.cls, []).append(setting)
    for cls, members in classes.items():
        lines.append("")
        lines.append(f"class {cls}")
        lines.append("{")
        for setting in members:
            lines.append("\t" + render_setting(setting, values[setting.variable]))
        lines.append("};")

    mission_lines = render_missions(values)
    if mission_lines:
        lines.append("")
        lines.append("// MISSIONS")
        lines.extend(mission_lines)

    if EXTRA_VARIABLE in values:
        lines.append("")
        lines.append("// EXTRA")
        lines.append(values[EXTRA_VARIABLE])

    return "\n".join(lines) + "\n"


def render_profile(values: dict) -> Optional[str]:
    """Renders <name>.Arma3Profile with the CustomDifficulty class.

    Returns None when no ARMA_DIFFICULTY_* variable is set, so the existing profile is left alone.
    Only the difficulty class is emitted: Arma writes the rest of the profile back itself.
    """
    present = [s for s in PROFILE_SETTINGS if s.variable in values]
    if not present:
        return None

    def members_of(cls: Optional[str]) -> list:
        return [f"{s.key}={s.parser(s.variable, values[s.variable])};" for s in present if s.cls == cls]

    lines = [
        "// Generated by server_config_generator/generate_server_config.py from ARMA_DIFFICULTY_* variables.",
        "// Edit the environment or defaults.env, not this file. Arma appends its own settings on run.",
        "version=1;",
        "",
        "class DifficultyPresets",
        "{",
        "\tclass CustomDifficulty",
        "\t{",
    ]
    options = members_of(DIFFICULTY_OPTIONS_CLASS)
    if options:
        lines.append(f"\t\tclass {DIFFICULTY_OPTIONS_CLASS}")
        lines.append("\t\t{")
        lines.extend("\t\t\t" + m for m in options)
        lines.append("\t\t};")
    lines.extend("\t\t" + m for m in members_of(None))
    ai = members_of(DIFFICULTY_AI_CLASS)
    if ai:
        lines.append(f"\t\tclass {DIFFICULTY_AI_CLASS}")
        lines.append("\t\t{")
        lines.extend("\t\t\t" + m for m in ai)
        lines.append("\t\t};")
    lines.append("\t};")
    lines.append("};")
    return "\n".join(lines) + "\n"


@dataclass
class Generated:
    server_cfg: str
    profile: Optional[str]   # None when no difficulty variables are set


def generate_all(environ: dict, defaults_path: Path) -> Generated:
    defaults = load_defaults_file(defaults_path)
    values = collect_values(environ, defaults)
    return Generated(server_cfg=render_config(values), profile=render_profile(values))


def generate(environ: dict, defaults_path: Path) -> str:
    """Kept for callers that only want server.cfg."""
    return generate_all(environ, defaults_path).server_cfg


# --------------------------------------------------------------------------- #
# Template for the defaults file
# --------------------------------------------------------------------------- #

def render_defaults_template() -> str:
    lines = [
        "# Defaults for the generated Arma 3 server.cfg and profile difficulty.",
        "#",
        "# Same format as the environment: ARMA_CFG_<NAME>=<value> or ARMA_DIFFICULTY_<NAME>=<value>,",
        "# one per line. Environment variables override anything set here.",
        "#",
        "# A line left commented out means the key is omitted and Arma uses its built-in behaviour.",
        "# The engine default shown beside each ARMA_CFG_ entry is documented at",
        "# https://community.bistudio.com/wiki/Arma_3:_Server_Config_File and is for reference only.",
        "#",
        "# ARMA_DIFFICULTY_* entries render class CustomDifficulty in <name>.Arma3Profile, where <name>",
        "# comes from the -name= startup argument. The profile is written only when at least one is set,",
        "# and a mission must use difficulty = \"Custom\" for it to apply.",
        "#",
        "# Value formats:",
        "#   number       integer or decimal, e.g. 24 or 0.7",
        "#   flag         0 or 1",
        "#   bool         true or false",
        "#   string list  item|item|item",
        "#   rows         field,field|field,field",
        "#   timeout      60  or  60|90  (ready|notReady)",
        "#   Any list also accepts a JSON array, e.g. [\"a\",\"b\"] or [[0,-1],[1,20]].",
        "#   An empty value emits \"\" or {}. The value null omits the key.",
        "#   Any variable may be given as <VARIABLE>_FILE=/path to read the value from a file.",
    ]
    current_section = None
    for setting in SERVER_CFG_SETTINGS:
        if setting.section != current_section:
            current_section = setting.section
            lines.append("")
            lines.append(f"# ---- {current_section} ----")
        lines.append(f"# {setting.key}  ({setting.kind}, engine default: {setting.engine_default})")
        lines.append(f"#{setting.variable}=")
    lines.extend([
        "",
        "# ---- MISSIONS ----",
        "# Indexed from 1, contiguous. TEMPLATE and DIFFICULTY are required per mission.",
        "# PARAMS values are emitted as written: wrap in \"...\" for a string parameter.",
        "#ARMA_CFG_MISSION_1_NAME=",
        "#ARMA_CFG_MISSION_1_TEMPLATE=",
        "#ARMA_CFG_MISSION_1_DIFFICULTY=",
        "#ARMA_CFG_MISSION_1_PARAMS=",
        "",
        "# ---- EXTRA ----",
        "# Raw server.cfg text appended verbatim at the end of the generated file.",
        "#ARMA_CFG_EXTRA=",
    ])
    for setting in PROFILE_SETTINGS:
        if setting.section != current_section:
            current_section = setting.section
            lines.append("")
            lines.append(f"# ---- {current_section} (profile) ----")
        lines.append(f"# {setting.key}  ({setting.kind}, values: {setting.engine_default})")
        lines.append(f"#{setting.variable}=")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an Arma 3 server.cfg from ARMA_CFG_* variables and a profile difficulty from ARMA_DIFFICULTY_* variables")
    parser.add_argument("--defaults", type=Path, default=DEFAULT_DEFAULTS_FILE,
                        help=f"defaults file in KEY=VALUE form (default: {DEFAULT_DEFAULTS_FILE})")
    parser.add_argument("--output", type=Path, help="write the generated server.cfg to this path")
    parser.add_argument("--profile-output", type=Path,
                        help="write the generated <name>.Arma3Profile to this path (skipped when no difficulty variables are set)")
    parser.add_argument("--print", action="store_true", help="print the generated files to stdout")
    parser.add_argument("--write-template", action="store_true",
                        help="print a fully commented defaults file template to stdout and exit")
    args = parser.parse_args(argv)

    if args.write_template:
        sys.stdout.write(render_defaults_template())
        return 0

    if not args.output and not args.profile_output and not args.print:
        parser.error("one of --output, --profile-output or --print is required")

    try:
        generated = generate_all(dict(os.environ), args.defaults)
    except ConfigError as e:
        print(f"config generation failed: {e}", file=sys.stderr)
        return 1

    if args.output:
        write_file(args.output, generated.server_cfg)
        print(f"Generated {args.output}", flush=True)
    if args.profile_output:
        if generated.profile is None:
            print(f"No ARMA_DIFFICULTY_* variables set, not writing {args.profile_output}", flush=True)
        else:
            write_file(args.profile_output, generated.profile)
            print(f"Generated {args.profile_output}", flush=True)
    if args.print:
        sys.stdout.write(generated.server_cfg)
        if generated.profile is not None:
            sys.stdout.write("\n// ==== <name>.Arma3Profile ====\n")
            sys.stdout.write(generated.profile)
    return 0


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


if __name__ == "__main__":
    sys.exit(main())
