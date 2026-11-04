// Writes game-day boosts into a dynasty save: for each player row, set only the listed fields (StartingHotCold,
// MentalAbility1-3, MentalAbilityRank1-3), then read the result back and verify it before replacing the file.
// Usage: node write_boosts.mjs <save file> <changes.json>   (a change may carry "onlyIf": {field: value} to skip fields that changed)
//   changes.json: [{"row": 4544, "set": {"StartingHotCold": "Hot", "MentalAbility1": "WinningTime", "MentalAbilityRank1": "Bronze"}}]
// Prints JSON: {"before": {row: {field: value}}, "players": n}. Exits non-zero (leaving the file untouched) on any problem.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const Franchise = require('madden-franchise').default || require('madden-franchise');
const ALLOWED = new Set(['StartingHotCold', 'MentalAbility1', 'MentalAbility2', 'MentalAbility3',
                         'MentalAbilityRank1', 'MentalAbilityRank2', 'MentalAbilityRank3']);
const opts = { gameYearOverride: 27, gameTypeOverride: 'college' };

const [, , savePath, changesPath] = process.argv;
const changes = JSON.parse(fs.readFileSync(changesPath, 'utf-8'));
for (const c of changes) {
  for (const field of Object.keys(c.set)) if (!ALLOWED.has(field)) throw new Error(`not allowed to write ${field}`);
}

const playersOf = async (franchise) => {
  const table = franchise.tables.find((t) => t.name === 'Player' && !t.header.tableStoreName);
  await table.readRecords();
  return table.records;
};
const liveCount = (records) => records.filter((r) => r && !r.isEmpty).length;

// Work on a temp copy next to the save; only a verified result replaces the real file
const work = path.join(path.dirname(savePath), `.basic_os_writing_${process.pid}`);
fs.copyFileSync(savePath, work);
try {
  let franchise = await Franchise.create(work, opts);
  let records = await playersOf(franchise);
  const count = liveCount(records);
  const before = {};
  const written = [];
  for (const c of changes) {
    const p = records[c.row];
    if (!p || p.isEmpty) throw new Error(`no player at row ${c.row}`);
    before[c.row] = {};
    for (const [field, value] of Object.entries(c.set)) {
      before[c.row][field] = p[field];
      // "onlyIf": take a boost back out only while the field still holds what we wrote (the game may have changed it since)
      if (c.onlyIf && field in c.onlyIf && p[field] !== c.onlyIf[field]) continue;
      p[field] = value;
      written.push([c.row, field, value]);
    }
  }
  await franchise.save(work);
  franchise = await Franchise.create(work, opts);
  records = await playersOf(franchise);
  if (liveCount(records) !== count) throw new Error('player count changed after writing');
  for (const [row, field, value] of written) {
    if (records[row][field] !== value) throw new Error(`row ${row} ${field} reads ${records[row][field]}, expected ${value}`);
  }
  fs.copyFileSync(work, savePath);
  console.log(JSON.stringify({ before, players: count }));
} finally {
  fs.rmSync(work, { force: true });
}
