import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import os

from app.main import app
from app.config import settings

client = TestClient(app)

def test_get_synonyms_api():
    """
    同義語取得APIが正しく構造化されたデータを返すかテストする。
    """
    # テスト用の同義語ファイルを作成
    synonym_file = settings.synonym_groups_path
    original_content = ""
    if synonym_file.exists():
        original_content = synonym_file.read_text(encoding="utf-8")
    
    test_content = "PC,パソコン,パーソナルコンピュータ\niPhone,アイフォン,アイフォーン\n"
    synonym_file.parent.mkdir(parents=True, exist_ok=True)
    synonym_file.write_text(test_content, encoding="utf-8")
    
    try:
        response = client.get("/api/index/synonyms")
        assert response.status_code == 200
        data = response.json()
        assert "groups" in data
        assert len(data["groups"]) == 2
        assert data["groups"][0] == ["PC", "パソコン", "パーソナルコンピュータ"]
        assert data["groups"][1] == ["iPhone", "アイフォン", "アイフォーン"]
    finally:
        # 元に戻す
        if original_content:
            synonym_file.write_text(original_content, encoding="utf-8")
        else:
            if synonym_file.exists():
                synonym_file.unlink()
