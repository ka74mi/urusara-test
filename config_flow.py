"""Daikin うるさら統合の Config Flow。

IPv4 アドレス (固定IP前提) のみを入力させる最小構成。
初回接続確認として op:2 を1回投げて疎通を確認する。
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DaikinApiClient, DaikinApiError
from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class DaikinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Daikin うるさら統合の設定フロー。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            session = async_get_clientsession(self.hass)
            client = DaikinApiClient(host, session)

            try:
                await client.async_test_connection()
            except DaikinApiError:
                _LOGGER.error("接続確認に失敗しました: host=%s", host, exc_info=True)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"Daikin ({host})", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
