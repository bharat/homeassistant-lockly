"""Frontend registration for Lockly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import INTEGRATION_VERSION, JSMODULES, URL_BASE


class JSModuleRegistration:
    """Register Lockly frontend resources."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.lovelace = hass.data.get("lovelace")

    async def async_register(self) -> None:
        """Register static paths and Lovelace resources."""
        await self._async_register_path()
        if self.lovelace and self.lovelace.mode == "storage":
            await self._async_wait_for_lovelace_resources()

    async def _async_register_path(self) -> None:
        """Register the static HTTP path for frontend assets."""
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, Path(__file__).parent, False)]
            )
        except RuntimeError:
            # Path already registered.
            return

    async def _async_wait_for_lovelace_resources(self) -> None:
        """Wait for Lovelace resources to load before registering."""

        async def _check_loaded(_now: Any) -> None:
            if self.lovelace.resources.loaded:
                await self._async_register_modules()
            else:
                async_call_later(self.hass, 5, _check_loaded)

        await _check_loaded(0)

    async def _async_register_modules(self) -> None:
        """Register or update Lovelace resources."""
        existing = list(self.lovelace.resources.async_items())
        legacy_resources = [
            item
            for item in existing
            if item["url"].startswith("/local/lockly-card/lockly-card.js")
        ]
        for resource in legacy_resources:
            await self.lovelace.resources.async_delete_item(resource["id"])
        existing = [item for item in existing if item["url"].startswith(URL_BASE)]
        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}"
            registered = False
            for resource in existing:
                if self._get_path(resource["url"]) == url:
                    registered = True
                    if self._get_version(resource["url"]) != module["version"]:
                        await self.lovelace.resources.async_update_item(
                            resource["id"],
                            {
                                "res_type": "module",
                                "url": f"{url}?v={module['version']}",
                            },
                        )
                    break
            if not registered:
                await self.lovelace.resources.async_create_item(
                    {"res_type": "module", "url": f"{url}?v={module['version']}"}
                )

    def _get_path(self, url: str) -> str:
        """Extract path without query params."""
        return url.split("?")[0]

    def _get_version(self, url: str) -> str:
        """Extract version from the query params."""
        parts = url.split("?")
        if len(parts) > 1 and parts[1].startswith("v="):
            return parts[1].replace("v=", "")
        return "0"
