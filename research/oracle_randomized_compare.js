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

const pokersolver = requireOptional("pokersolver");
const pokerEvaluator = requireOptional("poker-evaluator");
const deck = Array.from("23456789TJQKA").flatMap((rank) =>
  Array.from("cdhs").map((suit) => `${rank}${suit}`)
);

function mulberry32(seed) {
  let value = seed >>> 0;
  return function next() {
    value |= 0;
    value = (value + 0x6d2b79f5) | 0;
    let t = Math.imul(value ^ (value >>> 15), 1 | value);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sampleHand(random) {
  const pool = deck.slice();
  const hand = [];
  for (let i = 0; i < 7; i += 1) {
    const index = Math.floor(random() * pool.length);
    hand.push(pool.splice(index, 1)[0]);
  }
  return hand;
}

function main() {
  const count = Number.parseInt(process.argv[2] || "500", 10);
  const seed = Number.parseInt(process.argv[3] || "20260411", 10);
  const random = mulberry32(seed);
  const mismatches = [];
  let agreements = 0;

  for (let index = 0; index < count; index += 1) {
    const cards = sampleHand(random);
    const pe = pokerEvaluator.evalHand(cards);
    const ps = pokersolver.Hand.solve(cards);
    const peType = Number(pe.handType || pe.handName || 0);
    const psRank = Number(ps.rank || 0);
    if (peType === psRank) {
      agreements += 1;
      continue;
    }
    if (mismatches.length < 16) {
      mismatches.push({
        case: index,
        cards,
        poker_evaluator: {
          handType: pe.handType || pe.handName || null,
          handRank: pe.handRank || pe.value || null,
          value: pe.value || null,
        },
        pokersolver: {
          rank: Number.isFinite(ps.rank) ? ps.rank : null,
          name: ps.name || "",
          descr: ps.descr || "",
        },
      });
    }
  }

  process.stdout.write(
    JSON.stringify({
      kind: "oracle_randomized_js",
      cases: count,
      agreements,
      mismatches: count - agreements,
      agreement_rate: count ? Number((agreements / count).toFixed(4)) : 0,
      mismatch_samples: mismatches,
    })
  );
}

main();
