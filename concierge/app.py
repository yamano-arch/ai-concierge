"""
AIこどもコンシェルジュ バックエンドサーバー

GET /               → HTML配信
GET /api/facilities → プロファイルでフィルタ + Claude AI推薦理由・メリット生成
GET /api/photo      → Places API写真プロキシ（APIキーをサーバー側に隠蔽）
"""

import os
import json
import random
import requests
import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from flask import Flask, jsonify, request, send_file, Response
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

PLACES_API_KEY  = os.getenv('CONCIERGE_PLACES_API_KEY', '')
ANTHROPIC_KEY   = os.getenv('ANTHROPIC_API_KEY', '')
BASE_DIR        = os.path.dirname(__file__)
FACILITIES_FILE = os.path.join(BASE_DIR, 'facilities.json')
EVENTS_FILE     = os.path.join(BASE_DIR, 'events.json')

app = Flask(__name__)

GENRE_MAP = {
    'アート':   ['アート', '工作', 'DIY'],
    '農業':     ['農業', '自然'],
    '科学':     ['科学', 'プログラミング'],
    '音楽':     ['音楽', '演劇'],
    'スポーツ': ['スポーツ'],
    '料理':     ['料理', '食育'],
}

CATEGORY_MAP = [
    (['アート', '工作', 'DIY'],           {'label': 'アート・工作',      'emoji': '🎨', 'tag': 'tag-art',     'bg': 'card-img-1'}),
    (['科学', 'プログラミング'],           {'label': '科学・プログラミング', 'emoji': '🔬', 'tag': 'tag-science', 'bg': 'card-img-2'}),
    (['農業', '自然'],                     {'label': '自然・農業',        'emoji': '🌿', 'tag': 'tag-nature',  'bg': 'card-img-3'}),
    (['料理', '食育'],                     {'label': '料理・食育',        'emoji': '🍳', 'tag': 'tag-food',    'bg': 'card-img-4'}),
    (['音楽', '演劇'],                     {'label': '音楽・演劇',        'emoji': '🎵', 'tag': 'tag-music',   'bg': 'card-img-5'}),
]

def get_category(keyword: str) -> dict:
    for keys, cat in CATEGORY_MAP:
        if any(k in keyword for k in keys):
            return cat
    return {'label': '体験', 'emoji': '✨', 'tag': 'tag-art', 'bg': 'card-img-1'}


def calc_match_score(facility: dict, selected_genres: list[str]) -> int:
    score = 65
    cat_label = facility.get('category', {}).get('label', '')
    if selected_genres and any(g in cat_label for g in selected_genres):
        score += 15
    rating = facility.get('rating')
    if rating is not None:
        score += int((float(rating) - 4.0) * 10)
    review_count = facility.get('review_count') or 0
    score += min(int(review_count / 20), 10)
    if facility.get('has_photos'):
        score += 3
    if facility.get('source') == 'event':
        score += 5  # 期間限定イベントは希少性ボーナス
    return min(score, 99)


