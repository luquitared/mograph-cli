-- Drop the anonymous-handle identity model entirely.
-- Workflows are now owned directly by `users` (GitHub-backed accounts), and
-- the CLI tracks per-device Ed25519 keypairs in a dedicated `cli_devices`
-- table instead of repurposing anonymous_handles.

ALTER TABLE "workflows" DROP CONSTRAINT IF EXISTS "workflows_owner_handle_id_anonymous_handles_id_fk";
DROP INDEX IF EXISTS "workflows_owner_idx";
DELETE FROM "workflow_files";
DELETE FROM "workflow_videos";
DELETE FROM "workflows";
ALTER TABLE "workflows" DROP COLUMN IF EXISTS "owner_handle_id";

DROP TABLE IF EXISTS "cli_tokens" CASCADE;
DROP TABLE IF EXISTS "device_auth" CASCADE;
DROP TABLE IF EXISTS "anonymous_handles" CASCADE;

ALTER TABLE "workflows" ADD COLUMN "owner_user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE;
CREATE INDEX "workflows_owner_user_idx" ON "workflows"("owner_user_id");

CREATE TABLE "cli_devices" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "pubkey" text NOT NULL,
  "label" text,
  "last_used_at" timestamp with time zone,
  "created_at" timestamp with time zone NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX "cli_devices_pubkey_idx" ON "cli_devices"("pubkey");
CREATE INDEX "cli_devices_user_idx" ON "cli_devices"("user_id");
