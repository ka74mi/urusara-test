"""Daikin うるさら (BRP084系) 統合の定数定義。

パラメータ対応は daikin-brp084-protocol.md (実機検証メモ) に基づく。
検証機種: BRP084系, firmware 3_15_0 / wlan_adp_gen4
"""
from __future__ import annotations

from homeassistant.components.climate import HVACMode

DOMAIN = "daikin_urusara_x"

CONF_HOST = "host"

DEFAULT_SCAN_INTERVAL = 30  # 秒

# --- dsiot エンドポイント ---
ENDPOINT_INDOOR = "/dsiot/edge/adr_0100.dgc_status"
ENDPOINT_OUTDOOR = "/dsiot/edge/adr_0200.dgc_status"
ENDPOINT_MULTIREQ = "/dsiot/multireq"

RSC_SUCCESS = 2000

# --- ノード名 ---
NODE_INDOOR = "e_1002"
NODE_OUTDOOR = "e_1003"
NODE_POWER = "e_A002"  # 運転状態
NODE_COMMON = "e_3003"  # 共通設定 (制御フラグ・節電など)
NODE_MODE = "e_3001"  # モード別詳細設定
NODE_SENSOR = "e_A00B"  # 室内温湿度センサー

# 室内温湿度 (e_1002/e_A00B 配下、実測値のためそのまま数値として扱う)
SENSOR_TEMPERATURE_PARAM = "p_01"
SENSOR_HUMIDITY_PARAM = "p_02"

# --- 運転状態 (e_A002/p_01) ---
POWER_OFF = "00"
POWER_ON = "01"

# --- 制御内容 (e_3003/p_2D) ---
CTRL_START = "00"
CTRL_STOP = "01"
CTRL_CHANGE = "02"

# --- 運転モード (e_3001/p_01) ---
MODE_FAN_ONLY = "0000"
MODE_HEAT = "0100"
MODE_COOL = "0200"
MODE_AUTO = "0300"
MODE_DRY = "0500"
MODE_HUMIDIFY = "0800"  # climate エンティティの外で扱う (switch/select 経由)

HVAC_MODE_TO_DSIOT: dict[HVACMode, str] = {
    HVACMode.COOL: MODE_COOL,
    HVACMode.HEAT: MODE_HEAT,
    HVACMode.AUTO: MODE_AUTO,
    HVACMode.FAN_ONLY: MODE_FAN_ONLY,
    HVACMode.DRY: MODE_DRY,
}
DSIOT_TO_HVAC_MODE: dict[str, HVACMode] = {v: k for k, v in HVAC_MODE_TO_DSIOT.items()}

# --- モードごとの独立パラメータセット ---
# 風向上下
SWING_VERT_PARAM: dict[str, str] = {
    MODE_COOL: "p_05",
    MODE_HEAT: "p_07",
    MODE_AUTO: "p_20",
    MODE_FAN_ONLY: "p_24",
    MODE_DRY: "p_22",
    MODE_HUMIDIFY: "p_29",
}

# 風向左右
SWING_HORIZ_PARAM: dict[str, str] = {
    MODE_COOL: "p_06",
    MODE_HEAT: "p_08",
    MODE_AUTO: "p_21",
    MODE_FAN_ONLY: "p_25",
    MODE_DRY: "p_23",
    MODE_HUMIDIFY: "p_2A",
}

# 風量
FAN_PARAM: dict[str, str] = {
    MODE_COOL: "p_09",
    MODE_HEAT: "p_0A",
    MODE_AUTO: "p_26",
    MODE_FAN_ONLY: "p_28",
    MODE_DRY: "p_27",
    MODE_HUMIDIFY: "p_2B",
}

# 設定温度 (冷房・暖房のみ。自動はオフセット p_1F、送風・除湿・加湿は温度設定なし)
TEMPERATURE_PARAM: dict[str, str] = {
    MODE_COOL: "p_02",
    MODE_HEAT: "p_03",
}
AUTO_TEMP_OFFSET_PARAM = "p_1F"

# --- しつど (湿度) 関連: climate エンティティ外 (switch/select) で扱うため参考として保持 ---
HUMIDITY_ONOFF_PARAM: dict[str, str] = {
    MODE_COOL: "p_0C",
    MODE_HEAT: "p_2D",  # 親entityは e_1002/e_3001 (制御フラグ e_3003/p_2D とは別物)
    MODE_DRY: "p_31",
    MODE_HUMIDIFY: "p_33",
}
HUMIDITY_LEVEL_PARAM: dict[str, str] = {
    MODE_COOL: "p_0B",
    MODE_HEAT: "p_2C",
    MODE_DRY: "p_30",
    MODE_HUMIDIFY: "p_32",
}
AUTO_HUMIDITY_PARAM = "p_2F"  # 4段階一体型 (OFF/低め/普通/高め)、親entityは e_1002/e_3001

