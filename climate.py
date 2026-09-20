"""Daikin うるさら climate エンティティ。

HomeKit (HeaterCooler) で確実に表現できる範囲だけを公開する。
  運転モード : オフ / 冷房 / 暖房 / 自動
  設定温度   : 冷房・暖房のみ
  風量       : auto / low(静か) / medium(風量3) / high(風量5)
  スイング   : 風向上下の ON/OFF のみ
送風・除湿・加湿への切り替え、しつど、風向左右などは select / switch 側で扱う。
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    SWING_OFF,
    SWING_ON,
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
    FAN_ALLOWED_VALUES,
    FAN_DSIOT_TO_LABEL,
    FAN_LABEL_TO_DSIOT,
    FAN_MODES_EXPOSED,
    FAN_PARAM,
    FAN_VALUE_AUTO,
    HVAC_MODE_TO_DSIOT,
    SWING_LABEL_TO_VERT,
    SWING_VERT_AUTO_NOT_ALLOWED,
    SWING_VERT_OFF,
    SWING_VERT_PARAM,
    SWING_VERT_SWING,
    TEMPERATURE_PARAM,
    TEMPERATURE_RANGE,
)
from .coordinator import DaikinCoordinator
from .entity import DaikinEntity

_LOGGER = logging.getLogger(__name__)


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
    # 冷房 18〜32 / 暖房 14〜30 の和集合。モードごとの範囲は書き込み時に丸める。
    _attr_min_temp = 14.0
    _attr_max_temp = 32.0
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_MODE_TO_DSIOT]
    _attr_fan_modes = FAN_MODES_EXPOSED
    _attr_swing_modes = list(SWING_LABEL_TO_VERT)

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_climate"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def _dsiot_mode(self) -> str | None:
        return self.coordinator.current_mode

    # --- 運転モード ---

    @property
    def hvac_mode(self) -> HVACMode | None:
        if not self.coordinator.is_power_on:
            return HVACMode.OFF
        mode = self._dsiot_mode
        if mode is None:
            return None
        # 送風・除湿・加湿は COOL として表示する (実際のモードは運転モード select を参照)
        return DSIOT_TO_HVAC_MODE.get(mode)

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

    # --- 現在の温湿度 ---

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.current_temperature

    @property
    def current_humidity(self) -> float | None:
        return self.coordinator.current_humidity

    # --- 設定温度 (冷房・暖房のみ) ---

    @property
    def target_temperature(self) -> float | None:
        mode = self._dsiot_mode
        if mode not in TEMPERATURE_PARAM:
            return None  # 自動・送風・除湿・加湿は絶対温度を持たない
        raw = self.coordinator.get_mode_param(TEMPERATURE_PARAM[mode])
        if raw is None:
            return None
        return _hex_to_celsius(raw)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        mode = self._dsiot_mode
        if mode not in TEMPERATURE_PARAM:
            # HomeKit は自動モード等でも設定温度を送ってくるため、警告は出さず無視する
            _LOGGER.debug("現在のモードは温度設定に対応していません: mode=%s", mode)
            return
        low, high = TEMPERATURE_RANGE[mode]
        temperature = min(max(temperature, low), high)
        await self.coordinator.async_write_settings(
            {TEMPERATURE_PARAM[mode]: _celsius_to_hex(temperature)}
        )

    # --- 風量 ---

    @property
    def fan_mode(self) -> str | None:
        mode = self._dsiot_mode
        if mode not in FAN_PARAM:
            return None
        raw = self.coordinator.get_mode_param(FAN_PARAM[mode])
        if raw is None:
            return None
        return FAN_DSIOT_TO_LABEL.get(raw)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        mode = self._dsiot_mode
        if mode not in FAN_PARAM:
            _LOGGER.warning("現在のモードは風量設定に対応していません: mode=%s", mode)
            return
        value = FAN_LABEL_TO_DSIOT.get(fan_mode)
        if value is None:
            _LOGGER.warning("不明な fan_mode です: %s", fan_mode)
            return
        # 自動モードは「自動/静か」、除湿は「自動」しか受け付けない。
        # 選べない値は「自動」に丸める。
        if value not in FAN_ALLOWED_VALUES[mode]:
            _LOGGER.debug("モード %s では風量 %s を選べないため自動にします", mode, fan_mode)
            value = FAN_VALUE_AUTO
        await self.coordinator.async_write_settings({FAN_PARAM[mode]: value})

    # --- スイング (風向上下の ON/OFF のみ) ---

    @property
    def swing_mode(self) -> str | None:
        mode = self._dsiot_mode
        if mode not in SWING_VERT_PARAM:
            return None
        raw = self.coordinator.get_mode_param(SWING_VERT_PARAM[mode])
        if raw is None:
            return None
        # スイング以外 (自動・固定角度・サーキュレーション) はすべて OFF 扱い
        return SWING_ON if raw == SWING_VERT_SWING else SWING_OFF

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        mode = self._dsiot_mode
        if mode not in SWING_VERT_PARAM:
            _LOGGER.warning("現在のモードは風向上下設定に対応していません: mode=%s", mode)
            return
        value = SWING_LABEL_TO_VERT.get(swing_mode)
        if value is None:
            _LOGGER.warning("不明な swing_mode です: %s", swing_mode)
            return
        if swing_mode == SWING_OFF and mode in SWING_VERT_AUTO_NOT_ALLOWED:
            value = SWING_VERT_OFF  # このモードでは「自動」を選べない
        await self.coordinator.async_write_settings({SWING_VERT_PARAM[mode]: value})


def _hex_to_celsius(raw: str) -> float:
    """例: '3A' (16進) -> 58 (10進) -> 29.0℃。"""
    return int(raw, 16) / 2


def _celsius_to_hex(value: float) -> str:
    """摂氏温度を dsiot の16進表現に変換する (_hex_to_celsius の逆変換)。"""
    return format(int(round(value * 2)), "02X")
