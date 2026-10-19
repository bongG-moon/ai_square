import pytest
from unittest.mock import patch
from pymongo.errors import ServerSelectionTimeoutError
from pt_ai_square import create_app


def test_missing_database_configuration_requires_explicit_setup(tmp_path):
    with patch('pt_ai_square.init_db',side_effect=AssertionError('must not connect')):
        with pytest.raises(ValueError,match='MONGODB_URI'):
            create_app({'MONGODB_URI':'','DATA_DIR':str(tmp_path/'data')})
    assert not (tmp_path/'data').exists()


def test_configured_failure_has_no_fallback(tmp_path):
    with patch('pt_ai_square.init_db',side_effect=ServerSelectionTimeoutError('offline')):
        with pytest.raises(ServerSelectionTimeoutError):
            create_app({'MONGODB_URI':'mongodb://configured.invalid/','DATA_DIR':str(tmp_path)})
