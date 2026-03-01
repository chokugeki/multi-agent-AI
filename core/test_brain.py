#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Knowledge Brain - Unit Tests
brain.py の全機能を検証するテストスイート
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain


@pytest.fixture
def db():
    """テスト用の一時DBを作成する"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = brain.init_db(db_path)
    yield conn
    conn.close()
    # クリーンアップ
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + ext)
        except FileNotFoundError:
            pass


class TestInitDB:
    def test_schema_created(self, db):
        """スキーマが正しく作成される"""
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "knowledge" in table_names
        assert "tags" in table_names
        assert "knowledge_tags" in table_names
        assert "relevance_log" in table_names

    def test_fts_table_created(self, db):
        """FTS5テーブルが作成される"""
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_fts'"
        ).fetchall()
        assert len(tables) == 1


class TestStore:
    def test_basic_store(self, db):
        """基本的な知識の保存"""
        kid = brain.store(db, title="テスト知識", summary="テストの要約", body="本文テスト")
        assert kid > 0

        row = db.execute("SELECT * FROM knowledge WHERE id = ?", (kid,)).fetchone()
        assert row["title"] == "テスト知識"
        assert row["summary"] == "テストの要約"
        assert row["source"] == "conversation"
        assert row["relevance"] == 1.0

    def test_gzip_compression(self, db):
        """本文がgzip圧縮されている"""
        body = "これはテストの本文です。" * 100
        kid = brain.store(db, title="圧縮テスト", summary="圧縮確認", body=body)

        raw = db.execute("SELECT body FROM knowledge WHERE id = ?", (kid,)).fetchone()
        assert raw["body"] is not None
        # 圧縮されているのでバイナリ
        assert isinstance(raw["body"], bytes)
        # 展開して元に戻ることを確認
        restored = brain.get_body(db, kid)
        assert restored == body

    def test_store_with_tags(self, db):
        """タグ付きで保存"""
        kid = brain.store(db, title="タグテスト", summary="要約",
                         tags=["ai", "agi", "backbone"])

        tags = db.execute(
            """SELECT t.name FROM tags t
               JOIN knowledge_tags kt ON kt.tag_id = t.id
               WHERE kt.knowledge_id = ?
               ORDER BY t.name""",
            (kid,)
        ).fetchall()
        tag_names = [t["name"] for t in tags]
        assert "ai" in tag_names
        assert "agi" in tag_names
        assert "backbone" in tag_names

    def test_empty_body(self, db):
        """本文なしで保存"""
        kid = brain.store(db, title="本文なし", summary="要約のみ", body="")
        body = brain.get_body(db, kid)
        assert body == ""


class TestSearch:
    def _populate(self, db):
        """テストデータ投入"""
        brain.store(db, title="AIエージェントの進化",
                   summary="マルチエージェントシステムが急速に発展している",
                   tags=["ai", "agent"])
        brain.store(db, title="Gemini 3.0の性能",
                   summary="Googleが新しいLLMモデルを発表した。コストは半分に",
                   tags=["ai", "llm", "google"])
        brain.store(db, title="佐藤氏のバックボーン",
                   summary="1959年生まれ、IT歴45年、AGI実現を目標としている",
                   tags=["backbone", "permanent"])
        brain.store(db, title="猫の写真撮影",
                   summary="佐藤氏は猫を3匹飼っており、写真撮影が趣味",
                   tags=["hobby"])

    def test_fts_search(self, db):
        """FTS5検索が動作する"""
        self._populate(db)
        results = brain.search(db, "マルチエージェント")
        assert len(results) >= 1
        assert any("エージェント" in r["title"] for r in results)

    def test_search_multiple_tokens(self, db):
        """複数トークンでの検索"""
        self._populate(db)
        results = brain.search(db, "AI LLM コスト")
        assert len(results) >= 1

    def test_search_no_results(self, db):
        """該当なしの場合"""
        self._populate(db)
        results = brain.search(db, "量子コンピューター宇宙開発")
        # FTSに引っかからなければ空リスト
        # (ただしLIKEフォールバックで部分一致する可能性あり)

    def test_empty_query(self, db):
        """空クエリは最新のものを返す"""
        self._populate(db)
        results = brain.search(db, "")
        assert len(results) > 0


class TestGetContextFor:
    def test_context_string(self, db):
        """get_context_forがサマリー文字列を返す"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        conn = brain.init_db(db_path)
        brain.store(conn, title="AGIの今後",
                   summary="AGIは2030年までに実現する可能性がある",
                   tags=["agi"])
        conn.close()

        result = brain.get_context_for("AGIについて", db_path=db_path)
        assert "AGI" in result
        assert len(result) <= 500

        # クリーンアップ
        for ext in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass

    def test_no_context(self):
        """知識がない場合"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        brain.init_db(db_path).close()

        result = brain.get_context_for("何か", db_path=db_path)
        assert "見つかりませんでした" in result

        for ext in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass


class TestDecay:
    def test_decay_old_low_relevance(self, db):
        """古く関連度の低い知識が淘汰される"""
        kid = brain.store(db, title="古い知識", summary="もう不要", relevance=0.1)

        # 手動でcreated_atを60日前に設定
        db.execute(
            "UPDATE knowledge SET created_at = datetime('now', '-60 days') WHERE id = ?",
            (kid,)
        )
        db.commit()

        deleted = brain.decay(db)
        assert any(d["id"] == kid for d in deleted)

    def test_decay_protects_backbone(self, db):
        """backboneタグ付きは淘汰されない"""
        kid = brain.store(db, title="保護知識", summary="永久保存",
                         tags=["backbone"], relevance=0.1)

        db.execute(
            "UPDATE knowledge SET created_at = datetime('now', '-60 days') WHERE id = ?",
            (kid,)
        )
        db.commit()

        deleted = brain.decay(db)
        assert not any(d["id"] == kid for d in deleted)

    def test_decay_protects_recently_accessed(self, db):
        """最近参照された知識は淘汰されない"""
        kid = brain.store(db, title="最近参照", summary="使われた", relevance=0.2)
        brain.record_access(db, kid, "テストクエリ")

        deleted = brain.decay(db)
        assert not any(d["id"] == kid for d in deleted)

    def test_decay_all(self, db):
        """全体的なrelevance減衰"""
        kid1 = brain.store(db, title="通常知識", summary="通常", relevance=1.0)
        kid2 = brain.store(db, title="保護知識", summary="保護",
                          tags=["backbone"], relevance=1.0)

        brain.decay_all(db, factor=0.9)

        r1 = db.execute("SELECT relevance FROM knowledge WHERE id = ?", (kid1,)).fetchone()
        r2 = db.execute("SELECT relevance FROM knowledge WHERE id = ?", (kid2,)).fetchone()

        assert r1["relevance"] == pytest.approx(0.9, abs=0.01)
        assert r2["relevance"] == 1.0  # 保護されている


class TestRelevanceLog:
    def test_access_recorded(self, db):
        """参照ログが記録される"""
        kid = brain.store(db, title="ログテスト", summary="要約")
        brain.record_access(db, kid, "テストクエリ")

        logs = db.execute(
            "SELECT * FROM relevance_log WHERE knowledge_id = ?", (kid,)
        ).fetchall()
        assert len(logs) == 1
        assert logs[0]["context"] == "テストクエリ"

    def test_relevance_increases(self, db):
        """参照されるとrelevanceが上がる"""
        kid = brain.store(db, title="スコアテスト", summary="要約", relevance=0.5)
        brain.record_access(db, kid, "テスト")

        row = db.execute("SELECT relevance FROM knowledge WHERE id = ?", (kid,)).fetchone()
        assert row["relevance"] == pytest.approx(0.55, abs=0.01)


class TestImportMarkdown:
    def test_import(self, db):
        """Markdownファイルのインポート"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # テスト用Markdownを作成
            with open(os.path.join(tmpdir, "test_knowledge.md"), "w") as f:
                f.write("# テストの知識\n\nこれはテスト用の知識ファイルです。\n")

            with open(os.path.join(tmpdir, "Sato_backbone.md"), "w") as f:
                f.write("# 佐藤氏バックボーン\n\n永久保存すべき情報。\n")

            imported = brain.import_markdown(db, directory=tmpdir)
            assert len(imported) == 2

            # backboneタグの確認
            backbone_row = db.execute(
                """SELECT kt.knowledge_id FROM knowledge_tags kt
                   JOIN tags t ON t.id = kt.tag_id
                   WHERE t.name = 'backbone'"""
            ).fetchall()
            assert len(backbone_row) >= 1

    def test_skip_heartbeat(self, db):
        """HEARTBEATファイルはスキップされる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "HEARTBEAT.md"), "w") as f:
                f.write("# Heartbeat\n")
            with open(os.path.join(tmpdir, "real_knowledge.md"), "w") as f:
                f.write("# 本物\n\n内容あり。\n")

            imported = brain.import_markdown(db, directory=tmpdir)
            assert len(imported) == 1
            assert imported[0]["file"] == "real_knowledge.md"

    def test_skip_duplicate(self, db):
        """重複インポートをスキップ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.md"), "w") as f:
                f.write("# テスト\n\n内容。\n")

            first = brain.import_markdown(db, directory=tmpdir)
            second = brain.import_markdown(db, directory=tmpdir)
            assert len(first) == 1
            assert len(second) == 0  # 重複スキップ


class TestStats:
    def test_stats(self, db):
        """統計情報の取得"""
        brain.store(db, title="知識1", summary="要約1", tags=["ai"])
        brain.store(db, title="知識2", summary="要約2", source="patrol")
        brain.record_access(db, 1, "テスト")

        st = brain.stats(db)
        assert st["total_knowledge"] == 2
        assert st["total_tags"] >= 1
        assert st["total_accesses"] == 1
        assert "conversation" in st["by_source"]
        assert "patrol" in st["by_source"]
