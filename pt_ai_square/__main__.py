import argparse
from . import create_app

def main(argv=None):
    parser=argparse.ArgumentParser(description='P&T AI SQUARE')
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--host');run.add_argument('--port',type=int);run.add_argument('--dev',action='store_true')
    sub.add_parser('sync-activity',help='기존 이력과 저장 대기 이력을 MongoDB에 안전하게 반영')
    migrate=sub.add_parser('migrate-legacy',help='서버를 중지한 후 이전 SQLite 자료를 MongoDB에 한 번 이전');migrate.add_argument('path')
    args=parser.parse_args(argv);app=create_app()
    if app.config['DEMO_MODE'] and args.command!='run':
        parser.error('데모 모드입니다. runtime_config.py에 MONGODB_URI를 입력한 후 실행하세요.')
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
    mode='데모 · 저장 안 됨' if app.config['DEMO_MODE'] else app.config['AUTH_MODE']
    print(f'P&T AI SQUARE: http://{args.host}:{args.port} ({mode})',flush=True)
    if args.dev: app.run(host=args.host,port=args.port,debug=False,use_reloader=False)
    else:
        try: from waitress import serve
        except ImportError: parser.error('requirements.txt를 설치하거나 로컬 점검에만 --dev를 사용하세요.')
        serve(app,host=args.host,port=args.port,threads=8)

if __name__=='__main__': main()
