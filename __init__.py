"""Daikin うるさら (BRP084系) Home Assistant 統合。

最終目標は Home Assistant の HomeKit Bridge 連携を介した Apple Home 上での操作。
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DaikinApiClient
from .const import CONF_HOST, DOMAIN
from .coordinator import DaikinCoordinator

PLATFORMS: list[str] = ["climate", "switch", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry からの統合セットアップ。"""
    session = async_get_clientsession(hass)
    api = DaikinApiClient(entry.data[CONF_HOST], session)
    coordinator = DaikinCoordinator(hass, entry, api)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry のアンロード。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
