"""One-time, explicit, read-only import. SQLite is never used by the running service."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from flask import current_app
from .storage import db, ensure_user

def migrate(path):
    source=Path(path).resolve()
    if not source.is_file(): raise ValueError('이전 SQLite 파일이 없습니다.')
    migration_id=hashlib.sha256(str(source).encode()).hexdigest()
    marker=db().migrations.find_one({'_id':migration_id})
    if marker and marker['state']=='complete': return marker['counts']
    if db().tools.count_documents({}) and not marker: raise ValueError('새 MongoDB 또는 이전에 시작한 이전 작업에서만 실행할 수 있습니다. 대상 DB를 확인하세요.')
    db().migrations.update_one({'_id':migration_id},{'$setOnInsert':{'state':'running','source':str(source),'started':time.time()}},upsert=True)
    con=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def rows(table): return [dict(r) for r in con.execute('SELECT * FROM '+table)] if table in tables else []
    counts={}
    def insert(collection,document):
        db()[collection].update_one({'_id':document['_id']},{'$setOnInsert':document},upsert=True)
        counts[collection]=counts.get(collection,0)+1
    def taxonomy(kind,name):
        row=db().taxonomy.find_one({'kind':kind,'name':name})
        if row:return row['_id']
        key='legacy-'+hashlib.sha256((kind+name).encode()).hexdigest()[:24]
        db().taxonomy.update_one({'_id':key},{'$setOnInsert':{'kind':kind,'name':name,'enabled':True,'order':50,'owner':''}},upsert=True)
        return key
    users=rows('users')
    for u in users:
        insert('users',{'_id':u['id'],'name':u['name'],'orgId':taxonomy('organization',u['org']),'password':u.get('password'),'enabled':bool(u['enabled']),'created':time.time()})
        if u['role']=='admin':insert('administrators',{'_id':u['id'],'active':True,'actor':'legacy-migration','updated':time.time()})
    for o in rows('orgs'):taxonomy('organization',o['name'])
    versions=rows('versions')
    for t in rows('tools'):
        data=json.loads(t['data']);old_visibility=data.get('visibility','전체 공개');data['orgId']=taxonomy('organization',data['org']);data['categoryId']=taxonomy('category',data['category'])
        if old_visibility=='선택 조직':
            if not data.get('approval'):
                for u in users:
                    if u['org'] in data.get('audience',[]):insert('access',{'_id':f'{t["id"]}:{u["id"]}','tool':t['id'],'user':u['id'],'status':'승인','granted':True,'source':'기존 조직 권한','reason':'','decision':'','updated':time.time(),'history':[]})
            data['approval']=True
        data['visibility']='전체 공개';data['audience']=[]
        vs=[]
        for v in versions:
            if v['tool']==t['id']:
                v=dict(v);v.pop('tool');v['data']=json.loads(v.get('data') or '{}');v['deleted']=bool(v['deleted']);v['withdrawn']=bool(v['withdrawn']);vs.append(v)
        insert('tools',{'_id':t['id'],'owner':t['owner'],'data':data,'created':t['created'],'active':t['active'],'fallback':t['fallback'],'revision':t['revision'],'deleted':bool(t['hidden']),'paused':bool(t['paused']),'versions':vs})
    for r in rows('requests'):
        insert('access',{'_id':f'{r["tool"]}:{r["user"]}','legacyId':r['id'],'tool':r['tool'],'user':r['user'],'reason':r['reason'],'status':r['status'],'granted':r['status']=='승인','decision':r['decision'],'source':'신청','updated':time.time(),'history':[]})
    for c in rows('comments'):
        insert('feedback',{'_id':c['id'],'tool':c['tool'],'user':c['user'],'kind':c['kind'],'body':c['body'],'created':c['created'],'status':'접수','revision':0,'replies':[]})
    for i in rows('ideas'):
        insert('ideas',{'_id':i['id'],'user':i['user'],'name':i['name'],'body':i['body'],'category':i['category'],'categoryId':taxonomy('category',i['category']),'created':i['created'],'status':'접수 대기','revision':0,'assignee':None,'tool':None,'replies':[]})
    for r in rows('likes'):
        insert('activity_state',{'_id':f'like:{r["tool"]}:{r["user"]}','tool':r['tool'],'user':r['user'],'kind':'like','liked':True,'created':r['created']})
    for r in rows('downloads'):
        insert('activity_state',{'_id':f'download:{r["tool"]}:{r["user"]}:{r["day"]}','tool':r['tool'],'user':r['user'],'kind':'download','count':1,'created':r['created']})
    for r in rows('audit'):insert('audit',{'_id':'legacy:'+str(r['id']),**{k:v for k,v in r.items() if k!='id'}})
    for collection in ['tools','feedback','ideas']:
        last=db()[collection].find_one(sort=[('_id',-1)])
        db().counters.update_one({'_id':collection},{'$max':{'value':last['_id'] if last else 0}},upsert=True)
    for s in rows('settings'):
        if s['key']=='retention':db().settings.update_one({'_id':'retention'},{'$set':json.loads(s['value'])})
    # Preserve archived Mongo activity too; do not copy credentials or delete the source.
    old_collection=current_app.config['ACTIVITY_COLLECTION']
    if old_collection!='activity':
        for e in db()[old_collection].find():
            e=dict(e);e['_id']='legacy:'+str(e['_id']);insert('activity',e)
    legacy_settings={s['key']:s['value'] for s in rows('settings')}
    source_id=legacy_settings.get('activity_source','')
    for e in rows('activity_queue'):
        if db().activity.find_one({'source':source_id,'seq':e['id']}):continue
        insert('activity',dict(_id='legacy-queue:'+migration_id+':'+str(e['id']),tool=e['tool'],user=e['user'],kind=e['kind'],created=e['created'],version=e['version'],counted=bool(e['counted']),imported=bool(e['imported'])))
    for grant in db().access.find({'granted':True}):
        db().subscriptions.update_one({'tool':grant['tool'],'user':grant['user']},{'$setOnInsert':{'enabled':True}},upsert=True)
    for d in rows('downloads'):
        db().subscriptions.update_one({'tool':d['tool'],'user':d['user']},{'$setOnInsert':{'enabled':True}},upsert=True)
    # Older development databases without Mongo events still retain their current totals.
    key=source.parent/'session.key'
    if key.is_file():db().settings.update_one({'_id':'session'},{'$set':{'secret':key.read_text().strip()}})
    con.close()
    db().migrations.update_one({'_id':migration_id},{'$set':{'state':'complete','completed':time.time(),'counts':counts}})
    return counts
