import { backendDir, ensureBackendVenv, runPython } from "./python-utils.mjs";

const python = ensureBackendVenv();
const port = process.env.ROXANNE_PORT || "8000";
const host = process.env.ROXANNE_HOST || "127.0.0.1";

runPython(
  python,
  [
    "-m",
    "uvicorn",
    "roxanne_backend.main:app",
    "--reload",
    "--host",
    host,
    "--port",
    port,
    "--app-dir",
    backendDir,
    "--log-level",
    "debug",
  ],
  {
    cwd: backendDir,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      ROXANNE_SECRET_STORE: process.env.ROXANNE_SECRET_STORE || "local",
    },
  }
);
