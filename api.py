"""Daikin BRP084 dsiot API クライアント。

実機は HTTP 平文・認証なしの LAN 内アクセスのみを前提とする
(daikin-brp084-protocol.md / handover-for-ha-implementation.md を参照)。
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    CTRL_CHANGE,
    ENDPOINT_INDOOR,
    ENDPOINT_MULTIREQ,
    ENDPOINT_OUTDOOR,
    NODE_COMMON,
    NODE_INDOOR,
    NODE_MODE,
    NODE_POWER,
    RSC_SUCCESS,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=10)


class DaikinApiError(Exception):
    """dsiot API 呼び出しに関するエラー。"""


def flatten(
    node: dict[str, Any],
    fr: str | None = None,
    path: tuple[str, ...] = (),
    out: dict[tuple[str, tuple[str, ...]], dict[str, Any]] | None = None,
) -> dict[tuple[str, tuple[str, ...]], dict[str, Any]]:
    """dsiot 応答の pch ツリーを再帰的に辿り、フラットな辞書に変換する。

    op2-response-structure.md の diff.py 由来の実装を踏襲。
    判定は pt ではなく pv キーの有無で行う。
    """
    if out is None:
        out = {}

    if isinstance(node, dict):
        pn = node.get("pn")
        new_path = path + (pn,) if pn is not None else path

        if "pv" in node:
            md = node.get("md") or {}
            out[(fr, new_path)] = {
                "pv": node.get("pv"),
                "mi": md.get("mi"),
                "mx": md.get("mx"),
            }

        children = node.get("pch")
        if isinstance(children, list):
            for child in children:
                flatten(child, fr=fr, path=new_path, out=out)

    return out


def to_nested(flat: dict[tuple[str, tuple[str, ...]], dict[str, Any]]) -> dict[str, Any]:
    """flatten() の結果を {e_1002: {e_3001: {p_09: pv}}} 形式に整形する。

    coordinator.data として保持する最終形。pv 以外 (mi/mx) は保持しない。
    """
    nested: dict[str, Any] = {}
    for (_fr, path), entry in flat.items():
        if not path:
            continue
        # ルートの "dgc_status" ノード名はスキップする
        segments = [p for p in path if p != "dgc_status"]
        if not segments:
            continue
        node = nested
        for key in segments[:-1]:
            node = node.setdefault(key, {})
        node[segments[-1]] = entry["pv"]
    return nested


class DaikinApiClient:
    """Daikin BRP084 実機との通信を担当するクライアント。

    dsiot のパラメータ意味論はここでは扱わず、HTTP 通信と
    ペイロードの組み立て/パースのみを責務とする。
    """

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._host = host
        self._session = session

    @property
    def _base_url(self) -> str:
        return f"http://{self._host}{ENDPOINT_MULTIREQ}"

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.post(
                self._base_url, json=payload, timeout=TIMEOUT
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DaikinApiError(f"通信エラー: {err}") from err
        except TimeoutError as err:
            raise DaikinApiError(f"タイムアウト: {err}") from err

    async def async_test_connection(self) -> bool:
        """Config Flow での初回接続確認用。室内機エンドポイントに op:2 を1回投げる。"""
        payload = {"requests": [{"op": 2, "to": ENDPOINT_INDOOR}]}
        data = await self._post(payload)
        responses = data.get("responses", [])
        if not responses:
            raise DaikinApiError("空のレスポンス")
        if responses[0].get("rsc") != RSC_SUCCESS:
            raise DaikinApiError(f"rsc={responses[0].get('rsc')}")
        return True

    async def async_fetch_status(self) -> dict[str, Any]:
        """室内機・室外機の状態を取得し、ネスト辞書 (coordinator.data 形式) を返す。"""
        payload = {
            "requests": [
                {"op": 2, "to": ENDPOINT_INDOOR},
                {"op": 2, "to": ENDPOINT_OUTDOOR},
            ]
        }
        data = await self._post(payload)
        responses = data.get("responses", [])

        flat: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        for resp in responses:
            fr = resp.get("fr")
            rsc = resp.get("rsc")
            if rsc != RSC_SUCCESS:
                raise DaikinApiError(f"読み取り失敗: fr={fr}, rsc={rsc}")
            pc = resp.get("pc")
            if pc is not None:
                flatten(pc, fr=fr, out=flat)

        return to_nested(flat)

    async def _async_write(self, requests: list[dict[str, Any]]) -> None:
        payload = {"requests": requests}
        data = await self._post(payload)
        for resp in data.get("responses", []):
            if resp.get("rsc") != RSC_SUCCESS:
                raise DaikinApiError(
                    f"書き込み失敗: fr={resp.get('fr')}, rsc={resp.get('rsc')}"
                )

    @staticmethod
    def _build_indoor_pch(
        a002: dict[str, str] | None,
        e3003: dict[str, str] | None,
        e3001: dict[str, str] | None,
    ) -> dict[str, Any]:
        pch: list[dict[str, Any]] = []
        if a002:
            pch.append(
                {
                    "pn": NODE_POWER,
                    "pch": [{"pn": k, "pv": v} for k, v in a002.items()],
                }
            )
        if e3003:
            pch.append(
                {
                    "pn": NODE_COMMON,
                    "pch": [{"pn": k, "pv": v} for k, v in e3003.items()],
                }
            )
        if e3001:
            pch.append(
                {
                    "pn": NODE_MODE,
                    "pch": [{"pn": k, "pv": v} for k, v in e3001.items()],
                }
            )
        return {
            "op": 3,
            "to": ENDPOINT_INDOOR,
            "pc": {
                "pn": "dgc_status",
                "pch": [{"pn": NODE_INDOOR, "pch": pch}],
            },
        }

    async def async_write_settings(
        self,
        a002: dict[str, str],
        e3001: dict[str, str] | None = None,
        e3003_extra: dict[str, str] | None = None,
    ) -> None:
        """設定変更 (制御内容フラグは常に '設定変更' = CTRL_CHANGE 固定)。

        呼び出し側 (coordinator) が運転状態・現在モードを含むフルセットの
        パラメータを組み立てて渡す想定。e3003_extra は節電設定 (p_71) など、
        e_3003 配下のパラメータを制御フラグと合わせて送る場合に使う。
        """
        e3003 = {"p_2D": CTRL_CHANGE}
        if e3003_extra:
            e3003.update(e3003_extra)
        request = self._build_indoor_pch(
            a002=a002,
            e3003=e3003,
            e3001=e3001,
        )
        await self._async_write([request])

    async def async_set_power(self, a002: dict[str, str], ctrl_flag: str) -> None:
        """電源 ON/OFF 操作。制御内容フラグに CTRL_START/CTRL_STOP を渡す。"""
        request = self._build_indoor_pch(
            a002=a002,
            e3003={"p_2D": ctrl_flag},
            e3001=None,
        )
        await self._async_write([request])
