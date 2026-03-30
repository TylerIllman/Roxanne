import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const backendDir = path.join(repoRoot, "apps", "backend");
const distDir = path.join(backendDir, "dist");
const pyInstallerWorkDir = path.join(backendDir, "build", "pyinstaller");

const candidates = [];
if (process.env.ROXANNE_PYTHON_BIN) {
  candidates.push({ cmd: process.env.ROXANNE_PYTHON_BIN, prefix: [] });
}
if (process.platform === "win32") {
  candidates.push({ cmd: "py", prefix: ["-3"] });
  candidates.push({ cmd: "python", prefix: [] });
  candidates.push({ cmd: "python3", prefix: [] });
} else {
  candidates.push({ cmd: "python3", prefix: [] });
  candidates.push({ cmd: "python", prefix: [] });
}

function findPython() {
  for (const candidate of candidates) {
    const result = spawnSync(candidate.cmd, [...candidate.prefix, "--version"], {
      cwd: backendDir,
      stdio: "ignore",
    });
    if (!result.error && result.status === 0) {
      return candidate;
    }
  }
  throw new Error(
    "No usable Python interpreter was found. Set ROXANNE_PYTHON_BIN or install Python 3.10+."
  );
}

function runPython(candidate, args) {
  const result = spawnSync(candidate.cmd, [...candidate.prefix, ...args], {
    cwd: backendDir,
    stdio: "inherit",
    env: process.env,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const python = findPython();

fs.rmSync(distDir, { recursive: true, force: true });
fs.rmSync(pyInstallerWorkDir, { recursive: true, force: true });

runPython(python, ["-m", "pip", "install", "-e", ".[build]"]);
runPython(python, [
  "-m",
  "PyInstaller",
  "roxanne_backend/serve.py",
  "--name",
  "roxanne-backend",
  "--onefile",
  "--noconfirm",
  "--clean",
  "--distpath",
  "dist",
  "--workpath",
  "build/pyinstaller/work",
  "--specpath",
  "build/pyinstaller/spec",
  "--collect-submodules",
  "uvicorn",
]);
