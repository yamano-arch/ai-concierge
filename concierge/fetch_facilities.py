"""
子ども体験施設をGoogle Places APIで収集してJSONに保存するスクリプト。
取得条件: websiteフィールドあり + rating 4.0以上 + 子ども向けキーワード
"""

import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

API_KEY = os.getenv('CONCIERGE_PLACES_API_KEY')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'facilities.json')

# 検索キーワード × エリア の組み合わせ
SEARCH_TARGETS = [
    # キーワード, エリア
    ("子ども体験 工作", "東京都渋谷区"),
    ("子ども体験 工作", "東京都世田谷区"),
    ("科学実験 子ども", "東京都"),
    ("アート体験 子ども", "東京都"),
    ("農業体験 子ども", "東京都"),
    ("料理教室 子ども", "東京都"),
    ("自然体験 子ども", "東京都"),
    ("プログラミング 子ども", "東京都"),
]

def text_search(query: str) -> list[dict]:
    """Places API (New) Text Searchで施設を検索する"""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.websiteUri,places.rating,places.userRatingCount,"
            "places.regularOpeningHours,places.photos,"
            "places.editorialSummary,places.types,"
            "places.location,places.nationalPhoneNumber,"
            "places.reviews"
        ),
    }
    body = {
        "textQuery": query,
        "languageCode": "ja",
        "regionCode": "JP",
        "maxResultCount": 20,
    }
    resp = requests.post(url, headers=headers, json=body)
    resp.raise_for_status()
    return resp.json().get("places", [])


def is_valid(place: dict) -> bool:
    """予約導線あり・評価4.0以上の施設のみ通す"""
    has_website = bool(place.get("websiteUri"))
    rating = place.get("rating", 0)
    return has_website and rating >= 4.0


def normalize(place: dict, keyword: str) -> dict:
    """DBに入れやすい形に整形"""
    display_name = place.get("displayName", {})
    return {
        "place_id": place.get("id"),
        "name": display_name.get("text", ""),
        "address": place.get("formattedAddress", ""),
        "website": place.get("websiteUri", ""),
        "phone": place.get("nationalPhoneNumber", ""),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "summary": place.get("editorialSummary", {}).get("text", ""),
        "types": place.get("types", []),
        "lat": place.get("location", {}).get("latitude"),
        "lng": place.get("location", {}).get("longitude"),
        "search_keyword": keyword,
        "has_photos": len(place.get("photos", [])) > 0,
        "photo_refs": [p.get("name") for p in place.get("photos", [])[:3] if p.get("name")],
        "reviews": [
            {
                "text": r.get("text", {}).get("text", ""),
                "rating": r.get("rating"),
                "author": r.get("authorAttribution", {}).get("displayName", ""),
                "time": r.get("relativePublishTimeDescription", ""),
            }
            for r in place.get("reviews", [])
            if r.get("text", {}).get("text")
        ],
    }


def main():
    all_facilities: dict[str, dict] = {}  # place_idをキーにして重複排除

    for keyword, area in SEARCH_TARGETS:
        query = f"{keyword} {area}"
        print(f"検索中: {query}")
        try:
            places = text_search(query)
            valid = [p for p in places if is_valid(p)]
            for p in valid:
                pid = p.get("id")
                if pid and pid not in all_facilities:
                    all_facilities[pid] = normalize(p, keyword)
            print(f"  → {len(places)}件取得, {len(valid)}件有効")
        except Exception as e:
            print(f"  → エラー: {e}")
        time.sleep(0.5)  # API負荷軽減

    results = list(all_facilities.values())
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n完了: {len(results)}件を {OUTPUT_FILE} に保存しました")
    # サンプル表示
    for r in results[:3]:
        print(f"  - {r['name']} | ★{r['rating']} | {r['website']}")


if __name__ == "__main__":
    main()
