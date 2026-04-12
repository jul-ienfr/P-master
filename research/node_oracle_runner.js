#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");

const requireFromHere = createRequire(__filename);
const toolsPackageJson = path.join(__dirname, "..", ".tools", "npm", "package.json");
const requireFromTools = fs.existsSync(toolsPackageJson)
  ? createRequire(toolsPackageJson)
  : null;

function requireOptional(moduleName) {
  try {
    return requireFromHere(moduleName);
  } catch (error) {
    if (requireFromTools) {
      return requireFromTools(moduleName);
    }
    throw error;
  }
}

async function ensureVendoredPokersolver() {
  const vendorDir = path.join(__dirname, "vendor");
  const vendorPath = path.join(vendorDir, "pokersolver.js");
  if (fs.existsSync(vendorPath)) {
    return require(vendorPath);
  }

  try {
    return requireOptional("pokersolver");
  } catch (error) {
    if (process.env.POKERMASTER_ALLOW_ORACLE_DOWNLOAD !== "1") {
      throw new Error("pokersolver package is not installed and auto-download is disabled");
    }
  }

  fs.mkdirSync(vendorDir, { recursive: true });
  const response = await fetch("https://unpkg.com/pokersolver/pokersolver.js");
  if (!response.ok) {
    throw new Error(`unable to download pokersolver: ${response.status}`);
  }
  fs.writeFileSync(vendorPath, await response.text(), "utf8");
  return require(vendorPath);
}

function loadPokerEvaluator() {
  try {
    return requireOptional("poker-evaluator");
  } catch (error) {
    throw new Error("poker-evaluator package is not installed");
  }
}

async function rankWithPokersolver(cards) {
  const pokersolver = await ensureVendoredPokersolver();
  const hand = pokersolver.Hand.solve(cards);
  return {
    backend: "pokersolver",
    cards,
    name: hand.name || "",
    descr: hand.descr || "",
    rank: Number.isFinite(hand.rank) ? hand.rank : null,
  };
}

function rankWithPokerEvaluator(cards) {
  const evaluator = loadPokerEvaluator();
  const result = evaluator.evalHand(cards);
  return {
    backend: "poker_evaluator",
    cards,
    handType: result.handType || result.handName || "",
    handRank: result.handRank || result.value || null,
    value: result.value || null,
  };
}

async function main() {
  const [, , backend, ...cards] = process.argv;
  if (!backend || cards.length === 0) {
    throw new Error("usage: node_oracle_runner.js <backend> <card...>");
  }

  let payload;
  if (backend === "pokersolver") {
    payload = await rankWithPokersolver(cards);
  } else if (backend === "poker_evaluator") {
    payload = rankWithPokerEvaluator(cards);
  } else {
    throw new Error(`unsupported node oracle backend: ${backend}`);
  }

  process.stdout.write(JSON.stringify(payload));
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
