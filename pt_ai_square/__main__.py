import argparse
import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _square_bootstrap import load_package
    __package__ = load_package().__name__

from . import create_app

def main(argv=None):
    parser=argparse.ArgumentParser(description='P&T AI SQUARE')
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--host');run.add_argument('--port',type=int);run.add_argument('--dev',action='store_true')
    sub.add_parser('sync-activity',help='기존 이력과 저장 대기 이력을 MongoDB에 안전하게 반영')
    migrate=sub.add_parser('migrate-legacy',help='서버를 중지한 후 이전 SQLite 자료를 MongoDB에 한 번 이전');migrate.add_argument('path')
    args=parser.parse_args(argv)
    try: app=create_app()
    except ValueError as error: parser.error(str(error))
    if args.command=='migrate-legacy':
        from .migrate_legacy import migrate
        with app.app_context(): print(migrate(args.path))
        return
    if args.command=='sync-activity':
        from .activity import flush, is_mongo
        with app.app_context():
            if not is_mongo(): parser.error('runtime_config.py에서 PTAI_ACTIVITY_BACKEND=mongodb를 설정하세요.')
            print(f'MongoDB에 {flush()}개 이력을 반영했습니다.')
        return
    args.host=args.host or app.config['HOST'];args.port=args.port or app.config['PORT']
    if app.config['AUTH_MODE']=='mock' and args.host not in {'127.0.0.1','localhost','::1'}: parser.error('mock 모드는 로컬 주소로만 실행하세요.')
    mode='SSO 미사용' if app.config['AUTH_MODE']=='mock' else 'SSO 사용'
    use_flask=args.dev
    if not use_flask:
        try: from waitress import serve
        except ImportError:
            if app.config['AUTH_MODE']=='mock' and args.host in {'127.0.0.1','localhost','::1'}:
                print('Waitress가 없어 로컬 확인용 Flask 서버로 실행합니다. (디버그 꺼짐)',flush=True)
                use_flask=True
            else:
                requirements=Path(__file__).resolve().parent/'requirements.txt'
                parser.error(f'Waitress를 불러올 수 없습니다. 실행한 Python으로 설치하세요: "{sys.executable}" -m pip install -r "{requirements}"')
    print(f'P&T AI SQUARE 시작 요청: http://{args.host}:{args.port} ({mode})',flush=True)
    if use_flask:
        app.run(host=args.host,port=args.port,debug=False,use_reloader=False)
    else:
        serve(app,host=args.host,port=args.port,threads=8)

if __name__=='__main__': main()
