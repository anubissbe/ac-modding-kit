# Balance fields and engine boundaries

This is a dated, read-only audit of the exposed Ancient Cities balance data. It
does not describe a complete `.art` schema and it does not prove the closed
runtime formulas. Re-discover and re-audit after every game update.

## Contents

- [Audited baseline and evidence rules](#audited-baseline-and-evidence-rules)
- [Feasibility map](#feasibility-map)
- [Food, calories, and spoilage](#food-calories-and-spoilage)
- [Plants, gathering, and ecology](#plants-gathering-and-ecology)
- [Crops and replanting](#crops-and-replanting)
- [Recipes and production](#recipes-and-production)
- [Buildings, decay, and maintenance](#buildings-decay-and-maintenance)
- [Workgroups, AI, events, and UI](#workgroups-ai-events-and-ui)
- [Historical time](#historical-time)
- [Community-patch design](#community-patch-design)
- [Required runtime evidence](#required-runtime-evidence)

## Audited baseline and evidence rules

The audit was completed on 2026-07-23/24 against:

- Ancient Cities `1.9.3`;
- Steam build `23915225`;
- internal `GameVersion 22`; and
- base-content hash `D9BF481D195671BF9CB98274B4CFF604`.

Use the installed game data, an in-game skeleton, localization descriptions,
and `Log.txt` as the primary specification. Treat field names as evidence that
a value exists, not proof of the executable's complete formula.

Do not decompile or disassemble the executable. The installed Modding
Agreement prohibits reverse engineering outside its express permissions, and
the audited installation exposes no supported DLL, C#, BepInEx, Harmony, or
general binary plugin API.

Use these claim levels:

- **High**: a current scalar and its meaning are both evidenced by data or
  localization, but the resulting balance still needs a runtime test.
- **Partial**: a related scalar is exposed, while an important part of the
  behavior remains engine-controlled.
- **Closed**: no current configurable field or supported code hook was found.
- **Experimental**: a data construction is syntactically plausible but lacks
  isolated runtime evidence.

## Feasibility map

| Requested change | Assessment | Honest scope |
| --- | --- | --- |
| Human food demand | High | Change daily calories, not meal-selection AI |
| Food calories and open-air durability | High | Per-resource scalar balance |
| Storage preservation | Partial | Storage values exist; exact multiplier formula is closed |
| Plant output and seasonal supply | High | Output count, season, duration, and distribution |
| Ecological replenishment | Partial | Density, seeding, and age are exposed but affect map generation/performance |
| Harvest output | High | Change crop/resource output counts |
| Seed cost per planted cell | Closed | No current `SeedCount`-style field |
| Automatic harvest/replant ordering | Closed | Farm scheduling is engine logic |
| Recipe inputs and work | High | Per-product input vectors and `CraftWork` |
| Processor concurrency | High | `ProcessTaskCount`; test queues and save persistence |
| Global production formula | Closed | No general multiplier was found |
| Per-building decay and repair thresholds | High/partial | Per-definition values exist; some exact formula semantics remain unlocalized |
| Global building-maintenance multiplier | Closed | No such current `.art` scalar was found |
| AI task choice or assignment overhaul | Closed | No decision tree, score weights, or assignment rules |
| Jobs accepted inside a workgroup | High | Current `JobLimit` values are exposed |
| Number of creatable workgroups | Closed | No current group-count scalar was found |
| Existing notification/UI presentation | High | Labels, icons, layout, lifetime, and existing bindings |
| New logic-driven events or UI actions | Closed | Templates do not create triggers or simulation actions |

## Food, calories, and spoilage

`Entity/Local/Human/Human.art` exposes `Nutrition:"2200"`.
`Entity/Component/Nutrition/Index.en.loc` identifies this as calories per day.
Changing it directly changes human demand but does not change meal selection,
rationing decisions, access/pathfinding, or starvation recovery logic.

Food resources expose:

- `FoodCalorie`: calories per unit;
- `Decay`: months of durability when stored in the open;
- `Food`: palatability/unrest, not calories; and
- sometimes `FoodType`, trade, craft, or by-product data.

Representative current values:

| Food | `FoodCalorie` | `Decay` | `Food` |
| --- | ---: | ---: | ---: |
| Berry | 600 | 0.3 | 1.3 |
| Fish | 1250 | 0.2 | 1.2 |
| Raw meat | 1750 | 0.3 | 1.5 |
| Dry meat | 2750 | 1 | 1.1 |
| Pulse | 2000 | 1 | 0.5 |
| Wheat grain | 3000 | 1.5 | 0.2 |
| Bread | 3500 | 0.5 | 1.8 |

Storage buildings expose `Storage` and `StorageWeight`. Current localization
describes storage preservation as an improvement over open durability, but the
numeric composition is not exposed. Examples include Basket `Storage:2`, Pit
`3`, StoreHouse `3`, and PitPottery `4`. Test before translating those values
into a percentage claim.

Humidity and temperature effects are described in traits/tooltips, but no
current numeric climate-decay factor was found. Do not advertise a climate
spoilage rebalance without new evidence.

Prefer tuning specific outputs, durability, and bottlenecks before reducing the
historically plausible `2200` daily-calorie baseline globally.

## Plants, gathering, and ecology

Regenerative vegetation commonly exposes:

- `StorageResource` and `StorageCount` for produced resources;
- `ProductionStart` and `ProductionDuration` for seasonality;
- `Density`, `DensityByTribeSize`, and `DensityByYear`;
- `SeedProbability` and `SeedRadius`; and
- `Age`, `AgeStage`, climate, height, and historical ranges.

Examples on the audited build:

- Blackberry: 8 berries, starts in August, duration 2.
- DogRose: 20 rosehips, starts in May, duration 3.
- TreePear: 50 pears, starts in September, duration 1.

Destructively harvested or chopped entities instead use
`ConstitutionResource`, `ConstitutionCount`, and `Constitution`. For example,
TreeOak yields 8 logs and 10 sticks with `Constitution:2`; Arrowgrass yields 2
vegetal fibre with `Constitution:3`.

Localization identifies Constitution as physical integrity. It is therefore a
plausible work-to-destroy/harvest lever, but its conversion into worker time is
closed. Benchmark it rather than claiming a number of seconds.

Increasing density, seed probability, or age-related reproduction can change
map ecology, generation time, and performance. Such changes may only become
fully visible in a newly generated location.

Tool activity values are also exposed. Representative examples include a
primitive sickle with `Crop:1.5`, a biface knife with `Crop:1`, a bone knife
with `Crop:0.5`, a bone hoe with `Plow:0.75`, and a wooden spear with
`Plant:0.5` and `Plow:0.25`. Tool-selection AI remains closed.

## Crops and replanting

Current crop definitions separate the growing plant, ripe/crop object, seed
resource, harvested resource, output count, and physical integrity.

Representative data:

- Wheat uses WheatGrain as `SeedResource`; the ripe object yields WheatCrop
  with `ConstitutionCount:1.25` and `Constitution:0.4`.
- Flax uses FlaxGrain; the ripe object yields FlaxCrop `1.25` with
  `Constitution:0.4`.
- Beet uses Beetroot and yields Beetroot `1.5`.
- Kale uses Kale and yields Kale `2`.
- Domestic pea uses Pulse and regenerative `StorageCount:0.75`;
  `GatherOnProduction:false`.

No `SeedCount`, sowing-cost scalar, or equivalent per-cell seed quantity was
found in the current `.art` corpus. Seed consumption and automatic
harvest/replant ordering are engine logic.

An honest workaround for "the whole harvest is needed for replanting" is to
increase ripe `ConstitutionCount`, regenerative `StorageCount`, or a later
processing yield. Changing `SeedResource` is exposed but is a semantic hack,
not a supported seed-cost control.

`Entity/Local/Area/Farm/Index.art` exposes availability, slope, UI, and
knowledge/culture requirements. It does not expose harvest/replant behavior.
The Farm workgroup exposes `JobLimit:64`.

## Recipes and production

Product resource definitions commonly expose:

- `ConstitutionResource`: input-resource vector;
- `ConstitutionCount`: input amount vector; and
- `CraftWork`: required work.

Representative current recipes:

| Product | Inputs | `CraftWork` |
| --- | --- | ---: |
| Bread | 0.1 Flour | 4 |
| Flour | 2 WheatGrain | 2 |
| DryFish | 1 Fish | 16 |
| DryMeat | 1 RawMeat | 24 |
| Cheese | 1 Milk | 2 |
| Plank | 0.5 Log | 2 |

Processor buildings expose `ProcessTaskCount` and
`ProcessTaskWorkPercent`. Current concurrency examples are Dryer 1, Oven 2,
Dairy 2, MillSmall 1, LumberWork 1, and Threshing 1.
`ProcessTaskCount` is a defensible concurrency lever. The exact semantics of
`ProcessTaskWorkPercent` are not localized, so prefer `CraftWork` for an
initial production-time patch.

Fireplaces, houses, and tools may expose activity-efficiency values such as
`Craft`, but their composition with `CraftWork` remains engine-controlled.
Queued or partially completed jobs make existing-save tests higher risk.

## Buildings, decay, and maintenance

The audited base contains 61 construction definitions:

- 39 `Entity/Construction/Building`;
- 20 `Entity/Construction/Structure`; and
- 2 `Entity/Construction/Gate`.

Every definition has `ConstitutionResource`, `ConstitutionCount`,
`ConstitutionReady`, and `Constitution`. Forty-seven also expose
`ConstitutionRepair`; the remaining definitions are mostly non-maintained
monuments.

The current Structure Decay discussion identifies `Constitution` as the decay
control and `ConstitutionReady` as a repair threshold. `ConstitutionRepair` is
consistently above Ready on repairable examples and is plausibly a repair
target, but its exact engine semantics are not documented. Do not tune it
without an isolated decay-to-repair test.

No global durability or maintenance multiplier was found. A broad patch must
address individual definitions or prove that an additive link can update
their existing scalar properties at the correct load phase.

Representative current housing values:

| Building | `Constitution` | `ConstitutionReady` | `ConstitutionRepair` |
| --- | ---: | ---: | ---: |
| TentBig | 0.35 | 0.61 | 0.75 |
| MesoTent | 1 | 0.9 | 0.925 |
| RoundHouseStone | 6 | 0.85 | 0.925 |
| PitHutSmall/Pelt | 1 | 0.9375 | 0.955 |
| PitHutSmall/Straw | 3 | 0.7 | 0.8 |
| PitHutSmall/Stone | 0.16 | 0.609 | 0.686 |

The main stone roundhouse and hide tents therefore do not literally share the
same data values. `PitHutSmall/Stone` is a strong anomaly: its localized
description calls it small and solid, it costs 150 stone plus the pit/work
entry, yet its Constitution is below both the pelt and straw variants. Treat
this as a candidate balance defect, not a proven typo, until a current runtime
benchmark establishes the direction and magnitude of the field.

For a first probe, change only this one Constitution value and leave material
vectors and repair thresholds untouched. A candidate value such as `4` is
useful for an A/B experiment, not release data.

Construction and decay visuals use separate staged nodes/materials. A scalar
condition change should retain those mappings, but testing must cover visual
decay, repair, manual save, full exit, restart, and reload.

## Workgroups, AI, events, and UI

Current workgroup `JobLimit` values are:

| Workgroup | `JobLimit` |
| --- | ---: |
| Build, Chop, Craft, Fish, Herd, Hunt | 40 |
| Farm | 64 |
| Gather | 80 |

`JobLimit` controls jobs/workplaces accepted inside that workgroup type. It is
not evidence for the number of workgroups the player may create. The old
community suggestion to edit `CountLimit:"16"` is stale for 1.9.3, and no
current group-count scalar was found.

Do not increase `JobLimit` as a generic AI fix. A larger queue can worsen
overtasking and does not change how jobs are scored or assigned.

`Entity/Behavior/*/Index.art` mostly declares behavior types and enabled
state. `Entity/Task/*/Index.art` mostly declares task types, UI grouping,
icons, and order registration. The current data contains no configurable
decision tree, assignment rule, skill-based autoassignment filter, or general
task-score weights.

Existing policy definitions such as LaborAge, LaborCommon, LaborTime, and
Rationing expose defaults and attributes. They can change the default state of
existing controls, not create new AI.

Notifications expose presentation such as UI group, lifetime, repeat/reuse,
icon, and localization. Their triggers remain engine-driven. UI files expose
layout, labels, visibility, and bindings to existing properties. A new button
cannot perform a new simulation action without engine support.

Consequently, do not promise:

- conditional AI rules such as assigning fishers when food falls below a
  threshold;
- manual or automatic per-person assignment by skill/age/trait;
- custom task-priority algorithms;
- guaranteed trade demand for a mod resource;
- arbitrary calendar/condition-driven incidents; or
- an unlimited/configurable number of workgroups.

## Historical time

The current data exposes `Human.art` `AgeMultiplier` and
`State/Game.art` `YearHistoryFactor`. The new-game configuration also exposes
the supported Slow, Normal, and Fast historical-speed choices.

These fields do not expose the complete relationship between real time,
simulation ticks, seasons, aging, history, learning, production, and UI.
Prefer the built-in historical-speed setting. Treat `YearHistoryFactor` or
generic time-scale changes as a separate experimental mod with new-save,
aging, season, knowledge, performance, and save/reload tests. Do not include
them casually in a food or production patch.

## Community-patch design

Prefer modular packages so users can select and diagnose one concern:

1. **Community Fixes** - narrowly evidenced outliers such as the Stone Pit Hut
   candidate, each with its own runtime benchmark.
2. **Food and Spoilage** - calories and open-air durability.
3. **Gathering and Crops** - seasonal output and harvest yield, not claimed
   seed-cost logic.
4. **Production** - recipe inputs, `CraftWork`, and carefully tested
   concurrency.
5. **Maintenance** - per-building decay only after the one-building probe.

Exclude AI, event logic, group-count changes, climate formulas, and broad
historical-time changes from release claims.

First try a clean-room additive effect that links original constants to
existing scalar targets. The local camera and population mods prove this
pattern for some current properties, not for balance fields generally. If the
target is read too early or is not writable, an exact-path override may be
required.

An exact-path override is a whole-file winner, conflicts with every other mod
at that path, becomes stale after updates, and may require copied proprietary
text. Do not distribute copied base definitions without resolving the
Modding Agreement's original-asset/source restriction with Uncasual Games.

## Required runtime evidence

For every scalar or module:

1. Record the discovered build tuple, enabled order, candidate hash, and exact
   changed targets.
2. Use one module and one hypothesis per disposable/new save.
3. Record a pre-change control and a post-change run under the same season,
   game speed, population, policies, tools, distances, and worker count.
4. Measure the relevant outcome:
   - calories consumed and food units per person-day;
   - open versus stored spoilage duration;
   - resources per plant and per worker-hour;
   - seed spent, harvested output, and post-replant surplus;
   - recipe batches and worker-hours;
   - building condition over time, repair trigger, materials, and labor; or
   - accepted/completed jobs per workgroup.
5. Check visuals and inventory, not only logs or UI availability.
6. Make an explicit manual save, fully exit, restart cleanly, reload, and
   repeat the essential behavior.
7. Review `Log.txt`, restore the prior enabled configuration exactly, and
   retain sanitized evidence.

Any `.art` mod may disable achievements. Existing saves are unsafe by default:
scalar changes can immediately alter normalized condition, queued work,
spoilage, crop state, and repair tasks.
