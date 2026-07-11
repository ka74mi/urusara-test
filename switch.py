"""Daikin うるさら switch エンティティ。

うるさら特有機能 (加湿モードへの切替・換気ON/OFF・節電) を climate エンティティの
外に切り出して実装する (設計方針 B)。

しつどのON/OFF・レベル調整は select.py の統一しつど select
(DaikinHumiditySelect) に一本化されている。この switch.py の
DaikinHumidifySwitch は「climate の HVACMode にない加湿モードへ
切り替えるかどうか」のみを担当し、加湿モード中のしつどレベル調整は
統一 select 側が担う (役割分担)。
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
    HUMIDITY_ONOFF_PARAM,
    MODE_HUMIDIFY,
    ONOFF_OFF,
    ONOFF_ON,
    POWER_SAVING_PARAM,
    VENTILATION_ONOFF_PARAM,
)
from .coordinator import DaikinCoordinator
from .entity import DaikinEntity

_LOGGER = logging.getLogger(__name__)

# 加湿モードのしつどON/OFFパラメータ (e_3001/p_33)
HUMIDIFY_ONOFF_PARAM = HUMIDITY_ONOFF_PARAM[MODE_HUMIDIFY]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """switch プラットフォームのセットアップ。"""
    coordinator: DaikinCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DaikinHumidifySwitch(coordinator),
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


class DaikinHumidifySwitch(_DaikinModeParamSwitch):
    """加湿モードへの切替スイッチ。

    加湿は climate の HVACMode に存在しない独立運転モードのため、
    ON にする操作は「加湿モードへの切り替え」を意味する。
    加湿モード中のしつどレベル調整自体は select.py の統一しつど select
    (DaikinHumiditySelect) が担当する (このスイッチはモード切替のみ)。
    """

    _attr_translation_key = "humidify"
    _attr_icon = "mdi:water-percent"
    _param = HUMIDIFY_ONOFF_PARAM

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.current_mode == MODE_HUMIDIFY

    async def async_turn_on(self, **kwargs: Any) -> None:
        was_off = not self.coordinator.is_power_on
        # 加湿モードへ切り替える。しつどレベル自体は前回値を実機の記憶に委ねる
        # (モード切替時のパラメータ引き継ぎ方針と同様)。
        await self.coordinator.async_write_settings({"p_01": MODE_HUMIDIFY})
        if was_off:
            await self.coordinator.async_set_power(turn_on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        # 加湿モードを抜ける操作は実機データがなく未検証のため、ここでは
        # 何もしない (OFFにしたい場合は他モードへの切替 = climate 側の
        # hvac_mode 変更で行う想定)。
        _LOGGER.warning(
            "加湿モードを抜ける操作は未対応です。他の運転モードに切り替えてください。"
        )


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
