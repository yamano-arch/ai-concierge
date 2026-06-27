"""
facilities.json の内容を Supabase の facilities テーブルに一括投入。
既存レコードは place_id をキーにしてUPSERT（上書き更新）。
"""

import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
FACILITIES_FILE = os.path.join(os.path.dirname(__file__), 'facilities.json')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(".env に SUPABASE_URL と SUPABASE_SERVICE_KEY を設定してください")

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

def upsert_batch(records: list[dict]) -> None:
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/facilities",
        headers=HEADERS,
        json=records,
    )
    if resp.status_code not in (200, 201):
        print(f"  エラー {resp.status_code}: {resp.text[:200]}")
    else:
        print(f"  ✅ {len(records)}件 upsert完了")

def main():
    with open(FACILITIES_FILE, "r", encoding="utf-8") as f:
        facilities = json.load(f)

    print(f"投入対象: {len(facilities)}件")

    # 10件ずつバッチ処理
    batch_size = 10
    for i in range(0, len(facilities), batch_size):
        batch = facilities[i : i + batch_size]
        print(f"バッチ {i//batch_size + 1}: {i+1}〜{min(i+batch_size, len(facilities))}件目")
        upsert_batch(batch)
        time.sleep(0.3)

    print(f"\n完了: {len(facilities)}件を Supabase に投入しました")

if __name__ == "__main__":
    main()