# しつどレベルの値対応。冷房は除湿寄り(50/55/60%)、暖房・加湿は加湿寄り(40/45/50%)。
# 除湿 (p_30) は暖房と同じ範囲かは未確認 (daikin-brp084-protocol.md 参照) のため、
# ひとまず暖房・加湿と同一の値体系として扱う。
HUMIDITY_LEVEL_LABELS_COOL: dict[str, str] = {
    "0A": "50",
    "0B": "55",
    "0C": "60",
}
HUMIDITY_LEVEL_LABELS_HEAT_HUMIDIFY_DRY: dict[str, str] = {
    "08": "40",
    "09": "45",
    "0A": "50",
}
HUMIDITY_LEVEL_LABELS: dict[str, dict[str, str]] = {
    MODE_COOL: HUMIDITY_LEVEL_LABELS_COOL,
    MODE_HEAT: HUMIDITY_LEVEL_LABELS_HEAT_HUMIDIFY_DRY,
    MODE_DRY: HUMIDITY_LEVEL_LABELS_HEAT_HUMIDIFY_DRY,
    MODE_HUMIDIFY: HUMIDITY_LEVEL_LABELS_HEAT_HUMIDIFY_DRY,
}
HUMIDITY_LEVEL_LABEL_TO_VALUE: dict[str, dict[str, str]] = {
    mode: {v: k for k, v in labels.items()} for mode, labels in HUMIDITY_LEVEL_LABELS.items()
}

# しつどON/OFFの値対応 (共通)。'06'=連続 は冷房のみ確認されているが、
# 他モードでも同一値体系と推定し共通で扱う。
HUMIDITY_ONOFF_CONTINUOUS = "06"

# --- 統一しつど select (アプリUIに合わせ、モードごとに単一の選択肢リストとして扱う) ---
# 除湿・加湿モードは「OFF」選択肢を持たない (スマホアプリのUI仕様に基づく)。
HUMIDITY_SELECT_HAS_OFF: dict[str, bool] = {
    MODE_COOL: True,
    MODE_HEAT: True,
    MODE_DRY: False,
    MODE_HUMIDIFY: False,
}
HUMIDITY_SELECT_CONTINUOUS_LABEL = "continuous"

# 選択肢ラベル (表示順) を「OFF」「レベル群」「連続」の順で組み立てるためのヘルパー値。
# 実際の options 組み立ては select.py 側で HUMIDITY_SELECT_HAS_OFF と
# HUMIDITY_LEVEL_LABELS を使って動的に行う。

# 自動モードのしつど (4段階一体型)
AUTO_HUMIDITY_LABELS: dict[str, str] = {
    "00": "off",
    "04": "low",
    "02": "normal",
    "03": "high",
}
AUTO_HUMIDITY_LABEL_TO_VALUE: dict[str, str] = {v: k for k, v in AUTO_HUMIDITY_LABELS.items()}

# --- 風向 値対応 ---
SWING_VERT_OFF = "000000"
SWING_VERT_AUTO = "100000"
SWING_VERT_SWING = "0F0000"
SWING_VERT_CIRCULATE = "140000"
# 固定1段目(上)〜6段目(下): "010000"〜"060000"

SWING_HORIZ_OFF = "000000"
SWING_HORIZ_SWING = "0F0000"
# 固定1/5〜5/5: "0A0000"〜"0E0000"

# --- 風量 値対応 ---
FAN_AUTO = "0A00"
FAN_QUIET = "0B00"
# 風量1〜5: "0300"〜"0700"

FAN_MODE_LABELS: dict[str, str] = {
    FAN_AUTO: "auto",
    FAN_QUIET: "quiet",
    "0300": "1",
    "0400": "2",
    "0500": "3",
    "0600": "4",
    "0700": "5",
}
FAN_LABEL_TO_VALUE: dict[str, str] = {v: k for k, v in FAN_MODE_LABELS.items()}

SWING_VERT_LABELS: dict[str, str] = {
    SWING_VERT_OFF: "off",
    SWING_VERT_AUTO: "auto",
    SWING_VERT_SWING: "swing",
    SWING_VERT_CIRCULATE: "circulate",
    "010000": "1",
    "020000": "2",
    "030000": "3",
    "040000": "4",
    "050000": "5",
    "060000": "6",
}
SWING_VERT_LABEL_TO_VALUE: dict[str, str] = {v: k for k, v in SWING_VERT_LABELS.items()}

SWING_HORIZ_LABELS: dict[str, str] = {
    SWING_HORIZ_OFF: "off",
    SWING_HORIZ_SWING: "swing",
    "0A0000": "1",
    "0B0000": "2",
    "0C0000": "3",
    "0D0000": "4",
    "0E0000": "5",
}
SWING_HORIZ_LABEL_TO_VALUE: dict[str, str] = {v: k for k, v in SWING_HORIZ_LABELS.items()}

# --- 換気・節電など (うるさら特有、switch/select 対象) ---
VENTILATION_ONOFF_PARAM = "p_36"  # e_3001 配下
VENTILATION_STRENGTH_PARAM = "p_1C"  # e_3001 配下
VENTILATION_DIRECTION_PARAM = "p_45"  # e_3001 配下
POWER_SAVING_PARAM = "p_71"  # e_3003 配下

VENTILATION_STRENGTH_LABELS = {"01": "strong", "02": "auto"}
VENTILATION_STRENGTH_LABEL_TO_VALUE = {v: k for k, v in VENTILATION_STRENGTH_LABELS.items()}

VENTILATION_DIRECTION_LABELS = {"00": "intake", "01": "exhaust"}
VENTILATION_DIRECTION_LABEL_TO_VALUE = {v: k for k, v in VENTILATION_DIRECTION_LABELS.items()}

ONOFF_ON = "01"
ONOFF_OFF = "00"
