import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Octokit } from "@octokit/rest";

let token: string;
try {
  token = readFileSync(join(homedir(), ".config/secrets/PAT"), "utf8").trim();
} catch {
  throw new Error("Cannot read GitHub token from ~/.config/secrets/PAT.");
}

if (!token) {
  throw new Error("GitHub token file ~/.config/secrets/PAT is empty.");
}

export const authToken = token;
export const octokit = new Octokit({ auth: token });
