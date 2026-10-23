"""Process ownership and retryable-write compatibility using an isolated DB."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from bson import Int64
from pymongo import MongoClient, monitoring
from pymongo.errors import OperationFailure, AutoReconnect

from pt_ai_square.backend import mongo_store
from pt_ai_square.backend.mongo_errors import mongo_diagnostic


def test_client_is_reused_by_threads_in_same_process(app):
    parent = app.extensions['square_mongo_client']
    def get_client(_):
        with app.app_context():
            return mongo_store.db().client
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(client is parent for client in pool.map(get_client, range(20)))


def test_inherited_client_is_replaced_once_before_concurrent_writes(app, monkeypatch):
    original = app.extensions['square_mongo_client']
    factory = mongo_store.MongoClient
    created = []
    def construct(*args, **kwargs):
        client = factory(*args, **kwargs)
        created.append(client)
        return client
    monkeypatch.setattr(mongo_store, 'MongoClient', construct)
    app.extensions['square_mongo_pid'] = -1  # Simulate inherited app state.
    def write(number):
        with app.app_context():
            database = mongo_store.db()
            database.worker_probe.insert_one({'_id': number})
            return database.client
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            clients = list(pool.map(write, range(30)))
        assert len(created) == 1
        assert all(client is created[0] and client is not original for client in clients)
        assert app.extensions['square_mongo_pid'] == mongo_store.getpid()
        assert original.admin.command('ping')['ok'] == 1  # Not closed by child guard.
        with app.app_context():
            assert mongo_store.db().worker_probe.count_documents({}) == 30
    finally:
        original.close()  # This is a simulation in the same process, not a fork.


def test_failed_worker_connection_does_not_replace_or_close_inherited_client(app, monkeypatch):
    inherited = app.extensions['square_mongo_client']
    old_db = app.extensions['square_mongo']
    closed = []
    class BrokenClient:
        admin = SimpleNamespace(command=lambda *a, **kw: (_ for _ in ()).throw(AutoReconnect('private')))
        def __getitem__(self, key): return object()
        def close(self): closed.append(True)
    monkeypatch.setattr(mongo_store, 'MongoClient', lambda *a, **kw: BrokenClient())
    app.extensions['square_mongo_pid'] = -1
    try:
        with app.app_context(), pytest.raises(AutoReconnect):
            mongo_store.db()
        assert app.extensions['square_mongo_client'] is inherited
        assert app.extensions['square_mongo'] is old_db
        assert app.extensions['square_mongo_pid'] == -1
        assert closed == [True]
    finally:
        app.extensions['square_mongo_pid'] = mongo_store.getpid()


def test_capacity_reads_use_process_owned_connection(app):
    from pt_ai_square.backend.storage_capacity import policy
    original = app.extensions['square_mongo_client']
    app.extensions['square_mongo_pid'] = -1
    try:
        with app.app_context():
            assert policy()['mode'] == 'manual'
        assert app.extensions['square_mongo_client'] is not original
    finally:
        original.close()


def test_fork_hook_replaces_an_inherited_lock():
    lock = mongo_store._CLIENT_LOCK
    mongo_store._after_fork()
    assert mongo_store._CLIENT_LOCK is not lock
    with mongo_store._CLIENT_LOCK: pass


def test_old_config_defaults_to_no_write_replay_with_explicit_opt_in(monkeypatch, tmp_path):
    from pt_ai_square import config
    monkeypatch.setattr(config, 'BASE', tmp_path)
    monkeypatch.delenv('PTAI_MONGODB_RETRY_WRITES', raising=False)
    (tmp_path/'runtime_config.py').write_text("MONGODB_DATABASE='existing'\n", encoding='utf-8')
    assert config.settings()['MONGODB_RETRY_WRITES'] is False
    (tmp_path/'runtime_config.py').write_text('PTAI_MONGODB_RETRY_WRITES=True\n', encoding='utf-8')
    assert config.settings()['MONGODB_RETRY_WRITES'] is True
    monkeypatch.setenv('PTAI_MONGODB_RETRY_WRITES', 'false')
    assert config.settings()['MONGODB_RETRY_WRITES'] is False
    monkeypatch.setenv('PTAI_MONGODB_RETRY_WRITES', 'typo')
    with pytest.raises(ValueError, match='PTAI_MONGODB_RETRY_WRITES'):
        config.settings()


class Commands(monitoring.CommandListener):
    def __init__(self): self.writes = []
    def started(self, event):
        if event.command_name in {'insert','update','delete','findAndModify'}:
            # Record only protocol attributes, never documents/URIs.
            self.writes.append((event.command_name, 'txnNumber' in event.command))
    def succeeded(self, event): pass
    def failed(self, event): pass


def test_compatibility_option_overrides_uri_without_disabling_acknowledgement(app, monkeypatch):
    listener = Commands()
    old_client = app.extensions['square_mongo_client']
    factory = mongo_store.MongoClient
    uri = app.config['MONGODB_URI']
    app.config['MONGODB_URI'] = uri + ('&' if '?' in uri else '?') + 'retryWrites=true'
    app.config['MONGODB_RETRY_WRITES'] = False
    monkeypatch.setattr(mongo_store, 'MongoClient', lambda *a, **kw: factory(*a, event_listeners=[listener], **kw))
    app.extensions['square_mongo_pid'] = -1
    try:
        with app.app_context():
            database = mongo_store.db()
            result = database.write_probe.insert_one({'_id': 'single'})
            database.write_probe.update_one({'_id': 'single'}, {'$set': {'saved': True}})
            assert result.acknowledged
            assert database.write_probe.find_one({'_id': 'single'})['saved'] is True
            assert database.client.options.retry_writes is False
        assert listener.writes == [('insert', False), ('update', False)]
    finally:
        old_client.close()


def test_actual_225_mechanism_and_fresh_client_write(app):
    """Mechanism reproduction, not proof of the production topology/cause."""
    client = app.extensions['square_mongo_client']
    if not client.admin.command('hello').get('setName'):
        pytest.skip('Replica set required for transaction-number mechanism test')
    database = app.extensions['square_mongo']
    # Raw commands intentionally supply txnNumber to reproduce out-of-order
    # protocol state even when normal application retries are disabled.
    with client.start_session() as session:
        database.command({'insert':'txn_probe','documents':[{'_id':'accepted'}],
                          'txnNumber':Int64(20)}, session=session)
        with pytest.raises(OperationFailure) as caught:
            database.command({'insert':'txn_probe','documents':[{'_id':'rejected'}],
                              'txnNumber':Int64(19)}, session=session)
        assert caught.value.code == 225
        assert mongo_diagnostic(caught.value)['code'] == 'DB-SESSION-ORDER'
    assert database.txn_probe.count_documents({}) == 1
    app.extensions['square_mongo_pid'] = -1
    try:
        with app.app_context():
            fresh = mongo_store.db()
            assert fresh.client is not client
            assert fresh.txn_probe.insert_one({'_id':'fresh'}).acknowledged
            assert fresh.txn_probe.count_documents({}) == 2
    finally:
        client.close()
