-- 001_create_tables.sql
-- Creates machines, locks, transactions, and events tables with indexes

-- Create machines table
CREATE TABLE IF NOT EXISTS machines (
  id TEXT PRIMARY KEY,
  name TEXT,
  location TEXT,
  api_key TEXT,
  current_stock INTEGER DEFAULT 0,
  status TEXT DEFAULT 'idle',
  display_code TEXT,
  display_code_expires_at TIMESTAMP WITH TIME ZONE,
  last_seen_at TIMESTAMP WITH TIME ZONE
);

-- Create locks table
CREATE TABLE IF NOT EXISTS locks (
  machine_id TEXT PRIMARY KEY REFERENCES machines(id) ON DELETE CASCADE,
  locked_by TEXT,
  access_code_hash TEXT,
  locked_at TIMESTAMP WITH TIME ZONE,
  expires_at TIMESTAMP WITH TIME ZONE,
  status TEXT -- locked | consumed | expired
);

-- Create transactions table
CREATE TABLE IF NOT EXISTS transactions (
  id UUID PRIMARY KEY,
  machine_id TEXT REFERENCES machines(id),
  client_id TEXT,
  access_code TEXT,
  amount INTEGER,
  quantity INTEGER,
  payment_status TEXT,
  created_at TIMESTAMP WITH TIME ZONE,
  completed_at TIMESTAMP WITH TIME ZONE,
  dispensed INTEGER
);

-- Create events table
CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  machine_id TEXT,
  client_id TEXT,
  type TEXT,
  payload JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_locks_expires_at ON locks(expires_at);
CREATE INDEX IF NOT EXISTS idx_transactions_payment_status ON transactions(payment_status);
CREATE INDEX IF NOT EXISTS idx_machines_display_code ON machines(display_code);
