import unittest

import mybot.bot  # noqa: F401
from mybot.common.admin import get_feature_permission_level
from mybot.common.feature_flags import (
    DEFAULT_FEATURE_ENABLED,
    get_feature_name,
    module_feature_key,
    resolve_feature,
)
from mybot.common.help_registry import HelpItem
from mybot.common.plugin_metadata import (
    BackupPolicy,
    FeatureScope,
    PluginMetadata,
    PrivacyLevel,
    iter_loaded_plugin_modules,
    iter_plugin_metadata,
    validate_loaded_plugin_metadata,
)


class PluginMetadataConsistencyTest(unittest.TestCase):
    def test_every_loaded_plugin_has_registered_metadata(self):
        validate_loaded_plugin_metadata()

        loaded_modules = dict(iter_loaded_plugin_modules())
        self.assertFalse(any("._" in module_name for module_name in loaded_modules))
        metadata = iter_plugin_metadata()
        self.assertEqual(
            {item.module_name for item in metadata},
            set(loaded_modules),
        )
        self.assertEqual(len(metadata), len({item.feature_key for item in metadata}))

        for module_name, module in loaded_modules.items():
            with self.subTest(module=module_name):
                self.assertIsInstance(module.PLUGIN_META, PluginMetadata)
                self.assertEqual(module.PLUGIN_META.module_name, module_name)
                self.assertEqual(
                    module_feature_key(module_name),
                    module.PLUGIN_META.feature_key,
                )
                if hasattr(module, "FEATURE_KEY"):
                    self.assertEqual(
                        module.FEATURE_KEY,
                        module.PLUGIN_META.feature_key,
                    )

    def test_metadata_is_the_source_of_feature_behavior(self):
        for metadata in iter_plugin_metadata():
            with self.subTest(feature=metadata.feature_key):
                self.assertEqual(get_feature_name(metadata.feature_key), metadata.name)
                self.assertEqual(
                    DEFAULT_FEATURE_ENABLED[metadata.feature_key],
                    metadata.default_enabled,
                )
                self.assertEqual(
                    get_feature_permission_level(metadata.feature_key),
                    metadata.permission_level,
                )

        disabled_by_default = {
            metadata.feature_key
            for metadata in iter_plugin_metadata()
            if not metadata.default_enabled
        }
        self.assertEqual(
            disabled_by_default,
            {
                "image_library",
                "legacy_blackjack",
                "legacy_dice",
                "legacy_race",
                "legacy_roulette",
                "legacy_scratch",
                "legacy_slot",
            },
        )
        self.assertEqual(resolve_feature("youyimiya"), "yoimiya")

    def test_scope_privacy_data_and_backup_fields_are_consistent(self):
        for metadata in iter_plugin_metadata():
            with self.subTest(feature=metadata.feature_key):
                self.assertIsInstance(metadata.scope, FeatureScope)
                self.assertIsInstance(metadata.privacy_level, PrivacyLevel)
                self.assertIsInstance(metadata.backup_policy, BackupPolicy)
                if metadata.scope is FeatureScope.SYSTEM:
                    self.assertIsNone(metadata.permission_level)
                else:
                    self.assertIn(metadata.permission_level, range(1, 6))
                if metadata.data_files:
                    self.assertIsNot(metadata.backup_policy, BackupPolicy.NONE)
                    self.assertTrue(
                        all(path.startswith("data/") for path in metadata.data_files)
                    )
                else:
                    self.assertIs(metadata.backup_policy, BackupPolicy.NONE)

        optional_backup_features = {
            metadata.feature_key
            for metadata in iter_plugin_metadata()
            if metadata.backup_policy is BackupPolicy.OPTIONAL
        }
        self.assertEqual(optional_backup_features, {"group_chat_logs", "image_library"})

    def test_help_items_and_command_aliases_remain_plugin_local(self):
        for module_name, module in iter_loaded_plugin_modules():
            help_items = getattr(module, "HELP_ITEMS", ())
            aliases = getattr(module, "COMMAND_ALIASES", ())
            with self.subTest(module=module_name):
                self.assertIsInstance(help_items, tuple)
                self.assertTrue(all(isinstance(item, HelpItem) for item in help_items))
                self.assertIsInstance(aliases, tuple)
                self.assertTrue(
                    all(isinstance(alias, str) and alias.strip() for alias in aliases)
                )
                self.assertEqual(len(aliases), len(set(aliases)))
                if help_items:
                    self.assertTrue(aliases)


if __name__ == "__main__":
    unittest.main()
