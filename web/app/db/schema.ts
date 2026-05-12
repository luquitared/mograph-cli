import { sql } from "drizzle-orm";
import {
  bigint,
  boolean,
  index,
  integer,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

export const users = pgTable(
  "users",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    handle: text("handle").notNull(),
    email: text("email"),
    githubId: text("github_id"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [
    uniqueIndex("users_handle_idx").on(t.handle),
    uniqueIndex("users_github_idx").on(t.githubId),
  ],
);

export const anonymousHandles = pgTable(
  "anonymous_handles",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    handle: text("handle").notNull(),
    pubkey: text("pubkey").notNull(),
    claimedByUserId: uuid("claimed_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [
    uniqueIndex("anon_handle_idx").on(t.handle),
    uniqueIndex("anon_pubkey_idx").on(t.pubkey),
  ],
);

export const workflows = pgTable(
  "workflows",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    slug: text("slug").notNull(),
    title: text("title").notNull(),
    summary: text("summary"),
    readmeMd: text("readme_md").notNull(),
    ownerHandleId: uuid("owner_handle_id")
      .notNull()
      .references(() => anonymousHandles.id, { onDelete: "cascade" }),
    mainVideoId: uuid("main_video_id"),
    visibility: text("visibility").notNull().default("public"),
    license: text("license").default("CC-BY-4.0"),
    models: text("models").array(),
    clipCount: integer("clip_count"),
    totalDurationS: integer("total_duration_s"),
    totalBytes: bigint("total_bytes", { mode: "number" }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [
    uniqueIndex("workflows_slug_idx").on(t.slug),
    index("workflows_owner_idx").on(t.ownerHandleId),
    index("workflows_created_idx").on(t.createdAt),
  ],
);

export const workflowVideos = pgTable(
  "workflow_videos",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    workflowId: uuid("workflow_id")
      .notNull()
      .references(() => workflows.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    path: text("path").notNull(),
    r2Key: text("r2_key").notNull(),
    posterR2Key: text("poster_r2_key"),
    durationS: integer("duration_s"),
    isMain: boolean("is_main").notNull().default(false),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [index("workflow_videos_workflow_idx").on(t.workflowId)],
);

export const workflowFiles = pgTable(
  "workflow_files",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    workflowId: uuid("workflow_id")
      .notNull()
      .references(() => workflows.id, { onDelete: "cascade" }),
    kind: text("kind").notNull(),
    name: text("name").notNull(),
    path: text("path").notNull(),
    r2Key: text("r2_key").notNull(),
    sizeBytes: bigint("size_bytes", { mode: "number" }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [index("workflow_files_workflow_idx").on(t.workflowId)],
);

export const cliTokens = pgTable(
  "cli_tokens",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    handleId: uuid("handle_id")
      .notNull()
      .references(() => anonymousHandles.id, { onDelete: "cascade" }),
    tokenHash: text("token_hash").notNull(),
    label: text("label"),
    lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [
    uniqueIndex("cli_tokens_hash_idx").on(t.tokenHash),
    index("cli_tokens_handle_idx").on(t.handleId),
  ],
);

export const deviceAuth = pgTable(
  "device_auth",
  {
    code: text("code").primaryKey(),
    handleId: uuid("handle_id")
      .notNull()
      .references(() => anonymousHandles.id, { onDelete: "cascade" }),
    consumedAt: timestamp("consumed_at", { withTimezone: true }),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
);
