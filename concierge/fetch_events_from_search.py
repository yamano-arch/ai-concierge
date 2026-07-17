"""
Jina Search → Jina Reader → Claude Haiku で
期間限定の子ども体験イベントを自動収集して events.json に追記するスクリプト。

完全無料（Claude Haiku のトークン代のみ）で動作。

使い方:
  python concierge/fetch_events_from_search.py

必要な環境変数 (.env):
  ANTHROPIC_API_KEY: 既存のもの（Jina は登録不要・無料）
"""

import os
import sys
import json
import time
import hashlib
import requests
import anthropic
from datetime import datetime
from dotenv import load_dotenv
from ddgs import DDGS

# Windowsのコンソール文字コード問題を回避
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY', '')
OUTPUT_FILE   = os.path.join(os.path.dirname(__file__), 'events.json')

SEARCH_QUERIES = [
    "子ども 体験 イベント 東京 今週末",
    "親子 ワークショップ 東京 2026年7月",
    "子ども アート 工作 体験 期間限定",
    "キッズ 料理教室 東京 単発 イベント",
    "子ども 科学実験 イベント 東京",
    "自然体験 親子 東京近郊 夏",
    "子ども プログラミング 体験 イベント 東京",
    "親子 陶芸 体験 東京 予約",
]

SKIP_DOMAINS = [
    "youtube.com", "twitter.com", "x.com", "instagram.com",
    "facebook.com", "tiktok.com", "amazon.co.jp", "rakuten.co.jp",
    "wikipedia.org", "google.com", "google.co.jp",
]

KEYWORD_MAP = {
    "アート": "アート・工作", "工作": "アート・工作", "陶芸": "アート・工作",
    "料理": "料理・食育", "クッキング": "料理・食育",
    "科学": "科学・プログラミング", "プログラミング": "科学・プログラミング", "実験": "科学・プログラミング",
    "自然": "自然・農業", "農業": "自然・農業",
    "音楽": "音楽・演劇", "演劇": "音楽・演劇", "ダンス": "音楽・演劇",
    "スポーツ": "スポーツ",
}

def guess_keyword(text: str) -> str:
    for kw, cat in KEYWORD_MAP.items():
        if kw in text:
            return cat
    return "体験"


# ── DuckDuckGo Search: クエリ → URL一覧 ────────────────────────
def ddg_search(query: str, max_results: int = 10) -> list[dict]:
    """
    DuckDuckGo Search (完全無料・APIキー不要)
    ddgs パッケージを使用
    """
    try:
        results = list(DDGS().text(query, region="jp-jp", max_results=max_results))
        return [{"link": r["href"], "title": r.get("title", "")} for r in results if r.get("href")]
    except Exception as e:
        print(f"  DDG Search error: {e}")
        return []


# ── Jina Reader: URL → クリーンテキスト ─────────────────────────
def jina_fetch(url: str, max_chars: int = 3000) -> str:
    """
    Jina Reader API (無料・登録不要)
    https://r.jina.ai/{url} → ページ本文をテキストで返す
    """
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.text[:max_chars]
    except Exception:
        pass
    return ""


# ── Claude Haiku: テキスト → イベント構造化 ────────────────────
def extract_events(page_text: str, url: str, query: str) -> list[dict]:
    if not page_text.strip():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""以下のウェブページから、子ども・親子向けの「体験イベント・ワークショップ」情報を抽出してください。

今日の日付: {today}
ページURL: {url}

抽出条件:
- 子ども・親子向けの体験・ワークショップ・教室
- 今日({today})以降に開催
- 期間限定・単発・特定日程のもの（「毎週開催」の常設講座も可）

JSON配列で出力（該当なしは []）:
[
  {{
    "name": "イベント・教室名",
    "summary": "内容の概要（80文字以内）",
    "event_datetime": "YYYY-MM-DD（開始日）",
    "event_display": "例: 7月20日(土) 10:00〜12:00",
    "price": "例: 3,000円（材料費込）",
    "age_range": "例: 4〜10歳",
    "location": "会場名または住所",
    "website": "{url}",
    "search_keyword": "{guess_keyword(query)}"
  }}
]

ページテキスト:
{page_text}

JSON配列のみ返してください。余計な説明は不要です。"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # JSON配列部分だけ切り出す
        if "[" in raw and "]" in raw:
            raw = raw[raw.index("["):raw.rindex("]") + 1]
        return json.loads(raw)
    except json.JSONDecodeError:
        # JSON が途中で切れた場合は空リストを返す
        return []
    except Exception as e:
        print(f"     [Claude error] {e}")
        return []


# ── ユーティリティ ───────────────────────────────────────────────
def make_place_id(name: str, date: str) -> str:
    h = hashlib.md5(f"{name}{date}".encode()).hexdigest()[:10]
    return f"ev_{h}"

def load_existing() -> dict:
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return {e.get("place_id", e.get("name","")): e for e in json.load(f)}
    return {}

def save_events(events: list[dict]):
    today = datetime.now().strftime("%Y-%m-%d")
    future = [e for e in events if e.get("event_datetime", "9999") >= today]
    future.sort(key=lambda x: x.get("event_datetime", "9999"))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(future, f, ensure_ascii=False, indent=2)
    return len(future)


# ── メイン ──────────────────────────────────────────────────────
def main():
    print(f"=== event fetch start ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ===\n")

    existing   = load_existing()
    new_events: dict[str, dict] = {}
    visited    : set[str]       = set()

    for query in SEARCH_QUERIES:
        print(f"[検索] {query}")
        try:
            results = ddg_search(query)
        except Exception as e:
            print(f"  search error: {e}")
            continue

        urls = [r["link"] for r in results if r.get("link")]
        urls = [u for u in urls if not any(d in u for d in SKIP_DOMAINS)]
        print(f"  -> {len(urls)}件のURL")

        for url in urls[:5]:
            if url in visited:
                continue
            visited.add(url)

            try:
                text = jina_fetch(url)
                if not text:
                    continue

                events = extract_events(text, url, query)
                for ev in events:
                    pid = make_place_id(ev.get("name",""), ev.get("event_datetime",""))
                    ev["place_id"] = pid
                    ev["source"]   = "event"
                    if pid not in existing and pid not in new_events:
                        new_events[pid] = ev
                        print(f"     [追加] {ev['name']} ({ev.get('event_datetime','?')})")
            except Exception as e:
                print(f"     [skip] {url[:60]}... ({e})")

            time.sleep(1)

        # クエリ完了ごとに途中保存（クラッシュ対策）
        if new_events:
            all_so_far = list(existing.values()) + list(new_events.values())
            save_events(all_so_far)

        time.sleep(2)

    # 最終保存
    all_events = list(existing.values()) + list(new_events.values())
    saved = save_events(all_events)
    print(f"\n=== 完了: 新規 {len(new_events)} 件追加 / 合計 {saved} 件保存 ===")


if __name__ == "__main__":
    main()
