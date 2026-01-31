"""Config flow for Lockly."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENDPOINT,
    CONF_FIRST_SLOT,
    CONF_LAST_SLOT,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_FIRST_SLOT,
    DEFAULT_LAST_SLOT,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
)


class LocklyFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Lockly."""

    VERSION = 2

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            first_slot = user_input[CONF_FIRST_SLOT]
            last_slot = user_input[CONF_LAST_SLOT]
            if first_slot > last_slot:
                errors["base"] = "invalid_slot_range"
            else:
                data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_FIRST_SLOT: first_slot,
                    CONF_LAST_SLOT: last_slot,
                    CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC],
                    CONF_ENDPOINT: user_input[CONF_ENDPOINT],
                }
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default="Lockly Configuration"
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(
                        CONF_FIRST_SLOT,
                        default=DEFAULT_FIRST_SLOT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=100, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_LAST_SLOT,
                        default=DEFAULT_LAST_SLOT,
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
        self._current = entry.options or entry.data

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            name = user_input.get(CONF_NAME, self._entry.title)
            if name and name != self._entry.title:
                self.hass.config_entries.async_update_entry(self._entry, title=name)
            first_slot = user_input[CONF_FIRST_SLOT]
            last_slot = user_input[CONF_LAST_SLOT]
            if first_slot > last_slot:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._build_schema(),
                    errors={"base": "invalid_slot_range"},
                )
            return self.async_create_entry(
                title="",
                data={
                    CONF_FIRST_SLOT: first_slot,
                    CONF_LAST_SLOT: last_slot,
                    CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC],
                    CONF_ENDPOINT: user_input[CONF_ENDPOINT],
                },
            )

        current = self._entry.options or self._entry.data
        self._current = current
        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(),
            errors={},
            description_placeholders={"entry_id": self._entry.entry_id},
        )

    def _build_schema(self) -> vol.Schema:
        current = self._current
        first_slot = current.get(CONF_FIRST_SLOT, DEFAULT_FIRST_SLOT)
        last_slot = current.get(
            CONF_LAST_SLOT, current.get(CONF_MAX_SLOTS, DEFAULT_LAST_SLOT)
        )
        return vol.Schema(
            {
                vol.Optional(CONF_NAME, default=self._entry.title): (
                    selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    )
                ),
                vol.Required(
                    CONF_FIRST_SLOT,
                    default=first_slot,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=100, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_LAST_SLOT,
                    default=last_slot,
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
        )
