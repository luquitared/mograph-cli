-- Reusable bundles (character/voice/env refs, style packs) that workflows
-- can pull on-demand. Distinct from workflows: no main video, no clip count.

CREATE TABLE "packs" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "slug" text NOT NULL,
  "kind" text NOT NULL,
  "title" text NOT NULL,
  "summary" text,
  "readme_md" text NOT NULL DEFAULT '',
  "owner_user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "visibility" text NOT NULL DEFAULT 'public',
  "total_bytes" bigint,
  "total_files" integer,
  "created_at" timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at" timestamp with time zone NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX "packs_slug_idx" ON "packs"("slug");
CREATE INDEX "packs_kind_idx" ON "packs"("kind");
CREATE INDEX "packs_owner_user_idx" ON "packs"("owner_user_id");
CREATE INDEX "packs_created_idx" ON "packs"("created_at");

CREATE TABLE "pack_files" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "pack_id" uuid NOT NULL REFERENCES "packs"("id") ON DELETE CASCADE,
  "name" text NOT NULL,
  "path" text NOT NULL,
  "r2_key" text NOT NULL,
  "size_bytes" bigint,
  "created_at" timestamp with time zone NOT NULL DEFAULT now()
);
CREATE INDEX "pack_files_pack_idx" ON "pack_files"("pack_id");
