"""Daikin うるさら select エンティティ。

運転モード (全6モード)、うるさら特有機能 (換気の強さ・吸排気方向)、しつど設定を実装する。

運転モード select は climate が公開しない送風・除湿・加湿への切り替え口。
climate (HomeKit 公開用) は 冷房/暖房/自動 のみのため、それ以外はここで選ぶ。
しつどはスマホアプリのUIに合わせ、モード別に別エンティティへ分割せず、
現在の運転モードに応じて選択肢・現在値が動的に切り替わる単一エンティティ
(DaikinHumiditySelect) として実装する。
"""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AUTO_HUMIDITY_LABEL_TO_VALUE,
    AUTO_HUMIDITY_LABELS,
    AUTO_HUMIDITY_PARAM,
    DOMAIN,
    HUMIDITY_LEVEL_LABEL_TO_VALUE,
    HUMIDITY_LEVEL_LABELS,
    HUMIDITY_LEVEL_PARAM,
    HUMIDITY_ONOFF_CONTINUOUS,
    HUMIDITY_ONOFF_PARAM,
    HUMIDITY_SELECT_CONTINUOUS_LABEL,
    HUMIDITY_SELECT_HAS_OFF,
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_FAN_ONLY,
    MODE_HEAT,
    MODE_HUMIDIFY,
    ONOFF_OFF,
    ONOFF_ON,
    OPERATION_MODE_LABEL_TO_VALUE,
    OPERATION_MODE_LABELS,
    VENTILATION_DIRECTION_LABEL_TO_VALUE,
    VENTILATION_DIRECTION_LABELS,
    VENTILATION_DIRECTION_PARAM,
    VENTILATION_STRENGTH_LABEL_TO_VALUE,
    VENTILATION_STRENGTH_LABELS,
    VENTILATION_STRENGTH_PARAM,
)
from .coordinator import DaikinCoordinator
from .entity import DaikinEntity

_LOGGER = logging.getLogger(__name__)

HUMIDITY_LABEL_OFF = "off"

# しつど設定を持つモード (送風は非対応、自動は専用の4段階パラメータ)
HUMIDITY_ONOFF_LEVEL_MODES = {MODE_COOL, MODE_HEAT, MODE_DRY, MODE_HUMIDIFY}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """select プラットフォームのセットアップ。"""
    coordinator: DaikinCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DaikinOperationModeSelect(coordinator),
            DaikinVentilationStrengthSelect(coordinator),
            DaikinVentilationDirectionSelect(coordinator),
            DaikinHumiditySelect(coordinator),
        ]
    )


class _DaikinModeParamSelect(DaikinEntity, SelectEntity):
    """e_3001 配下のパラメータを操作する共通実装 (モード非依存パラメータ用)。"""

    _param: str
    _labels: dict[str, str]
    _label_to_value: dict[str, str]

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self._param}"
        self._attr_options = list(self._labels.values())

    @property
    def current_option(self) -> str | None:
        raw = self.coordinator.get_mode_param(self._param)
        if raw is None:
            return None
        return self._labels.get(raw)

    async def async_select_option(self, option: str) -> None:
        value = self._label_to_value.get(option)
        if value is None:
            _LOGGER.warning("不明な option です: %s", option)
            return
        await self.coordinator.async_write_settings({self._param: value})


class DaikinOperationModeSelect(DaikinEntity, SelectEntity):
    """運転モード (冷房/暖房/自動/送風/除湿/加湿)。

    運転の ON/OFF は変更しない (モードだけを切り替える)。停止中に選んだ場合は
    次に運転を開始したときにそのモードで動く。運転開始は climate 側で行う。
    """

    _attr_translation_key = "operation_mode"
    _attr_icon = "mdi:air-conditioner"

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_operation_mode"
        self._attr_options = list(OPERATION_MODE_LABELS.values())

    @property
    def current_option(self) -> str | None:
        return OPERATION_MODE_LABELS.get(self.coordinator.current_mode)

    async def async_select_option(self, option: str) -> None:
        value = OPERATION_MODE_LABEL_TO_VALUE.get(option)
        if value is None:
            _LOGGER.warning("不明な option です: %s", option)
            return
        await self.coordinator.async_write_settings({"p_01": value})


class DaikinVentilationStrengthSelect(_DaikinModeParamSelect):
    """換気の強さ (換気ON時のみ有効)。"""

    _attr_translation_key = "ventilation_strength"
    _attr_icon = "mdi:weather-windy"
    _param = VENTILATION_STRENGTH_PARAM
    _labels = VENTILATION_STRENGTH_LABELS
    _label_to_value = VENTILATION_STRENGTH_LABEL_TO_VALUE


class DaikinVentilationDirectionSelect(_DaikinModeParamSelect):
    """吸気/排気 (換気ON時のみ有効)。"""

    _attr_translation_key = "ventilation_direction"
    _attr_icon = "mdi:swap-horizontal"
    _param = VENTILATION_DIRECTION_PARAM
    _labels = VENTILATION_DIRECTION_LABELS
    _label_to_value = VENTILATION_DIRECTION_LABEL_TO_VALUE


