-- =====================================================================
-- INBOXORCHESTRATOR AI - ESSENTIAL SUPABASE DATABASE INDEXES
-- =====================================================================
-- Recommended SQL DDL script matched strictly to backend query patterns.
-- DO NOT RUN AUTOMATICALLY IN CODE - Apply manually in Supabase SQL Editor if desired.

-- 1. Connected Accounts: Fast filtering of active mailboxes during background sync
CREATE INDEX IF NOT EXISTS idx_connected_accounts_user_active 
ON public.connected_accounts (user_id, is_active);

-- 2. Email Threads: Inbox sorting by connected account & SLA background worker checks
CREATE INDEX IF NOT EXISTS idx_email_threads_account_last_msg 
ON public.email_threads (connected_account_id, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_email_threads_sla_lookup 
ON public.email_threads (workflow_status, last_message_at);

-- 3. Emails: Message timeline rendering and batch sync deduplication
CREATE INDEX IF NOT EXISTS idx_emails_thread_received 
ON public.emails (thread_id, received_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_emails_gmail_message_id 
ON public.emails (gmail_message_id);

-- 4. Email Facts: Fast retrieval of extracted facts per email/thread
CREATE INDEX IF NOT EXISTS idx_email_facts_email_id 
ON public.email_facts (email_id);

-- 5. Tasks: Dashboard filtering by status/due_date & background task deduplication
CREATE INDEX IF NOT EXISTS idx_tasks_user_status_due 
ON public.tasks (user_id, status, due_date ASC);

CREATE INDEX IF NOT EXISTS idx_tasks_user_fingerprint 
ON public.tasks (user_id, action_fingerprint);

-- 6. Email Drafts: Fast lookup of active unsent draft per thread
CREATE INDEX IF NOT EXISTS idx_email_drafts_thread_status 
ON public.email_drafts (thread_id, status);
