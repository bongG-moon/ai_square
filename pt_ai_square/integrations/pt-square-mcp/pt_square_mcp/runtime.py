"""MCP tool orchestration; ownership and publishing approval remain server-side."""
import re
import threading
import uuid
from urllib.parse import urlencode

from .client import Client, positive, automatic_download_directory
from .config import SquareError, Settings, atomic_json, scoped_path, no_links
from .files import inspect, package, sha256
from .install import Installer
from .profiles import validate_profile


class Runtime:
    def __init__(self, settings, client=None, home=None):
        self.settings = settings
        self.client = client or Client(settings)
        self.installer = Installer(settings,self.client,home)
        self.lock = threading.RLock()

    def connection_status(self):
        try:
            response=self.client.json('/api/integration/me')
        except SquareError as error:
            return {'connected':False,'baseUrl':self.settings.url,'authUrl':self.settings.url+'/local-access',
                    'message':str(error),'databaseAccess':False,'notice':'KEY가 없거나 바뀌었다면 웹에서 확인한 뒤 setup을 다시 실행하세요. KEY를 대화창에 넣지 마세요.'}
        return dict(response,connected=True,baseUrl=self.settings.url,trustedRoots=[str(p) for p in self.settings.roots],
                    downloadDirectory=str(self.settings.downloads),
                    transport='local-stdio',databaseAccess=False,credentialStored=self.settings.data['credentialRef'].split(':')[0],
                    encryptedTransport=self.settings.url.startswith('https:'))

    def search_items(self,query='',kind='',sort='recommended',organization='',platform='',offset=0,limit=10):
        if sort not in {'recommended','realtime','cumulative','newest'}:
            raise SquareError('정렬은 recommended/realtime/cumulative/newest 중 선택하세요.')
        if len(query)>200 or type(offset)is not int or type(limit)is not int or offset<0 or not 1<=limit<=100:
            raise SquareError('검색어는 200자 이내, limit는 1~100이어야 합니다.')
        return self.client.json('/api/catalog?'+urlencode(dict(q=query,type=kind,sort=sort,orgId=organization,platform=platform,offset=offset,limit=limit)))

    def get_item(self,tool_id):
        return self.client.json(f'/api/tools/{positive(tool_id)}')

    def download_item(self,tool_id,output_directory='',update=False):
        manifest=self.client.manifest(tool_id)
        output=scoped_path(output_directory,self.settings.roots) if output_directory else automatic_download_directory(self.settings,manifest)
        artifact=self.client.download(manifest,output,update=update)
        return {'downloaded':True,'installed':False,'file':str(artifact),'toolId':tool_id,'release':manifest['release'],
                'sha256':manifest['sha256'],'notice':'웹과 동일한 다운로드 API를 사용합니다. 업데이트 수신은 추가 집계하지 않습니다.'}

    def check_updates(self,tool_id=None):
        results=[]
        for key,record in self.installer.records().items():
            if record['origin']!=self.settings.url or tool_id is not None and record['toolId']!=tool_id:
                continue
            if record.get('status') not in {'installed','configured','verified-file'}:
                continue
            result=self.client.json(f'/api/tools/{record["toolId"]}/version-check?release={positive(record["release"])}')
            results.append(dict(installationId=key,scope=record['scope'],scopeDir=record['scopeDir'],result=result))
        return {'items':results,'automaticallyUpdated':False,'notice':'버전 확인만 수행했습니다. 실제 교체는 새 설치 준비안과 범위 확인 후 진행합니다.'}

    def inspect_source(self,source_path):
        return dict(inspect(source_path,self.settings.roots),options=self.client.json('/api/catalog/options'))

    def prepare_publish(self,metadata,source_path='',target='review',tool_id=None):
        if target not in {'review','new','update'}:
            raise SquareError('target은 review/new/update 중 선택하세요. 비슷한 이름만으로 업데이트하지 않습니다.')
        if not isinstance(metadata,dict):
            raise SquareError('등록 metadata JSON 객체가 필요합니다.')
        values=dict(metadata)
        options=self.client.json('/api/catalog/options')
        query={}
        if values.get('packageId'):
            query['packageId']=values['packageId']
        if values.get('name'):
            query['q']=values['name']
        candidates=self.client.json('/api/publish-targets?'+urlencode(query)).get('items',[])
        if target=='review':
            return {'targetSelectionRequired':True,'candidates':candidates,'options':options,'metadata':values,
                    'source':inspect(source_path,self.settings.roots) if source_path else None,
                    'notice':'기존 본인 도구의 새 버전인지 별도 신규 도구인지, 조직·업무·조회 권한을 사용자에게 확인하세요. 아직 서버에 초안을 보내지 않았습니다.'}
        required=['name','desc','platform','type','guide','orgId','categoryId']
        missing=[key for key in required if not isinstance(values.get(key),str) or not values[key].strip()]
        if type(values.get('approval'))is not bool:
            missing.append('approval (false=전체 공개 / true=조회 승인 필요)')
        if missing:
            return {'ready':False,'missing':missing,'options':options,'candidates':candidates}
        if values['orgId'] not in {x['id'] for x in options['organizations']} or values['categoryId'] not in {x['id'] for x in options['categories']}:
            raise SquareError('웹의 현재 조직·업무 선택지에서 ID를 선택하세요.')
        if target=='new' and tool_id is not None:
            raise SquareError('신규 등록에는 기존 tool_id를 지정하지 않습니다.')
        values.pop('toolId',None)
        values.pop('expectedRevision',None)
        if target=='update':
            positive(tool_id)
            # Client hints are not authority. The backend independently enforces the KEY employee as owner.
            existing=self.get_item(tool_id)
            identity=self.client.json('/api/integration/me')['user']['id']
            if existing.get('ownerId')!=identity:
                raise SquareError('본인이 등록한 도구만 새 버전을 게시할 수 있습니다.')
            values.update(toolId=tool_id,expectedRevision=existing['revision'])
        if 'installProfile' in values:
            validate_profile(values['installProfile'])
        artifact=None
        declaration=None
        local_id=uuid.uuid4().hex
        if source_path:
            artifact,declaration=package(source_path,values,self.settings.roots,self.settings.state/'publish'/local_id)
            values['mode']='file'
        elif values.get('mode') not in {'url','command'}:
            raise SquareError('배포할 파일/폴더 또는 URL·명령형 정보를 지정하세요.')
        values.setdefault('clientRequestId',str(uuid.uuid4()))
        result=self.client.draft(values,artifact)
        review=result.get('reviewUrl','')
        if isinstance(review,str) and re.fullmatch(r'/publish-review/[a-f0-9-]{16,64}',review):
            result['reviewUrl']=self.settings.url+review
        else:
            result.pop('reviewUrl',None)
        # Draft bytes are already on the web server, immutable and waiting for human web approval.
        return dict(result,localPreparationId=local_id,preparedFile=str(artifact) if artifact else None,
                    preparedSha256=sha256(artifact) if artifact else None,package=declaration,
                    notice='웹 확인 주소를 열어 내용·공개 범위를 승인하세요. MCP는 승인 API를 호출할 수 없습니다. 승인 후 publish_item으로 게시합니다.')

    def get_publish_status(self,draft_id):
        return self.client.json('/api/publish-drafts/'+self._draft_id(draft_id))

    def publish_item(self,draft_id):
        return self.client.json('/api/publish-drafts/'+self._draft_id(draft_id)+'/commit','POST',{})

    @staticmethod
    def _draft_id(value):
        if not isinstance(value,str) or not re.fullmatch('[a-f0-9-]{16,64}',value):
            raise SquareError('게시 초안 ID를 확인하세요.')
        return value
