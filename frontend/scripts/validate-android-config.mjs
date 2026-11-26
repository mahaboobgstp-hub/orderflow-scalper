import fs from "node:fs";
import path from "node:path";

const packagePath = path.resolve("package.json");
const capacitorPath = path.resolve("capacitor.config.json");

const pkg = JSON.parse(fs.readFileSync(packagePath, "utf8"));
const capacitor = JSON.parse(fs.readFileSync(capacitorPath, "utf8"));

const errors = [];
if (!capacitor.appId || !/^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$/.test(capacitor.appId)) {
  errors.push("capacitor.appId must be a valid reverse-domain Android identifier");
}
if (capacitor.webDir !== "dist") errors.push('capacitor.webDir must be "dist" for the Vite build output');
for (const dependency of ["@capacitor/core", "@capacitor/android"]) {
  if (!pkg.dependencies?.[dependency]) errors.push(`Missing runtime dependency: ${dependency}`);
}
if (!pkg.devDependencies?.["@capacitor/cli"]) errors.push("Missing dev dependency: @capacitor/cli");
if (!fs.existsSync(path.resolve("assets/icon.png"))) errors.push("Missing launcher source image: assets/icon.png");

if (errors.length) {
  console.error("Android CI prerequisite validation failed:");
  for (const error of errors) console.error(` - ${error}`);
  process.exit(1);
}
console.log("Android CI prerequisites valid:", capacitor.appId, "webDir=", capacitor.webDir);
