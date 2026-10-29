"""MCP orchestration; the server checks KEY ownership and confirmed draft integrity."""
import re
import threading
import uuid
from urllib.parse import urlencode

from .client import Client, positive, automatic_download_directory
from .config import AuthenticationRequired, SquareError, Settings, atomic_json, scoped_path, no_links
from .files import inspect, package, sha256
from .install import Installer, digest
from .profiles import validate_profile


def fixed_package_id(item):
    """Prefer the platform identity; old servers expose it only in first releases."""
    if isinstance(item.get('packageId'),str) and item['packageId']:
        return item['packageId']
    versions=[v for v in item.get('versions',[]) if isinstance(v,dict)
              and type(v.get('n')) is int and isinstance(v.get('package'),dict)
              and isinstance(v['package'].get('packageId'),str) and v['package']['packageId']]
    first=min(versions,key=lambda v:v['n'],default=None)
    return first['package']['packageId'] if first else None


class Runtime:
    def __init__(self, settings, client=None, home=None):
        self.settings = settings
        self.client = client or Client(settings)
        self.installer = Installer(settings,self.client,home)
        self.lock = threading.RLock()

    def connection_status(self):
        try:
            response=self.client.json('/api/integration/me')
        except AuthenticationRequired as error:
            return dict(error.recovery(),connected=False,baseUrl=self.settings.url,databaseAccess=False)
        except SquareError as error:
            return {'connected':False,'authRequired':False,'baseUrl':self.settings.url,
                    'message':str(error),'databaseAccess':False,
                    'notice':'표시된 권한 또는 서버 연결 문제를 확인하세요. 이 오류만으로 KEY를 재발급할 필요는 없습니다.'}
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

    def like_item(self,tool_id,liked):
        # Use an explicit desired state so retries cannot toggle the selection.
        if type(liked) is not bool:
            raise SquareError('좋아요 상태는 true 또는 false로 지정해 주세요.')
        return self.client.json(f'/api/tools/{positive(tool_id)}/like', 'PUT', {'liked': liked})

    def download_item(self,tool_id,output_directory='',update=False):
        if type(update) is not bool:
            raise SquareError('수신 용도는 true 또는 false여야 합니다.')
        tool_id=positive(tool_id)
        identity=self.client.json('/api/integration/me').get('user')
        user_id=identity.get('id') if isinstance(identity,dict) else None
        if not isinstance(user_id,str) or not user_id:
            raise SquareError('연결된 사용자 정보를 확인할 수 없습니다. 다시 연결해 주세요.')
        account_binding=digest([self.settings.url,user_id])
        receipt=no_links(self.settings.state/'download-receipts'/(digest([self.settings.url,user_id,tool_id])+'.json'))
        installed=any(record.get('origin')==self.settings.url and record.get('toolId')==tool_id
                      and record.get('accountBinding')==account_binding
                      for record in self.installer.records().values() if isinstance(record,dict))
        # An update requested with a newly switched employee KEY is that
        # employee's first receipt, even if another account populated the cache.
        # An existing installation or a successful previous receipt for this
        # account retains the ordinary update purpose.
        known=receipt.is_file() or installed
        manifest=self.client.manifest(tool_id)
        output=scoped_path(output_directory,self.settings.roots) if output_directory else automatic_download_directory(self.settings,manifest)
        artifact=self.client.download(manifest,output,update=update and known)
        receipt_pending=False
        try:
            atomic_json(receipt,{'schemaVersion':1})
        except (OSError,SquareError):
            # A receipt is an optimization for the next call; the server
            # already accepted this download. Its per-user deduplication
            # prevents another rank point if a later call needs to retry it.
            receipt_pending=True
        return {'downloaded':True,'installed':False,'file':str(artifact),'toolId':tool_id,'release':manifest['release'],
                'sha256':manifest['sha256'],'receiptPending':receipt_pending,
                'notice':'웹과 동일한 다운로드 API를 사용합니다. 같은 사번의 반복 수신은 추가 점수가 없습니다.'}

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

    def publish_options(self, tool_id=None):
        """Show enabled organizations without choosing one for the user.

        For an update, offer the original classification as context only. A
        caller still has to obtain the user's explicit choice before preparing.
        """
        options = self.client.json('/api/catalog/options')
        result = {'organizations': options['organizations'], 'categories': options['categories']}
        if tool_id is not None:
            existing = self.get_item(positive(tool_id))
            identity = self.client.json('/api/integration/me')['user']['id']
            if existing.get('ownerId') != identity:
                raise SquareError('본인이 등록한 도구만 새 버전을 게시할 수 있습니다.')
            org_id, name = existing.get('orgId'), existing.get('org')
            if isinstance(org_id, str) and org_id:
                result['currentOrganization'] = {
                    'id': org_id, 'name': name or '',
                    'available': any(row.get('id') == org_id for row in options['organizations']),
                }
        return result

    def prepare_publish(self,metadata,source_path='',target='review',tool_id=None):
        if target not in {'review','new','update'}:
            raise SquareError('target은 review/new/update 중 선택하세요. 비슷한 이름만으로 업데이트하지 않습니다.')
        if not isinstance(metadata,dict):
            raise SquareError('등록 metadata JSON 객체가 필요합니다.')
        values=dict(metadata)
        options=self.client.json('/api/catalog/options')
        query={'packageId':values['packageId']} if values.get('packageId') else {'q':values['name']} if values.get('name') else {}
        candidates=self.client.json('/api/publish-targets?'+urlencode(query)).get('items',[])
        candidate_match='packageId' if query.get('packageId') else 'name' if query.get('q') else 'all'
        if not candidates and query.get('packageId') and values.get('name'):
            # Names are only a second candidate search, never an update decision.
            candidates=self.client.json('/api/publish-targets?'+urlencode({'q':values['name']})).get('items',[])
            candidate_match='name'
        if target=='review':
            return {'targetSelectionRequired':True,'candidates':candidates,'options':options,'metadata':values,
                    'candidateMatch':candidate_match if candidates else 'none',
                    'source':inspect(source_path,self.settings.roots) if source_path else None,
                    'notice':'기존 본인 도구의 새 버전인지 별도 신규 도구인지, 조직·업무·조회 권한을 사용자에게 확인하세요. 이름이 비슷해도 같은 도구로 확정하지 않습니다. 아직 서버에 초안을 보내지 않았습니다.'}
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
        values.pop('sourcePackageId',None)
        values.pop('packageIdentityChanged',None)
        platform_package_id=None
        if target=='update':
            positive(tool_id)
            # Client hints are not authority. The backend independently enforces the KEY employee as owner.
            existing=self.get_item(tool_id)
            identity=self.client.json('/api/integration/me')['user']['id']
            if existing.get('ownerId')!=identity:
                raise SquareError('본인이 등록한 도구만 새 버전을 게시할 수 있습니다.')
            values.update(toolId=tool_id,expectedRevision=existing['revision'])
            platform_package_id=fixed_package_id(existing)
            if source_path and platform_package_id and not values.get('packageId'):
                source=scoped_path(source_path,self.settings.roots,existing=True)
                if source.is_dir() and not (source/'ai-square.json').exists():
                    # Only a new declaration needs a default. Existing ZIP bytes,
                    # source declarations and explicitly supplied IDs stay intact.
                    values['packageId']=platform_package_id
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
        source_package_id=declaration.get('packageId') if isinstance(declaration,dict) else None
        # New servers provide the authoritative identity. Fill only absent fields
        # for an older server, without replacing its identity with raw ZIP data.
        result.setdefault('packageId',platform_package_id or source_package_id)
        result.setdefault('sourcePackageId',source_package_id)
        result.setdefault('packageIdentityChanged',bool(result['packageId'] and result['sourcePackageId'] and result['packageId']!=result['sourcePackageId']))
        notice=('게시할 파일·내용·신규/업데이트 대상·공개 범위를 확인했습니다. '
                '사용자가 이 내용으로 등록을 요청했다면 reviewDigest를 review_digest에 전달하고 '
                'confirmed=true로 publish_item을 호출해 바로 게시하세요. 별도 웹 승인은 필요 없습니다. '
                '등록 대상이나 공개 범위가 불명확할 때만 채팅에서 확인하세요.')
        if values.get('mode')=='url':
            notice+=' 등록 주소는 연결 링크와 안내로 저장됩니다. 원격 MCP 자동 연결이나 API 변환은 수행하지 않습니다.'
        if target=='update':
            notice+=' 선택한 기존 도구 ID의 새 버전으로 준비했습니다.'
            if isinstance(declaration,dict):
                notice+=' 플랫폼 고정 packageId와 원본 ZIP의 sourcePackageId를 함께 확인하세요. 식별자가 달라도 원본 ZIP을 수정하지 않습니다.'
        direct_supported=result.get('directCommitSupported') is True
        if not direct_supported:
            notice=('현재 웹 서버가 채팅에서 바로 게시하는 기능을 지원한다고 응답하지 않았습니다. '
                    '웹 서버에 최신 버전을 반영한 뒤 get_publish_status로 이 초안을 다시 확인하세요. '
                    '초안만 준비했으며 아직 게시하지 않았습니다.')
        # Immutable draft bytes are on the server. The next explicit publish call
        # confirms their digest; the website remains an optional review surface.
        return dict(result,localPreparationId=local_id,preparedFile=str(artifact) if artifact else None,
                    preparedSha256=sha256(artifact) if artifact else None,package=declaration,
                    approvalMethod='chat' if direct_supported else 'server-update-required',
                    serverReviewRequired=not direct_supported,serverUpdateRequired=not direct_supported,
                    requiresConfirmation=True,nextTool='publish_item' if direct_supported else 'get_publish_status',
                    notice=notice)

    def get_publish_status(self,draft_id):
        return self.client.json('/api/publish-drafts/'+self._draft_id(draft_id))

    def publish_item(self,draft_id,review_digest='',confirmed=False):
        if type(confirmed) is not bool:
            raise SquareError('등록 요청 확인 값은 true 또는 false여야 합니다.')
        data={}
        if confirmed:
            if not isinstance(review_digest,str) or not re.fullmatch(r'[a-f0-9]{64}',review_digest):
                raise SquareError('게시할 초안의 reviewDigest를 확인하세요. 내용이 달라졌다면 초안을 다시 준비하세요.')
            data={'confirmed':True,'reviewDigest':review_digest}
        elif review_digest:
            raise SquareError('사용자가 요청한 등록 내용·대상·공개 범위를 확인한 뒤 confirmed=true로 게시하세요.')
        # An empty body preserves the optional browser-approved legacy flow.
        return self.client.json('/api/publish-drafts/'+self._draft_id(draft_id)+'/commit','POST',data)

    @staticmethod
    def _draft_id(value):
        if not isinstance(value,str) or not re.fullmatch('[a-f0-9-]{16,64}',value):
            raise SquareError('게시 초안 ID를 확인하세요.')
        return value