def generate_ai_content(profile: dict, facility: dict) -> tuple[str, list[str]]:
    """Claude haiku でパーソナライズ推薦理由＋子どものメリットを生成"""
    child_name  = profile.get('name', 'お子さま')
    age         = profile.get('age', '')
    personality = profile.get('personality', '')
    policy      = profile.get('policy', '')
    cat_label   = facility.get('category', {}).get('label', '')

    is_event = facility.get('source') == 'event'
    if is_event:
        event_context = f"- 開催日時: {facility.get('event_display', '')}\n- 概要: {facility.get('summary', '')[:200]}"
        reviews_text = ''
    else:
        event_context = ''
        reviews_text = '\n'.join(
            f"「{r['text'][:150]}」"
            for r in (facility.get('reviews') or [])[:2]
            if r.get('text')
        )

    prompt = f"""子ども体験{'イベント' if is_event else '施設'}の推薦コンテンツを生成してください。

子どもの情報:
- 名前: {child_name}（{age}）
- 性格・特徴: {personality or '（未入力）'}
- 教育方針: {policy or '（未入力）'}

{'イベント' if is_event else '施設'}:
- 名前: {facility['name']}
- カテゴリ: {cat_label}
{event_context if is_event else (f"- 口コミ抜粋:{chr(10)}{reviews_text}" if reviews_text else "")}

以下の形式で出力してください（余計な説明は不要）:

推薦理由: （絵文字で始まる1文・{child_name}の特徴と施設を結びつけて・60文字以内）
メリット1: （絵文字1つ＋体験で得られること・15文字以内）
メリット2: （絵文字1つ＋体験で得られること・15文字以内）
メリット3: （絵文字1つ＋体験で得られること・15文字以内）"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        lines = msg.content[0].text.strip().splitlines()
        reason   = ''
        benefits = []
        for line in lines:
            line = line.strip()
            if line.startswith('推薦理由:'):
                reason = line.replace('推薦理由:', '').strip()
            elif line.startswith('メリット') and ':' in line:
                benefits.append(line.split(':', 1)[1].strip())
        if not reason:
            reason = f"✨ {child_name}の個性を活かせる{cat_label}施設です"
        if not benefits:
            benefits = ['🌟 新しい体験で視野が広がる', '🧠 集中力・創造力が伸びる', '👥 仲間と楽しく成長できる']
        return reason, benefits[:3]
    except Exception:
        return (
            f"✨ {child_name}の個性を活かせる{cat_label}施設です",
            ['🌟 新しい体験で視野が広がる', '🧠 集中力・創造力が伸びる', '👥 仲間と楽しく成長できる'],
        )


def enrich(facility: dict, genres: list[str]) -> dict:
    cat    = get_category(facility.get('search_keyword', ''))
    refs   = facility.get('photo_refs') or []
    addr   = facility.get('address', '')
    parts  = addr.replace('〒', '').strip().split()
    short  = ' '.join(parts[1:3]) if len(parts) >= 3 else addr[:20]
    top_review = ((facility.get('reviews') or [{}])[0]).get('text', '')

    return {
        **facility,
        'category':     cat,
        'short_address': short,
        'photo_urls':   [f"/api/photo?ref={quote(r, safe='')}" for r in refs],
        'match_score':  calc_match_score({**facility, 'category': cat}, genres),
        'top_review':   top_review,
        'is_event':     facility.get('source') == 'event',
    }


@app.route('/')
def index():
    return send_file(os.path.join(BASE_DIR, '..', 'ai_concierge_ui.html'))


@app.route('/api/facilities')
def get_facilities():
    genres_raw  = request.args.get('genres', '')
    limit       = min(int(request.args.get('limit', 3)), 10)
    exclude_raw = request.args.get('exclude', '')
    profile = {
        'name':        request.args.get('name', 'お子さま'),
        'age':         request.args.get('age', ''),
        'personality': request.args.get('personality', ''),
        'policy':      request.args.get('policy', ''),
    }

    with open(FACILITIES_FILE, 'r', encoding='utf-8') as f:
        all_facilities = json.load(f)
    all_events = []
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
            all_events = json.load(f)
    all_combined = all_facilities + all_events

    exclude_ids = set(filter(None, exclude_raw.split(',')))
    facilities  = [f for f in all_combined if f.get('place_id') not in exclude_ids]

    # ジャンルフィルタ
    genres: list[str] = []
    if genres_raw:
        genres = [g.strip() for g in genres_raw.split(',') if g.strip()]
        keywords: list[str] = []
        for g in genres:
            keywords.extend(GENRE_MAP.get(g, [g]))
        matched = [f for f in facilities if any(k in f.get('search_keyword', '') for k in keywords)]
        if not matched:
            matched = facilities
    else:
        matched = facilities

    # 施設とイベントを分離してプール構築（イベントは常に混入）
    events_pool    = [f for f in matched if f.get('source') == 'event']
    facility_pool  = [f for f in matched if f.get('source') != 'event']
    facility_pool.sort(key=lambda x: float(x.get('rating') or 0), reverse=True)
    random.shuffle(events_pool)
    random.shuffle(facility_pool[:30])
    # イベントを最大1件、残りを施設で埋める
    event_slots   = min(1, len(events_pool), max(0, limit - 1))
    facility_slots = limit - event_slots
    pool = events_pool[:event_slots] + facility_pool[:facility_slots + 10]
    random.shuffle(pool)
    selected = [enrich(f, genres) for f in pool[:limit]]

    # Claude でAI推薦理由・メリットを並列生成
    def add_ai(fac):
        reason, benefits = generate_ai_content(profile, fac)
        return {**fac, 'ai_reason': reason, 'benefits': benefits}

    result = [None] * len(selected)
    with ThreadPoolExecutor(max_workers=len(selected)) as ex:
        futures = {ex.submit(add_ai, f): i for i, f in enumerate(selected)}
        for future in as_completed(futures):
            result[futures[future]] = future.result()

    return jsonify(result)


@app.route('/api/photo')
def proxy_photo():
    """Places API の写真をプロキシしてAPIキーをクライアントに渡さない"""
    ref = request.args.get('ref', '')
    if not ref or not PLACES_API_KEY:
        return ('', 404)
    url  = f"https://places.googleapis.com/v1/{ref}/media?maxWidthPx=600&key={PLACES_API_KEY}"
    resp = requests.get(url, stream=True, timeout=10)
    return Response(
        resp.iter_content(chunk_size=8192),
        content_type=resp.headers.get('Content-Type', 'image/jpeg'),
        status=resp.status_code,
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000)
