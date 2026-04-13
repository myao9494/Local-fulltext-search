"""
起動設定の既定値を検証する。
意図せず既定ポートが変わらないように固定する。
"""

from app.config import Settings


def test_settings_default_bind_port_is_8079() -> None:
    """
    環境変数未指定時の既定ポートは 8079 を使う。
    """
    assert Settings.model_fields["bind_port"].default == 8079
