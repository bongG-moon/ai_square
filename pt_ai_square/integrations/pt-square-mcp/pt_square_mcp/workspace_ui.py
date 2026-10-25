"""Compatibility entry for old commands: location selection now happens in chat."""
import json


def main(argv=None):
    # Old --request files are intentionally ignored; they cannot grant access.
    print(json.dumps({'selected': False, 'chatRequired': True, 'nextTool': 'select_workspace',
                      'message': 'AI 채팅에서 현재 프로젝트/공통(내 계정)/기타 경로를 선택해 주세요. 별도 폴더 창은 열지 않습니다.'},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
