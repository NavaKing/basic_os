# Design: player care (needs, phone and inbox, off-field incidents)

**Status:** tabled (design only, nothing built). Drafted 2026-11-03; revised the same day to turn incidents
into a Tamagotchi-style care game with a phone and an inbox.

## Goal

Make the head coach care for players beyond kickoff, as a game. Each player has needs that drain between
games. Tend to them and players grow, trust you and stay. Neglect them and the mess piles up: warning signs
first, then **off-field incidents** that hit the actual game save (injuries, Hot/Cold starts, confidence,
suspensions). Players text you through an in-app **phone**; school staff send an **inbox** of grades, medical
updates and requests. The Locker Room, Press Room, dispatch and podcast carry the fallout.

## The core loop

1. **Needs drain each week**, at a speed set by each player's persona.
2. The app picks a **weekly care list** of the players who need you, and they message you.
3. You spend a limited budget of **coach hours** on texts, calls, sit-downs and visits, or **delegate** to a
   position coach.
4. Needs left empty create **warning signs**, which escalate into **incidents** if still ignored.
5. Care builds **trust**, which pays off on and off the field.

### Needs

| Need | What drains it | What fills it |
|---|---|---|
| Morale | losing snaps, losses, being benched | praise, playing time, wins |
| Academics | game weeks, travel, low discipline | tutors, study hall, check-ins |
| Home life | distance from home, family events | calls home, letting him travel |
| Focus | Undisciplined trait, fame, big wins | structure, mentors, a talk |
| Health / rest | heavy snap counts, injuries | rest days, trainer visits |

Each need runs 0-100. Persona sets the drain speed: Undisciplined or Headstrong traits drain Focus faster,
star or elite dev traits drain Focus and Morale faster (fame), Disciplined drains Focus slower. Players far
from home drain Home life faster (hometown and state are already in the save).

### Making 85 players playable

- **Weekly care list:** about 5-10 players a week need attention (starters, stars, anyone with a low need,
  anyone whose persona flags them). The rest of the roster runs on autopilot with slow, gentle drains.
- **Coach hours:** about 10 hours a week. A text costs 1, a call 2, a sit-down 3, a home visit 5. Choosing
  who gets your time is the game.
- **Delegation:** a position coach can handle a player for less of your time but restores less, and builds
  little trust with you.

### Trust: the reward for care

Trust is per player and grows with care. A trusted player:

- recovers a little faster from injuries and is likelier to start **Hot**
- can earn a **mental ability** over a storyline arc (e.g. ClearHeaded, Headstrong)
- is less likely to land on the **Offseason transfer watch**
- gives better Press Room and podcast material ("Coach has always been there for me")

## The phone (Messages)

- One thread per player. Players text in their own voice, written by gemma from their persona, needs and
  situation, e.g. "Coach, my grandma's in the hospital, can I go home this weekend?", "Why am I not getting
  snaps?", "Can I skip Thursday film for an NIL shoot?"
- **Replies:** choice buttons (quick, predictable effects) and/or free text, which gemma reads for tone and
  intent and maps to the same effects (open question 3).
- **Unanswered texts drain the need faster.** This is the Tamagotchi pressure.
- **Incidents land here too:** a 2 a.m. text from an assistant, a call from campus police, a reporter asking
  for comment. You must respond before the next game is played.

## The inbox (Email)

School staff send information that needs action:

| Sender | Sends | Typical action |
|---|---|---|
| Academic advisor | midterm grade reports, GPA, eligibility warnings | assign a tutor, mandate study hall |
| Team doctor / trainer | injury updates, rest recommendations, burnout flags | rest a player, limit snaps |
| Compliance office | NIL deals to approve, rules questions | approve or deny |
| Athletic director | expectations, booster pressure, hot-seat warnings tied to the record | none: context and pressure |
| Parents, media | concerns, interview requests | reply, schedule, decline |

Grades are an app-side meter (the save has no academics). For real players, academic trouble stays mild
("struggling in a class"); no cheating or eligibility scandals (see the rule below).

## Timing

The game ticks when a **new week syncs** from the save: needs drain, the care list refreshes, messages and
emails arrive, and incident rolls happen. You handle them before playing the next game. Nothing ticks while
you aren't playing.

## Off-field incidents

### How often

There's no published rate: the NCAA's injury tracking only records games and practices. College-age data
(US 18-24) suggests roughly:

- non-sport concussions: about 0.7 per 85-man roster per year
- assault injuries: about 0.8 per roster per year
- serious crashes: rare

**Baseline:** about 1-3 off-field incidents per team per season, mostly minor; about one that costs games
each season, and a dramatic one every few seasons.

### What sets one off

