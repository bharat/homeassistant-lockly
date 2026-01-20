"""Config flow for Lockly."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENDPOINT,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
)


class LocklyFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Lockly."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_MAX_SLOTS: user_input[CONF_MAX_SLOTS],
                CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC],
                CONF_ENDPOINT: user_input[CONF_ENDPOINT],
            }
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Lockly"): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(
                        CONF_MAX_SLOTS,
                        default=DEFAULT_MAX_SLOTS,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=100, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_MQTT_TOPIC,
                        default=DEFAULT_MQTT_TOPIC,
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(
                        CONF_ENDPOINT,
                        default=DEFAULT_ENDPOINT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=255, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                },
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return LocklyOptionsFlowHandler(config_entry)


class LocklyOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for Lockly."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Initialize Lockly options flow."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_MAX_SLOTS: user_input[CONF_MAX_SLOTS],
                    CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC],
                    CONF_ENDPOINT: user_input[CONF_ENDPOINT],
                },
            )

        current = self._entry.options or self._entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MAX_SLOTS,
                        default=current.get(CONF_MAX_SLOTS, DEFAULT_MAX_SLOTS),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=100, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_MQTT_TOPIC,
                        default=current.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(
                        CONF_ENDPOINT,
                        default=current.get(CONF_ENDPOINT, DEFAULT_ENDPOINT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=255, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                },
            ),
            errors={},
        )
