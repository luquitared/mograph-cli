ALTER TABLE "workflow_files" ADD COLUMN "path" text;--> statement-breakpoint
UPDATE "workflow_files" SET "path" = 'examples/' || "name" WHERE "path" IS NULL;--> statement-breakpoint
ALTER TABLE "workflow_files" ALTER COLUMN "path" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "workflow_videos" ADD COLUMN "name" text;--> statement-breakpoint
UPDATE "workflow_videos" SET "name" = split_part("r2_key", '/', -1) WHERE "name" IS NULL;--> statement-breakpoint
ALTER TABLE "workflow_videos" ALTER COLUMN "name" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "workflow_videos" ADD COLUMN "path" text;--> statement-breakpoint
UPDATE "workflow_videos" SET "path" = 'examples/' || "name" WHERE "path" IS NULL;--> statement-breakpoint
ALTER TABLE "workflow_videos" ALTER COLUMN "path" SET NOT NULL;
