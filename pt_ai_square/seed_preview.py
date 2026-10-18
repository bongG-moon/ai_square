"""Create labeled examples only in the dedicated .preview database. Never production."""
import io
import json
import zipfile
from pathlib import Path
from . import create_app

def main():
    app=create_app({'AUTH_MODE':'mock','MOCK_ADMIN':True,'MONGODB_URI':'mongodb://127.0.0.1:27018/','MONGODB_DATABASE':'pt_ai_square_preview','DATA_DIR':str(Path(__file__).parent/'.preview'),'SESSION_COOKIE_SECURE':False})
    c=app.test_client();bootstrap=c.get('/api/bootstrap').json
    if len(bootstrap['items'])>=10:return
    h={'X-CSRF-Token':bootstrap['csrf']}
    rows=[('주간 보고서 작성','Skill','제조팀','주간 보고,실적 정리'),('문서 검색 연결','MCP','기술팀','문서 검색,매뉴얼'),('장비 점검 요약','Skill','장비팀','장비 점검,이력 정리'),('회의록 정리','Skill','공통','회의록,할 일'),('품질 데이터 정리','Tool','제조팀','품질 분석,수율 검토'),('업무 실행 하네스','하네스','기술팀','업무 자동화,테스트'),('코드 검토 플러그인','플러그인','기술팀','코드 검토,개발'),('Excel 활용 안내','Skill','공통','Excel,보고서'),('설비 매뉴얼 안내','MCP','장비팀','설비,매뉴얼')]
    existing={x['name'] for x in bootstrap['items']}
    for name,kind,org,tags in rows:
        name='[예제] '+name
        if name in existing:continue
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('README.md','# '+name+'\n화면 확인용 예제이며 실제 업무 기능은 포함하지 않습니다.\n')
        b.seek(0)
        m=dict(name=name,desc='화면 확인용 자료입니다. 실제 업무 기능을 포함하지 않습니다.',owner='개발 사용자',org=org,platform='Claude',type=kind,category='공통 업무',visibility='전체 공개',guide='ZIP의 README.md를 읽어주세요. 화면 확인용 예제이며 설치하지 않습니다.',workTags=tags,approval=False,audience=[],mode='file')
        r=c.post('/api/tools',data={'metadata':json.dumps(m),'artifact':(b,'preview.zip')},headers=h)
        assert r.status_code==201,r.json
    print('Preview examples created. Production instance is untouched.')

if __name__=='__main__':main()
