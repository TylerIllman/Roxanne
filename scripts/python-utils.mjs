import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const repoRoot = path.resolve(__dirname, "..");
export const backendDir = path.join(repoRoot, "apps", "backend");
export const backendVenvDir = path.join(backendDir, ".venv");

function venvPythonCandidate() {
  if (process.platform === "win32") {
    return { cmd: path.join(backendVenvDir, "Scripts", "python.exe"), prefix: [] };
  }
  return { cmd: path.join(backendVenvDir, "bin", "python3"), prefix: [] };
}

export function defaultPythonCandidates() {
  const candidates = [];
  const venvPython = venvPythonCandidate();
  if (fs.existsSync(venvPython.cmd)) {
    candidates.push(venvPython);
  }

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

  return candidates;
}

export function findPython(candidates = defaultPythonCandidates()) {
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

export function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    env: process.env,
    ...options,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

export function runPython(candidate, args, options = {}) {
  runCommand(candidate.cmd, [...candidate.prefix, ...args], {
    cwd: backendDir,
    ...options,
  });
}

export function ensureBackendVenv() {
  const venvPython = venvPythonCandidate();
  if (fs.existsSync(venvPython.cmd)) {
    return venvPython;
  }

  const bootstrapPython = findPython(
    defaultPythonCandidates().filter((candidate) => candidate.cmd !== venvPython.cmd)
  );
  runPython(bootstrapPython, ["-m", "venv", backendVenvDir]);
  return findPython([venvPython]);
}
