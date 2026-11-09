import { defineRailway, github, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const backendData = volume("backend-data", {
    region: "asia-southeast1-eqsg3a",
    sizeMB: 500,
  });

  const backend = service("backend", {
    source: github("SumiranKC/doc-image-ocr", {
      branch: "main",
      rootDirectory: "backend",
    }),
    healthcheck: "/health",
    healthcheckTimeout: 300,
    replicas: {
      "asia-southeast1-eqsg3a": 1,
    },
    env: {
      ALLOWED_ORIGINS: '["https://sumirankc.github.io"]',
      DATA_DIR: "/data",
      RAILWAY_RUN_UID: "0",
    },
    volumeMounts: {
      "/data": backendData,
    },
  });

  return project("doc-image-ocr", {
    resources: [backend, backendData],
  });
});
