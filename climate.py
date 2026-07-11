"""Daikin うるさら climate エンティティ。

対応: 冷房・暖房・自動・送風・除湿の5モード。加湿は独立運転モードのため
switch/select エンティティ側 (humidify_switch.py 相当) で扱う。
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DSIOT_TO_HVAC_MODE,
    FAN_LABEL_TO_VALUE,
    FAN_MODE_LABELS,
    FAN_PARAM,
    HVAC_MODE_TO_DSIOT,
    SWING_HORIZ_LABEL_TO_VALUE,
    SWING_HORIZ_LABELS,
    SWING_HORIZ_PARAM,
    SWING_VERT_LABEL_TO_VALUE,
    SWING_VERT_LABELS,
    SWING_VERT_PARAM,
    TEMPERATURE_PARAM,
)
from .coordinator import DaikinCoordinator
from .entity import DaikinEntity

_LOGGER = logging.getLogger(__name__)

# 設定温度に対応するモード (冷房・暖房のみ。自動はオフセット制御のため対象外)
TEMPERATURE_CAPABLE_MODES = set(TEMPERATURE_PARAM.keys())


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """climate プラットフォームのセットアップ。"""
    coordinator: DaikinCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DaikinClimateEntity(coordinator)])


class DaikinClimateEntity(DaikinEntity, ClimateEntity):
    """Daikin エアコンのメイン climate エンティティ。"""

    _attr_name = None  # デバイスの主機能として扱う
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_MODE_TO_DSIOT.keys()]
    _attr_fan_modes = list(FAN_MODE_LABELS.values())
    _attr_swing_modes = list(SWING_VERT_LABELS.values())
    _attr_swing_horizontal_modes = list(SWING_HORIZ_LABELS.values())

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_climate"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.SWING_HORIZONTAL_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    # --- 現在モードの取得 ---

    @property
    def _current_dsiot_mode(self) -> str | None:
        return self.coordinator.current_mode

    @property
    def hvac_mode(self) -> HVACMode | None:
        if not self.coordinator.is_power_on:
            return HVACMode.OFF
        mode = self._current_dsiot_mode
        if mode is None:
            return None
        # 加湿モード (MODE_HUMIDIFY) は climate の HVACMode に存在しないため None を返す
        return DSIOT_TO_HVAC_MODE.get(mode)

    # --- 設定温度 ---

    @property
    def current_temperature(self) -> float | None:
        """e_1002/e_A00B/p_01 (室内温度実測値) を返す。"""
        return self.coordinator.current_temperature

    @property
    def current_humidity(self) -> float | None:
        """e_1002/e_A00B/p_02 (室内湿度実測値) を返す。"""
        return self.coordinator.current_humidity

    @property
    def target_temperature(self) -> float | None:
        # 自動モードはオフセット制御 (AUTO_TEMP_OFFSET_PARAM = p_1F) のため、
        # 絶対温度としての target_temperature は冷房・暖房のみ対応する。
        # 自動モードのオフセット調整UIは将来的に number エンティティ等での
        # 別実装を検討 (現時点では未実装)。
        mode = self._current_dsiot_mode
        if mode not in TEMPERATURE_CAPABLE_MODES:
            return None
        param = TEMPERATURE_PARAM[mode]
        raw = self.coordinator.get_mode_param(param)
        if raw is None:
            return None
        return _hex_to_celsius(raw)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        mode = self._current_dsiot_mode
        if mode not in TEMPERATURE_CAPABLE_MODES:
            _LOGGER.warning("現在のモードは温度設定に対応していません: mode=%s", mode)
            return
        param = TEMPERATURE_PARAM[mode]
        await self.coordinator.async_write_settings({param: _celsius_to_hex(temperature)})

    # --- 風量 ---

    @property
    def fan_mode(self) -> str | None:
        mode = self._current_dsiot_mode
        if mode is None or mode not in FAN_PARAM:
            return None
        raw = self.coordinator.get_mode_param(FAN_PARAM[mode])
        if raw is None:
            return None
        return FAN_MODE_LABELS.get(raw)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        mode = self._current_dsiot_mode
        if mode is None or mode not in FAN_PARAM:
            _LOGGER.warning("現在のモードは風量設定に対応していません: mode=%s", mode)
            return
        value = FAN_LABEL_TO_VALUE.get(fan_mode)
        if value is None:
            _LOGGER.warning("不明な fan_mode です: %s", fan_mode)
            return
        await self.coordinator.async_write_settings({FAN_PARAM[mode]: value})

    # --- 風向上下 (swing_mode) ---

    @property
    def swing_mode(self) -> str | None:
        mode = self._current_dsiot_mode
        if mode is None or mode not in SWING_VERT_PARAM:
            return None
        raw = self.coordinator.get_mode_param(SWING_VERT_PARAM[mode])
        if raw is None:
            return None
        return SWING_VERT_LABELS.get(raw)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        mode = self._current_dsiot_mode
        if mode is None or mode not in SWING_VERT_PARAM:
            _LOGGER.warning("現在のモードは風向上下設定に対応していません: mode=%s", mode)
            return
        value = SWING_VERT_LABEL_TO_VALUE.get(swing_mode)
        if value is None:
            _LOGGER.warning("不明な swing_mode です: %s", swing_mode)
            return
        await self.coordinator.async_write_settings({SWING_VERT_PARAM[mode]: value})

    # --- 風向左右 (swing_horizontal_mode) ---

    @property
    def swing_horizontal_mode(self) -> str | None:
        mode = self._current_dsiot_mode
        if mode is None or mode not in SWING_HORIZ_PARAM:
            return None
        raw = self.coordinator.get_mode_param(SWING_HORIZ_PARAM[mode])
        if raw is None:
            return None
        return SWING_HORIZ_LABELS.get(raw)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        mode = self._current_dsiot_mode
        if mode is None or mode not in SWING_HORIZ_PARAM:
            _LOGGER.warning("現在のモードは風向左右設定に対応していません: mode=%s", mode)
            return
        value = SWING_HORIZ_LABEL_TO_VALUE.get(swing_horizontal_mode)
        if value is None:
            _LOGGER.warning("不明な swing_horizontal_mode です: %s", swing_horizontal_mode)
            return
        await self.coordinator.async_write_settings({SWING_HORIZ_PARAM[mode]: value})

    # --- HVACMode / 電源 ---

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_power(turn_on=False)
            return

        dsiot_mode = HVAC_MODE_TO_DSIOT.get(hvac_mode)
        if dsiot_mode is None:
            _LOGGER.warning("未対応の hvac_mode です: %s", hvac_mode)
            return

        was_off = not self.coordinator.is_power_on
        # モード切替は p_01 のみ送信し、他パラメータ (風量・風向等) は
        # 実機側が前回のそのモードの設定値を記憶している前提に委ねる。
        await self.coordinator.async_write_settings({"p_01": dsiot_mode})
        if was_off:
            await self.coordinator.async_set_power(turn_on=True)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_power(turn_on=True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_power(turn_on=False)


def _hex_to_celsius(raw: str) -> float:
    """例: '3A' (16進) -> 58 (10進) -> 29.0℃。"""
    return int(raw, 16) / 2

def _celsius_to_hex(value: float) -> str:
    """摂氏温度を dsiot の16進表現に変換する (_hex_to_celsius の逆変換)。"""
    return format(int(round(value * 2)), "02X")
