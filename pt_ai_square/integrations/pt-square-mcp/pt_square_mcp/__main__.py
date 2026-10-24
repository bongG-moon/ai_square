"""CLI setup uses a hidden KEY prompt; no KEY argument or MCP tool parameter."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import webbrowser

from .config import DEFAULT_CONFIG, SquareError, normalize_url, save_config, Settings


def main(argv=None):
    parser=argparse.ArgumentParser(description='P&T AI SQUARE 로컬 MCP (별도 서버/포트 없음)')
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    subs=parser.add_subparsers(dest='command',required=True)
    setup=subs.add_parser('setup',help='서버·작업 폴더·KEY를 처음 한 번 연결')
    setup.add_argument('--url',required=True)
    setup.add_argument('--workspace',action='append',required=True,help='허용할 작업 폴더. 여러 번 지정 가능')
    setup.add_argument('--token-from-env',action='store_true',help='영구 저장 대신 PTAI_API_TOKEN 사용')
    setup.add_argument('--accept-http-origin',help='HTTP 비암호화 위험을 확인한 정확한 서버 origin (KEY 아님)')
    subs.add_parser('auth',help='웹 KEY 발급 화면 열기')
    subs.add_parser('serve',help='MCP 호스트가 실행하는 stdio 모드')
    subs.add_parser('status',help='연결 상태 확인 (KEY는 출력하지 않음)')
    args=parser.parse_args(argv)
    try:
        if args.command=='setup':
            url=normalize_url(args.url)
            acknowledged=False
            if url.startswith('http:'):
                print('주의: HTTP는 KEY와 파일 전송을 암호화하지 않습니다. 회사의 신뢰할 수 있는 네트워크에서만 사용하세요.',file=sys.stderr)
                if args.accept_http_origin:
                    acknowledged=normalize_url(args.accept_http_origin)==url
                elif sys.stdin.isatty():
                    acknowledged=input('이 주소에 연결하려면 정확한 주소를 다시 입력하세요: ').strip()==url
                if not acknowledged:
                    raise SquareError('HTTP 주소 확인이 필요합니다. --accept-http-origin에 확인한 정확한 주소를 넣으세요.')
            token=None
            if not args.token_from_env:
                if not sys.stdin.isatty():
                    raise SquareError('KEY 숨김 입력은 대화형 터미널에서 실행하세요. 자동 설정은 --token-from-env를 사용하세요.')
                token=getpass.getpass('웹에서 발급한 연결 KEY (없으면 Enter): ').strip()
                if not token:
                    webbrowser.open(url+'/local-access')
                    print('KEY 발급 후 setup을 다시 실행하세요: '+url+'/local-access')
                    return 0
            data=save_config(args.config,url,args.workspace,token,allow_http=acknowledged)
            print(json.dumps({'configured':True,'baseUrl':url,'config':str(args.config.resolve()),'credentialRef':data['credentialRef']},ensure_ascii=False))
            return 0
        if args.command=='serve':
            from .server import make_server
            make_server(args.config).run(transport='stdio')
            return 0
        settings=Settings(args.config)
        if args.command=='auth':
            link=settings.url+'/local-access'
            webbrowser.open(link)
            print(link)
            return 0
        from .runtime import Runtime
        print(json.dumps(Runtime(settings).connection_status(),ensure_ascii=False,indent=2))
        return 0
    except (SquareError,OSError) as error:
        message=str(error) if isinstance(error,SquareError) else '설정 파일·네트워크에 접근하지 못했습니다.'
        print(message,file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
