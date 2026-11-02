from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

import mybot.bot  # noqa: F401
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment

from mybot.common.config import get_image_library_settings
from mybot.common.feature_flags import DEFAULT_FEATURE_ENABLED
from mybot.common.image_library import (
    ImageDownloadError,
    ImageNotFoundError,
    ImagePermissionError,
    ImageQuotaError,
    InvalidImageError,
    _validate_remote_url,
    add_image_tags,
    delete_image,
    get_library_stats,
    list_images,
    normalize_tags,
    read_image_bytes,
    remove_image_tags,
    search_images,
    store_image,
)
from mybot.common.onebot_capabilities import (
    Capability,
    CapabilityStatus,
    ImplementationFamily,
    ImplementationInfo,
    onebot_capability_registry,
)
from mybot.plugins.image_library import (
    _consume_image_rate,
    _extract_image_segments,
    _extract_ocr_text,
    _parse_tag_edit_args,
    _read_ocr,
    _render_image_library_help,
    _image_rate_records,
    _refresh_image_data,
    _resolve_source_image,
)


PNG_ONE = b"\x89PNG\r\n\x1a\n" + b"test-image-one"
PNG_TWO = b"\x89PNG\r\n\x1a\n" + b"test-image-two"


def _group_event(message) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate(
        {
            "time": 0,
            "self_id": 99999,
            "post_type": "message",
            "sub_type": "normal",
            "user_id": 10001,
            "message_type": "group",
            "message_id": 88001,
            "message": message,
            "original_message": message,
            "raw_message": "",
            "font": 0,
            "group_id": 20001,
            "sender": {"user_id": 10001, "nickname": "tester", "role": "member"},
        }
    )


def _store(
    root: Path,
    group_id: str,
    content: bytes,
    *,
    tags: str,
    saved_by: str = "10001",
    source_user_id: str = "10002",
    ocr_text: str = "",
    max_group_images: int = 10,
    max_group_bytes: int = 1024,
):
    return store_image(
        group_id,
        content,
        tags=tags,
        saved_by=saved_by,
        source_user_id=source_user_id,
        source_message_id="90001",
        ocr_text=ocr_text,
        max_file_bytes=1024,
        max_group_bytes=max_group_bytes,
        max_group_images=max_group_images,
        root=root,
    )


