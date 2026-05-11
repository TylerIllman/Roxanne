import fs from "node:fs";
import path from "node:path";
import { backendDir, findPython, runPython } from "./python-utils.mjs";

const distDir = path.join(backendDir, "dist");
const pyInstallerWorkDir = path.join(backendDir, "build", "pyinstaller");

const python = findPython();

fs.rmSync(distDir, { recursive: true, force: true });
fs.rmSync(pyInstallerWorkDir, { recursive: true, force: true });

runPython(python, ["-m", "pip", "install", "-e", ".[build]"]);
// Packages with dynamic imports / native libraries / sibling data dirs that
// PyInstaller's static analyzer misses. Without these flags the released
// binary fails at runtime with errors like `No module named
// 'chromadb.api.rust'`, `cannot load library '.../vosk/libvosk.dyld'`, or
// `cannot load library '.../piper/espeakbridge.so'`.
const dynamicPackages = ["chromadb", "fastembed", "onnxruntime", "vosk", "piper"];
// Packages that ship native shared libraries inside their site-packages dir
// and therefore need --collect-binaries (in addition to submodules+data).
const nativeBinaryPackages = ["vosk", "piper"];
const collectArgs = [
  "--collect-submodules", "uvicorn",
  ...dynamicPackages.flatMap((pkg) => ["--collect-submodules", pkg]),
  ...dynamicPackages.flatMap((pkg) => ["--collect-data", pkg]),
  ...nativeBinaryPackages.flatMap((pkg) => ["--collect-binaries", pkg]),
];

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
  ...collectArgs,
]);
