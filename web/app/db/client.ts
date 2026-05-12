import { neon } from "@neondatabase/serverless";
import { drizzle } from "drizzle-orm/neon-http";
import * as schema from "./schema";

export type Database = ReturnType<typeof db>;

export function db(databaseUrl: string) {
  return drizzle(neon(databaseUrl), { schema });
}
