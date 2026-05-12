CREATE TABLE "anonymous_handles" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"handle" text NOT NULL,
	"pubkey" text NOT NULL,
	"claimed_by_user_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "cli_tokens" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"handle_id" uuid NOT NULL,
	"token_hash" text NOT NULL,
	"label" text,
	"last_used_at" timestamp with time zone,
	"revoked_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "device_auth" (
	"code" text PRIMARY KEY NOT NULL,
	"handle_id" uuid NOT NULL,
	"consumed_at" timestamp with time zone,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"handle" text NOT NULL,
	"email" text,
	"github_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflow_files" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workflow_id" uuid NOT NULL,
	"kind" text NOT NULL,
	"name" text NOT NULL,
	"r2_key" text NOT NULL,
	"size_bytes" bigint,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflow_videos" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workflow_id" uuid NOT NULL,
	"r2_key" text NOT NULL,
	"poster_r2_key" text,
	"duration_s" integer,
	"is_main" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "workflows" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" text NOT NULL,
	"title" text NOT NULL,
	"summary" text,
	"readme_md" text NOT NULL,
	"owner_handle_id" uuid NOT NULL,
	"main_video_id" uuid,
	"visibility" text DEFAULT 'public' NOT NULL,
	"license" text DEFAULT 'CC-BY-4.0',
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "anonymous_handles" ADD CONSTRAINT "anonymous_handles_claimed_by_user_id_users_id_fk" FOREIGN KEY ("claimed_by_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "cli_tokens" ADD CONSTRAINT "cli_tokens_handle_id_anonymous_handles_id_fk" FOREIGN KEY ("handle_id") REFERENCES "public"."anonymous_handles"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "device_auth" ADD CONSTRAINT "device_auth_handle_id_anonymous_handles_id_fk" FOREIGN KEY ("handle_id") REFERENCES "public"."anonymous_handles"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_files" ADD CONSTRAINT "workflow_files_workflow_id_workflows_id_fk" FOREIGN KEY ("workflow_id") REFERENCES "public"."workflows"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflow_videos" ADD CONSTRAINT "workflow_videos_workflow_id_workflows_id_fk" FOREIGN KEY ("workflow_id") REFERENCES "public"."workflows"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "workflows" ADD CONSTRAINT "workflows_owner_handle_id_anonymous_handles_id_fk" FOREIGN KEY ("owner_handle_id") REFERENCES "public"."anonymous_handles"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "anon_handle_idx" ON "anonymous_handles" USING btree ("handle");--> statement-breakpoint
CREATE UNIQUE INDEX "anon_pubkey_idx" ON "anonymous_handles" USING btree ("pubkey");--> statement-breakpoint
CREATE UNIQUE INDEX "cli_tokens_hash_idx" ON "cli_tokens" USING btree ("token_hash");--> statement-breakpoint
CREATE INDEX "cli_tokens_handle_idx" ON "cli_tokens" USING btree ("handle_id");--> statement-breakpoint
CREATE UNIQUE INDEX "users_handle_idx" ON "users" USING btree ("handle");--> statement-breakpoint
CREATE UNIQUE INDEX "users_github_idx" ON "users" USING btree ("github_id");--> statement-breakpoint
CREATE INDEX "workflow_files_workflow_idx" ON "workflow_files" USING btree ("workflow_id");--> statement-breakpoint
CREATE INDEX "workflow_videos_workflow_idx" ON "workflow_videos" USING btree ("workflow_id");--> statement-breakpoint
CREATE UNIQUE INDEX "workflows_slug_idx" ON "workflows" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "workflows_owner_idx" ON "workflows" USING btree ("owner_handle_id");--> statement-breakpoint
CREATE INDEX "workflows_created_idx" ON "workflows" USING btree ("created_at");