class ImageLibraryStoreTest(unittest.TestCase):
    def test_feature_is_opt_in_and_image_rate_is_group_scoped(self):
        self.assertFalse(DEFAULT_FEATURE_ENABLED["image_library"])
        _image_rate_records.clear()
        for offset in range(2):
            self.assertEqual(
                _consume_image_rate("20001", "10001", "send", 2, now=float(offset)),
                0,
            )
        self.assertGreater(
            _consume_image_rate("20001", "10001", "send", 2, now=2.0),
            0,
        )
        self.assertEqual(
            _consume_image_rate("20002", "10001", "send", 2, now=2.0),
            0,
        )

    def test_settings_use_safe_defaults_and_bounded_overrides(self):
        with patch.dict(
            "os.environ",
            {
                "IMAGE_LIBRARY_OCR_ENABLED": "true",
                "IMAGE_LIBRARY_MAX_FILE_MB": "12",
                "IMAGE_LIBRARY_MAX_GROUP_MB": "640",
                "IMAGE_LIBRARY_MAX_GROUP_IMAGES": "700",
            },
            clear=False,
        ):
            settings = get_image_library_settings()
        self.assertTrue(settings.ocr_enabled)
        self.assertEqual(settings.max_file_bytes, 12 * 1024 * 1024)
        self.assertEqual(settings.max_group_bytes, 640 * 1024 * 1024)
        self.assertEqual(settings.max_group_images, 700)

        with patch.dict(
            "os.environ",
            {
                "IMAGE_LIBRARY_MAX_FILE_MB": "0",
                "IMAGE_LIBRARY_MAX_GROUP_MB": "999999",
                "IMAGE_LIBRARY_MAX_GROUP_IMAGES": "invalid",
            },
            clear=False,
        ):
            defaults = get_image_library_settings()
        self.assertEqual(defaults.max_file_bytes, 10 * 1024 * 1024)
        self.assertEqual(defaults.max_group_bytes, 512 * 1024 * 1024)
        self.assertEqual(defaults.max_group_images, 500)

    def test_tags_are_normalized_deduplicated_and_bounded(self):
        self.assertEqual(normalize_tags("#猫猫， 开心 猫猫"), ["猫猫", "开心"])
        with self.assertRaisesRegex(ValueError, "too_many_image_tags"):
            normalize_tags("一 二 三 四 五 六 七 八 九")

    def test_store_deduplicates_within_group_and_isolates_groups(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            created = _store(root, "20001", PNG_ONE, tags="猫猫 开心")
            duplicate = _store(root, "20001", PNG_ONE, tags="别的标签")
            other_group = _store(root, "20002", PNG_ONE, tags="别群")

            self.assertEqual(created.status, "created")
            self.assertEqual(duplicate.status, "duplicate")
            self.assertEqual(duplicate.record["tags"], ["猫猫", "开心"])
            self.assertEqual(other_group.status, "created")
            self.assertEqual(len(list_images("20001", root=root)), 1)
            self.assertEqual(len(list_images("20002", root=root)), 1)
            self.assertNotEqual(
                root / "20001" / "index.json",
                root / "20002" / "index.json",
            )

    def test_existing_image_tags_can_be_added_and_removed(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _store(root, "20001", PNG_ONE, tags="猫猫 开心").record

            updated = add_image_tags(
                "20001",
                record["id"],
                "夜景 猫猫",
                root=root,
            )
            self.assertEqual(updated["tags"], ["猫猫", "开心", "夜景"])
            self.assertEqual(
                [item["id"] for item in search_images("20001", "夜景", root=root)],
                [record["id"]],
            )

            updated = remove_image_tags(
                "20001",
                record["id"],
                "猫猫 不存在",
                root=root,
            )
            self.assertEqual(updated["tags"], ["开心", "夜景"])
            self.assertEqual(search_images("20001", "猫猫", root=root), [])

    def test_tag_edits_are_group_scoped_and_keep_tag_limit(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _store(
                root,
                "20001",
                PNG_ONE,
                tags="一 二 三 四 五 六 七 八",
            ).record
            _store(root, "20002", PNG_TWO, tags="别群")

            with self.assertRaises(ImageNotFoundError):
                add_image_tags("20002", record["id"] + 1, "越界", root=root)
            with self.assertRaisesRegex(ValueError, "too_many_image_tags"):
                add_image_tags("20001", record["id"], "九", root=root)

            remove_image_tags("20001", record["id"], "一 二 三 四 五 六 七 八", root=root)
            self.assertEqual(list_images("20001", root=root)[0]["tags"], [])
            self.assertEqual(list_images("20002", root=root)[0]["tags"], ["别群"])

    def test_exact_tags_rank_above_ocr_and_all_terms_are_required(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            exact = _store(root, "20001", PNG_ONE, tags="月亮 猫猫")
            _store(
                root,
                "20001",
                PNG_TWO,
                tags="截图",
                ocr_text="月亮下面有一只猫猫",
            )

            matches = search_images("20001", "月亮 猫猫", root=root)

            self.assertEqual([record["id"] for record in matches], [exact.record["id"], 2])
            self.assertEqual(search_images("20001", "月亮 狗狗", root=root), [])

    def test_quota_is_checked_after_duplicate_detection(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            _store(root, "20001", PNG_ONE, tags="一", max_group_images=1)
            duplicate = _store(root, "20001", PNG_ONE, tags="一", max_group_images=1)
            self.assertEqual(duplicate.status, "duplicate")
            with self.assertRaises(ImageQuotaError):
                _store(root, "20001", PNG_TWO, tags="二", max_group_images=1)

    def test_delete_allows_collector_source_sender_or_moderator(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _store(root, "20001", PNG_ONE, tags="猫").record
            with self.assertRaises(ImagePermissionError):
                delete_image("20001", record["id"], actor_id="10003", root=root)

            deleted = delete_image("20001", record["id"], actor_id="10002", root=root)
            self.assertEqual(deleted["id"], record["id"])
            self.assertEqual(list_images("20001", root=root), [])
            with self.assertRaises(ImageNotFoundError):
                delete_image("20001", record["id"], actor_id="10001", root=root)

            moderator_record = _store(root, "20001", PNG_TWO, tags="二").record
            delete_image(
                "20001",
                moderator_record["id"],
                actor_id="10003",
                allow_any=True,
                root=root,
            )

    def test_read_verifies_digest_and_stats(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            record = _store(root, "20001", PNG_ONE, tags="猫 猫").record
            self.assertEqual(
                read_image_bytes("20001", record, max_file_bytes=1024, root=root),
                PNG_ONE,
            )
            stats = get_library_stats("20001", root=root)
            self.assertEqual(stats["count"], 1)
            self.assertEqual(stats["size_bytes"], len(PNG_ONE))
            self.assertEqual(stats["top_tags"], [("猫", 1)])

            path = root / "20001" / "images" / record["file_name"]
            path.write_bytes(PNG_TWO)
            with self.assertRaisesRegex(Exception, "image_digest_mismatch"):
                read_image_bytes("20001", record, max_file_bytes=1024, root=root)

    def test_corrupted_index_is_not_overwritten_on_mutation(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            index = root / "20001" / "index.json"
            index.parent.mkdir(parents=True)
            index.write_text("not json", encoding="utf-8")

            with self.assertRaises(Exception):
                _store(root, "20001", PNG_ONE, tags="猫")
            self.assertEqual(index.read_text(encoding="utf-8"), "not json")

    def test_unsupported_content_is_rejected(self):
        with TemporaryDirectory() as tmp_dir:
            with self.assertRaises(InvalidImageError):
                _store(Path(tmp_dir), "20001", b"not-an-image", tags="坏图")


class ImageLibraryProtocolTest(unittest.TestCase):
    def test_tag_commands_parse_ids_and_image_library_help_lists_subcommands(self):
        self.assertEqual(_parse_tag_edit_args("#12 猫猫，开心"), (12, ["猫猫", "开心"]))
        with self.assertRaisesRegex(ValueError, "invalid_image_id"):
            _parse_tag_edit_args("猫猫 开心")
        with self.assertRaisesRegex(ValueError, "missing_image_tags"):
            _parse_tag_edit_args("12")

        help_text = _render_image_library_help(
            get_image_library_settings(),
            {"count": 0, "size_bytes": 0, "top_tags": []},
        )
        for command in ("/收图", "/找图", "/随机图", "/加标签", "/删标签", "/删图"):
            self.assertIn(command, help_text)

    def test_extracts_image_segments_and_ocr_text_from_api_shapes(self):
        payload = {
            "data": {
                "message": [
                    {"type": "text", "data": {"text": "看图"}},
                    {"type": "image", "data": {"file": "abc", "url": "https://example.com/a.png"}},
                ]
            }
        }
        self.assertEqual(
            _extract_image_segments(payload),
            [{"file": "abc", "url": "https://example.com/a.png"}],
        )
        self.assertEqual(
            _extract_ocr_text(
                {"data": {"texts": [{"text": "明月"}, {"text": "清风"}]}}
            ),
            "明月\n清风",
        )

    def test_private_and_local_urls_are_rejected(self):
        for url in (
            "file:///tmp/a.png",
            "http://localhost/a.png",
            "http://127.0.0.1/a.png",
            "http://10.0.0.1/a.png",
            "http://[::1]/a.png",
        ):
            with self.subTest(url=url), self.assertRaises(ImageDownloadError):
                _validate_remote_url(url)
        self.assertEqual(
            _validate_remote_url("https://gchat.qpic.cn/a.png")[1],
            "gchat.qpic.cn",
        )


class ImageLibraryNapCatContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        generation = onebot_capability_registry.begin_connection()
        onebot_capability_registry.apply_probe(
            generation,
            ImplementationInfo("NapCat.Onebot", "4.8.95", "v11", ImplementationFamily.NAPCAT),
            healthy=True,
            issue=None,
        )

    async def asyncTearDown(self):
        onebot_capability_registry.mark_disconnected()

    async def test_direct_and_replied_images_keep_group_source_identity(self):
        bot = AsyncMock()
        direct_event = _group_event(
            [
                MessageSegment.text("/收图 猫"),
                MessageSegment.image("https://gchat.qpic.cn/direct.png"),
            ]
        )
        direct, direct_user, direct_message = await _resolve_source_image(
            bot,
            direct_event,
        )
        self.assertEqual(direct["file"], "https://gchat.qpic.cn/direct.png")
        self.assertEqual(direct_user, "10001")
        self.assertEqual(direct_message, "88001")

        bot.get_msg.return_value = {
            "sender": {"user_id": 10002},
            "message": [
                {
                    "type": "image",
                    "data": {"file": "reply-image-id", "url": "https://gchat.qpic.cn/reply.png"},
                }
            ],
        }
        reply_event = _group_event(
            [MessageSegment.reply("77001"), MessageSegment.text("/收图 月亮")]
        )
        replied, source_user, source_message = await _resolve_source_image(
            bot,
            reply_event,
        )
        self.assertEqual(replied["file"], "reply-image-id")
        self.assertEqual(source_user, "10002")
        self.assertEqual(source_message, "77001")

    async def test_get_image_refresh_preserves_original_ocr_reference(self):
        bot = AsyncMock()
        bot.call_api.return_value = {
            "file": "/napcat/cache/image.png",
            "url": "https://gchat.qpic.cn/refreshed.png",
        }

        refreshed = await _refresh_image_data(bot, {"file": "image-id"})

        bot.call_api.assert_awaited_once_with("get_image", file="image-id")
        self.assertEqual(refreshed["file"], "/napcat/cache/image.png")
        self.assertEqual(refreshed["_ocr_reference"], "image-id")

    async def test_ocr_failure_degrades_only_ocr_capability(self):
        bot = AsyncMock()
        bot.call_api = AsyncMock(side_effect=RuntimeError("temporary failure"))

        self.assertEqual(await _read_ocr(bot, {"file": "image-id"}), "")

        snapshot = onebot_capability_registry.snapshot()
        self.assertEqual(
            snapshot.capability(Capability.IMAGE_OCR).status,
            CapabilityStatus.DEGRADED,
        )
        self.assertEqual(
            snapshot.capability(Capability.IMAGE_REFRESH).status,
            CapabilityStatus.SUPPORTED,
        )


if __name__ == "__main__":
    unittest.main()
