import asyncio
import unittest

from mybot.common.onebot_capabilities import (
    Capability,
    CapabilityStatus,
    CapabilityUnavailable,
    ConnectionStatus,
    ImplementationFamily,
    OneBotCapabilityRegistry,
    call_capability_api,
    probe_onebot_connection,
    register_onebot_capability_hooks,
)


class FakeAdapter:
    @staticmethod
    def get_name() -> str:
        return "OneBot V11"


class FakeBot:
    adapter = FakeAdapter()

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def call_api(self, action: str, **params):
        self.calls.append((action, params))
        response = self.responses[action]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response()
        if asyncio.iscoroutine(response):
            return await response
        return response


def version_info(app_name: str, app_version: str = "1.2.3") -> dict:
    return {
        "app_name": app_name,
        "app_version": app_version,
        "protocol_version": "v11",
    }


def healthy_status() -> dict:
    return {"online": True, "good": True, "stat": {"ignored": True}}


class UnsupportedActionError(RuntimeError):
    def __init__(self):
        super().__init__("action unavailable")
        self.info = {"retcode": 1404, "message": "unsupported action"}


class OneBotCapabilityProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_napcat_probe_is_readonly_and_registers_declared_capabilities(self):
        registry = OneBotCapabilityRegistry()
        bot = FakeBot(
            {
                "get_version_info": {"data": version_info("NapCat.Onebot", "4.8.95")},
                "get_status": {"data": healthy_status()},
            }
        )

        snapshot = await probe_onebot_connection(bot, registry=registry)

        self.assertEqual(
            [action for action, _ in bot.calls],
            ["get_version_info", "get_status"],
        )
        self.assertEqual(snapshot.connection_status, ConnectionStatus.CONNECTED)
        self.assertEqual(snapshot.implementation_family, ImplementationFamily.NAPCAT)
        self.assertEqual(snapshot.implementation_name, "NapCat.Onebot")
        self.assertEqual(snapshot.implementation_version, "4.8.95")
        for capability in Capability:
            self.assertEqual(
                snapshot.capability(capability).status,
                CapabilityStatus.SUPPORTED,
            )

    async def test_plain_onebot_marks_only_standard_capabilities_supported(self):
        registry = OneBotCapabilityRegistry()
        snapshot = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("OneBot V11"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )

        self.assertEqual(snapshot.implementation_family, ImplementationFamily.ONEBOT)
        self.assertEqual(
            snapshot.capability(Capability.PROFILE_LIKE).status,
            CapabilityStatus.SUPPORTED,
        )
        self.assertEqual(
            snapshot.capability(Capability.IMAGE_REFRESH).status,
            CapabilityStatus.SUPPORTED,
        )
        for capability in (
            Capability.GROUP_POKE,
            Capability.ESSENCE_MESSAGE,
            Capability.IMAGE_OCR,
        ):
            self.assertEqual(
                snapshot.capability(capability).status,
                CapabilityStatus.UNSUPPORTED,
            )

    async def test_unknown_implementation_does_not_infer_napcat_from_version(self):
        registry = OneBotCapabilityRegistry()
        snapshot = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("BridgeBox", "NapCat-compat"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )

        self.assertEqual(snapshot.implementation_family, ImplementationFamily.UNKNOWN)
        self.assertEqual(
            snapshot.capability(Capability.PROFILE_LIKE).status,
            CapabilityStatus.SUPPORTED,
        )
        self.assertEqual(
            snapshot.capability(Capability.IMAGE_REFRESH).status,
            CapabilityStatus.SUPPORTED,
        )
        for capability in (
            Capability.GROUP_POKE,
            Capability.ESSENCE_MESSAGE,
            Capability.IMAGE_OCR,
        ):
            self.assertEqual(
                snapshot.capability(capability).status,
                CapabilityStatus.UNKNOWN,
            )

    async def test_timeout_degrades_probe_without_disabling_standard_capabilities(self):
        async def delayed_version():
            await asyncio.sleep(0.05)
            return version_info("NapCat.Onebot")

        registry = OneBotCapabilityRegistry()
        snapshot = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": delayed_version,
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
            timeout=0.001,
        )

        self.assertTrue(snapshot.adapter_connected)
        self.assertEqual(snapshot.connection_status, ConnectionStatus.DEGRADED)
        self.assertEqual(snapshot.probe_issue, "timeout")
        self.assertEqual(
            snapshot.capability(Capability.PROFILE_LIKE).status,
            CapabilityStatus.SUPPORTED,
        )
        self.assertEqual(
            snapshot.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.UNKNOWN,
        )

    async def test_malformed_responses_degrade_without_raising(self):
        registry = OneBotCapabilityRegistry()
        snapshot = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": ["not", "a", "mapping"],
                    "get_status": {"online": "yes", "good": True},
                }
            ),
            registry=registry,
        )

        self.assertEqual(snapshot.connection_status, ConnectionStatus.DEGRADED)
        self.assertEqual(snapshot.probe_issue, "invalid_response")
        self.assertIsNone(snapshot.implementation_name)

    async def test_sensitive_implementation_name_is_not_recorded(self):
        registry = OneBotCapabilityRegistry()
        snapshot = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("access-token-value"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )

        self.assertEqual(snapshot.connection_status, ConnectionStatus.DEGRADED)
        self.assertEqual(snapshot.probe_issue, "invalid_response")
        self.assertIsNone(snapshot.implementation_name)

    async def test_disconnect_and_reconnect_replace_stale_capabilities(self):
        registry = OneBotCapabilityRegistry()
        await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("NapCat.Onebot"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )

        disconnected = registry.mark_disconnected()
        self.assertEqual(disconnected.connection_status, ConnectionStatus.DISCONNECTED)
        self.assertEqual(
            disconnected.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.DEGRADED,
        )

        reconnected = await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("OneBot V11", "11.0"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )
        self.assertEqual(reconnected.connection_status, ConnectionStatus.CONNECTED)
        self.assertEqual(reconnected.implementation_family, ImplementationFamily.ONEBOT)
        self.assertEqual(
            reconnected.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.UNSUPPORTED,
        )


