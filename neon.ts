import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  preview: {
    realtime: true,
  },
  auth: true,
  functions: {
    fleethealth: {
      name: "Fleet Health & Security Engine",
      source: "functions/fleet_health/index.ts",
    },
  },
  triggers: {
    "fleet-prune-10m": {
      type: "schedule",
      function: "fleethealth",
      cron: "*/10 * * * *",
      functionPath: "/cron",
    },
  },
  branch: (branch) => {
    if (branch.isDefault) {
      return {};
    }
    if (!branch.exists) {
      return { ttl: "7d" };
    }
    return {};
  },
});
