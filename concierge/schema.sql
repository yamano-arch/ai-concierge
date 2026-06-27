-- Supabase SQL Editor に貼り付けて実行
-- AIこどもコンシェルジュ 施設テーブル

CREATE TABLE IF NOT EXISTS facilities (
  id                BIGSERIAL PRIMARY KEY,
  place_id          TEXT UNIQUE NOT NULL,
  name              TEXT NOT NULL,
  address           TEXT,
  website           TEXT,
  phone             TEXT,
  rating            NUMERIC(2,1),
  review_count      INTEGER,
  summary           TEXT,
  types             TEXT[],
  lat               NUMERIC(10,7),
  lng               NUMERIC(10,7),
  search_keyword    TEXT,
  has_photos        BOOLEAN DEFAULT FALSE,
  photo_ref         TEXT,
  reviews           JSONB DEFAULT '[]',
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  last_verified_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 評価順クエリを高速化
CREATE INDEX IF NOT EXISTS idx_facilities_rating     ON facilities (rating DESC);
-- カテゴリ絞り込み高速化
CREATE INDEX IF NOT EXISTS idx_facilities_keyword    ON facilities USING GIN (to_tsvector('simple', search_keyword));
-- 位置情報検索（将来の近所フィルタ用）
CREATE INDEX IF NOT EXISTS idx_facilities_location   ON facilities (lat, lng);

-- 匿名ユーザーに読み取りのみ許可（Supabase RLS）
ALTER TABLE facilities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read" ON facilities FOR SELECT USING (true);
