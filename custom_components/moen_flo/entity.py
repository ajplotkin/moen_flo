"""Base entity for Moen Flo (SSO)."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import MoenFloCoordinator


class MoenFloEntity(CoordinatorEntity[MoenFloCoordinator]):
    """Common device info + availability for Flo entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MoenFloCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        static = coordinator.data.get("static", {}) if coordinator.data else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=static.get("nickname", "Flo"),
            manufacturer=MANUFACTURER,
            model=static.get("deviceModel"),
            serial_number=static.get("serialNumber"),
            sw_version=static.get("fwVersion"),
        )

    @property
    def _device(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("device", {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._device.get("isConnected", True))
