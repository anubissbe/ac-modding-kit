# Legal, provenance, and publishing guardrails

Read the installed `Modding Agreement.txt` itself; this file is only a navigation summary and not legal advice.

The agreement audited on 2026-07-19 states, among other things:

- Create/distribute mods only through the permitted modding API and do not reverse engineer except where non-excludable law allows.
- Use mods non-commercially unless the developer gives prior written consent.
- Include accurate, current contact details for mod owners/authors with distributed files and listings.
- Do not distribute original game assets, images, or source code with the mod.
- Do not bypass DRM, add malware/third-party installers, infringe IP/trademark/publicity rights, or collect personal data without consent.
- Follow the donation/advertising restrictions and accept that the developer receives broad rights to use/modify/distribute the mod.

Stop and ask the user when rights, contact details, commercial intent, privacy collection, or full proprietary-file redistribution is unclear. Do not invent personal/contact details.

## Provenance checklist

For every nontrivial file, record:

- original author/owner;
- source URL or creation method;
- license/permission;
- modifications;
- whether AI generation was used;
- whether the file is safe to redistribute.

Reject Workshop/base-game copying as a shortcut. Use installed mods as structural evidence only.

## Publish/Update authorization

A rights review, release approval, successful test, or earlier upload attempt is not consent for
the next external action. Immediately before the final in-game Publish/Update control, present
and explicitly confirm one single-use packet containing:

- the action (`Publish` or `Update`) and a current timestamp with the agreed immediate validity
  window;
- the exact candidate and every transmitted item with its SHA-256;
- Steam app `667610` plus **new item**/manifest `SteamModId 0,0`, or the exact existing
  PublishedFileId/`SteamModId` for Update; and
- the exact visibility shown by the UI, or an explicit statement that the current client exposes
  no visibility selector, plus the intended result to verify afterward.

Expire the confirmation when its window ends or any byte, hash, item list, action, target ID,
selected UI item, active account, or visibility state changes. A retry requires a new packet and
confirmation. One packet authorizes one action on one mod only; never treat consent for a list or
batch as consent for its individual publications. Do not infer consent from silence or reuse
approval given for inspection, staging, deployment, testing, another candidate, or another
Workshop item.

Before creating or updating an item, confirm in Steam's own UI that the active account is the
intended publisher. For Update, also confirm that the PublishedFileId exists and belongs to that
account. Store only a sanitized pass/fail statement in public documentation, not account names,
Steam IDs, login state, credentials, tokens, or Steam Guard data.

A wrong-owned or deleted Workshop identity remains historical evidence. Preserve its project and
nonzero id unchanged. A replacement must be a separate successor project and loose folder that
starts at `SteamModId 0,0`, passes fresh rights/runtime/release checks, and receives its own
single-use publication confirmation. Never transfer an id between projects or claim ownership
merely because the local manifest contains it.

## Current web anchors

- Ancient Cities site, EULA/Modding sections: https://www.ancient-cities.com/
- Official FAQ (describes support as basic): https://www.ancient-cities.com/faq.php
- Steam Workshop app overview: https://steamcommunity.com/workshop/about/?appid=667610
- Secondary SteamDB mirror of build 23915225 / v1.9.3 notes:
  https://steamdb.info/patchnotes/23915225/
- Secondary SteamDB mirror of the ZIP/compatibility system patch:
  https://steamdb.info/patchnotes/10211774/
- Secondary SteamDB mirror of empty-mod creator and publishing fixes:
  https://steamdb.info/patchnotes/14882315/

Some older developer-forum links may be unavailable. When online instructions conflict
with the current in-game creator, local skeleton, or loader log, treat the current
installed build as authoritative and label the web instruction stale.
