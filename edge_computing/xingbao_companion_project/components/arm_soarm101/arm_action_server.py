#!/usr/bin/env python3
"""Expose a fail-closed ``stay_still``/``nod`` board arm service.

The verified board driver remains in the existing SO-101 module.  This r5
adapter deliberately contains no joint positions, timing sequences, PWM,
GPIO, or raw serial operations.  The previously verified nod preset exceeded
the physical safe range on this board, so nod stays disabled until the
hardware team supplies a replacement high-level preset.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


LEGACY_SERVER_PATH = Path(
    os.getenv(
        "XINGBAO_VERIFIED_ARM_SERVER",
        "/home/fibo/xingbao_project/soarm101_module/arm_action_server.py",
    )
)
PUBLIC_ACTIONS = frozenset({"stay_still", "nod"})
NOD_HARDWARE_GROUP = "group_1"


def _feedback(
    action: str,
    request_id: str,
    *,
    implemented: bool,
    ok: bool = True,
    error: str | None = None,
    hardware_group: str = "",
) -> dict[str, Any]:
    hardware_feedback: dict[str, Any] = {
        "ok": ok,
        "implemented_by": "board_hardware_team",
        "arm_action": action,
        "implemented": implemented,
        "error": error,
    }
    if hardware_group:
        hardware_feedback["hardware_group"] = hardware_group
    return {
        "type": "command_result",
        "request_id": request_id,
        "ok": ok,
        "results": [],
        "hardware_feedback": hardware_feedback,
    }


def _load_verified_driver(path: Path = LEGACY_SERVER_PATH) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError(f"verified SO-101 service is missing: {path}")
    spec = importlib.util.spec_from_file_location("xingbao_verified_so101", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load verified SO-101 service: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArmActionServer:
    """Whitelist wrapper around the existing verified SO-101 nod driver."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8764) -> None:
        self.host = host
        self.port = int(port)
        self._driver_server: Any | None = None
        self._driver_stay_still: Callable[[str, str], dict[str, Any]] | None = None

    def execute_group(self, group_name: str) -> dict[str, Any]:
        """Delegate the one verified nod group without exposing it over TCP."""
        if group_name != NOD_HARDWARE_GROUP:
            return {"ok": False, "implemented": False, "error": "unsafe_group"}
        if self._driver_server is None:
            raise RuntimeError("SO-101 driver is not initialized")
        result = self._driver_server.execute_group(NOD_HARDWARE_GROUP)
        return dict(result) if isinstance(result, dict) else {
            "ok": False,
            "implemented": False,
            "error": "invalid_driver_result",
        }

    def handle_action_sync(self, action_name: str, request_id: str = "") -> dict[str, Any]:
        """Accept only public product actions before touching the driver."""
        action = str(action_name or "").strip()
        if action not in PUBLIC_ACTIONS:
            return _feedback(
                "stay_still",
                request_id,
                implemented=False,
                error=f"unknown_action: {action}",
            )
        if action == "stay_still":
            return _feedback("stay_still", request_id, implemented=True)

        # Do not scale or trial-and-error the legacy joint endpoints here.
        # A nod can only be re-enabled by replacing this guard with a newly
        # verified high-level hardware preset.
        return _feedback(
            "stay_still",
            request_id,
            ok=False,
            implemented=False,
            error="unsafe_nod_disabled",
        )

    async def run(self) -> None:
        """Serve the safe handler without initializing or opening the robot."""
        module = _load_verified_driver()
        driver = module.ArmActionServer(host=self.host, port=self.port)
        self._driver_server = driver
        driver.handle_action_sync = self.handle_action_sync
        server = await asyncio.start_server(
            driver.handle_client,
            self.host,
            self.port,
            reuse_address=True,
        )
        async with server:
            await server.serve_forever()

    def shutdown(self) -> None:
        if self._driver_server is not None:
            self._driver_server.shutdown()


def main() -> None:
    server = ArmActionServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
