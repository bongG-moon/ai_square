from concurrent.futures import ThreadPoolExecutor
import time
from pt_ai_square.storage import db
from pt_ai_square import activity
from .conftest import ready, publish

def test_concurrent_like_idempotence_and_history(app):
    c,h=ready(app);publish(c,h)
    def like(_):
        client,headers=ready(app,'member');return client.put('/api/tools/1/like',json={'liked':True},headers=headers).status_code
    with ThreadPoolExecutor(8) as pool:assert set(pool.map(like,range(20)))=={200}
    x=c.get('/api/bootstrap').json['items'][0];assert x['likes']==1
    with app.app_context():assert db().activity.count_documents({'kind':'like'})==1
    member,mh=ready(app,'member');member.put('/api/tools/1/like',json={'liked':False},headers=mh)
    assert c.get('/api/bootstrap').json['items'][0]['likes']==0

def test_download_daily_unique_and_repeated_events(app):
    c,h=ready(app);publish(c,h)
    member,mh=ready(app,'member')
    assert member.head('/download/1/1').status_code==200
    assert c.get('/api/bootstrap').json['items'][0]['downloads']==0
    def download(_):
        client,_=ready(app,'member');r=client.get('/download/1/1');r.close();return r.status_code
    with ThreadPoolExecutor(6) as pool:assert set(pool.map(download,range(12)))=={200}
    assert c.get('/api/bootstrap').json['items'][0]['downloads']==1
    with app.app_context():
        assert db().activity.count_documents({'kind':'download'})==12
        assert db().activity.count_documents({'kind':'download','counted':True})==1

def test_weights_and_same_timestamp_cursor(app):
    c,h=ready(app);publish(c,h)
    with app.app_context():
        now=time.time()
        for n,age in enumerate([100,4000,30000,90000]):
            db().activity_state.insert_one({'_id':f'weight{n}','tool':1,'user':str(n),'kind':'like','liked':True,'created':now-age})
        assert activity.statistics([1],'0',now)[1]['rankScore']==21
        for n in range(80):db().activity.insert_one({'_id':f'cursor{n:03}','kind':'like','tool':1,'user':'owner','created':now})
        one,cursor=activity.history();two,end=activity.history(cursor)
        assert len(one)==50 and len(two)==30 and end is None
        assert len({r['id'] for r in one+two})==80
