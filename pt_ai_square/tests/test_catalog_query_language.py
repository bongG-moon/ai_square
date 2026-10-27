"""Plain Korean requests retain literal names and rank concrete work first."""
import pytest
from werkzeug.exceptions import BadRequest

from pt_ai_square.backend.catalog_search import query_groups, relevance


def item(name, desc='', tags=()):
    return {'_id': 1, 'data': {'name': name, 'desc': desc, 'workTags': list(tags)}}


@pytest.mark.parametrize('query, intended, other', [
    ('엑셀 파일을 하나로 합치고 싶어',
     item('Excel 병합', '여러 통합 문서를 한 파일로 모읍니다.'),
     item('문서 파일 정리', '파일 이름을 바꾸고 자료를 분류합니다.')),
    ('회의 내용을 정리해 줘',
     item('회의록 만들기', '회의에서 결정한 일을 정리합니다.'),
     item('폴더 정리', '폴더 내용을 정리합니다.')),
    ('PPT 발표 자료 만들기',
     item('PowerPoint 제작', '슬라이드를 만듭니다.'),
     item('자료 만들기', '문서 내용을 작성합니다.')),
    ('전에 하던 업무를 이어서 하고 싶어',
     item('작업 기록 모아 보기', '지난 기록을 보고 업무를 이어서 합니다.'),
     item('업무 자료 작성', '업무 내용을 문서로 만듭니다.')),
])
def test_everyday_requests_rank_the_subject_above_generic_words(query, intended, other):
    groups = query_groups(query)
    assert relevance(intended, query, groups)[:3] > relevance(other, query, groups)[:3]


@pytest.mark.parametrize('name', ['코드에서', '모두를', '요약하기', 'PPT 발표 자료', 'meeting minutes'])
def test_literal_names_survive_request_word_and_phrase_handling(name):
    exact, matches, _, fields = relevance(item(name), name, query_groups(name))
    assert exact and matches > 0 and 'name' in fields


def test_alias_repetition_does_not_inflate_relevance():
    tool = item('PowerPoint 자료')
    once = relevance(tool, 'PPT', query_groups('PPT'))[1:3]
    repeated = relevance(tool, 'PPT 발표 자료 파워포인트', query_groups('PPT 발표 자료 파워포인트'))[1:3]
    assert repeated == once


def test_punctuation_or_request_only_is_not_a_match_all_query():
    for query in ['.*', '추천해줘', '좀 알려줘']:
        assert relevance(item('엑셀 병합', '파일을 합칩니다.'), query, query_groups(query))[1] == 0
    assert query_groups('') == []
    with pytest.raises(BadRequest):
        query_groups(' '.join(f'word{i}' for i in range(13)))
