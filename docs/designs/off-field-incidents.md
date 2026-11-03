# Design: off-field incidents and player care

**Status:** tabled (design only, nothing built). Drafted 2026-11-03.

## Goal

Make the head coach care for players beyond kickoff. Things happen to players off the field. They're
shaped by each player's persona and by the moment in the season, and how the coach responds changes the
player in the actual game save: availability (injuries), how he starts the next game (Hot/Cold), his
confidence, and occasionally a mental ability. The Locker Room, Press Room, dispatch and podcast all carry
the fallout.

## What the save allows (tested on throwaway copies, never the real save)

| Lever | Fields on the player record | Write test |
|---|---|---|
| Starts Hot / Cold | `StartingHotCold` (Hot, Neutral, Cold) | Worked |
| Confidence | `ConfidenceRating` (0-99, reset to 50 each preseason) | Worked |
| Mental ability | `MentalAbility1-3` + `MentalAbilityRank1-3` (Bronze-Platinum) | Worked |
| Injury | `InjuryStatus`, `InjuryType`, `InjurySeverity`, `Min/Max/TotalInjuryDuration`, `LatestInjuryWeek`, `LatestInjuryStage`, `WasPreviouslyInjured` | Worked |
| Heal | the same fields back to Uninjured | Not yet tried |

What we learned about the game:

- **Hot/Cold is not earned.** About 3% of players are Hot and 3% Cold. The state doesn't follow confidence,
  the last game's grade or overall rating. It is rolled per dynasty, mostly holds all season, and
  occasionally reshuffles a few players.
- **Confidence does move with performance.** Wyoming's standouts sit at 66-71; everyone else is at 52 or
  higher. But this dynasty has `ConfidenceAdjustedRatingsEnabled = false`, so confidence currently doesn't
  change ratings.
- **Injury types carry their severity in the name** (`HipDislocationCoupleGames`,
  `AnkleDislocatedSeveralGames`, `AnkleAchillesTear` for season-ending). A forced injury must use a real
  type from the matching group. Durations count down: Total is the original length, Min/Max the games left.
- **Mental abilities seen:** WinningTime, ClearHeaded, TheNatural, Headstrong, HomeFanFavorite,
  RoadFanFavorite, BestFriend, OL/DL/DB Rally. Wyoming currently has none.

**Must be confirmed in the game before building on it:**

1. The game honours an edited Hot/Cold at kickoff and doesn't re-roll it.
2. Which mental abilities a position can actually use. For example, does ClearHeaded on a left tackle do
   anything?
3. A forced injury counts down weekly, shows on the Injury Report, and AI depth charts sit the player.
4. Whether confidence-adjusted ratings can be switched on, and whether confidence matters while they're off.

## Real players vs generated players

Rosters are about 90% real college athletes (their own scanned face, `Unique_...` head asset) and 10%
generated (generic face). The real players are gone by the **2031** season (dynasty year 6): the last are
today's freshmen who use a redshirt year.

**Rule:** scandalous incidents (drunk-driving crash, a fight or shooting, legal trouble) only ever happen
to **generic-face players**. Real players only get **blameless** incidents: a car accident that isn't their
fault, a pickup-game injury, a family emergency, illness, burnout. The app never writes a story accusing a
real, named person of a crime or scandal. Caveat: a generic face usually means fictional but isn't
guaranteed, since a real player who simply wasn't scanned also gets a generic face.

## How often

There's no published rate: the NCAA's injury tracking only records games and practices. College-age data
(US 18-24) suggests roughly:

- non-sport concussions: about 0.7 per 85-man roster per year
- assault injuries: about 0.8 per roster per year
- serious crashes: rare

**Baseline for the game:** about 1-3 off-field incidents per team per season, mostly minor. About one that
costs games each season, and a dramatic one every few seasons. Tunable in settings.

## What sets an event off (three layers)

1. **A quiet background chance each week**, from the baseline, adjusted by:
   - **Persona:** Undisciplined, Headstrong or showboat-type traits, and star or elite dev trait, raise it.
     Disciplined lowers it.
   - **Status:** starters and stars are likelier to be in the spotlight.
   - **Confidence:** unusually high (overconfident) or unusually low (struggling) raises it.
   - **Calendar:** bye weeks, holidays, the offseason.
   - **Big moments spike it:** a rivalry win, a ranked upset, a conference title, and a **national
     championship** (a 25-40% chance of a celebration incident, never guaranteed).
   - **Care lowers it:** players the coach has recently supported or mentored are less likely to be involved.
2. **Storylines that build to it.** Most incidents get warning signs first, in Locker Room storylines or on
   the campus feed: missed curfew, late to film, partying talk, a feud. The coach can act on them (talk,
   discipline, assign a mentor), which lowers the risk. Ignoring them lets the arc escalate into an incident.
   A bad outcome should feel earned, not random.
3. **The message is how it lands.** A "phone buzz" in the app: a 2 a.m. text from an assistant, a call from
   campus police, a reporter asking for comment. The coach must respond before the next game is played.

## The coach's response

| Response | Typical effects (examples, to be tuned) |
|---|---|
| Support (visit, family time) | Confidence +, locker room approves; may start Cold next game |
| Discipline (extra conditioning, sit a half) | Confidence -, discipline storyline; teammates respect it |
| Suspend (1+ games) | Marked out on the depth chart for N games; press pressure drops |
| Counseling / mentor | Lower future risk; chance of a mental ability over the arc (e.g. Headstrong) |
| Protect him from the press | Short-term calm; risk the story breaks later, bigger |

Injury severity comes from the incident itself, not the response. Responses shape recovery speed (a small
bonus for good care), confidence and storyline outcomes.

## Writing to the save (safety rules)

- Changes queue as **pending save changes** in BASIC_OS and are listed exactly ("Rex Johnsen: Injured,
  HipDislocationCoupleGames, 2 games"). The coach approves each batch.
- Written only when **CFB27 is closed**. The save file is **backed up first**, re-read afterwards to verify,
  and every batch has **one-click undo** from that backup.
- Never touches anything but the listed player fields.

## Where it shows up in the app

- **Locker Room:** warning signs and incident storylines.
- **Phone buzz:** the incident message and response choices, plus the finish notice.
- **Press Room:** reporters ask about it, and the coach's answer can calm or inflame it.
- **Dispatch, campus feed and podcast** cover it (blameless wording for real players).
- **Injury report, depth chart, player profile:** the incident and its status.

## Open questions

- How often and how harsh by default, and should there be a difficulty setting?
- Apply automatically, or always require approval? (The design assumes approval.)
- Can incidents happen in the offseason (stronger risk: summer, spring break)?
- Should the national-title spike also apply to other teams (league news), or only to us?

## Build order (when un-tabled)

1. **In-game test:** one edited Hot/Cold, ability, injury and heal, loaded in CFB27 to see what the game honours.
2. **Save writer:** pending changes, backup, write, verify, undo.
3. **Background chance and calendar spikes.**
4. **Warning-sign storylines** and coach interventions.
5. **Phone buzz and responses**, wired to the save writer and the story outlets.
