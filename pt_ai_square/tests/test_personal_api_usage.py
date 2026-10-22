from .conftest import ready, publish
from pt_ai_square.backend.storage import db
from pt_ai_square.backend import activity


def issue(c, h, scope='publish'):
    r = c.post('/api/local-tokens', headers=h, json={'name':'PC', 'scope':scope, 'user':'admin'})
    assert r.status_code == 201
    return r.json, {'Authorization':'Bearer '+r.json['token']}


def test_publish_token_scope_employee_and_counts(app):
    owner, h = ready(app)
    token, auth = issue(owner, h)
    api = app.test_client()
    options = api.get('/api/catalog/options', headers=auth).json
    assert options['employee']['id'] == 'owner' and options['organizations']
    r = publish(api, auth, owner='admin')
    assert r.status_code == 201
    assert api.get('/api/tools/1', headers=auth).json['ownerId'] == 'owner'
    assert publish(api, auth, tid=1, revision=1).status_code == 201
    assert publish(api, auth, tid=1, revision=1).status_code == 409
    assert api.post('/api/tools', headers=auth).status_code == 400
    for method, path in [('delete','/api/tools/1'), ('patch','/api/tools/1'), ('post','/api/local-tokens'), ('get','/api/local-tokens')]:
        assert getattr(api, method)(path, headers=auth).status_code == 403
    data = owner.get('/api/local-tokens').json
    assert data['employee']['id'] == 'owner'
    assert data['usage'] == {'uploads':2, 'downloads':0}
    assert data['tokens'][0]['uploads'] == 2
    assert len(data['history']) == 2
    with app.app_context():
        assert db().local_tokens.find_one({'id':token['id']})['user'] == 'owner'
    member, mh = ready(app, 'member')
    _, mauth = issue(member, mh)
    assert publish(api, mauth, tid=1, revision=2).status_code == 403
    assert member.get('/api/local-tokens').json['usage'] == {'uploads':0,'downloads':0}
    assert member.get('/api/local-tokens').json['history'] == []


def test_reissued_key_keeps_download_counts_and_lifetime_ranking(app):
    owner, h = ready(app)
    publish(owner, h, approval=True)
    t1, a1 = issue(owner, h, 'read')
    c = app.test_client()
    assert c.head('/download/1/1', headers=a1).status_code == 200
    assert c.get('/download/1/1', headers=a1).status_code == 200
    assert c.get('/download/1/1', headers=a1).status_code == 200
    t2, a2 = issue(owner, h, 'publish')
    assert c.get('/download/1/1', headers=a1).status_code == 401
    assert c.get('/download/1/1', headers=a2).status_code == 200
    assert c.get('/download/1/99', headers=a2).status_code == 404
    assert owner.get('/download/1/1').status_code == 200  # web download isn't API usage
    data = owner.get('/api/local-tokens').json
    assert data['usage'] == {'uploads':0,'downloads':1}
    by_id = {t['id']:t for t in data['tokens']}
    assert by_id[t1['id']]['downloads'] == 1
    assert by_id[t2['id']]['downloads'] == 0
    assert owner.get('/api/tools/1').json['downloads'] == 1
    with app.app_context():
        activity.flush()
        activity.flush()
    assert owner.get('/api/local-tokens').json['usage']['downloads'] == 1
    owner.delete('/api/local-tokens/'+t1['id'], headers=h)
    assert c.get('/download/1/1', headers=a1).status_code == 401
    data = owner.get('/api/local-tokens').json
    assert data['usage']['downloads'] == 1
    assert next(t for t in data['tokens'] if t['id']==t1['id'])['status'] == 'replaced'
    assert c.get('/api/catalog', headers=a2).status_code == 200


def test_legacy_keys_remain_read_only_and_failed_access_not_counted(app):
    owner, h = ready(app)
    publish(owner, h, approval=True)
    member, mh = ready(app, 'member')
    t, auth = issue(member, mh)
    with app.app_context():
        db().local_tokens.update_one({'id':t['id']}, {'$unset':{'scope':''}})
    assert publish(app.test_client(), auth).status_code == 403
    assert app.test_client().get('/download/1/1', headers=auth).status_code == 403
    assert member.get('/api/local-tokens').json['usage'] == {'uploads':0,'downloads':0}
    assert member.get('/api/local-tokens').json['tokens'][0]['scope'] == 'read'
    for scope in ['admin', ['publish'], True, None]:
        assert owner.post('/api/local-tokens', headers=h, json={'scope':scope}).status_code == 400
