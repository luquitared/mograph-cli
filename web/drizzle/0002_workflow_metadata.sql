ALTER TABLE "workflows" ADD COLUMN "models" text[];--> statement-breakpoint
ALTER TABLE "workflows" ADD COLUMN "clip_count" integer;--> statement-breakpoint
ALTER TABLE "workflows" ADD COLUMN "total_duration_s" integer;--> statement-breakpoint
ALTER TABLE "workflows" ADD COLUMN "total_bytes" bigint;