class OneBotBusinessCapabilityTest(unittest.IsolatedAsyncioTestCase):
    async def _unknown_registry(self) -> OneBotCapabilityRegistry:
        registry = OneBotCapabilityRegistry()
        await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("BridgeBox"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )
        return registry

    async def test_real_success_updates_only_called_capability(self):
        registry = await self._unknown_registry()
        bot = FakeBot({"ocr_image": {"texts": []}})

        result = await call_capability_api(
            bot,
            Capability.IMAGE_OCR,
            "ocr_image",
            registry=registry,
            image="opaque-image-reference",
        )

        self.assertEqual(result, {"texts": []})
        snapshot = registry.snapshot()
        self.assertEqual(
            snapshot.capability(Capability.IMAGE_OCR).status,
            CapabilityStatus.SUPPORTED,
        )
        self.assertEqual(
            snapshot.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.UNKNOWN,
        )

    async def test_unsupported_result_only_disables_corresponding_extension(self):
        registry = await self._unknown_registry()
        bot = FakeBot({"group_poke": UnsupportedActionError()})

        with self.assertRaises(UnsupportedActionError):
            await call_capability_api(
                bot,
                Capability.GROUP_POKE,
                "group_poke",
                registry=registry,
                group_id="opaque",
                user_id="opaque",
            )

        snapshot = registry.snapshot()
        self.assertEqual(
            snapshot.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.UNSUPPORTED,
        )
        self.assertEqual(
            snapshot.capability(Capability.IMAGE_OCR).status,
            CapabilityStatus.UNKNOWN,
        )

    async def test_transient_failure_marks_only_one_capability_degraded(self):
        registry = await self._unknown_registry()
        bot = FakeBot({"set_essence_msg": TimeoutError("temporary timeout")})

        with self.assertRaises(TimeoutError):
            await call_capability_api(
                bot,
                Capability.ESSENCE_MESSAGE,
                "set_essence_msg",
                registry=registry,
                message_id="opaque",
            )

        snapshot = registry.snapshot()
        self.assertEqual(
            snapshot.capability(Capability.ESSENCE_MESSAGE).status,
            CapabilityStatus.DEGRADED,
        )
        self.assertEqual(
            snapshot.capability(Capability.GROUP_POKE).status,
            CapabilityStatus.UNKNOWN,
        )

    async def test_declared_unsupported_capability_is_not_called(self):
        registry = OneBotCapabilityRegistry()
        await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("OneBot V11"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )
        bot = FakeBot({"group_poke": None})

        with self.assertRaises(CapabilityUnavailable):
            await call_capability_api(
                bot,
                Capability.GROUP_POKE,
                "group_poke",
                registry=registry,
            )
        self.assertEqual(bot.calls, [])

    async def test_stale_business_result_does_not_overwrite_reconnected_state(self):
        registry = await self._unknown_registry()
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed_success():
            started.set()
            await release.wait()
            return None

        stale_bot = FakeBot({"group_poke": delayed_success})
        stale_call = asyncio.create_task(
            call_capability_api(
                stale_bot,
                Capability.GROUP_POKE,
                "group_poke",
                registry=registry,
            )
        )
        await started.wait()

        await probe_onebot_connection(
            FakeBot(
                {
                    "get_version_info": version_info("OneBot V11"),
                    "get_status": healthy_status(),
                }
            ),
            registry=registry,
        )
        release.set()
        await stale_call

        self.assertEqual(
            registry.snapshot().capability(Capability.GROUP_POKE).status,
            CapabilityStatus.UNSUPPORTED,
        )


class FakeDriver:
    def __init__(self):
        self.connect_hooks = []
        self.disconnect_hooks = []

    def on_bot_connect(self, callback):
        self.connect_hooks.append(callback)

    def on_bot_disconnect(self, callback):
        self.disconnect_hooks.append(callback)


class OneBotHookRegistrationTest(unittest.TestCase):
    def test_hooks_register_once(self):
        driver = FakeDriver()

        register_onebot_capability_hooks(driver)
        register_onebot_capability_hooks(driver)

        self.assertEqual(len(driver.connect_hooks), 1)
        self.assertEqual(len(driver.disconnect_hooks), 1)


if __name__ == "__main__":
    unittest.main()
