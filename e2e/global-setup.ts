import { execSync } from "child_process";

const COMPOSE = "docker compose -f local.yml";
const COMPOSE_E2E = "docker compose -f local.yml -f e2e.yml";
const MAX_WAIT_MS = 90_000;
const POLL_INTERVAL_MS = 2_000;

function run(cmd: string) {
  console.log(`[e2e setup] ${cmd}`);
  return execSync(cmd, { stdio: "pipe", timeout: 120_000 }).toString().trim();
}

async function waitForDjango() {
  // First, wait for any old container to stop responding so we don't
  // mistake a stale response from the pre-restart container as "ready".
  console.log("[e2e setup] Waiting for old Django to stop...");
  await new Promise((r) => setTimeout(r, 5_000));

  const start = Date.now();
  while (Date.now() - start < MAX_WAIT_MS) {
    try {
      const status = run(
        `curl -sk -o /dev/null -w "%{http_code}" https://dev.squarelet.com/accounts/login/`,
      );
      if (status === "200" || status === "302") {
        console.log(`[e2e setup] Django is ready (HTTP ${status})`);
        return;
      }
      console.log(`[e2e setup] Django returned HTTP ${status}, waiting...`);
    } catch {
      console.log("[e2e setup] Waiting for Django...");
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error("Django did not become ready in time");
}

export default async function globalSetup() {
  console.log("[e2e setup] Creating test database...");
  try {
    run(
      `${COMPOSE} exec -T squarelet_postgres bash -c 'createdb -U "$POSTGRES_USER" test_squarelet'`,
    );
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : String(e);
    if (message.includes("already exists")) {
      console.log("[e2e setup] Test database already exists, continuing...");
    } else {
      throw e;
    }
  }

  console.log("[e2e setup] Restarting Django with test database...");
  run(`${COMPOSE_E2E} up -d squarelet_django`);

  // The container's /start script runs `migrate && runserver_plus`,
  // so when Django is serving HTTP 200, migrations are already complete.
  await waitForDjango();

  console.log("[e2e setup] Seeding test data...");
  run(
    `${COMPOSE_E2E} exec -T squarelet_django /entrypoint python manage.py seed_e2e_data --action seed`,
  );

  console.log("[e2e setup] Setup complete");
}
