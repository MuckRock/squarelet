import { execSync } from "child_process";

const COMPOSE = "docker compose -f local.yml";

function run(cmd: string) {
  console.log(`[e2e teardown] ${cmd}`);
  return execSync(cmd, { stdio: "pipe", timeout: 120_000 }).toString().trim();
}

export default async function globalTeardown() {
  console.log("[e2e teardown] Restoring original Django service...");
  try {
    run(`${COMPOSE} up -d squarelet_django`);
  } catch (e) {
    console.error("[e2e teardown] Failed to restore Django:", e);
  }

  console.log("[e2e teardown] Dropping test database...");
  try {
    run(
      `${COMPOSE} exec -T squarelet_postgres bash -c 'dropdb -U "$POSTGRES_USER" --if-exists test_squarelet'`,
    );
  } catch (e) {
    console.error("[e2e teardown] Failed to drop test database:", e);
  }

  console.log("[e2e teardown] Teardown complete");
}