1. **Neglect:** needs left empty, especially Focus. This is the main driver: the "mess" of the Tamagotchi.
2. **A background chance each week**, from the baseline, adjusted by:
   - **Persona:** Undisciplined, Headstrong, star or elite dev trait raise it; Disciplined lowers it.
   - **Status:** starters and stars are likelier to be in the spotlight.
   - **Confidence:** unusually high (overconfident) or low (struggling) raises it.
   - **Calendar:** bye weeks, holidays, the offseason.
   - **Big moments spike it:** a rivalry win, a ranked upset, a conference title, and a **national
     championship** (a 25-40% chance of a celebration incident, never guaranteed).
   - **Trust lowers it.**
3. **Warning-sign storylines first.** Most incidents are preceded by signs in the Locker Room, on the campus
   feed, in texts or emails: missed curfew, late to film, partying talk, a feud, bad grades. Acting on them
   lowers the risk; ignoring them lets the arc escalate. A bad outcome should feel earned, not random.

### Real players vs generated players

Rosters are about 90% real college athletes (their own scanned face, `Unique_...` head asset) and 10%
generated (generic face). The real players are gone by the **2031** season (dynasty year 6).

**Rule:** scandalous incidents (drunk-driving crash, a fight or shooting, legal trouble, cheating) only ever
happen to **generic-face players**. Real players only get **blameless** incidents: a car accident that isn't
their fault, a pickup-game injury, a family emergency, illness, burnout. The app never writes a story
accusing a real, named person of a crime or scandal. Caveat: a generic face usually means fictional but
isn't guaranteed (a real player who wasn't scanned also gets one).

### The coach's response

| Response | Typical effects (to be tuned) |
|---|---|
| Support (visit, family time) | Confidence and trust up, locker room approves; may start Cold next game |
| Discipline (extra conditioning, sit a half) | Confidence down, discipline storyline; teammates respect it |
| Suspend (1+ games) | Marked out on the depth chart for N games; press pressure drops |
| Counseling / mentor | Lower future risk; chance of a mental ability over the arc |
| Protect him from the press | Short-term calm; the story may break later, bigger |

Injury severity comes from the incident itself. Responses shape recovery speed (a small bonus for good care),
confidence, trust and storyline outcomes.

## What the save allows (tested on throwaway copies, never the real save)

| Lever | Fields on the player record | Write test |
|---|---|---|
| Starts Hot / Cold | `StartingHotCold` (Hot, Neutral, Cold) | Worked |
| Confidence | `ConfidenceRating` (0-99, reset to 50 each preseason) | Worked |
| Mental ability | `MentalAbility1-3` + `MentalAbilityRank1-3` (Bronze-Platinum) | Worked |
| Injury | `InjuryStatus`, `InjuryType`, `InjurySeverity`, `Min/Max/TotalInjuryDuration`, `LatestInjuryWeek`, `LatestInjuryStage`, `WasPreviouslyInjured` | Worked |
| Heal | the same fields back to Uninjured | Not yet tried |

What we learned about the game:

- **Hot/Cold is not earned.** About 3% of players are Hot and 3% Cold, regardless of confidence, recent
  grades or rating. It is rolled per dynasty, mostly holds all season, and occasionally reshuffles a few.
