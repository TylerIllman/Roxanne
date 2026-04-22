import fs from "node:fs";
import path from "node:path";
import { backendDir, findPython, runPython } from "./python-utils.mjs";

const distDir = path.join(backendDir, "dist");
const pyInstallerWorkDir = path.join(backendDir, "build", "pyinstaller");

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
