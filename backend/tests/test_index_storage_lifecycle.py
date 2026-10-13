"""文件说明：验证索引存储退役的保护条件和历史成功运行复用门禁，不访问真实服务。"""

import sqlite3
import unittest
import os
from contextlib import contextmanager, closing
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from knowledge.indexing.indexer import PolicyIndexer
from knowledge.indexing.maintenance import validate_targets, retire_collections


@contextmanager
def isolated_directory():
    """与现有测试一致，将少量SQLite产物保留在独立测试目录便于排查。"""
    root = Path(os.environ.get("POLICY_TEST_RUNTIME_ROOT", Path(__file__).resolve().parents[2] / "var/tests"))
    directory = root / uuid4().hex
    directory.mkdir(parents=True)
    yield directory


class IndexStorageLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE index_run(id INTEGER PRIMARY KEY, collection_name TEXT, status TEXT, activation_status TEXT);
            CREATE TABLE index_profile(active_index_run_id INTEGER, latest_index_run_id INTEGER);
            CREATE TABLE index_storage_retirement(index_run_id INTEGER, state TEXT);
            INSERT INTO index_run VALUES(1,'old','succeeded','superseded'),(8,'keep','succeeded','superseded'),(9,'current','succeeded','active');
            INSERT INTO index_profile VALUES(9,9);
            ALTER TABLE index_profile ADD COLUMN id INTEGER DEFAULT 1;
            ALTER TABLE index_profile ADD COLUMN profile_name TEXT DEFAULT 'policy_platform_dense';
            ALTER TABLE index_profile ADD COLUMN alias_name TEXT DEFAULT 'policy_platform_dense_active';
            ALTER TABLE index_run ADD COLUMN profile_id INTEGER DEFAULT 1;
        """)
        self.store = Mock()
        self.store.alias_targets.return_value = {"current"}
        self.store.collection_exists.return_value = True
        self.store.exact_count.return_value = 3
        self.indexer = object.__new__(PolicyIndexer)
        self.indexer.db = SimpleNamespace(connection=self.db)
        self.indexer.vector_store = self.store
        self.run = {"id": 1, "collection_name": "old", "expected_count": 3}

    def tearDown(self):
        self.db.close()

    def test_exact_old_target_is_allowed(self):
        self.assertEqual(validate_targets(self.db, self.store, [1], [8,9])[0]["collection_name"], "old")

    def test_keep_active_missing_and_empty_are_rejected(self):
        for ids in ([8], [9], [100], []):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                validate_targets(self.db, self.store, ids, [8,9])

    def test_any_alias_protects_old_run(self):
        self.store.alias_targets.return_value = {"old", "current"}
        with self.assertRaises(ValueError):
            validate_targets(self.db, self.store, [1], [8,9])

    def test_running_is_protected(self):
        self.db.execute("UPDATE index_run SET status='running' WHERE id=1")
        with self.assertRaises(ValueError):
            validate_targets(self.db, self.store, [1], [8,9])

    def test_available_success_is_reusable(self):
        self.indexer._assert_storage_available(self.run)

    def test_missing_collection_is_rejected(self):
        self.store.collection_exists.return_value = False
        with self.assertRaisesRegex(ValueError, "缺失"):
            self.indexer._assert_storage_available(self.run)

    def test_incomplete_collection_is_rejected(self):
        self.store.exact_count.return_value = 2
        with self.assertRaisesRegex(ValueError, "不完整"):
            self.indexer._assert_storage_available(self.run)

    def test_retired_and_incomplete_deletion_are_rejected(self):
        for state in ("DELETING", "DELETED"):
            self.db.execute("DELETE FROM index_storage_retirement")
            self.db.execute("INSERT INTO index_storage_retirement VALUES(1,?)", (state,))
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "退役"):
                self.indexer._assert_storage_available(self.run)

    def test_cleanup_dry_run_delete_and_repeat(self):
        """实测维护事务和重入；模拟向量删除但使用真实临时SQLite。"""
        with isolated_directory() as directory:
            platform = Path(directory) / "platform.db"
            with closing(sqlite3.connect(platform)) as connection:
                connection.execute("CREATE TABLE index_publication_request(id TEXT, status TEXT)")
                connection.commit()
            self.db.execute("DROP TABLE index_storage_retirement")
            self.db.execute("CREATE TABLE index_storage_retirement(index_run_id INTEGER PRIMARY KEY, collection_name TEXT, state TEXT, requested_at TEXT, deleted_at TEXT, reason TEXT)")
            self.db.commit()
            manager = Mock()
            manager.__enter__ = Mock(return_value=SimpleNamespace(connection=self.db))
            manager.__exit__ = Mock(side_effect=lambda *args: self.db.rollback())
            with patch("knowledge.indexing.maintenance.IndexDatabase", return_value=manager):
                retire_collections(Path("unused"), platform, self.store, [1], [8,9])
                self.store.delete_collection.assert_not_called()
                self.assertEqual(self.db.execute("SELECT count(*) FROM index_storage_retirement").fetchone()[0], 0)
                self.store.delete_collection.side_effect = RuntimeError("模拟Qdrant断连")
                with self.assertRaisesRegex(RuntimeError, "断连"):
                    retire_collections(Path("unused"), platform, self.store, [1], [8,9], execute=True)
                self.assertEqual(self.db.execute("SELECT state FROM index_storage_retirement").fetchone()[0], "DELETING")
                def deleted(_name):
                    self.store.collection_exists.return_value = False
                self.store.delete_collection.side_effect = deleted
                retire_collections(Path("unused"), platform, self.store, [1], [8,9], execute=True)
                retire_collections(Path("unused"), platform, self.store, [1], [8,9], execute=True)
                self.assertEqual(self.store.delete_collection.call_count, 2)
                self.store.delete_collection.assert_called_with("old")
                self.assertEqual(self.db.execute("SELECT state FROM index_storage_retirement").fetchone()[0], "DELETED")
                self.assertEqual(self.db.execute("SELECT count(*) FROM index_run").fetchone()[0], 3)

    def test_pending_publication_blocks_cleanup(self):
        with isolated_directory() as directory:
            platform = Path(directory) / "platform.db"
            with closing(sqlite3.connect(platform)) as connection:
                connection.execute("CREATE TABLE index_publication_request(id TEXT, status TEXT)")
                connection.execute("INSERT INTO index_publication_request VALUES('pending','READY_TO_PUBLISH')")
                connection.commit()
            self.db.commit()
            manager = Mock()
            manager.__enter__ = Mock(return_value=SimpleNamespace(connection=self.db))
            manager.__exit__ = Mock(side_effect=lambda *args: self.db.rollback())
            with patch("knowledge.indexing.maintenance.IndexDatabase", return_value=manager):
                with self.assertRaisesRegex(ValueError, "未完成"):
                    retire_collections(Path("unused"), platform, self.store, [1], [8,9], execute=True)
                self.store.delete_collection.assert_not_called()

    def test_foreign_namespace_blocks_cleanup(self):
        """新环境即使收到旧运行ID，也应在删除向量前拒绝。"""
        with isolated_directory() as directory:
            platform = Path(directory) / "platform.db"
            with closing(sqlite3.connect(platform)) as connection:
                connection.execute("CREATE TABLE index_publication_request(id TEXT, status TEXT)")
                connection.commit()
            self.db.commit()
            manager = Mock()
            manager.__enter__ = Mock(return_value=SimpleNamespace(connection=self.db))
            manager.__exit__ = Mock(side_effect=lambda *args: self.db.rollback())
            config = SimpleNamespace(profile_name="pg_test", alias_name="pg_test_active")
            with patch("knowledge.indexing.maintenance.IndexDatabase", return_value=manager), patch("knowledge.indexing.maintenance.IndexConfig.from_environment", return_value=config):
                with self.assertRaisesRegex(ValueError, "命名空间"):
                    retire_collections(Path("unused"), platform, self.store, [1], [8,9], execute=True)
                self.store.delete_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
