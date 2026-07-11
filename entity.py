"""共通ベースエンティティ。"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import DaikinCoordinator


class DaikinEntity(CoordinatorEntity[DaikinCoordinator]):
    """全プラットフォーム共通の DeviceInfo を提供するベースクラス。"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaikinCoordinator) -> None:
        super().__init__(coordinator)
        host = coordinator.entry.data[CONF_HOST]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Daikin エアコン",
            manufacturer="Daikin",
            model="うるさら (BRP084系)",
            configuration_url=f"http://{host}",
        )
