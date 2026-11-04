// Reads a College Football 27 dynasty save with madden-franchise and prints the
// schedule, roster and depth chart for the user's team as JSON on stdout.
//
// Usage: node read_dynasty.mjs <path to DYNASTY-* save>
//
// The save is never modified: we parse a temporary copy and never call save().
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Franchise from 'madden-franchise';

const savePath = process.argv[2];
if (!savePath) {
  console.error('Usage: node read_dynasty.mjs <path to DYNASTY-* save>');
  process.exit(2);
}

const copyPath = path.join(os.tmpdir(), `basic_os_save_${process.pid}`);
fs.copyFileSync(savePath, copyPath);

try {
  const franchise = await Franchise.create(copyPath, { gameYearOverride: 27, gameTypeOverride: 'college' });

  // Several tables share a name; the real data lives in the "...Store" tables
  const byStore = (name) => franchise.tables.find((t) => t.header.tableStoreName === name);
  const byName = (name) => franchise.tables.find((t) => t.name === name && !t.header.tableStoreName);
  const read = async (table, label) => {
    if (!table) throw new Error(`Table ${label} not found in save`);
    await table.readRecords();
    return table;
  };
  const ref = (record, key) => {
    try { return record.getReferenceDataByKey(key); } catch { return null; }
  };
  const isValidRef = (data) => data && Number.isInteger(data.tableId) && data.rowNumber >= 0;
  const live = (record) => record && !record.isEmpty ? record : null;
  const refFields = (record) => record.fieldsArray.filter((field) => field.offset.isReference).map((field) => field.offset.name);

  const teamTable = await read(byStore('TeamStore'), 'TeamStore');
  const rosterTable = await read(byStore('RosterStore'), 'RosterStore');
  const gameTable = await read(byStore('SeasonGameStore'), 'SeasonGameStore');
  const depthChartTable = await read(byStore('DepthChartStore'), 'DepthChartStore');
  const depthArrayTable = await read(byStore('DepthChartArrayStore'), 'DepthChartArrayStore');
  const playerTable = await read(byName('Player'), 'Player');
  const teamStatsTable = await read(byName('TeamStats'), 'TeamStats');
  const userTable = await read(byName('FranchiseUser'), 'FranchiseUser');
  const seasonInfo = (await read(byName('SeasonInfo'), 'SeasonInfo')).records.find(live);

  const recordFrom = (table, data) => isValidRef(data) && data.tableId === table.header.tableId ? live(table.records[data.rowNumber]) : null;

  // The user's team is the one with any staff slot (HC, OC, DC...) pointing at a franchise user's coach
  const userEntities = userTable.records.filter(live).map((user) => ref(user, 'UserEntity')).filter(isValidRef);
  const userTeam = teamTable.records.filter(live).find((team) => refFields(team).some((key) => {
    const data = ref(team, key);
    return data && userEntities.some((entity) => entity.tableId === data.tableId && entity.rowNumber === data.rowNumber);
  }));
  if (!userTeam) throw new Error('Could not find the user-controlled team in this save');

  const playerId = (player) => `${playerTable.header.tableId}:${player.index}`;
  // Where a player is from and how he was recruited (player profiles)
  const STARS = { ONE_STAR: 1, TWO_STAR: 2, THREE_STAR: 3, FOUR_STAR: 4, FIVE_STAR: 5 };
  const PERSONA_TRAITS = [['PT_DISCIPLINED', 'Disciplined'], ['PT_UNDISCIPLINED', 'Undisciplined'], ['PT_BIGHITTER', 'Big Hitter'],
    ['PT_PARANOID', 'Paranoid'], ['PT_OBLIVIOUS', 'Oblivious'], ['PT_CONSERVATIVE', 'Conservative'], ['PT_QUICKTRIGGER', 'Quick Trigger']];
  const background = (player) => ({
    hometown: player.PLYR_HOME_TOWN || '', homeState: player.PLYR_HOME_STATE || '', stars: STARS[player.ProspectStarRating] ?? null
  });
  const clean = (value) => value === 'Invalid_' ? '' : (value || '');

  // Stat records point at tables we haven't read yet (GameOffensiveStats, GameDefensiveStats, ...)
  const tableById = new Map(franchise.tables.map((t) => [t.header.tableId, t]));
  const recordFromAny = async (data) => {
    if (!isValidRef(data)) return null;
    const table = tableById.get(data.tableId);
    if (!table) return null;
    if (!table.recordsRead) await table.readRecords();
    return live(table.records[data.rowNumber]);
  };

  // This season's per-game stat lines for a player: [{week, type, stats: {PASSYARDS: 218, ...}}]
  const gameStatsFor = async (player) => {
    const list = await recordFromAny(ref(player, 'GameStats'));
    if (!list) return [];
    const output = [];
    for (const key of refFields(list)) {
      const statData = ref(list, key);
      const stat = await recordFromAny(statData);
      const game = stat && await recordFromAny(ref(stat, 'SeasonGame'));
      if (!game || game.SeasonYear !== seasonInfo.CurrentYear) continue;
      const stats = {};
      for (const field of stat.fieldsArray) {
        const value = stat[field.offset.name];
        if (!field.offset.isReference && typeof value === 'number' && value !== 0) stats[field.offset.name] = value;
      }
      output.push({ week: game.SeasonWeek, type: tableById.get(statData.tableId).name, stats });
    }
    return output;
  };

  // Roster
  const rosterRecord = recordFrom(rosterTable, ref(userTeam, 'Roster'));
  const rosterPlayers = (rosterRecord ? refFields(rosterRecord) : [])
    .map((key) => recordFrom(playerTable, ref(rosterRecord, key)))
    .filter(Boolean);
  const roster = [];
  for (const player of rosterPlayers) {
    roster.push({
      id: playerId(player),
      name: `${player.FirstName || ''} ${player.LastName || ''}`.trim(),
      position: player.Position,
      jersey: player.JerseyNum ?? null,
      overall: player.OverallRating ?? null,
      assetName: clean(player.PLYR_ASSETNAME),
      headAsset: clean(player.GenericHeadAssetName),
      classYear: clean(player.SchoolYear),
      heightInches: player.Height ?? null,
      weightPounds: Number.isFinite(player.Weight) ? player.Weight + 160 : null, // stored as pounds over 160
      injuryStatus: clean(player.InjuryStatus) || 'Uninjured',
      injuryType: clean(player.InjuryType),
      injurySeverity: clean(player.InjurySeverity),
      minInjuryDuration: player.MinInjuryDuration ?? null,
      maxInjuryDuration: player.MaxInjuryDuration ?? null,
      redshirt: clean(player.RedshirtStatus),
      ...background(player),
      devTrait: clean(player.TraitDevelopment), nil: player.CurrentNILCompensation ?? null, captain: Boolean(player.PLYR_ISCAPTAIN),
      // Player care: personality traits that shape behaviour, confidence and how he starts the next game
      traits: PERSONA_TRAITS.filter(([field]) => player[field] === true).map(([, name]) => name),
      confidence: player.ConfidenceRating ?? null, hotCold: clean(player.StartingHotCold),
      // The three mental ability slots (empty slots read "None"): the game-day boosts only fill empty ones
      mentals: [1, 2, 3].map((i) => ({ slot: i, name: clean(player[`MentalAbility${i}`]), rank: clean(player[`MentalAbilityRank${i}`]) })),
      // The game's own odds (0-100) that he transfers or turns pro after the season
      transferChance: player.AbsoluteTransferChance ?? null,
      goProChance: player.AbsoluteGoProChance ?? null,
      gameStats: await gameStatsFor(player)
    });
  }

  // Depth chart: position -> ordered player ids
  const depthChartOf = (team) => {
    const result = {};
    const chart = recordFrom(depthChartTable, ref(team, 'DepthChart'));
    for (const position of chart ? refFields(chart) : []) {
      if (position === 'LockedEntries') continue;
      const slots = recordFrom(depthArrayTable, ref(chart, position));
      if (!slots) continue;
      result[position] = refFields(slots)
        .map((key) => recordFrom(playerTable, ref(slots, key)))
        .filter(Boolean)
        .map(playerId);
    }
    return result;
  };
  const depthChart = depthChartOf(userTeam);

  // Games normally have no stadium set (they're at the home team's park). Only neutral-site games
  // (Red River, Army-Navy, Week 0 openers, title games) point at a stadium. Bowls and playoffs are always neutral.
  const isNeutralSite = (game) => {
    const data = ref(game, 'Stadium');
    return Boolean(data && data.tableId) || (game.SeasonWeekType && game.SeasonWeekType !== 'RegularSeason');
  };

  // This season's schedule for the user's team
  const teamStats = (data) => {
    const stats = recordFrom(teamStatsTable, data);
    return stats ? { passingYards: stats.OFFPASSYARDS ?? 0, rushingYards: stats.OFFRUSHYARDS ?? 0 } : null;
  };
  const schedule = [];
  for (const game of gameTable.records.filter(live)) {
    if (game.SeasonYear !== seasonInfo.CurrentYear) continue;
    const home = recordFrom(teamTable, ref(game, 'HomeTeam'));
    const away = recordFrom(teamTable, ref(game, 'AwayTeam'));
    if (!home || !away || (home.index !== userTeam.index && away.index !== userTeam.index)) continue;
    const isHome = home.index === userTeam.index;
    const opponent = isHome ? away : home;
    const played = game.GameStatus !== 'Unplayed';
    schedule.push({
      week: game.SeasonWeek,
      weekType: game.SeasonWeekType,
      site: isNeutralSite(game) ? 'Neutral' : (isHome ? 'Home' : 'Away'),
      opponent: opponent.DisplayName,
      opponentNickname: opponent.NickName || '',
      played,
      teamScore: played ? (isHome ? game.HomeScore : game.AwayScore) : null,
      opponentScore: played ? (isHome ? game.AwayScore : game.HomeScore) : null,
      teamStats: played ? teamStats(ref(game, isHome ? 'HomeTeamStatCache' : 'AwayTeamStatCache')) : null,
      opponentStats: played ? teamStats(ref(game, isHome ? 'AwayTeamStatCache' : 'HomeTeamStatCache')) : null,
      day: clean(game.DayOfWeek),
      date: game.GameDateMonth > 0 && game.GameDateDay > 0
        ? `${(seasonInfo.BaseCalendarYear ?? 2026) + (game.SeasonYear ?? 0)}-${String(game.GameDateMonth).padStart(2, '0')}-${String(game.GameDateDay).padStart(2, '0')}`
        : null,
      kickoffMinutes: game.TimeOfDay ?? null, // minutes after midnight, e.g. 900 = 3:00 PM
      network: clean(game.BroadcastNetwork),
      weather: {
        condition: clean(game.Weather),
        temperature: game.Temperature ?? null,
        precipitation: clean(game.Precipitation),
        precipitationChance: game.PrecipitationChance ?? null,
        wind: clean(game.Wind),
        windSpeed: game.WindSpeed ?? null
      }
    });
  }
  schedule.sort((a, b) => a.week - b.week);


  // ---------- League-wide data for the weekly recap ----------
  const hexColor = (r, g, b) => [r, g, b].every(Number.isFinite)
    ? '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('')
    : null;
  // The Coach table has no schema in madden-franchise yet, so its fields are unnamed. Text fields hold
  // offsets into the table's string block: Field_2 first name, Field_5 last name, Field_44 portrait asset
  // (e.g. "Unique_C_SawvelJay_830"). Field_6 is the portrait id. Checked against Wyoming, Alabama, Georgia...
  const coachTable = byName('Coach');
  if (coachTable) await coachTable.readRecords();
  const coachText = (coach, key) => {
    const offset = coach[key];
    if (!Number.isInteger(offset) || !coachTable.header.hasSecondTable) return '';
    const start = coachTable.header.table2StartIndex + offset;
    const end = coachTable.data.indexOf(0, start);
    return end > start ? coachTable.data.toString('utf8', start, end) : '';
  };
  const staffMember = (team, key) => {
    const data = coachTable && ref(team, key);
    const coach = data && recordFrom(coachTable, data);
    if (!coach) return null;
    return {
      name: `${coachText(coach, 'Field_2')} ${coachText(coach, 'Field_5')}`.trim(),
      portraitAsset: coachText(coach, 'Field_44'),
      portraitId: Number.isInteger(coach.Field_6) ? coach.Field_6 : null
    };
  };
  const staff = (team) => ({
    hc: staffMember(team, 'HeadCoach'),
    oc: staffMember(team, 'OffensiveCoordinator'),
    dc: staffMember(team, 'DefensiveCoordinator')
  });
  const pollRank = (value) => Number.isFinite(value) && value > 0 ? value : null;
  const leagueTeams = teamTable.records.filter(live).map((team) => ({
    id: team.index,
    name: team.DisplayName,
    nickname: team.NickName || '',
    short: team.ShortName || '',
    color: hexColor(team.TEAM_BACKGROUNDCOLORR, team.TEAM_BACKGROUNDCOLORG, team.TEAM_BACKGROUNDCOLORB),
    color2: team.TEAM_HAS_SECONDARY_COLOR ? hexColor(team.TEAM_BACKGROUNDCOLORR2, team.TEAM_BACKGROUNDCOLORG2, team.TEAM_BACKGROUNDCOLORB2) : null,
    mediaRank: pollRank(team.MediaPoll_CurrentRank),
    mediaLastRank: pollRank(team.MediaPoll_LastWeeksRank),
    coachesRank: pollRank(team.CoachesPoll_CurrentRank),
    staff: staff(team),
    offScheme: clean(team.CurrentOffensiveScheme),
    defScheme: clean(team.CurrentDefensiveScheme),
    offRank: team.OffensiveRank ?? null,
    defRank: team.DefensiveRank ?? null,
    ratings: Object.fromEntries(['OVR', 'OFF', 'DEF', 'QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB', 'ST']
      .map((unit) => [unit, team[`TEAM_RATING${unit}`] ?? null]))
  }));

  const totalYards = (data) => {
    const stats = recordFrom(teamStatsTable, data);
    return stats ? (stats.OFFYARDS ?? null) : null;
  };
  // A played game's team stat line, for the box score (TeamStats via Home/AwayTeamStatCache)
  const GAME_STATS = ['FIRSTDOWNS', 'OFFYARDS', 'OFFPASSYARDS', 'PASSCOMPLETIONS', 'PASSATTEMPTS', 'PASSTDS', 'OFFRUSHYARDS', 'RUSHATTEMPTS',
    'RUSHTDS', 'THIRDDOWNCONV', 'THIRDDOWNS', 'FOURTHDOWNCONV', 'FOURTHDOWNS', 'OFFREDZONETDS', 'OFFREDZONES', 'TAKEAWAYS', 'SACKS',
    'PENALTIES', 'PENALTYYARDS', 'POSSESSIONTIME'];
  const gameStatLine = (data) => {
    const stats = recordFrom(teamStatsTable, data);
    return stats ? Object.fromEntries(GAME_STATS.map((key) => [key, stats[key] ?? 0])) : null;
  };
  const leagueGames = [];
  for (const game of gameTable.records.filter(live)) {
    if (game.SeasonYear !== seasonInfo.CurrentYear) continue;
    const home = recordFrom(teamTable, ref(game, 'HomeTeam'));
    const away = recordFrom(teamTable, ref(game, 'AwayTeam'));
    if (!home || !away) continue;
    // Only finished games count as played ('HomeWon', 'AwayWon', ties)
    const played = /Won|Tie/.test(game.GameStatus || '');
    leagueGames.push({
      id: game.index,
      week: game.SeasonWeek,
      weekType: game.SeasonWeekType,
      homeId: home.index,
      awayId: away.index,
      played,
      homeScore: played ? game.HomeScore : null,
      awayScore: played ? game.AwayScore : null,
      homeQuarters: played ? [game.HomeScoreQuarter1, game.HomeScoreQuarter2, game.HomeScoreQuarter3, game.HomeScoreQuarter4] : null,
      awayQuarters: played ? [game.AwayScoreQuarter1, game.AwayScoreQuarter2, game.AwayScoreQuarter3, game.AwayScoreQuarter4] : null,
      homeYards: played ? totalYards(ref(game, 'HomeTeamStatCache')) : null,
      awayYards: played ? totalYards(ref(game, 'AwayTeamStatCache')) : null,
      homeStats: played ? gameStatLine(ref(game, 'HomeTeamStatCache')) : null,
      awayStats: played ? gameStatLine(ref(game, 'AwayTeamStatCache')) : null
    });
  }

  // Every rostered player's stat lines this season. Lines with nothing but snaps/starts are skipped to keep the output small.
  const QUIET_FIELDS = new Set(['GAMESSTARTED', 'DOWNSPLAYED']);
  const leaguePlayers = [];
  for (const team of teamTable.records.filter(live)) {
    const teamRoster = recordFrom(rosterTable, ref(team, 'Roster'));
    for (const key of teamRoster ? refFields(teamRoster) : []) {
      const player = recordFrom(playerTable, ref(teamRoster, key));
      if (!player) continue;
      const list = await recordFromAny(ref(player, 'GameStats'));
      if (!list) continue;
      const games = [];
      for (const statKey of refFields(list)) {
        const stat = await recordFromAny(ref(list, statKey));
        const game = stat && await recordFromAny(ref(stat, 'SeasonGame'));
        if (!game || game.SeasonYear !== seasonInfo.CurrentYear) continue;
        const stats = {};
        for (const field of stat.fieldsArray) {
          const value = stat[field.offset.name];
          if (!field.offset.isReference && typeof value === 'number' && value !== 0) stats[field.offset.name] = value;
        }
        if (Object.keys(stats).some((name) => !QUIET_FIELDS.has(name))) games.push({ gameId: game.index, week: game.SeasonWeek, stats });
      }
      if (!games.length) continue;
      leaguePlayers.push({
        id: playerId(player),
        name: `${player.FirstName || ''} ${player.LastName || ''}`.trim(),
        position: player.Position,
        classYear: clean(player.SchoolYear),
        redshirt: clean(player.RedshirtStatus),
        jersey: player.JerseyNum ?? null,
        assetName: clean(player.PLYR_ASSETNAME),
        headAsset: clean(player.GenericHeadAssetName),
        ...background(player),
        teamId: team.index,
        games
      });
    }
  }

  // ---------- Scoring summaries (a rolling pool of about 60 recent games; older ones get overwritten) ----------
  // Each score records the quarter, time left, score type and the running score, plus a stat snapshot of each team's
  // featured passer, rusher and receiver. The snapshots aren't linked records: each is a packed list of up to ten
  // references (table id in the top 15 bits, row in the low 17). The snapshot players identify the two teams.
  // Several tables share these names; the real ones are the largest
  const largest = async (name) => {
    let best = null, bestCount = 0;
    for (const table of franchise.tables.filter((t) => t.name === name)) {
      if (!table.recordsRead) await table.readRecords();
      const count = table.records.filter(live).length;
      if (count > bestCount) { best = table; bestCount = count; }
    }
    return best;
  };
  const scoringPool = await largest('ScoringSummary');
  const scoringLists = await largest('ScoringSummary[]');
  const scoringSummaries = [];
  if (scoringPool && scoringLists) {
    const teamOfPlayer = new Map();
    for (const team of teamTable.records.filter(live)) {
      const teamRoster = recordFrom(rosterTable, ref(team, 'Roster'));
      for (const key of teamRoster ? refFields(teamRoster) : []) {
        const data = ref(teamRoster, key);
        if (isValidRef(data)) teamOfPlayer.set(data.rowNumber, team.index);
      }
    }
    const packedRefs = (record) => {
      const field = record.fieldsArray[0];
      const view = field && record[field.offset.name] && record[field.offset.name]._view;
      if (!view) return [];
      const bytes = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
      const refs = [];
      for (let i = 0; i + 4 <= bytes.length; i += 4) {
        const value = ((bytes[i] << 24) | (bytes[i + 1] << 16) | (bytes[i + 2] << 8) | bytes[i + 3]) >>> 0;
        if (value) refs.push({ tableId: value >>> 17, rowNumber: value & 0x1FFFF });
      }
      return refs;
    };
    const snapshots = async (row, side) => {
      const list = await recordFromAny(ref(row, side));
      const out = [];
      for (const data of list ? packedRefs(list) : []) {
        const snap = await recordFromAny(data);
        const player = snap && recordFrom(playerTable, ref(snap, 'PlayerRef'));
        if (!player) continue;
        out.push({ playerId: playerId(player), name: `${player.FirstName || ''} ${player.LastName || ''}`.trim(), position: player.Position,
                   teamId: teamOfPlayer.get(player.index) ?? null, touchdowns: snap.Touchdowns || 0, catches: snap.CompsRecs || 0,
                   attempts: snap.Attempts || 0, yards: snap.Yards || 0 });
      }
      return out;
    };
    for (const list of scoringLists.records.filter(live)) {
      const plays = [];
      for (const key of refFields(list)) {
        const row = recordFrom(scoringPool, ref(list, key));
        if (!row) continue;
        plays.push({ quarter: row.Quarter, secondsLeft: row.TimeStampInSec, type: clean(row.Conversion),
                     homeBefore: row.HomePreviousScore, homeAfter: row.HomeCurrentScore, awayBefore: row.AwayPreviousScore, awayAfter: row.AwayCurrentScore,
                     home: await snapshots(row, 'HomePlayerSnapshots'), away: await snapshots(row, 'AwayPlayerSnapshots') });
      }
      if (!plays.length) continue;
      // Game order: by quarter, then the clock running down
      plays.sort((a, b) => a.quarter - b.quarter || b.secondsLeft - a.secondsLeft);
      const side = (key) => plays.flatMap((p) => p[key]).map((s) => s.teamId).find((id) => id !== null && id !== undefined) ?? null;
      const last = plays[plays.length - 1];
      scoringSummaries.push({ homeId: side('home'), awayId: side('away'), homeScore: last.homeAfter, awayScore: last.awayAfter, plays });
    }
  }

  // The game's own national awards and Heisman ranking
  const awardsTable = byName('Awards');
  const awardRoot = awardsTable ? (await awardsTable.readRecords(), awardsTable.records.find(live)) : null;
  const recordsIn = async (owner, key) => {
    const list = owner && await recordFromAny(ref(owner, key));
    const rows = [];
    for (const fieldKey of list ? refFields(list) : []) {
      const row = await recordFromAny(ref(list, fieldKey));
      if (row) rows.push(row);
    }
    return rows;
  };
  const teamIdOf = (row) => recordFrom(teamTable, ref(row, 'Team'))?.index ?? null;
  const playerIdOf = (row) => { const p = recordFrom(playerTable, ref(row, 'Player')); return p ? playerId(p) : null; };
  const weeklyAwards = (await recordsIn(awardRoot, 'WeeklyAwards')).map((row) => ({
    type: row.AwardType, week: row.PeriodIndex, playerId: playerIdOf(row), teamId: teamIdOf(row)
  }));
  const heisman = (await recordsIn(awardRoot, 'HeismanRanking')).map((row) => ({
    rank: Number.isFinite(row.CurrentRank) ? row.CurrentRank + 1 : null,
    lastRank: Number.isFinite(row.LastWeekRank) && row.LastWeekRank >= 0 ? row.LastWeekRank + 1 : null,
    playerId: playerIdOf(row), teamId: teamIdOf(row)
  }));

  // ---------- Conferences, season awards and the bowl schedule ----------
  // Conference: Name plus TeamSlots, a list pointing at the member teams (directly, or through a slot record)
  const conferences = [];
  const conferenceTable = await largest('Conference');
  for (const conf of conferenceTable ? conferenceTable.records.filter(live) : []) {
    const slots = await recordFromAny(ref(conf, 'TeamSlots'));
    const teamIds = [];
    for (const key of slots ? refFields(slots) : []) {
      const data = ref(slots, key);
      let team = recordFrom(teamTable, data);
      if (!team) {
        const slot = await recordFromAny(data);
        team = slot && recordFrom(teamTable, ref(slot, 'Team'));
      }
      if (team) teamIds.push(team.index);
    }
    conferences.push({ id: conf.index, name: clean(conf.Name), champGame: clean(conf.ConfChampGameName), teamIds });
  }
  const conferenceName = new Map();
  if (conferenceTable) for (const conf of conferences) conferenceName.set(conf.id, conf.name);

  // PlayerAward holds the game's All-America and All-Conference teams (preseason now, final ones at season end)
  // and the weekly player awards. Players are exported in full: linemen often have no stat lines.
  const playerAwardTable = await largest('PlayerAward');
  const seasonAwards = [];
  for (const row of playerAwardTable ? playerAwardTable.records.filter(live) : []) {
    if (row.Period !== 'Season') continue;
    const player = recordFrom(playerTable, ref(row, 'Player'));
    if (!player) continue;
    const confRef = ref(row, 'Conference');
    seasonAwards.push({
      type: clean(row.AwardType), position: clean(row.Position), score: row.AwardScore ?? null,
      conference: confRef && conferenceTable && confRef.tableId === conferenceTable.header.tableId ? conferenceName.get(confRef.rowNumber) || null : null,
      teamId: teamIdOf(row), playerId: playerId(player),
      name: `${player.FirstName || ''} ${player.LastName || ''}`.trim(), jersey: player.JerseyNum ?? null,
      classYear: clean(player.SchoolYear), overall: player.OverallRating ?? null,
      assetName: clean(player.PLYR_ASSETNAME), headAsset: clean(player.GenericHeadAssetName)
    });
  }

  // Bowls and the playoff: scheduled from the start of the season with the teams left empty until they're set
  const bowlInfoName = async (game) => clean((await recordFromAny(ref(game, 'BowlGame')))?.Name);
  const bowlGames = [];
  for (const game of gameTable.records.filter(live)) {
    if (game.SeasonYear !== seasonInfo.CurrentYear || !game.SeasonWeekType || game.SeasonWeekType === 'RegularSeason') continue;
    const home = recordFrom(teamTable, ref(game, 'HomeTeam'));
    const away = recordFrom(teamTable, ref(game, 'AwayTeam'));
    const played = /Won|Tie/.test(game.GameStatus || '');
    bowlGames.push({
      id: game.index, week: game.SeasonWeek, weekType: game.SeasonWeekType, name: await bowlInfoName(game),
      homeId: home ? home.index : null, awayId: away ? away.index : null, played,
      homeScore: played ? game.HomeScore : null, awayScore: played ? game.AwayScore : null,
      date: game.GameDateMonth > 0 && game.GameDateDay > 0
        ? `${(seasonInfo.BaseCalendarYear ?? 2026) + (game.SeasonYear ?? 0) + (game.GameDateMonth < 7 ? 1 : 0)}-${String(game.GameDateMonth).padStart(2, '0')}-${String(game.GameDateDay).padStart(2, '0')}`
        : null
    });
  }

  // ---------- Rivals ----------
  // The team's three named rivals (Rival1-3) and its rivalry records: name, all-time series, streak and last meeting,
  // which the game updates after every rivalry game. StreakTeam 0 means Team1 holds the streak, 1 means Team2.
  const rivalries = [];
  const rivalRank = new Map(['Rival1TeamRef', 'Rival2TeamRef', 'Rival3TeamRef']
    .map((key, i) => [recordFrom(teamTable, ref(userTeam, key))?.index, i + 1]).filter(([id]) => id !== undefined));
  const rivalryList = await recordFromAny(ref(userTeam, 'Rivalries'));
  for (const key of rivalryList ? refFields(rivalryList) : []) {
    const row = await recordFromAny(ref(rivalryList, key));
    const team1 = row && recordFrom(teamTable, ref(row, 'Team1'));
    const team2 = row && recordFrom(teamTable, ref(row, 'Team2'));
    if (!team1 || !team2) continue;
    const weAreTeam1 = team1.index === userTeam.index;
    const opponent = weAreTeam1 ? team2 : team1;
    const [ours, theirs] = weAreTeam1 ? ['Team1', 'Team2'] : ['Team2', 'Team1'];
    rivalries.push({
      name: clean(row.Name), opponentId: opponent.index, rank: rivalRank.get(opponent.index) ?? null,
      ourWins: row[`${ours}Wins`] ?? 0, theirWins: row[`${theirs}Wins`] ?? 0,
      streakOurs: (row.StreakTeam === 0) === weAreTeam1, streakLength: row.StreakLength ?? 0,
      lastOurs: row[`${ours}LastScore`] ?? null, lastTheirs: row[`${theirs}LastScore`] ?? null
    });
  }
  // Named rivals without a rivalry record still count (e.g. a rival with no trophy game)
  for (const [teamId, rank] of rivalRank) {
    if (!rivalries.some((r) => r.opponentId === teamId)) rivalries.push({ name: '', opponentId: teamId, rank });
  }

  // ---------- Program history ----------
  // The school record book (game, season and career records in nine stats, with the real record holders; the game
  // updates them when a record falls) and the year-by-year history the game keeps for the program (one entry per
  // season played in the dynasty).
  const programRecords = [];
  for (const [scope, key] of [['game', 'GameStatRecords'], ['season', 'SeasonStatRecords'], ['career', 'CareerStatRecords']]) {
    const list = await recordFromAny(ref(userTeam, key));
    for (const field of list ? refFields(list) : []) {
      const row = await recordFromAny(ref(list, field));
      if (!row || !row.statType) continue;
      programRecords.push({ scope, stat: clean(row.statType), value: row.statValue ?? null, year: row.calendarYear ?? null,
                            name: `${row.firstName || ''} ${row.lastName || ''}`.trim(), position: clean(row.position) });
    }
  }
  const programHistory = [];
  const seasons = await recordFromAny(ref(userTeam, 'TeamSeriesHistory'));
  for (const field of seasons ? refFields(seasons) : []) {
    const row = await recordFromAny(ref(seasons, field));
    if (!row || !row.Year) continue;
    programHistory.push({
      year: row.Year, wins: row.Wins ?? 0, losses: row.Losses ?? 0, ties: row.Ties ?? 0,
      confWins: row.ConferenceWins ?? 0, confLosses: row.ConferenceLosses ?? 0, conference: clean(row.ConferenceName),
      confStanding: row.FinalConferenceStanding ?? null, finalRank: row.FinalMediaRank ?? null, coach: clean(row.CoachName),
      bowls: ['FirstRoundCFPBowlGameResult', 'QuarterFinalsBowlGameResult', 'SemiFinalsBowlGameResult', 'NationalBowlGameResult']
        .map((k) => clean(row[k])).filter(Boolean)
    });
  }

  // ---------- Game plan rosters: us and every opponent on our schedule ----------
  const RATING_FIELDS = {
    SPD: 'SpeedRating', ACC: 'AccelerationRating', AGI: 'AgilityRating', STR: 'StrengthRating', AWR: 'AwarenessRating',
    PBK: 'PassBlockRating', PBP: 'PassBlockPowerRating', PBF: 'PassBlockFinesseRating',
    RBK: 'RunBlockRating', RBP: 'RunBlockPowerRating', RBF: 'RunBlockFinesseRating', IBL: 'ImpactBlockingRating',
    PMV: 'PowerMovesRating', FMV: 'FinesseMovesRating', BSH: 'BlockSheddingRating', TAK: 'TackleRating',
    HPW: 'HitPowerRating', PUR: 'PursuitRating', PRC: 'PlayRecognitionRating',
    MCV: 'ManCoverageRating', ZCV: 'ZoneCoverageRating', PRS: 'PressRating',
    CTH: 'CatchingRating', CIT: 'CatchInTrafficRating', SPC: 'SpectacularCatchRating', RLS: 'ReleaseRating',
    SRR: 'ShortRouteRunningRating', MRR: 'MediumRouteRunningRating', DRR: 'DeepRouteRunningRating',
    CAR: 'CarryingRating', BCV: 'BCVisionRating', BTK: 'BreakTackleRating', JKM: 'JukeMoveRating', TRK: 'TruckingRating',
    THP: 'ThrowPowerRating', SAC: 'ThrowAccuracyShortRating', MAC: 'ThrowAccuracyMidRating', DAC: 'ThrowAccuracyDeepRating',
    TUP: 'ThrowUnderPressureRating', TOR: 'ThrowOnTheRunRating', PAC: 'PlayActionRating', BSK: 'BreakSackRating',
    KPW: 'KickPowerRating', KAC: 'KickAccuracyRating'
  };
  const planPlayer = (player) => ({
    id: playerId(player),
    name: `${player.FirstName || ''} ${player.LastName || ''}`.trim(),
    position: player.Position,
    jersey: player.JerseyNum ?? null,
    overall: player.OverallRating ?? null,
    classYear: clean(player.SchoolYear),
    handed: clean(player.PLYR_HANDEDNESS),
    heightInches: player.Height ?? null,
    weightPounds: Number.isFinite(player.Weight) ? player.Weight + 160 : null,
    injuryStatus: clean(player.InjuryStatus) || 'Uninjured',
    injuryType: clean(player.InjuryType),
    injurySeverity: clean(player.InjurySeverity),
    assetName: clean(player.PLYR_ASSETNAME),
    headAsset: clean(player.GenericHeadAssetName),
    ratings: Object.fromEntries(Object.entries(RATING_FIELDS).map(([key, field]) => [key, player[field] ?? 0]))
  });
  const planTeamIds = new Set([userTeam.index]);
  for (const game of gameTable.records.filter(live)) {
    if (game.SeasonYear !== seasonInfo.CurrentYear) continue;
    const home = recordFrom(teamTable, ref(game, 'HomeTeam'));
    const away = recordFrom(teamTable, ref(game, 'AwayTeam'));
    if (home && away && (home.index === userTeam.index || away.index === userTeam.index)) {
      planTeamIds.add(home.index);
      planTeamIds.add(away.index);
    }
  }
  const planRosters = [];
  for (const team of teamTable.records.filter(live)) {
    if (!planTeamIds.has(team.index)) continue;
    const teamRoster = recordFrom(rosterTable, ref(team, 'Roster'));
    const players = (teamRoster ? refFields(teamRoster) : [])
      .map((key) => recordFrom(playerTable, ref(teamRoster, key)))
      .filter(Boolean)
      .map(planPlayer);
    planRosters.push({ teamId: team.index, players, depthChart: depthChartOf(team) });
  }

  // ---------- Recruiting: our board, our commits and the top national prospects ----------
  // Recruiting refers to teams by the team's TeamIndex field, not its row, so translate back to our team ids
  const teamIdByIndex = new Map(teamTable.records.filter(live).map((team) => [team.TeamIndex, team.index]));
  const recordsOf = async (owner, key) => {
    const list = owner && await recordFromAny(ref(owner, key));
    const rows = [];
    for (const fieldKey of list ? refFields(list) : []) {
      const row = await recordFromAny(ref(list, fieldKey));
      if (row) rows.push(row);
    }
    return rows;
  };
  const prospect = async (recruit, extra = {}) => {
    const player = await recordFromAny(ref(recruit, 'Player'));
    if (!player) return null;
    const topSchools = (await recordsOf(recruit, 'TopSchoolsList'))
      .map((school) => ({ teamId: teamIdByIndex.get(school.TeamId) ?? null, influence: school.TeamInfluence ?? 0 }))
      .filter((school) => school.teamId !== null);
    return {
      id: playerId(player),
      name: `${player.FirstName || ''} ${player.LastName || ''}`.trim(),
      position: player.Position,
      stars: STARS[player.ProspectStarRating] ?? null,
      overall: player.OverallRating ?? null,
      heightInches: player.Height ?? null,
      weightPounds: Number.isFinite(player.Weight) ? player.Weight + 160 : null,
      hometown: [clean(player.PLYR_HOME_TOWN), clean(player.PLYR_HOME_STATE)].filter(Boolean).join(', '),
      recruitClass: clean(recruit.Class),
      stage: clean(recruit.RecruitStage),
      nationalRank: recruit.NationalRank ?? null,
      positionRank: recruit.PositionRank ?? null,
      stateRank: recruit.StateRank ?? null,
      offers: recruit.TotalScholarshipOffers ?? null,
      assetName: clean(player.PLYR_ASSETNAME),
      headAsset: clean(player.GenericHeadAssetName),
      topSchools,
      ...extra
    };
  };

  const recruitingBoard = [];
  const boardRecord = await recordFromAny(ref(userTeam, 'RecruitingBoard'));
  for (const target of await recordsOf(boardRecord, 'Recruits')) {
    const recruit = await recordFromAny(ref(target, 'Recruit'));
    const entry = recruit && await prospect(recruit, {
      scholarship: clean(target.ScholarshipStatus),
      influence: target.ProspectInfluenceTotal ?? 0,
      influenceLastWeek: target.ProspectInfluenceTotalLastWeek ?? 0,
      committedWeek: target.CommittedWeekNumber || null,
      favorite: Boolean(target.IsFavorite)
    });
    if (entry) recruitingBoard.push(entry);
  }

  const commitsTable = await recordFromAny(ref(userTeam, 'CommittedPlayers'));
  const commits = [];
  for (const row of commitsTable ? await recordsOf(userTeam, 'CommittedPlayers') : []) {
    // Entries may point at the Recruit or straight at the Player
    const recruit = row.fieldsArray.some((field) => field.offset.name === 'TopSchoolsList') ? row : null;
    const entry = recruit ? await prospect(recruit) : null;
    if (entry) commits.push(entry);
  }

  const recruitTable = byName('Recruit');
  if (recruitTable && !recruitTable.recordsRead) await recruitTable.readRecords();
  const topProspects = [];
  const ranked = (recruitTable ? recruitTable.records.filter(live) : [])
    .filter((r) => Number.isInteger(r.NationalRank) && r.NationalRank > 0)
    .sort((a, b) => a.NationalRank - b.NationalRank)
    .slice(0, 50);
  for (const recruit of ranked) {
    const entry = await prospect(recruit);
    if (entry) topProspects.push(entry);
  }

  // ---------- Offseason ----------
  // Where the dynasty is in its year, and the game's end-of-season departure lists (empty until the season ends)
  const phase = {
    stage: clean(seasonInfo.CurrentStage), weekType: clean(seasonInfo.CurrentWeekType), offseasonStage: seasonInfo.CurrentOffseasonStage ?? 0,
    offseasonStages: seasonInfo.OffseasonNumStages ?? null, seasonYear: seasonInfo.CurrentSeasonYear ?? null,
    carousel: Boolean(seasonInfo.IsCarouselPeriodActive), staffHiring: Boolean(seasonInfo.IsStaffHiringPeriodActive),
    transferPortal: Boolean(seasonInfo.IsTransferPortalNewlyAvailable || seasonInfo.IsTransferSignPeriodActive),
    signing: Boolean(seasonInfo.IsSigningPeriodActive), draft: Boolean(seasonInfo.IsDraftPeriodActive || seasonInfo.IsDraftActive)
  };
  const playersIn = async (owner, key) => {
    const list = owner && await recordFromAny(ref(owner, key));
    const out = [];
    for (const field of list ? refFields(list) : []) {
      const data = ref(list, field);
      let player = recordFrom(playerTable, data);
      if (!player) {
        const entry = await recordFromAny(data);  // a LeavingPlayer-style record pointing at the player
        player = entry && recordFrom(playerTable, ref(entry, 'Player'));
      }
      if (player) out.push(playerId(player));
    }
    return out;
  };
  const leavingTable = byName('PlayersLeavingEndOfSeason');
  const leavingRoot = leavingTable ? (await leavingTable.readRecords(), leavingTable.records.find(live)) : null;
  const departures = { transferCandidates: await playersIn(leavingRoot, 'TransferCandidates'), earlyDraft: await playersIn(leavingRoot, 'EarlyDraft') };

  process.stdout.write(JSON.stringify({
    source: path.basename(savePath),
    team: { name: userTeam.DisplayName, nickname: userTeam.NickName || '' },
    currentWeek: seasonInfo.CurrentWeek,
    currentWeekType: seasonInfo.CurrentWeekType,
    phase,
    departures,
    schedule,
    roster,
    depthChart,
    league: { userTeamId: userTeam.index, teams: leagueTeams, games: leagueGames, players: leaguePlayers, weeklyAwards, heisman,
              conferences, seasonAwards, bowlGames },
    scoringSummaries,
    recruiting: { board: recruitingBoard, commits, topProspects },
    rivalries,
    programRecords,
    programHistory,
    planRosters
  }));
} finally {
  fs.rmSync(copyPath, { force: true });
}
