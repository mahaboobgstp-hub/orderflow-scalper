#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const tokenLiteral = "['\"]ofs_token['\"]";
const normalize = (source) => String(source)
  .replace(/\?\./g, ".")
  .replace(/\.\s*\[/g, "[")
  .replace(/\b(?:window|globalThis|self)\s*\.\s*localStorage\b/g, "localStorage");

export function scanSource(source, file = "<source>") {
  const text = normalize(source);
  const storageAliases = new Set(["localStorage"]);
  const tokenAliases = new Set();
  const tokenInit = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*['"]ofs_token['"]/g;
  for (const match of text.matchAll(tokenInit)) tokenAliases.add(match[1]);
  let changed = true;
  while (changed) {
    changed = false;
    const names = [...tokenAliases].join("|");
    if (!names) break;
    const chained = new RegExp("\\b(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*(?:" + names + ")\\b", "g");
    for (const match of text.matchAll(chained)) if (!tokenAliases.has(match[1])) { tokenAliases.add(match[1]); changed = true; }
  }
  const tokenArg = tokenAliases.size ? "(?:" + tokenLiteral + "|\\b(?:" + [...tokenAliases].join("|") + ")\\b)" : tokenLiteral;
  changed = true;
  while (changed) {
    changed = false;
    const names = [...storageAliases].join("|");
    const storageAlias = new RegExp("\\b(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*(?:" + names + ")\\b", "g");
    for (const match of text.matchAll(storageAlias)) if (!storageAliases.has(match[1])) { storageAliases.add(match[1]); changed = true; }
  }
  const findings = [];
  const seen = new Set();
  const add = (index, method) => { const key = index + ":" + method; if (!seen.has(key)) { seen.add(key); findings.push({file,offset:index,method}); } };
  const methodAliases = new Map();
  const accessor = "(?:\\.\\s*(getItem|setItem)|\\[\\s*['\"](getItem|setItem)['\"]\s*\])";
  for (const storage of storageAliases) {
    const access = "\\b" + storage + "\\s*" + accessor;
    const direct = new RegExp(access + "\\s*\\(\\s*" + tokenArg, "g");
    for (const match of text.matchAll(direct)) add(match.index, match[1]||match[2]||"unknown");
    const indirect = new RegExp(access + "\\s*\\.\\s*(?:call|apply)\\s*\\(\\s*[^,]+,\\s*(?:\\[\\s*)?" + tokenArg, "g");
    for (const match of text.matchAll(indirect)) add(match.index, (match[1]||match[2]||"unknown")+".call/apply");
    const reflect = new RegExp("Reflect\\s*\\.\\s*apply\\s*\\(\\s*" + access + "\\s*,\\s*" + storage + "\\s*,\\s*\\[\\s*" + tokenArg, "g");
    for (const match of text.matchAll(reflect)) add(match.index, "Reflect.apply("+(match[1]||match[2]||"unknown")+")");
    const methodAlias = new RegExp("\\b(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*" + access + "(?:\\s*\\.\\s*bind\\s*\\(\\s*[^)]*\\))?\\s*(?:;|(?=\\n|$))", "g");
    for (const match of text.matchAll(methodAlias)) methodAliases.set(match[1],match[2]||match[3]||"unknown");
    const destructure = new RegExp("\\b(?:const|let|var)\\s*\\{([^}]+)\\}\\s*=\\s*(?:"+names+")\\b", "g");
    for (const d of text.matchAll(destructure)) for (const binding of d[1].split(",")) {
      const b=binding.trim().match(/^(getItem|setItem)(?:\s*:\s*([A-Za-z_$][\w$]*))?$/);
      if(b) methodAliases.set(b[2]||b[1],b[1]);
    }
  }
  changed=true;
  while(changed) {
    changed=false;
    for(const [name,method] of [...methodAliases]) {
      const alias=new RegExp("\\b(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*"+name+"(?:\\s*\\.\\s*bind\\s*\\([^)]*\\))?\\s*(?:;|(?=\\n|$))","g");
      for(const match of text.matchAll(alias)) if(!methodAliases.has(match[1])) {methodAliases.set(match[1],method);changed=true;}
    }
  }
  for(const [name,method] of methodAliases) {
    const directAlias=new RegExp("\\b"+name+"\\s*\\(\\s*"+tokenArg,"g");
    for(const match of text.matchAll(directAlias)) if(text[match.index-1]!==".") add(match.index,"alias-"+method);
    const indirectAlias=new RegExp("\\b"+name+"\\s*\\.\\s*(?:call|apply)\\s*\\(\\s*[^,]+,\\s*(?:\\[\\s*)?"+tokenArg,"g");
    for(const match of text.matchAll(indirectAlias)) if(text[match.index-1]!==".") add(match.index,"alias-"+method+".call/apply");
    const reflectAlias=new RegExp("Reflect\\s*\\.\\s*apply\\s*\\(\\s*"+name+"\\s*,\\s*[^,]+,\\s*\\[\\s*"+tokenArg,"g");
    for(const match of text.matchAll(reflectAlias)) add(match.index,"Reflect.apply(alias-"+method+")");
  }
  return findings;
}

export function scanDirectory(directory) {
  const findings = [];
  const extensions = new Set([".js",".jsx",".ts",".tsx",".mjs",".cjs",".html"]);
  function walk(current) {
    for (const entry of fs.readdirSync(current,{withFileTypes:true})) {
      const full = path.join(current,entry.name);
      if (entry.isDirectory()) walk(full);
      else if (extensions.has(path.extname(entry.name).toLowerCase())) findings.push(...scanSource(fs.readFileSync(full,"utf8"),full));
    }
  }
  walk(directory);
  return findings;
}
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  const target=process.argv[2]||"frontend/dist";
  const findings=scanDirectory(target);
  if(findings.length){console.error("FAIL: persistent ofs_token access detected ("+findings.length+")");for(const f of findings)console.error(f.file+":"+f.offset+" "+f.method);process.exitCode=1;}
  else console.log("PASS: no persistent ofs_token reads/writes detected in "+target);
}
