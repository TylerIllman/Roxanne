import { backendDir, ensureBackendVenv, repoRoot, runCommand, runPython } from "./python-utils.mjs";

const python = ensureBackendVenv();

runPython(python, ["-m", "pip", "install", "--upgrade", "pip"]);
runPython(python, ["-m", "pip", "install", "-e", ".[test]"], { cwd: backendDir });
runCommand("npm", ["install"], { cwd: repoRoot, shell: process.platform === "win32" });
