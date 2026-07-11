"""Daikin うるさら統合の DataUpdateCoordinator。"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DaikinApiClient, DaikinApiError
from .const import (
    CTRL_START,
    CTRL_STOP,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    NODE_INDOOR,
    NODE_MODE,
    NODE_POWER,
    NODE_SENSOR,
    POWER_OFF,
    POWER_ON,
    SENSOR_HUMIDITY_PARAM,
    SENSOR_TEMPERATURE_PARAM,
)

_LOGGER = logging.getLogger(__name__)


class DaikinCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """室内機/室外機の状態を定期取得し、エンティティへ配布する。

    書き込み系メソッド (async_write_settings / async_set_power) もここに集約し、
    「現在の運転状態・モードを補完してフルセットで送信する」という
    書き込みポリシーの実装責務を持つ。
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: DaikinApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_fetch_status()
        except DaikinApiError as err:
            raise UpdateFailed(f"状態取得に失敗しました: {err}") from err

    # --- 現在値の補完ヘルパー ---

    @property
    def current_mode(self) -> str | None:
        """e_3001/p_01 (現在の運転モード) の生値。"""
        return self.data.get(NODE_INDOOR, {}).get(NODE_MODE, {}).get("p_01")

    @property
    def is_power_on(self) -> bool:
        return self.data.get(NODE_INDOOR, {}).get(NODE_POWER, {}).get("p_01") == POWER_ON

    def get_mode_param(self, param: str) -> str | None:
        """e_3001 配下の任意パラメータの現在値を取得する。"""
        return self.data.get(NODE_INDOOR, {}).get(NODE_MODE, {}).get(param)

    def get_common_param(self, param: str) -> str | None:
        """e_3003 配下の任意パラメータの現在値を取得する。"""
        return self.data.get(NODE_INDOOR, {}).get("e_3003", {}).get(param)

    @property
    def current_temperature(self) -> float | None:
        """e_1002/e_A00B/p_01 (室内温度、実測値) を摂氏の数値として返す。

        daikin-brp084-protocol.md によれば実測値系は16進文字列ではなく
        数値がそのまま入ることがあるため、両方のケースに対応する。
        """
        raw = self.data.get(NODE_INDOOR, {}).get(NODE_SENSOR, {}).get(SENSOR_TEMPERATURE_PARAM)
        return _to_float(raw)

    @property
    def current_humidity(self) -> float | None:
        """e_1002/e_A00B/p_02 (室内湿度、実測値) を%の数値として返す。"""
        raw = self.data.get(NODE_INDOOR, {}).get(NODE_SENSOR, {}).get(SENSOR_HUMIDITY_PARAM)
        return _to_float(raw)

    # --- 書き込み ---

    async def async_write_settings(self, changes: dict[str, str]) -> None:
        """設定変更。運転状態・現在モードを自動補完し、フルセットで送信する。

        changes: 変更したい e_3001 配下のパラメータ差分 (例: {"p_09": "0300"})。
                 p_01 (モード) 自体を変更したい場合もここに含める。
        """
        current_mode = self.current_mode
        if current_mode is None:
            raise UpdateFailed("現在の運転モードが不明なため書き込みできません")

        e3001 = {"p_01": current_mode, **changes}
        a002 = {"p_01": POWER_ON if self.is_power_on else POWER_OFF}

        try:
            await self.api.async_write_settings(a002=a002, e3001=e3001)
        except DaikinApiError:
            _LOGGER.error("設定変更の書き込みに失敗しました: changes=%s", changes, exc_info=True)
            return
        await self.async_request_refresh()

    async def async_write_common_settings(self, changes: dict[str, str]) -> None:
        """e_3003 配下 (節電など) のパラメータを変更する。運転状態を自動補完する。

        changes: 例 {"p_71": "01"} (節電ON)。
        """
        a002 = {"p_01": POWER_ON if self.is_power_on else POWER_OFF}
        try:
            await self.api.async_write_settings(a002=a002, e3003_extra=changes)
        except DaikinApiError:
            _LOGGER.error("共通設定の書き込みに失敗しました: changes=%s", changes, exc_info=True)
            return
        await self.async_request_refresh()

    async def async_set_power(self, turn_on: bool) -> None:
        """電源 ON/OFF。制御内容フラグに開始/停止を指定する。"""
        a002 = {"p_01": POWER_ON if turn_on else POWER_OFF}
        ctrl_flag = CTRL_START if turn_on else CTRL_STOP

        try:
            await self.api.async_set_power(a002=a002, ctrl_flag=ctrl_flag)
        except DaikinApiError:
            _LOGGER.error("電源操作の書き込みに失敗しました: turn_on=%s", turn_on, exc_info=True)
            return
        await self.async_request_refresh()


def _to_float(raw: Any) -> float | None:
    """実測値パラメータを float に変換する。

    数値がそのまま入る場合と、16進文字列で入る場合の両方に対応する
    (daikin-brp084-protocol.md の実測値系パラメータの注記を参照)。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            pass
        try:
            return float(int(raw, 16))
        except ValueError:
            _LOGGER.debug("実測値のパースに失敗しました: raw=%s", raw)
            return None
    return None
