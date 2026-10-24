"""CLI setup uses a hidden KEY prompt; no KEY argument or MCP tool parameter."""
import argparse
import getpass
import json
from pathlib import Path
import sys
import webbrowser

from .config import DEFAULT_CONFIG, SquareError, normalize_url, Settings
from .onboarding import connect, resolve_connection


def main(argv=None):
    parser=argparse.ArgumentParser(description='P&T AI SQUARE 로컬 MCP (별도 서버/포트 없음)')
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    subs=parser.add_subparsers(dest='command',required=True)
    setup=subs.add_parser('setup',help='KEY를 입력해 웹 계정을 연결합니다. 주소와 다운로드 폴더는 자동 설정됩니다.')
    setup.add_argument('--url',help='고급 설정: ZIP의 서버 주소를 명시적으로 변경')
    setup.add_argument('--workspace',action='append',help='고급 설정: 추가로 허용할 기존 작업 폴더. 여러 번 지정 가능')
    setup.add_argument('--token-from-env',action='store_true',help='영구 저장 대신 PTAI_API_TOKEN 사용')
    setup.add_argument('--accept-http-origin',help='HTTP 비암호화 위험을 확인한 정확한 서버 origin (KEY 아님)')
    subs.add_parser('connect',help='KEY만 입력하는 연결 창 열기')
    subs.add_parser('auth',help='웹 KEY 발급 화면 열기')
    subs.add_parser('serve',help='MCP 호스트가 실행하는 stdio 모드')
    subs.add_parser('status',help='연결 상태 확인 (KEY는 출력하지 않음)')
    args=parser.parse_args(argv)
    try:
        if args.command=='setup':
            url=resolve_connection(args.config,args.url)
            print('연결할 AI SQUARE: '+url,file=sys.stderr)
            acknowledged=False
            if url.startswith('http:'):
                print('주의: HTTP는 KEY와 파일 전송을 암호화하지 않습니다. 회사의 신뢰할 수 있는 네트워크에서만 사용하세요.',file=sys.stderr)
                if args.accept_http_origin:
                    acknowledged=normalize_url(args.accept_http_origin)==url
                elif sys.stdin.isatty():
                    acknowledged=input('표시된 사이트에 연결할까요? [y/N]: ').strip().lower() in {'y','yes','예'}
                if not acknowledged:
                    raise SquareError('HTTP 연결 확인이 필요합니다. 연결 창에서 확인하거나 --accept-http-origin에 정확한 주소를 넣으세요.')
            token=None
            if not args.token_from_env:
                if not sys.stdin.isatty():
                    raise SquareError('KEY 숨김 입력은 대화형 터미널에서 실행하세요. 자동 설정은 --token-from-env를 사용하세요.')
                token=getpass.getpass('웹에서 발급한 연결 KEY (없으면 Enter): ').strip()
                if not token:
                    webbrowser.open(url+'/local-access')
                    print('KEY 발급 후 setup을 다시 실행하세요: '+url+'/local-access')
                    return 0
            data=connect(args.config,url,token,args.workspace,allow_http=acknowledged,
                         token_from_env=args.token_from_env)
            print(json.dumps(data,ensure_ascii=False))
            return 0
        if args.command=='connect':
            from .connection_ui import open_connection
            return open_connection(args.config)
        if args.command=='serve':
            from .server import make_server
            make_server(args.config).run(transport='stdio')
            return 0
        if args.command=='auth':
            link=resolve_connection(args.config)+'/local-access'
            webbrowser.open(link)
            print(link)
            return 0
        settings=Settings(args.config)
        from .runtime import Runtime
        print(json.dumps(Runtime(settings).connection_status(),ensure_ascii=False,indent=2))
        return 0
    except (SquareError,OSError) as error:
        message=str(error) if isinstance(error,SquareError) else '설정 파일·네트워크에 접근하지 못했습니다.'
        print(message,file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
