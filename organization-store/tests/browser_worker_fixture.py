"""UI-only synthetic service. No real KEY, platform, profile or installer access."""
import json
import sys
import time
from pathlib import Path

r = json.load(sys.stdin)
data = Path(r['dataDirectory']); data.mkdir(parents=True, exist_ok=True)
file = data/'fixture-state.json'
state = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {'connected': False, 'liked': False, 'records': [], 'actions': []}
action, p = r['action'], r.get('payload', {})
state['actions'].append(action)  # Never store request payloads (especially KEY).
items = [
 {'id': 1, 'name': '업무 보고서 작성', 'type': 'Skill', 'desc': '업무 자료를 정리해 보고서 초안을 만듭니다. 제공된 양식과 작성 기준을 함께 활용합니다.', 'category': '문서 작성', 'workTags': ['보고서', '요약']},
 {'id': 2, 'name': '사내 자료 검색', 'type': 'Tool', 'desc': '허용된 사내 자료를 찾아 근거와 함께 정리합니다.', 'category': '자료 검색', 'workTags': ['검색']},
 {'id': 3, 'name': '설비 점검 도우미', 'type': '하네스', 'desc': '설비 점검 작업을 도와주는 Windows 프로그램입니다. 설치 파일을 받은 뒤 안내에 따라 실행합니다.', 'category': '제조 업무', 'workTags': ['점검']},
 {'id': 4, 'name': '업무 시작 가이드', 'type': 'Skill', 'desc': '반복하는 작업의 시작 순서와 체크리스트를 확인합니다.', 'category': '업무 지원', 'workTags': ['체크리스트']},
 {'id': 5, 'name': '문서 연결 MCP', 'type': 'MCP', 'desc': '승인된 폴더의 문서 검색을 연결합니다.', 'category': '자료 검색', 'workTags': ['문서']},
 {'id': 6, 'name': '업무 템플릿 모음', 'type': '플러그인', 'desc': '팀에서 사용하는 요청 양식과 스킬을 모았습니다.', 'category': '업무 지원', 'workTags': ['템플릿']},
]
for item in items:
 item.update(org='AX 추진팀', orgId='ax', owner='업무 담당자', registrantName='예시 등록자', registrantId='example-author', platform='Claude', access='approved', statistics={'likes': 12 + int(state['liked']), 'downloads': 28, 'views': 120 + item['id']}, liked=state['liked'])
if action == 'status':
 result = {'configured': state['connected'], 'baseUrl': 'https://square.example.test' if state['connected'] else '', 'existingConnectionAvailable': False}
elif action == 'connect':
 state['connected'] = True; result = {'configured': True}
elif action == 'disconnect':
 state['connected'] = False; result = {'configured': False}
elif action == 'options':
 result = {'organizations': [{'id': 'ax', 'name': 'AX 추진팀'}]}
elif action == 'catalog':
 result = {'items': [i for i in items if p.get('q', '') in i['name'] and (not p.get('type') or p['type'] == i['type'])], 'total': len(items), 'nextOffset': None}
elif action == 'detail':
 item = next(i for i in items if i['id'] == p['toolId'])
 result = {'item': dict(item, mode='zip', active=2, views=item['statistics']['views'], downloads=28, likes=item['statistics']['likes'], guide='1. 사용할 자료를 준비합니다.\n2. 대화에서 기능을 선택하고 요청합니다.\n3. 결과를 확인한 뒤 필요한 내용을 보완합니다.', environment='Windows · Claude Code', changes='첫 배포 · 기본 업무 흐름 지원', workflow={'steps':[{'title':'자료 준비','description':'사용할 문서를 선택합니다.'},{'title':'요청 작성','description':'원하는 결과를 입력합니다.'},{'title':'결과 확인','description':'결과를 확인하고 보완합니다.'}]}, versions=[{'n': 2, 'filename': 'fixture.zip', 'note':'업무 흐름과 안내를 개선했습니다.','created':1792800000},{'n':1,'filename':'fixture-v1.zip','note':'첫 배포','created':1792700000}], comments=[]), 'manifest': {'release':2,'downloadUrl': '/download/1/2','installProfile':{'scopes':['project','user']}}, 'canInstall': item['type'] in {'Skill','MCP'}, 'installNotice': '검증용 예시입니다. 실제 서버나 개인 프로필에는 접근하지 않습니다.', 'webUrl': 'https://square.example.test/'}
elif action == 'like':
 state['liked'] = p['liked']; result = {'liked': state['liked'], 'count': 12+int(state['liked'])}
elif action == 'download':
 result = {'downloaded': True, 'installed': False, 'file': str(data/'example.zip')}
elif action == 'prepareInstall':
 scope_dir = r['context'].get('selectedDirectory') if p['scope'] == 'directory' else r['context'].get('workspace') if p['scope'] == 'project' else str(data/'isolated-user')
 state['plan'] = {'scope':'project' if p['scope']=='directory' else p['scope'],'scopeDir':scope_dir,'target':str(Path(scope_dir)/'.claude/skills/example')}
 result = {'canInstall': True, 'planId': 'fixture-plan', 'approvalDigest': 'fixture-digest', 'scope': p['scope'], 'scopeDir': scope_dir, 'destination': state['plan']['target'], 'release': 2}
elif action == 'install':
 time.sleep(.25)
 state['records'] = [{'installationId': 'fixture-install', 'toolId': 1, 'release': 2, **state['plan'], 'status': 'installed', 'rollbackAvailable': True}]
 result = {'installed': True, 'status': 'installed'}
elif action == 'installations':
 result = {'items': state['records'], 'recovery': state.get('recovery', {'recovered': [], 'blocked': []})}
elif action == 'checkUpdates':
 result = {'items': [{'installationId': row['installationId'], 'result': {'updateAvailable': False}} for row in state['records']]}
elif action == 'verify':
 result = {'filesIntact': True, 'connectionVerified': False, 'notice': '검증용 설치 기록을 확인했습니다.'}
elif action == 'rollback':
 state['records'] = []; result = {'restored': True}
else:
 raise ValueError('Unexpected fixture request')
file.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False))