class DaikinHumiditySelect(DaikinEntity, SelectEntity):
    """しつど設定 (現在の運転モードに応じて選択肢・現在値が動的に切り替わる)。

    スマホアプリのUIに合わせた単一エンティティ構成:
      自動  : OFF, 低め, 標準, 高め           (p_2F 4段階一体型)
      冷房  : OFF, 50%, 55%, 60%, 連続        (p_0C/p_0B)
      暖房  : OFF, 40%, 45%, 50%, 連続        (p_2D/p_2C, 親entityはe_3001)
      除湿  : 50%, 55%, 60%, 連続 (OFFなし)   (p_31/p_30)
      加湿  : 40%, 45%, 50%, 連続             (p_33/p_32)
      送風  : 非対応 (unavailable)             (しつどパラメータ自体が存在しない)

    冷房/暖房/除湿/加湿はON/OFFパラメータとレベルパラメータの2つを、
    1つの選択肢文字列 (例: "50", "連続", "off") に合成/分解して扱う。
    """

    _attr_translation_key = "humidity"
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_humidity"

    @property
    def available(self) -> bool:
        # 送風モードはしつどパラメータ自体が存在しないため非対応
        return super().available and self.coordinator.current_mode != MODE_FAN_ONLY

    @property
    def options(self) -> list[str]:
        mode = self.coordinator.current_mode
        if mode == MODE_AUTO:
            return list(AUTO_HUMIDITY_LABELS.values())
        if mode in HUMIDITY_ONOFF_LEVEL_MODES:
            return self._build_onoff_level_options(mode)
        # モード不明時・送風時はひとまず空リスト
        return []

    def _build_onoff_level_options(self, mode: str) -> list[str]:
        options: list[str] = []
        if HUMIDITY_SELECT_HAS_OFF.get(mode, True):
            options.append(HUMIDITY_LABEL_OFF)
        options.extend(HUMIDITY_LEVEL_LABELS[mode].values())
        options.append(HUMIDITY_SELECT_CONTINUOUS_LABEL)
        return options

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.current_mode
        if mode == MODE_AUTO:
            raw = self.coordinator.get_mode_param(AUTO_HUMIDITY_PARAM)
            if raw is None:
                return None
            return AUTO_HUMIDITY_LABELS.get(raw)

        if mode in HUMIDITY_ONOFF_LEVEL_MODES:
            return self._current_onoff_level_option(mode)

        return None

    def _current_onoff_level_option(self, mode: str) -> str | None:
        onoff_raw = self.coordinator.get_mode_param(HUMIDITY_ONOFF_PARAM[mode])
        if onoff_raw is None:
            return None
        if onoff_raw == ONOFF_OFF:
            return HUMIDITY_LABEL_OFF
        if onoff_raw == HUMIDITY_ONOFF_CONTINUOUS:
            return HUMIDITY_SELECT_CONTINUOUS_LABEL
        if onoff_raw == ONOFF_ON:
            level_raw = self.coordinator.get_mode_param(HUMIDITY_LEVEL_PARAM[mode])
            if level_raw is None:
                return None
            return HUMIDITY_LEVEL_LABELS[mode].get(level_raw)
        _LOGGER.debug("未知のしつどON/OFF値です: mode=%s, raw=%s", mode, onoff_raw)
        return None

    async def async_select_option(self, option: str) -> None:
        mode = self.coordinator.current_mode
        if mode == MODE_AUTO:
            await self._async_select_auto(option)
            return
        if mode in HUMIDITY_ONOFF_LEVEL_MODES:
            await self._async_select_onoff_level(mode, option)
            return
        _LOGGER.warning("現在のモードはしつど設定に対応していません: mode=%s", mode)

    async def _async_select_auto(self, option: str) -> None:
        value = AUTO_HUMIDITY_LABEL_TO_VALUE.get(option)
        if value is None:
            _LOGGER.warning("不明な option です: %s", option)
            return
        await self.coordinator.async_write_settings({AUTO_HUMIDITY_PARAM: value})

    async def _async_select_onoff_level(self, mode: str, option: str) -> None:
        onoff_param = HUMIDITY_ONOFF_PARAM[mode]

        if option == HUMIDITY_LABEL_OFF:
            await self.coordinator.async_write_settings({onoff_param: ONOFF_OFF})
            return

        if option == HUMIDITY_SELECT_CONTINUOUS_LABEL:
            # 連続運転はレベルパラメータを送らず、ON/OFF側のみ変更する
            # (現在の設計方針: モード切替と同様、実機側の記憶に委ねる)
            await self.coordinator.async_write_settings({onoff_param: HUMIDITY_ONOFF_CONTINUOUS})
            return

        level_value = HUMIDITY_LEVEL_LABEL_TO_VALUE[mode].get(option)
        if level_value is None:
            _LOGGER.warning("不明な option です: %s", option)
            return
        level_param = HUMIDITY_LEVEL_PARAM[mode]
        await self.coordinator.async_write_settings(
            {onoff_param: ONOFF_ON, level_param: level_value}
        )
