"""
connpass APIで子ども向けイベントを取得して events.json に保存するスクリプト。
取得条件: 今日以降の開催 + 東京 + 子ども関連キーワード
"""

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'events.json')
JST = timezone(timedelta(hours=9))
WEEKDAYS_JA = ['月', '火', '水', '木', '金', '土', '日']

# キーワード → search_keyword（app.py の CATEGORY_MAP で分類できるように）
SEARCH_TARGETS = [
    ('子ども 工作 東京',          '工作'),
    ('親子 科学実験 東京',        '科学'),
    ('子ども アート 東京',        'アート'),
    ('親子 料理教室 子ども 東京', '料理'),
    ('子ども プログラミング 東京','プログラミング'),
    ('親子 自然体験 東京',        '自然'),
    ('子ども 音楽 東京',          '音楽'),
    ('キッズ 体験 東京',          'アート'),
]


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
}

def fetch_connpass(keyword: str, start_from: str) -> list[dict]:
    resp = requests.get(
        'https://connpass.com/api/v1/event/',
        params={
            'keyword':     keyword,
            'count':       20,
            'order':       2,
            'start_from':  start_from,
        },
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get('events', [])


def format_dt(started_at: str) -> str:
    dt = datetime.fromisoformat(started_at)
    wd = WEEKDAYS_JA[dt.weekday()]
    return f"{dt.month}/{dt.day}（{wd}） {dt.hour:02d}:{dt.minute:02d}〜"


def normalize(event: dict, search_keyword: str) -> dict:
    started_at   = event.get('started_at', '')
    event_display = ''
    if started_at:
        try:
            event_display = format_dt(started_at)
        except Exception:
            pass

    summary  = event.get('catch', '') or (event.get('description') or '')[:200]
    limit    = event.get('limit')
    accepted = event.get('accepted', 0) or 0
    remaining = (limit - accepted) if isinstance(limit, int) else None

    return {
        'place_id':        f"connpass_{event['id']}",
        'name':            event.get('title', ''),
        'address':         event.get('address', '') or event.get('place', ''),
        'website':         event.get('event_url', ''),
        'phone':           '',
        'rating':          None,
        'review_count':    accepted,
        'summary':         summary,
        'types':           ['event'],
        'lat':             event.get('lat'),
        'lng':             event.get('lon'),
        'search_keyword':  search_keyword,
        'has_photos':      False,
        'photo_refs':      [],
        'reviews':         [],
        'source':          'connpass',
        'event_display':   event_display,
        'event_datetime':  started_at,
        'event_capacity':  limit,
        'event_remaining': remaining,
        'organizer':       event.get('owner_display_name', ''),
    }


def main():
    now = datetime.now(tz=JST)
    start_from = now.strftime('%Y-%m-%dT%H:%M:%S')
    all_events: dict[int, dict] = {}

    for keyword, search_kw in SEARCH_TARGETS:
        print(f"検索中: {keyword}")
        try:
            events = fetch_connpass(keyword, start_from)
            added = 0
            for e in events:
                eid = e['id']
                if eid not in all_events:
                    all_events[eid] = normalize(e, search_kw)
                    added += 1
            print(f"  → {len(events)}件取得, {added}件追加")
        except Exception as ex:
            print(f"  → エラー: {ex}")
        time.sleep(0.5)

    results = list(all_events.values())
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完了: {len(results)}件 → {OUTPUT_FILE}")
    for r in results[:3]:
        print(f"  - {r['name']} | {r['event_display']}")


if __name__ == '__main__':
    main()
