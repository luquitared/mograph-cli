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
    githubLogin: text("github_login"),
    displayName: text("display_name"),
    avatarUrl: text("avatar_url"),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [
    uniqueIndex("users_handle_idx").on(t.handle),
    uniqueIndex("users_github_idx").on(t.githubId),
  ],
);

export const cliDevices = pgTable(
  "cli_devices",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    pubkey: text("pubkey").notNull(),
    label: text("label"),
    lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .default(sql`now()`),
  },
  (t) => [
    uniqueIndex("cli_devices_pubkey_idx").on(t.pubkey),
    index("cli_devices_user_idx").on(t.userId),
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
    ownerUserId: uuid("owner_user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
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
    index("workflows_owner_user_idx").on(t.ownerUserId),
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