- **Confidence moves with performance** (Wyoming's standouts sit at 66-71), but this dynasty has
  `ConfidenceAdjustedRatingsEnabled = false`, so it doesn't change ratings.
- **Injury types carry their severity in the name** (`HipDislocationCoupleGames`,
  `AnkleDislocatedSeveralGames`, `AnkleAchillesTear` for season-ending). A forced injury must use a real type
  from the matching group. Durations count down: Total is the original length, Min/Max the games left.
- **Mental abilities seen:** WinningTime, ClearHeaded, TheNatural, Headstrong, HomeFanFavorite,
  RoadFanFavorite, BestFriend, OL/DL/DB Rally. Wyoming currently has none.

**Must be confirmed in the game before relying on it:**

1. The game honours an edited Hot/Cold at kickoff and doesn't re-roll it.
2. Which mental abilities a position can actually use (e.g. ClearHeaded on a left tackle).
3. A forced injury counts down weekly, shows on the Injury Report, and AI depth charts sit the player.
4. Whether confidence-adjusted ratings can be switched on, and whether confidence matters while off.

### Writing to the save (safety rules)

- Changes queue as **pending save changes**, listed exactly ("Rex Johnsen: Injured,
  HipDislocationCoupleGames, 2 games"). The coach approves each batch.
- Written only when **CFB27 is closed**. The save is **backed up first**, re-read afterwards to verify, and
  every batch has **one-click undo** from that backup.
- Never touches anything but the listed player fields.

## Built to be tuned

The balance will take tuning over time, so the system is built for it from day one:

- **Every number in one place:** drain rates, coach hours, action costs, incident odds, trust rewards and
  severity live in one tuning file, shown on a **Settings > Player Care** page. Changing a dial never needs a
  code change.
- **Difficulty presets** (Relaxed, Normal, Demanding) set those dials as a starting point.
- **Simulator:** plays a whole fake season of the care system in seconds and reports incidents, games missed,
  and whether ignoring everyone is a disaster and caring for everyone too easy. Tuning happens here, not in
  the real dynasty.
- **Care log:** each week records what drained, what the coach did, what fired and why ("Focus empty 2 weeks
  + Undisciplined + big win: incident roll 34%"). When something feels unfair, the log points at the dial.
- **Start gentle:** the first release runs on Relaxed, with incidents mostly as warning signs.
- **Save writes come last:** for the first weeks, effects are **app-only** (storylines, press, podcast). Once
  the balance feels right, writing injuries, Hot/Cold and confidence to the save is switched on.

## Where it shows up in the app

- **Phone** and **Inbox:** new windows (like Backups), with unread badges in the tab bar.
- **Care dashboard:** the weekly care list, needs, trust, coach hours left (if needs are visible; question 1).
- **Locker Room:** warning signs and incident storylines.
- **Press Room:** reporters ask about incidents; the coach's answer can calm or inflame them.
- **Dispatch, campus feed and podcast** cover it (blameless wording for real players).
- **Injury report, depth chart, player profile:** status, trust and needs per player.
- **Offseason:** trust feeds the transfer watch.

## Open questions

1. **Visible or hidden needs?** Visible meters with a Care dashboard (classic Tamagotchi), or hidden ones read
   from messages (more realistic)? Leaning visible.
2. **Coach-hours budget:** yes or no?
3. **Replies:** choice buttons, free text read by gemma, or both?
4. **Difficulty:** how punishing should neglect be by default?
5. Apply save changes automatically, or always require approval? (The design assumes approval.)
6. Can incidents happen in the offseason (summer, spring break)?
7. Should big-moment spikes also hit other teams (league news), or only us?

## Iteration 1 (built on feature/player-care)

App-only: nothing is written to the save. The Care button in the tab bar opens the care window.

- **Needs and trust.** Five needs, 0-100, plus trust. Starting needs vary around 70 per player. Each player has a
  stable *temperament* (each need drains 0.6x-1.4x), so one gets homesick easily and another loses focus first.
- **The weekly model.** Each need drains by base + modifiers, scaled by temperament, difficulty and trust (a player
  who trusts the coach drains up to half as fast). The support staff then pull it `staff_rate` of the way back to
  `staff_target`. A player with no extra stress settles around the middle; only stressed players sink below the
  low line (35). This replaced a flat drain, which sent the whole roster to zero together and made care pointless.
- **Warning signs** come almost only from low needs: about 12% a week for each low need (Focus counts extra),
  times persona, big wins and trust. A player whose needs are fine almost never shows one.
- **Coach hours and the care list.** The ten most urgent players each week (lowest need, warnings, birthdays,
  slightly weighted to starters). Actions: Text 1h, Call 2h, Sit-down 3h (clears warnings), Home visit 5h
  (home and morale), Ask a captain 1h, Position coach 1h.
- **Addition 1, leadership council:** 2-4 captains, with suggestions (upperclassmen by rating). "Ask a captain"
  needs one. A captain with morale under 30 drains everyone's morale.
- **Addition 2, life calendar:** exam weeks (7, 8, 14), holiday weeks, senior day (last home game), away games,
  last week's result, and big wins over ranked teams or rivals. App-assigned birthdays give trust bonuses.
- **Addition 3, mentorship pairs:** a good mentor slows the mentee's morale and focus drain and gains trust. An
  undisciplined or unfocused mentor makes focus drain faster.
- **Addition 4, campus feed as a mood ring:** *not built yet.* It needs changes to the hub generator's tweet
  prompts. Next iteration.
- **Tuning:** `basic_os/care_tuning.json` holds every dial. The simulator (12 made-up weeks, ignore vs care)
  currently reports, for the real roster:

  | Preset | Warnings, ignore | Warnings, care | Player-weeks with a low need, ignore | Player-weeks with a low need, care |
  |---|---|---|---|---|
  | Relaxed | 1 | 1 | 5 | 0 |
  | Normal | 19 | 16 | 136 | 86 |
  | Demanding | 36 | 29 | 249 | 187 |

  Care cuts time spent struggling by about a third on Normal. One coach can't reach 85 players, which is the
  point: the council, mentors and the position coach extend reach.
- **Save facts found along the way:** none of Wyoming's 85 players currently carry the Disciplined/Undisciplined
  persona traits (about 430 players league-wide do), so those rules wait until one joins. Hot/Cold today:
  1 Hot, 2 Cold.

## Build order (when un-tabled)

1. **In-game test:** one edited Hot/Cold, ability, injury and heal, loaded in CFB27 to see what the game honours.
2. **Needs, trust, care list and coach hours**, with the tuning file, presets, simulator and care log (app-only).
3. **Phone** (player messages and replies) and **Inbox** (staff emails and actions).
4. **Warning-sign storylines and incidents** (app-only effects: storylines, press, podcast).
5. **Save writer:** pending changes, backup, write, verify, undo; then switch on save effects once tuned.
