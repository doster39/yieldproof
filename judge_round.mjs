// Definitive live round for YieldProof.
//
// The evidence URL is derived from the local fixture, so this script works whether or
// not the repository has been published yet: disclosure-sample.md is base64-encoded
// and served back verbatim by httpbin. The same text also lives in the repo, so the
// jsdelivr URL is equivalent once the repo exists.
//
//   GL_PK=0x<operator key>  GL_PK_CH=0x<challenger key>  node judge_round.mjs
//
// Round A claims 800 bps for 2026-Q3 — the page states 8.00% (800 bps) with a
// methodology, so it derives `supported` and the challenger's stake is forfeited.
// Round C claims 1990 bps for the same period against the same page, so it derives
// `unsupported` and the challenger is paid the stake plus the bounty from the bond.
//
// Keys are read from the environment on purpose — never commit them.

import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ADDR = "0x34747A848366656bDDdFefc6fDCf1cD6c917f9b8";
const SDIG = "sha256:disclosure-2f9a1c7b";
const MDIG = "sha256:methodology-77be0d31";
const VAULT = "blueharbor";
const STAKE = 100000000000000000n;   // 0.1 GEN
const BOUNTY = 20000000000000000n;   // 0.02 GEN

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = fs.readFileSync(path.join(here, "disclosure-sample.md"), "utf-8");
const SRC_URL = "https://httpbin.org/base64/" + Buffer.from(fixture, "utf-8").toString("base64");

const PK = process.env.GL_PK, PK_CH = process.env.GL_PK_CH;
if (!PK || !PK.startsWith("0x") || !PK_CH || !PK_CH.startsWith("0x")) {
  console.error("Set GL_PK (operator) and GL_PK_CH (challenger) to 0x-prefixed private keys.");
  process.exit(1);
}

const OP = createAccount(PK), CH = createAccount(PK_CH);
const reader = createClient({ chain: studionet });
const mk = (a) => {
  const c = createClient({ chain: studionet, account: a });
  c.estimateTransactionGas = async () => 3_000_000n;
  return c;
};

async function wait(hash) {
  for (let i = 0; i < 200; i++) {
    await new Promise((r) => setTimeout(r, 5000));
    let tx = null;
    try { tx = await reader.getTransaction({ hash }); } catch { continue; }
    if (!tx) continue;
    const st = String(tx.statusName || tx.status || "");
    if (st === "FINALIZED" || st === "ACCEPTED") {
      const exec = tx.consensus_data?.leader_receipt?.[0]?.execution_result;
      return { status: st, exec: String(exec || "") };
    }
    if (st === "UNDETERMINED" || st === "LEADER_TIMEOUT") return { status: st, exec: "CONSENSUS_FAIL" };
  }
  return { status: "TIMEOUT", exec: "" };
}

async function send(tag, acct, fn, args, value = 0n) {
  try {
    const hash = await mk(acct).writeContract({ address: ADDR, functionName: fn, args, value });
    const r = await wait(hash);
    console.log(`[${tag}] ${fn} -> exec=${r.exec} ${r.status} ${hash}`);
    return r;
  } catch (e) {
    console.log(`[${tag}] ${fn} -> THREW ${String(e?.details || e?.message || e).split("\n")[0].slice(0, 150)}`);
    return { exec: "THREW" };
  }
}

const view = async (fn, args) => {
  try { return await reader.readContract({ address: ADDR, functionName: fn, args }); }
  catch (e) { return { error: String(e?.message || e).slice(0, 140) }; }
};

console.log("evidence URL:", SRC_URL.length, "chars");
console.log("operator:", OP.address, "| challenger:", CH.address);
console.log("vault before:", JSON.stringify(await view("get_vault", [VAULT])));
console.log("");

async function round(label, period, claimBps, note) {
  await send(label, OP, "record_report", [VAULT, period, claimBps, SRC_URL, SDIG, MDIG]);
  const rid = BigInt((await view("get_counts", [])).report_count);
  await send(label, CH, "challenge_report", [rid, note, BOUNTY], STAKE);
  const cid = BigInt((await view("get_counts", [])).challenge_count);
  await send(label, CH, "judge_challenge", [cid]);
  console.log(`${label} verdict:`, JSON.stringify(await view("get_challenge", [cid])));
  await send(label, CH, "settle_challenge", [cid]);
  console.log(`${label} settled:`, JSON.stringify(await view("get_challenge", [cid])));
  console.log("");
}

// A: honest claim -> supported, stake forfeited into the bond
await round("A", "2026-Q3", 800n,
  "verify the disclosed 8.00 percent really supports the claimed 800 basis points");

// C: inflated claim for the same period -> unsupported, bounty paid from the bond
await round("C", "2026-Q3", 1990n,
  "the page states 8.00 percent for 2026-Q3, far below the claimed 19.90 percent");

console.log("FINAL vault:", JSON.stringify(await view("get_vault", [VAULT])));
console.log("FINAL counts:", JSON.stringify(await view("get_counts", [])));
