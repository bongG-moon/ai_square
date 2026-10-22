from concurrent.futures import ThreadPoolExecutor
import time
from pt_ai_square.backend.storage import db
from pt_ai_square.backend import activity
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

def test_download_lifetime_unique_and_repeated_events(app):
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

def test_seven_day_scores_and_same_timestamp_cursor(app):
    c,h=ready(app);publish(c,h)
    with app.app_context():
        now=time.time()
        for n,age in enumerate([100,4000,30000,90000,7*86400,7*86400+1]):
            db().activity_state.insert_one({'_id':f'weight{n}','tool':1,'user':str(n),'kind':'like','liked':True,'created':now-age})
        stats=activity.statistics([1],'0',now)[1]
        assert (stats['recentLikes'],stats['likes'])==(5,6)
        assert (stats['rankScore'],stats['totalRankScore'])==(10,12)
        for n in range(80):db().activity.insert_one({'_id':f'cursor{n:03}','kind':'like','tool':1,'user':'owner','created':now})
        one,cursor=activity.history();two,end=activity.history(cursor)
        assert len(one)==50 and len(two)==30 and end is None
        assert len({r['id'] for r in one+two})==80


def test_like_toggle_does_not_refresh_ranking_date(app,monkeypatch):
    from pt_ai_square.backend import mongo_activity
    c,h=ready(app);publish(c,h)
    clock=[1_800_000_000.0]
    monkeypatch.setattr(mongo_activity.time,'time',lambda:clock[0])
    with app.app_context():
        activity.set_like(1,'member',True)
        assert activity.statistics([1],'member',clock[0])[1]['rankScore']==2
        clock[0]+=8*86400
        activity.set_like(1,'member',False)
        assert activity.statistics([1],'member',clock[0])[1]['totalRankScore']==0
        activity.set_like(1,'member',True)
        stats=activity.statistics([1],'member',clock[0])[1]
        assert (stats['likes'],stats['rankScore'],stats['totalRankScore'])==(1,0,2)
        # Legacy rows retain their available date when first touched.
        db().activity_state.insert_one({'_id':'like:2:member','tool':2,'user':'member','kind':'like','liked':True,'created':clock[0]-9*86400})
        activity.set_like(2,'member',False);activity.set_like(2,'member',True)
        assert activity.statistics([2],'member',clock[0])[2]['rankScore']==0


def test_download_windows_and_formula(app,monkeypatch):
    from pt_ai_square.backend import mongo_activity
    c,h=ready(app);publish(c,h)
    clock=[1_800_000_000.0]
    monkeypatch.setattr(mongo_activity.time,'time',lambda:clock[0])
    with app.app_context():
        activity.record_download(1,'member',1)
        activity.record_download(1,'member',2)
        clock[0]+=8*86400
        activity.record_download(1,'member',2)
        activity.record_download(1,'other',1)
        activity.set_like(1,'member',True)
        stats=activity.statistics([1],'member',clock[0])[1]
        assert (stats['recentDownloads'],stats['downloads'])==(1,2)
        assert (stats['rankScore'],stats['totalRankScore'])==(3,4)
        assert activity.statistics([99],'member',clock[0])[99]['totalRankScore']==0
