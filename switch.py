"""Daikin うるさら switch エンティティ。

うるさら特有機能 (換気ON/OFF・節電) を climate エンティティの外に切り出して実装する。

しつどのON/OFF・レベル調整は select.py の統一しつど select
(DaikinHumiditySelect) に、加湿を含む運転モードの切り替えは
運転モード select (DaikinOperationModeSelect) に一本化されている。
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ONOFF_OFF,
    ONOFF_ON,
    POWER_SAVING_PARAM,
    VENTILATION_ONOFF_PARAM,
)
from .coordinator import DaikinCoordinator
from .entity import DaikinEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """switch プラットフォームのセットアップ。"""
    coordinator: DaikinCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DaikinVentilationSwitch(coordinator),
            DaikinPowerSavingSwitch(coordinator),
        ]
    )


class _DaikinModeParamSwitch(DaikinEntity, SwitchEntity):
    """e_3001 配下の ON/OFF パラメータを操作する共通実装。"""

    _param: str

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self._param}"

    @property
    def is_on(self) -> bool | None:
        raw = self.coordinator.get_mode_param(self._param)
        if raw is None:
            return None
        return raw == ONOFF_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_settings({self._param: ONOFF_ON})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_settings({self._param: ONOFF_OFF})


class DaikinVentilationSwitch(_DaikinModeParamSwitch):
    """換気 ON/OFF (マスタースイッチ)。他運転モードと併用可能。"""

    _attr_translation_key = "ventilation"
    _attr_icon = "mdi:air-filter"
    _param = VENTILATION_ONOFF_PARAM


class DaikinPowerSavingSwitch(DaikinEntity, SwitchEntity):
    """節電設定 ON/OFF (e_3003 配下、運転中のみ有効)。"""

    _attr_translation_key = "power_saving"
    _attr_icon = "mdi:leaf"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{POWER_SAVING_PARAM}"

    @property
    def is_on(self) -> bool | None:
        raw = self.coordinator.get_common_param(POWER_SAVING_PARAM)
        if raw is None:
            return None
        return raw == ONOFF_ON

    @property
    def available(self) -> bool:
        # メモ記載の通り、運転OFF中はアプリ側でグレーアウトする項目のため、
        # 実機の挙動に合わせて運転中のみ利用可能として扱う。
        return super().available and self.coordinator.is_power_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_common_settings({POWER_SAVING_PARAM: ONOFF_ON})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_common_settings({POWER_SAVING_PARAM: ONOFF_OFF})
