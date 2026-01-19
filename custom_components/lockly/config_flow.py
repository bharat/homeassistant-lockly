"""Config flow for Lockly."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify

from .const import (
    CONF_ENDPOINT,
    CONF_LOCK_ENTITIES,
    CONF_LOCK_GROUP_ENTITY,
    CONF_LOCK_GROUP_NAME,
    CONF_MAX_SLOTS,
    CONF_MQTT_TOPIC,
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_SLOTS,
    DEFAULT_MQTT_TOPIC,
    DOMAIN,
    LOGGER,
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
            group_name = user_input[CONF_LOCK_GROUP_NAME]
            lock_entities = user_input[CONF_LOCK_ENTITIES]
            group_object_id = slugify(group_name)
            group_entity_id = f"group.{group_object_id}"
            if not await async_setup_component(self.hass, "group", {}):
                errors["base"] = "group_setup_failed"
            else:
                try:
                    service_data = {
                        "entities": lock_entities,
                        "name": group_name,
                    }
                    if self.hass.states.get(group_entity_id):
                        service_data["entity_id"] = group_entity_id
                    else:
                        service_data["object_id"] = group_object_id
                    await self.hass.services.async_call(
                        "group",
                        "set",
                        service_data,
                        blocking=True,
                    )
                except Exception as err:  # noqa: BLE001
                    LOGGER.exception("Failed to create lock group: %s", err)
                    errors["base"] = "group_create_failed"

            if errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                CONF_NAME, default=user_input.get(CONF_NAME, "Lockly")
                            ): selector.TextSelector(
                                selector.TextSelectorConfig(
                                    type=selector.TextSelectorType.TEXT
                                )
                            ),
                            vol.Required(
                                CONF_LOCK_GROUP_NAME,
                                default=user_input.get(
                                    CONF_LOCK_GROUP_NAME, "Lockly Locks"
                                ),
                            ): selector.TextSelector(
                                selector.TextSelectorConfig(
                                    type=selector.TextSelectorType.TEXT
                                )
                            ),
                            vol.Required(
                                CONF_LOCK_ENTITIES,
                                default=user_input.get(CONF_LOCK_ENTITIES, []),
                            ): selector.EntitySelector(
                                selector.EntitySelectorConfig(
                                    domain="lock", multiple=True
                                )
                            ),
                            vol.Required(
                                CONF_MAX_SLOTS,
                                default=user_input.get(
                                    CONF_MAX_SLOTS, DEFAULT_MAX_SLOTS
                                ),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=1, max=100, mode=selector.NumberSelectorMode.BOX
                                )
                            ),
                            vol.Required(
                                CONF_MQTT_TOPIC,
                                default=user_input.get(
                                    CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC
                                ),
                            ): selector.TextSelector(
                                selector.TextSelectorConfig(
                                    type=selector.TextSelectorType.TEXT
                                )
                            ),
                            vol.Required(
                                CONF_ENDPOINT,
                                default=user_input.get(CONF_ENDPOINT, DEFAULT_ENDPOINT),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=1, max=255, mode=selector.NumberSelectorMode.BOX
                                )
                            ),
                        },
                    ),
                    errors=errors,
                )
            data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_LOCK_GROUP_NAME: group_name,
                CONF_LOCK_GROUP_ENTITY: group_entity_id,
                CONF_LOCK_ENTITIES: lock_entities,
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
                        CONF_LOCK_GROUP_NAME,
                        default="Lockly Locks",
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_LOCK_ENTITIES): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="lock", multiple=True)
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
        errors: dict[str, str] = {}
        if user_input is not None:
            group_entity_id = (self._entry.data or {}).get(CONF_LOCK_GROUP_ENTITY)
            lock_entities = user_input[CONF_LOCK_ENTITIES]
            if group_entity_id:
                if not await async_setup_component(self.hass, "group", {}):
                    errors["base"] = "group_setup_failed"
                else:
                    try:
                        await self.hass.services.async_call(
                            "group",
                            "set",
                            {
                                "entity_id": group_entity_id,
                                "entities": lock_entities,
                            },
                            blocking=True,
                        )
                    except Exception as err:  # noqa: BLE001
                        LOGGER.exception("Failed to update lock group: %s", err)
                        errors["base"] = "group_update_failed"
                if errors:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=vol.Schema(
                            {
                                vol.Required(
                                    CONF_LOCK_ENTITIES,
                                    default=lock_entities,
                                ): selector.EntitySelector(
                                    selector.EntitySelectorConfig(
                                        domain="lock", multiple=True
                                    )
                                ),
                                vol.Required(
                                    CONF_MAX_SLOTS,
                                    default=user_input.get(
                                        CONF_MAX_SLOTS, DEFAULT_MAX_SLOTS
                                    ),
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=1,
                                        max=100,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                                vol.Required(
                                    CONF_MQTT_TOPIC,
                                    default=user_input.get(
                                        CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC
                                    ),
                                ): selector.TextSelector(
                                    selector.TextSelectorConfig(
                                        type=selector.TextSelectorType.TEXT
                                    )
                                ),
                                vol.Required(
                                    CONF_ENDPOINT,
                                    default=user_input.get(
                                        CONF_ENDPOINT, DEFAULT_ENDPOINT
                                    ),
                                ): selector.NumberSelector(
                                    selector.NumberSelectorConfig(
                                        min=1,
                                        max=255,
                                        mode=selector.NumberSelectorMode.BOX,
                                    )
                                ),
                            },
                        ),
                        errors=errors,
                    )
            return self.async_create_entry(
                title="",
                data={
                    CONF_LOCK_ENTITIES: lock_entities,
                    CONF_MAX_SLOTS: user_input[CONF_MAX_SLOTS],
                    CONF_MQTT_TOPIC: user_input[CONF_MQTT_TOPIC],
                    CONF_ENDPOINT: user_input[CONF_ENDPOINT],
                },
            )

        current = self._entry.options or self._entry.data
        group_entity_id = current.get(CONF_LOCK_GROUP_ENTITY)
        group_entities = []
        if group_entity_id:
            group_state = self.hass.states.get(group_entity_id)
            if group_state:
                group_entities = group_state.attributes.get("entity_id", [])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCK_ENTITIES,
                        default=group_entities,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="lock", multiple=True)
                    ),
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
            errors=errors,
        )
