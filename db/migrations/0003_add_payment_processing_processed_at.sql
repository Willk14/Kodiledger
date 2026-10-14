ALTER TABLE payment_processing
ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;
