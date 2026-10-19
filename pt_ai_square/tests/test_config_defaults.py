from pt_ai_square import config


def test_no_private_config_defaults_to_local_mock(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'BASE', tmp_path)
    for name in ('PTAI_AUTH_MODE', 'PTAI_COOKIE_SECURE', 'PTAI_MOCK_USER',
                 'PTAI_HOST', 'PTAI_PORT'):
        monkeypatch.delenv(name, raising=False)
    settings = config.settings()
    assert settings['AUTH_MODE'] == 'mock'
    assert settings['MOCK_USER'] == '1000001'
    assert settings['SESSION_COOKIE_SECURE'] is False
    assert settings['HOST'] == '127.0.0.1'
    assert settings['PORT'] == 5080


def test_explicit_sso_is_still_supported(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'BASE', tmp_path)
    monkeypatch.delenv('PTAI_AUTH_MODE', raising=False)
    monkeypatch.delenv('PTAI_COOKIE_SECURE', raising=False)
    (tmp_path / 'runtime_config.py').write_text("PTAI_AUTH_MODE = 'sso'\n", encoding='utf-8')
    assert config.settings()['AUTH_MODE'] == 'sso'
    assert config.settings()['SESSION_COOKIE_SECURE'] is True
    monkeypatch.setenv('PTAI_AUTH_MODE', 'mock')
    assert config.settings()['AUTH_MODE'] == 'mock'
