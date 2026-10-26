"""Public, fixed-path download for the maintained file-distribution Skill."""
from pathlib import Path

from flask import Blueprint, current_app, send_file
from werkzeug.exceptions import ServiceUnavailable


distribution_skill = Blueprint('distribution_skill', __name__)
SOURCE_NAMES = ('pt-file-distribution.zip', 'PT_AI_SQUARE_파일배포_Skill.zip')
DOWNLOAD_NAME = 'pt-file-distribution.zip'
UNAVAILABLE = ('파일 배포 Skill 파일이 서버에 준비되지 않았습니다. '
               '운영자가 최신 배포의 static/guides 파일을 반영해야 합니다.')


@distribution_skill.get('/resources/distribution-skill.zip')
def download():
    # No request parameter selects the file or changes its contents. Keep the
    # legacy filename as a fallback for deployments copied before the new build.
    guides = Path(current_app.static_folder) / 'guides'
    for name in SOURCE_NAMES:
        source = guides / name
        try:
            if not source.is_file():
                continue
            response = send_file(source, mimetype='application/zip',
                                 as_attachment=True, download_name=DOWNLOAD_NAME,
                                 conditional=True)
        except FileNotFoundError:
            # A deployment may replace the file between the check and open.
            continue
        except OSError:
            raise ServiceUnavailable(UNAVAILABLE) from None
        # The URL remains stable across updates: validate cached content before
        # reuse, without adding credentials or generating a ZIP per request.
        response.headers['Cache-Control'] = 'public, no-cache'
        return response
    raise ServiceUnavailable(UNAVAILABLE)
