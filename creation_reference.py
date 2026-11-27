"""Structured, beginner-friendly character creation reference data backed by the Corebook index."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import corebook_gm_data as cgd
from creation import BASIC, ROLES, STATS, _norm_skill, _role_skills, _template
from creation_catalog import (
    build_campaign_presets,
    build_corebook_ammo_attachments_exotics,
    build_corebook_armor,
    build_corebook_cyberware_additions,
    build_corebook_drugs,
    build_corebook_gear,
    build_corebook_hardware,
    build_corebook_net_catalog,
    build_corebook_services_housing_fashion,
    build_corebook_vehicles,
    build_corebook_weapons,
    parse_hl_int,
)
from library import list_category
from sourcecatalog import skills as source_skills_catalog

STAT_INFO: dict[str, dict[str, Any]] = {
    "INT": {
        "name": "Intelligence",
        "short": "Smarts, awareness, street perception, deduction, and education.",
        "mechanics": "Drives Perception, Education, Cryptography, Library Search, Conceal/Reveal Object, Deduction, Tactics, and Languages.",
        "tip": "Don't dump INT too low if you want to spot ambushes, traps, or lies cleanly.",
    },
    "REF": {
        "name": "Reflexes",
        "short": "Reaction speed, initiative, aiming guns, and driving vehicles.",
        "mechanics": "Adds to Initiative + 1d10 and all Ranged Weapon skills (Handgun, Shoulder Arms, Autofire, Heavy Weapons). At REF 8+, you can attempt to dodge bullets with Evasion!",
        "tip": "The single most important combat STAT if you plan to shoot or dodge gunfire (REF 8 threshold).",
    },
    "DEX": {
        "name": "Dexterity",
        "short": "Agility, dodging, stealth, athletics, and melee fighting.",
        "mechanics": "Drives Evasion, Stealth, Athletics, Brawling, Melee Weapon, Martial Arts, and Contortionist.",
        "tip": "Essential for dodging attacks in close combat (or bullets when REF >= 8) and staying unseen.",
    },
    "TECH": {
        "name": "Technique",
        "short": "Working with tools, cyberware, locks, electronics, and medical stabilization.",
        "mechanics": "Drives First Aid, Paramedic, Basic Tech, Cybertech, Electronics/Security Tech, Weaponstech, Pick Lock, Pick Pocket, and Tech Maker checks.",
        "tip": "Crucial for Techs, Medtechs, Netrunners cracking hardware, and anyone doing field repairs or First Aid.",
    },
    "COOL": {
        "name": "Cool",
        "short": "Presence, composure under pressure, bluffing, and street credibility.",
        "mechanics": "Drives Persuasion, Streetwise, Bribery, Interrogation, Acting, Personal Grooming, and Wardrobe & Style.",
        "tip": "High COOL helps you talk your way past bouncers, negotiate pay, and intimidate rivals.",
    },
    "WILL": {
        "name": "Willpower",
        "short": "Mental grit, stamina, concentration, and total Hit Points.",
        "mechanics": "Combines with BODY to calculate starting HP (10 + 5 × ceil((BODY + WILL)/2)). Drives Concentration and Resist Torture/Drugs.",
        "tip": "Every point of WILL + BODY boosts your Hit Points and seriously wounded threshold.",
    },
    "LUCK": {
        "name": "Luck",
        "short": "A spendable pool of clutch points to turn near-misses into hits.",
        "mechanics": "You start each session with LUCK points equal to this STAT. Declare LUCK before rolling a d10 to add +1 per point spent.",
        "tip": "Great safety net for critical shots, death saves, or clutch social rolls when you cannot afford to fail.",
    },
    "MOVE": {
        "name": "Movement",
        "short": "How fast you sprint across a firefight or rooftop.",
        "mechanics": "Move Action distance is MOVE × 2 meters (or yards) per turn. Run Action doubles it.",
        "tip": "MOVE 5–7 keeps pace in street fights; low MOVE leaves you exposed between cover.",
    },
    "BODY": {
        "name": "Body",
        "short": "Physical toughness, Hit Points, Death Saves, and brawling power.",
        "mechanics": "Determines HP (with WILL) and your Death Save target (roll under BODY when Mortally Wounded). Also affects grapple/choke/throw damage.",
        "tip": "Higher BODY keeps you alive longer and makes Death Saves easier to survive.",
    },
    "EMP": {
        "name": "Empathy",
        "short": "Reading people and how much cyberware your mind can handle.",
        "mechanics": "Starting max Humanity = EMP × 10. Every 10 Humanity lost drops current EMP by 1 (and cyberware Humanity Loss lowers Humanity). Drives Conversation & Human Perception.",
        "tip": "Don't tank EMP if you plan on installing heavy cyberware like Sandevistan or Cybereyes.",
    },
}

CREATION_METHODS: list[dict[str, Any]] = [
    {
        "id": "streetrat",
        "name": "Streetrat (Templates)",
        "badge": "Best for Beginners",
        "summary": "Fastest official Cyberpunk RED build: pick a Role, roll 1d10 (or pick a row) for STATs, get pre-tuned skills and a ready-to-run starting kit + 500 eb.",
        "rules": "Corebook pp. 74–98: 1d10 selects one balanced STAT template row for your Role, 20 pre-set Role Skills (weighted 86 pts), +4 free Cultural Language, starting Role weapons/armor/cyberware, and 500 eb.",
    },
    {
        "id": "edgerunner",
        "name": "Edgerunner (Fast & Dirty)",
        "badge": "Balanced Control",
        "summary": "Keep your Role's starter gear & cyberware kit, roll/pick each STAT column individually from your Role's templates, and customize your 86 skill points across your Role's 20 skills.",
        "rules": "Corebook pp. 77, 89–98: Roll 1d10 per STAT column, allocate 86 weighted points across your Role's 20 skills (each rank 2–6; x2 skills cost double), +4 Cultural Language, starting Role gear + 500 eb.",
    },
    {
        "id": "complete_package",
        "name": "Complete Package (Calculated)",
        "badge": "Full Point-Buy",
        "summary": "Build from scratch with 62 STAT points (2–8 each), 86 Skill points across all 66 Corebook skills, 2,550 eb to buy your own weapons/armor/cyberware, plus 800 eb for fashion.",
        "rules": "Corebook pp. 78–104: 62 STAT pts (2..8), 86 weighted Skill pts (all 13 Basic Skills min 2, max 6; Surgery/Medical Tech are Medtech-only), 2,550 eb gear/cyberware + 800 eb fashion.",
    },
    {
        "id": "freeform",
        "name": "Freeform / Custom Sheet",
        "badge": "Unrestricted",
        "summary": "Skip strict point-buy limits and set any STATs, Skills, Role, Backstory, Starting Gear, Cyberware, and Eurobucks you want for house-ruled or custom campaigns.",
        "rules": "Ideal for custom power levels, importing an existing sheet, or tables without strict Corebook caps.",
    },
]

_SKILL_GROUPS = {
    "Awareness": {"Concentration", "Conceal/Reveal Object", "Lip Reading", "Perception", "Tracking"},
    "Body": {"Athletics", "Contortionist", "Dance", "Endurance", "Resist Torture/Drugs", "Stealth"},
    "Control": {"Drive Land Vehicle", "Pilot Air Vehicle", "Pilot Sea Vehicle", "Riding"},
    "Education": {"Accounting", "Animal Handling", "Bureaucracy", "Business", "Composition", "Criminology", "Cryptography", "Deduction", "Education", "Gamble", "Language", "Library Search", "Local Expert", "Science", "Tactics", "Wilderness Survival"},
    "Fighting": {"Brawling", "Evasion", "Martial Arts", "Melee Weapon"},
    "Performance": {"Acting", "Play Instrument"},
    "Ranged": {"Archery", "Autofire", "Handgun", "Heavy Weapons", "Shoulder Arms"},
    "Social": {"Bribery", "Conversation", "Human Perception", "Interrogation", "Persuasion", "Personal Grooming", "Streetwise", "Trading", "Wardrobe & Style"},
    "Technique": {"Air Vehicle Tech", "Basic Tech", "Cybertech", "Demolitions", "Electronics/Security Tech", "First Aid", "Forgery", "Land Vehicle Tech", "Paint/Draw/Sculpt", "Paramedic", "Photography/Film", "Pick Lock", "Pick Pocket", "Sea Vehicle Tech", "Weaponstech"},
}

ROLE_INFO: dict[str, dict[str, Any]] = {
    "Rockerboy": {
        "ability": "Charismatic Impact",
        "ability_summary": "Sway crowds, fans, and contacts—ask favors from a small group (DV 10) or huge venue (DV 12) using Charismatic Impact + 1d10.",
        "tagline": "Charismatic rebel, performer, and voice of The Street.",
        "best_for": "Players who love social influence, stirring riots, concerts, and calling in fan favors.",
        "key_stats": ["COOL", "EMP", "DEX"],
        "page": 144,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Signature Sidearm (Very Heavy Pistol)",
                "options": [
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                    "Militech \"Boomer Buster\" (Very Heavy Pistol)",
                ],
            },
            {"type": "fixed", "item": "Basic VH Pistol Ammunition", "qty": 50},
            {
                "type": "choice",
                "label": "Melee / Grenade Option",
                "options": [
                    "Street Katana (Heavy Melee)",
                    "Lead Pipe / Crowbar (Heavy Melee)",
                    "Flashbang Grenade",
                ],
            },
            {"type": "fixed", "item": "Teargas Grenade", "qty": 2},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Computer", "Glow Paint x5", "Pocket Amp", "Radio Scanner/Music Player", "Video Camera", "Generic Chic & Leisurewear Wardrobe"],
        "outfit_choice": {"label": "Stage Gear Choice", "options": ["Electric Guitar", "Bug Detector"]},
        "starting_cyberware": [
            {"name": "Audio Recorder", "hl": 2, "install": "Clinic", "notes": "Records audio cleanly."},
            {"name": "Chemskin", "hl": 0, "install": "Mall", "notes": "Color/pattern-shifting skin (+2 Personal Grooming with Techhair)."},
            {"name": "Cyberaudio Suite", "hl": 7, "install": "Clinic", "notes": "Houses Cyberaudio options."},
            {"name": "Techhair", "hl": 0, "install": "Mall", "notes": "Color-shifting artificial hair."},
        ],
        "starting_hl": 9,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Rockerboy are You?",
                "options": [
                    "Musician",
                    "Slam Poet",
                    "Street Artist",
                    "Performance Artist",
                    "Comedian",
                    "Orator",
                    "Politico",
                    "Rap Artist",
                    "DJ",
                    "Idoru",
                ],
            },
            {
                "key": "act",
                "label": "Are You in a Group or a Solo Act?",
                "options": [
                    "Solo Act",
                    "Part of a Group",
                ],
            },
            {
                "key": "leave_reason",
                "label": "Group History / Departure",
                "options": [
                    "Always performed solo",
                    "Voted out after clashing with bandmates",
                    "Personal entanglement split the lineup",
                    "Bandmates perished in a suspicious disaster",
                    "Outside rivals dismantled the group",
                    "Split over artistic direction",
                    "Left voluntarily for a solo career",
                ],
            },
            {
                "key": "venue",
                "label": "Typical Performance Venue",
                "options": [
                    "Underground cafes",
                    "Members-only clubs",
                    "Rough neighborhood dives",
                    "Pop-up street shows",
                    "Major city nightclubs",
                    "Data Pool livestreams",
                ],
            },
            {
                "key": "enemy",
                "label": "Primary Rival or Enemy",
                "options": [
                    "Bitter former bandmate",
                    "Competing act fighting for audience share",
                    "Corporate execs angered by your lyrics",
                    "Hostile critic or Data Pool influencer",
                    "Established star threatened by your rise",
                    "Vengeful ex-partner or media figure",
                ],
            },
        ],
    },
    "Solo": {
        "ability": "Combat Awareness",
        "ability_summary": "Allocate 4 tactical points anytime in combat into Threat Detection (+Perception), Initiative Reaction (+Init), Precision Attack (+Hit), Spot Weakness (+Dmg), Damage Deflection (armor), or Fumble Recovery.",
        "tagline": "Bodyguard, assassin, mercenary—the apex gunfighter.",
        "best_for": "Players who want reliable firepower, high combat survival, and tactical edge.",
        "key_stats": ["REF", "DEX", "BODY"],
        "page": 146,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Primary Assault Rifle",
                "options": [
                    "Militech \"Ronin\" Light Assault (Assault Rifle)",
                    "Chadran Arms \"Jungle Reaper\" (Assault Rifle)",
                    "Militech \"Dragon\" Assault (Assault Rifle)",
                ],
            },
            {
                "type": "choice",
                "label": "Backup Sidearm (Very Heavy Pistol)",
                "options": [
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                ],
            },
            {
                "type": "choice",
                "label": "Close / Tactical Option",
                "options": [
                    "Kendachi Mono-Blade / Machete (Heavy Melee)",
                    "Street Katana (Heavy Melee)",
                    "Bulletproof Shield (10 HP)",
                ],
            },
            {"type": "fixed", "item": "Basic VH Pistol Ammunition", "qty": 30},
            {"type": "fixed", "item": "Basic Rifle Ammunition", "qty": 70},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Leisurewear Tactical Wardrobe"],
        "starting_cyberware": [
            {"name": "Neural Link", "hl": 7, "install": "Clinic", "notes": "Wired nervous system interface."},
            {"name": "Biomonitor", "hl": 0, "install": "Mall", "notes": "Subdermal vital-signs LED/Agent readout."},
        ],
        "cyberware_choice": {
            "label": "Signature Solo Cyberware",
            "options": [
                {"name": "Sandevistan", "hl": 7, "install": "Clinic", "notes": "+3 Initiative for 1 minute when triggered (7 HL)."},
                {"name": "Wolvers", "hl": 7, "install": "Clinic", "notes": "Extendable Heavy Melee Blades hidden in knuckles (3d6 dmg, ROF 2, 7 HL)."},
            ],
        },
        "starting_hl": 14,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Solo are You?",
                "options": [
                    "Bodyguard",
                    "Street Muscle for Hire",
                    "Corporate Enforcer who takes jobs on the side",
                    "Corporate or Freelance Black Ops Agent",
                    "Local Vigilante for Hire",
                    "Assassin/Hitman for Hire",
                ],
            },
            {
                "key": "compass",
                "label": "Moral Code",
                "options": [
                    "Principled—only targets genuinely dangerous predators",
                    "Strict non-combatant rule—never harms bystanders",
                    "Mostly ethical with rare desperate compromises",
                    "Purely transactional—takes any paying contract",
                    "Results-first—ignores laws to finish the job",
                    "Ruthless—embraces dirty and illegal contracts",
                ],
            },
            {
                "key": "territory",
                "label": "What's Your Operational Territory?",
                "options": [
                    "A Corporate Zone",
                    "Combat Zones",
                    "The whole City",
                    "The territory of a single Corporation",
                    "The territory of a particular Fixer or contact",
                    "Wherever the money takes you",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning for You?",
                "options": [
                    "A Corporation you may have angered.",
                    "A boostergang you may have tackled earlier.",
                    "Corrupt Lawmen or Lawmen who mistakenly think you're guilty of something.",
                    "A rival Solo from another Corp.",
                    "A Fixer who sees you as a threat.",
                    "A rival Solo who sees you as their nemesis.",
                ],
            },
        ],
    },
    "Netrunner": {
        "ability": "Interface",
        "ability_summary": "Jack into NET Architectures in Virtuality to breach passwords, control drones/turrets, slide past Black ICE, and run Programs with multiple NET Actions per turn.",
        "tagline": "Brain-burning cyber-hacker walking digital architectures.",
        "best_for": "Players who want to hijack cameras, turrets, data vaults, and duel Black ICE.",
        "key_stats": ["INT", "REF", "TECH"],
        "page": 147,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Sidearm (Very Heavy Pistol)",
                "options": [
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                ],
            },
            {"type": "fixed", "item": "Basic VH Pistol Ammunition", "qty": 30},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Cyberdeck (7 Slots)", "Virtuality Goggles", "Program: Armor", "Program: Sword", "Generic Chic & Urban Flash Wardrobe"],
        "outfit_choice": {
            "label": "Extra Programs (Choose 3 per Corebook p. 103)",
            "options": [
                "Program: See Ya + Sword + Worm",
                "Program: Eraser + Vrizzbolt + Sword",
                "Program: See Ya + Vrizzbolt + Worm",
                "Program: Eraser + Sword + Worm",
            ],
        },
        "starting_cyberware": [
            {"name": "Neural Link", "hl": 7, "install": "Clinic", "notes": "Required foundation for Interface Plugs."},
            {"name": "Interface Plugs", "hl": 7, "install": "Clinic", "notes": "Direct wrist/temple jacks for your Cyberdeck."},
            {"name": "Shift Tacts", "hl": 0, "install": "Mall", "notes": "Color-changing cosmetic eye lenses."},
        ],
        "starting_hl": 14,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Runner are You?",
                "options": [
                    "Freelancer who will hack for hire.",
                    "Corporate \"clone runner\" who hacks for the Man.",
                    "Hacktivist interested in cracking systems and exposing bad guys.",
                    "Just like to crack systems for the fun of it.",
                    "Part of a regular team of freelancers.",
                    "Hack for a Media, politico, or Lawman who hires you as needed.",
                ],
            },
            {
                "key": "partner",
                "label": "Got a Partner, or Do You Work Alone?",
                "options": [
                    "Work alone",
                    "Family member",
                    "Old friend",
                    "Possible romantic partner as well",
                    "Secret partner who might be a rogue AI. Might.",
                    "Secret partner with mob/gang connections",
                    "Secret partner with Corporate connections",
                ],
            },
            {
                "key": "workspace",
                "label": "Typical Setup & Workspace",
                "options": [
                    "Walls lined with monitors and holo-displays.",
                    "Looks much cleaner inside Virtuality than in meatspace.",
                    "Tangled cables spilling across a cramped bunk.",
                    "Stark, modular corporate workstation.",
                    "Minimalist, tidy, and strictly organized.",
                    "Hardware and cooling rigs have swallowed your whole apartment.",
                ],
            },
            {
                "key": "clients",
                "label": "Who are Some of Your Other Clients?",
                "options": [
                    "Local Fixers who send you clients.",
                    "Local gangers who also protect your work area while you sweep for NET threats.",
                    "Corporate Execs who use you for \"black project\" work.",
                    "Local Solos or other combat types who use you to keep their personal systems secure.",
                    "Local Nomads and Fixers who use you to keep their family systems secure.",
                    "You work for yourself and sell whatever data you can find on the NET.",
                ],
            },
            {
                "key": "programs",
                "label": "Where Do You Get Your Programs?",
                "options": [
                    "Dig around in old abandoned City Zones.",
                    "Steal them from other Netrunners you brain-burn.",
                    "Have a local Fixer supply programs in exchange for hack work.",
                    "Corporate Execs supply you with programs in exchange for your services.",
                    "You have backdoors into a few Corporate warehouses.",
                    "You hit the Night Markets and score programs whenever you can.",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning for You?",
                "options": [
                    "You think it might be a rogue AI or a NET Ghost. Either way, it's bad news.",
                    "Rival Netrunners who just don't like you.",
                    "Corporates who want you to work for them exclusively.",
                    "Lawmen who consider you an illegal \"black hat\" and want to bust you.",
                    "Old clients who think you screwed them over.",
                    "Fixer or another client who wants your services exclusively.",
                ],
            },
        ],
    },
    "Tech": {
        "ability": "Maker",
        "ability_summary": "At Rank 4, gain 8 specialty points across Field Expertise (jury-rig/repair), Upgrade Expertise (improve gear/slots), Fabrication (build items), and Invention (design new tech).",
        "tagline": "Gearhead, inventor, and miracle-worker with a wrench.",
        "best_for": "Players who love crafting custom gear, upgrading weapons/armor, and repairing everything.",
        "key_stats": ["TECH", "INT", "DEX"],
        "page": 147,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Primary Longarm",
                "options": [
                    "Arasaka \"Rapid Assault\" (Shotgun)",
                    "Militech \"Bulldog\" (Shotgun)",
                    "Militech \"Ronin\" Light Assault (Assault Rifle)",
                    "Chadran Arms \"Jungle Reaper\" (Assault Rifle)",
                ],
            },
            {"type": "fixed", "item": "Basic Longarm Ammunition", "qty": 100},
            {"type": "fixed", "item": "Flashbang Grenade"},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Tech Bag", "Anti-Smog Breathing Mask", "Disposable Cell Phone", "Duct Tape x5", "Flashlight", "Road Flare x6", "Generic Chic & Leisurewear Wardrobe"],
        "starting_cyberware": [
            {"name": "Cybereye", "hl": 7, "install": "Clinic", "notes": "Allows optic mods (includes MicroOptics)."},
            {"name": "MicroOptics", "hl": 2, "install": "Clinic", "notes": "400x microscope vision (+2 to micro repairs)."},
            {"name": "Tool Hand", "hl": 3, "install": "Clinic", "notes": "Fingers hold screwdriver, wrench, soldering iron, etc."},
            {"name": "Skinwatch", "hl": 0, "install": "Mall", "notes": "Subdermal LED time readout."},
        ],
        "starting_hl": 12,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Tech are You?",
                "options": [
                    "Cyberware Technician",
                    "Vehicle Mechanic",
                    "Jack of All Trades",
                    "Small Electronics Technician",
                    "Weaponsmith",
                    "Crazy Inventor",
                    "Robot and Drone Mechanic",
                    "Heavy Machinery Mechanic",
                    "Scavenger",
                    "Nautical Mechanic",
                ],
            },
            {
                "key": "partner",
                "label": "Got a Partner, or Do You Work Alone?",
                "options": [
                    "Work alone",
                    "Family member",
                    "Old friend",
                    "Possible romantic partner as well",
                    "Mentor",
                    "Secret partner with mob/gang connections",
                    "Secret partner with Corporate connections",
                ],
            },
            {
                "key": "workspace",
                "label": "Typical Workshop",
                "options": [
                    "Buried under scattered schematics and parts trays.",
                    "Color-coded bins that somehow remain chaotic.",
                    "Paperless digital CAD setup backed up daily.",
                    "All schematics drafted on the move via Agent.",
                    "Hoards every scrap bolt and circuit just in case.",
                    "Idiosyncratic filing system only you can navigate.",
                ],
            },
            {
                "key": "clients",
                "label": "Who are Your Main Clients?",
                "options": [
                    "Local Fixers who send you clients.",
                    "Local gangers who also protect your work area or home.",
                    "Corporate Execs who use you for \"black project\" work.",
                    "Local Solos or other combat types who use you for weapon upkeep.",
                    "Local Nomads and Fixers who bring you \"found\" tech to repair.",
                    "You work for yourself and sell what you invent/repair.",
                ],
            },
            {
                "key": "supplies",
                "label": "Where Do You Get Your Supplies?",
                "options": [
                    "Scavenge the wreckage you find in abandoned City Zones.",
                    "Strip gear from bodies after firefights.",
                    "Have a local Fixer bring you supplies in exchange for repair work.",
                    "Corporate Execs supply you with stuff in exchange for your services.",
                    "You have backdoor into a few Corporate warehouses.",
                    "You hit the Night Markets and score deals whenever you can.",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning For You?",
                "options": [
                    "Combat Zone gangers who want you to work for them exclusively.",
                    "Rival Tech trying to steal your customers.",
                    "Corporates who want you to work for them exclusively.",
                    "Larger manufacturer trying to bring you down because your mods are a threat.",
                    "Old client who thinks you screwed them over.",
                    "Rival Tech trying to beat you out for resources and parts.",
                ],
            },
        ],
    },
    "Medtech": {
        "ability": "Medicine",
        "ability_summary": "Allocate 4 Medicine points across Surgery (trauma operations), Pharmaceuticals (craft Speedheal, Rapidetox, Stim, Surge, Antibiotic), and Cryosystem Operation (save dying teammates).",
        "tagline": "Street doc, Trauma Team surgeon, and life-saver under fire.",
        "best_for": "Players who want to patch up critical injuries, craft combat stims, and handle cyber-surgery.",
        "key_stats": ["TECH", "WILL", "EMP"],
        "page": 149,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Primary Longarm",
                "options": [
                    "Arasaka \"Rapid Assault\" (Shotgun)",
                    "Militech \"Bulldog\" (Shotgun)",
                    "Militech \"Ronin\" Light Assault (Assault Rifle)",
                    "Chadran Arms \"Jungle Reaper\" (Assault Rifle)",
                ],
            },
            {"type": "fixed", "item": "Bulletproof Shield (10 HP)"},
            {"type": "fixed", "item": "Basic Longarm Ammunition", "qty": 100},
            {"type": "fixed", "item": "Incendiary Ammunition", "qty": 10},
            {"type": "fixed", "item": "Smoke Grenade", "qty": 2},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Medtech Bag", "Airhypo", "Flashlight", "Handcuffs", "Glow Paint", "Generic Chic & Leisurewear Wardrobe"],
        "starting_cyberware": [
            {"name": "Cybereye", "hl": 7, "install": "Clinic", "notes": "Allows TeleOptics optic link."},
            {"name": "TeleOptics", "hl": 3, "install": "Clinic", "notes": "Telescope vision up to 800m (+1 aimed shots/Surgery)."},
            {"name": "Biomonitor", "hl": 0, "install": "Mall", "notes": "Real-time vitals readout."},
        ],
        "cyberware_choice": {
            "label": "Protection Option",
            "options": [
                {"name": "Nasal Filters", "hl": 2, "install": "Clinic", "notes": "Immune to inhalable gases/fumes."},
                {"name": "Toxin Binders", "hl": 2, "install": "Clinic", "notes": "+2 to Resist Torture/Drugs saves."},
            ],
        },
        "starting_hl": 12,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Medtech are You?",
                "options": [
                    "Surgeon",
                    "General Practitioner",
                    "Trauma Medic",
                    "Psychiatrist",
                    "Cyberpsycho Therapist",
                    "Ripperdoc",
                    "Cryosystems Operator",
                    "Pharmacist",
                    "Bodysculptor",
                    "Forensic Pathologist",
                ],
            },
            {
                "key": "partner",
                "label": "Got a Partner, or Do You Work Alone?",
                "options": [
                    "Work alone",
                    "Trauma Team group",
                    "Old friend",
                    "Possible romantic partner as well",
                    "Family member",
                    "Secret partner with mob/gang connections",
                    "Secret partner with Corporate connections",
                ],
            },
            {
                "key": "workspace",
                "label": "Clinic or Operating Space",
                "options": [
                    "Scrubbed and sterilized every single morning.",
                    "Dated gear, yet familiar and reliable.",
                    "Cryo-cooler doubles as beverage storage between runs.",
                    "Packed exclusively with compact single-use disposables.",
                    "Decidedly grittier than most patients would prefer.",
                    "Spotless surgical suite with razor-sharp instruments.",
                ],
            },
            {
                "key": "clients",
                "label": "Who are Your Main Clients?",
                "options": [
                    "Local Fixers who send you clients.",
                    "Local gangers who also protect your work area or home in exchange for medical help.",
                    "Corporate Execs who use you for \"black project\" medical work.",
                    "Local Solos or other combat types who use you for medical help.",
                    "Local Nomads and Fixers who bring you wounded clients.",
                    "Trauma Team paramedical work.",
                ],
            },
            {
                "key": "supplies",
                "label": "Where Do You Get Your Supplies?",
                "options": [
                    "Scavenge stashes of medical supplies you find in abandoned City Zones.",
                    "Strip parts from bodies after firefights.",
                    "Have a local Fixer bring you supplies in exchange for medical work.",
                    "Corporate Execs or Trauma Team supply you with stuff in exchange for your services.",
                    "You have a backdoor into a few Corporate or Hospital warehouses.",
                    "You hit the Night Markets and score deals whenever you can.",
                ],
            },
        ],
    },
    "Media": {
        "ability": "Credibility",
        "ability_summary": "Uncover secrets, verify rumors, rally public outrage, and make stories stick so Corps and gangs actually feel the heat.",
        "tagline": "Investigative journalist, scream-sheet muckraker, and truth-seeker.",
        "best_for": "Players who love mystery, digging up dirt, interviewing NPCs, and turning info into leverage.",
        "key_stats": ["INT", "COOL", "EMP"],
        "page": 151,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Sidearm",
                "options": [
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                    "Mustang Arms \"Mark III\" (Heavy Pistol)",
                    "Novak Model 75 (Heavy Pistol)",
                ],
            },
            {"type": "fixed", "item": "Basic Pistol Ammunition", "qty": 50},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Audio Recorder", "Binoculars", "Computer", "Flashlight", "Radio Scanner/Music Player", "Scrambler/Descrambler", "Video Camera", "Generic Chic & Leisurewear Wardrobe"],
        "outfit_choice": {"label": "Field Kit Option", "options": ["Grapple Gun", "Disposable Cellphone x2"]},
        "starting_cyberware": [
            {"name": "Cyberaudio Suite", "hl": 7, "install": "Clinic", "notes": "Houses audio mods."},
            {"name": "Light Tattoo", "hl": 0, "install": "Mall", "notes": "Subdermal light tattoo."},
        ],
        "cyberware_choice": {
            "label": "Audio Enhancement",
            "options": [
                {"name": "Amplified Hearing", "hl": 3, "install": "Mall", "notes": "+2 Perception for hearing checks."},
                {"name": "Voice Stress Analyzer", "hl": 3, "install": "Mall", "notes": "+2 Human Perception & Interrogation lie detection."},
            ],
        },
        "starting_hl": 10,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Media are You?",
                "options": [
                    "Blogger",
                    "Writer (Books)",
                    "Videographer",
                    "Documentarian",
                    "Investigative Reporter",
                    "Street Scribe",
                ],
            },
            {
                "key": "ethics",
                "label": "Journalistic Standards",
                "options": [
                    "Strictly fact-checked—publishes only verified evidence.",
                    "Honest intent, but willing to run unverified street leads.",
                    "Mostly principled with occasional ethical shortcuts.",
                    "Bends rules when chasing corrupt targets.",
                    "Aggressive muckraker willing to break laws for a scoop.",
                    "Completely for sale—spins stories for the highest bidder.",
                ],
            },
            {
                "key": "reach",
                "label": "How Does Your Work Reach the Public?",
                "options": [
                    "Monthly magazine",
                    "Blog",
                    "Mainstream vid feed",
                    "News channel",
                    "\"Book\" sales",
                    "Screamsheets",
                ],
            },
            {
                "key": "stories",
                "label": "What Types of Stories Do You Want to Tell?",
                "options": [
                    "Political Intrigue",
                    "Ecological Impact",
                    "Celebrity News",
                    "Corporate Takedowns",
                    "Editorials",
                    "Propaganda",
                ],
            },
        ],
    },
    "Lawman": {
        "ability": "Backup",
        "ability_summary": "Radio in allied responders—fellow officers, precinct tactical squads, or armored AV support depending on your Backup rank and location.",
        "tagline": "Badge on The Street—beat cop, precinct detective, or Private Security.",
        "best_for": "Players who want investigation authority, street firefights, and calling in squad reinforcements.",
        "key_stats": ["REF", "BODY", "COOL"],
        "page": 158,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Primary Longarm",
                "options": [
                    "Militech \"Ronin\" Light Assault (Assault Rifle)",
                    "Chadran Arms \"Jungle Reaper\" (Assault Rifle)",
                    "Arasaka \"Rapid Assault\" (Shotgun)",
                    "Militech \"Bulldog\" (Shotgun)",
                ],
            },
            {
                "type": "choice",
                "label": "Service Sidearm (Heavy Pistol)",
                "options": [
                    "Mustang Arms \"Mark III\" (Heavy Pistol)",
                    "Novak Model 75 (Heavy Pistol)",
                ],
            },
            {"type": "fixed", "item": "Basic Longarm Ammunition", "qty": 100},
            {"type": "fixed", "item": "Basic H Pistol Ammunition", "qty": 30},
            {"type": "choice", "label": "Tactical Extra", "options": ["Bulletproof Shield (10 HP)", "Smoke Grenade x2"]},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Handcuffs x2", "Flashlight", "Radio Communicator", "Road Flare x10", "Generic Chic & Leisurewear Wardrobe"],
        "starting_cyberware": [
            {"name": "Hidden Holster", "hl": 7, "install": "Clinic", "notes": "Conceals a concealable firearm inside your body."},
            {"name": "Subdermal Pocket", "hl": 3, "install": "Clinic", "notes": "2\"×4\" concealed skin storage pocket."},
        ],
        "starting_hl": 10,
        "role_lifepath": [
            {
                "key": "position",
                "label": "What is Your Position on the Force?",
                "options": [
                    "Guard",
                    "Standard Beat or Patrol",
                    "Criminal Investigation",
                    "Special Weapons and Tactics",
                    "Motor Patrol",
                    "Internal Affairs",
                ],
            },
            {
                "key": "jurisdiction",
                "label": "How Wide is Your Group's Jurisdiction?",
                "options": [
                    "Corporate Zones",
                    "Standard City Patrol Zone",
                    "Combat Zones",
                    "Outer City",
                    "Recovery Zones",
                    "Open Highways",
                ],
            },
            {
                "key": "corruption",
                "label": "Precinct / Squad Integrity",
                "options": [
                    "By-the-book officers upholding strict ethics.",
                    "Honest squad with a hardline stance against street crime.",
                    "Mostly clean, though corners get cut on rare occasions.",
                    "Willing to bend procedure to put bad actors away.",
                    "Heavy-handed enforcers who ignore laws to hold territory.",
                    "Thoroughly compromised—takes bribes and runs dirty side rackets.",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning for Your Group?",
                "options": [
                    "Organized Crime",
                    "Boostergangs",
                    "Police Accountability Group",
                    "Dirty Politicians",
                    "Smugglers",
                    "Street Criminals",
                ],
            },
            {
                "key": "target",
                "label": "Who is Your Group's Major Target?",
                "options": [
                    "Organized Crime",
                    "Boostergangs",
                    "Drug Runners",
                    "Dirty Politicians",
                    "Smugglers",
                    "Street Crime",
                ],
            },
        ],
    },
    "Exec": {
        "ability": "Teamwork",
        "ability_summary": "Backed by a Megacorp housing stipend, free Trauma Team coverage, business attire, and loyal Corporate Team Members (techs, netrunners, or bodyguards) you can deploy.",
        "tagline": "Corporate shark with expense accounts, Trauma Team, and loyal staff.",
        "best_for": "Players who want high resources, luxury leverage, intrigue, and loyal NPC minions.",
        "key_stats": ["INT", "COOL", "EMP"],
        "page": 153,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Executive Sidearm (Very Heavy Pistol)",
                "options": [
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                    "Militech \"Boomer Buster\" (Very Heavy Pistol)",
                ],
            },
            {"type": "fixed", "item": "Basic VH Pistol Ammunition", "qty": 50},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Businesswear Suit & Mirrorshades", "Radio Communicator x4", "Scrambler/Descrambler"],
        "starting_cyberware": [
            {"name": "Cyberaudio Suite", "hl": 7, "install": "Clinic", "notes": "Houses Internal Agent."},
            {"name": "Internal Agent", "hl": 3, "install": "Mall", "notes": "Always-available mental smartphone & Audio HUD."},
        ],
        "cyberware_choice": {
            "label": "Executive Style Mod",
            "options": [
                {"name": "Biomonitor", "hl": 0, "install": "Mall", "notes": "Vitals monitor synced to Trauma Team."},
                {"name": "Techhair", "hl": 0, "install": "Mall", "notes": "Color-tunable designer hair."},
            ],
        },
        "cyberware_choice_2": {
            "label": "Defensive Filter",
            "options": [
                {"name": "Toxin Binders", "hl": 2, "install": "Clinic", "notes": "+2 to Resist Torture/Drugs."},
                {"name": "Nasal Filters", "hl": 2, "install": "Clinic", "notes": "Stops airborne gases/fumes."},
            ],
        },
        "starting_hl": 12,
        "role_lifepath": [
            {
                "key": "corp_type",
                "label": "What Kind of Corp Do You Work For?",
                "options": [
                    "Financial",
                    "Media and Communications",
                    "Cybertech and Medical Technologies",
                    "Pharmaceuticals and Biotech",
                    "Food, Clothing, or other General Consumables",
                    "Energy Production",
                    "Personal Electronics and Robotics",
                    "Corporate Services",
                    "Consumer Services",
                    "Real Estate and Construction",
                ],
            },
            {
                "key": "division",
                "label": "What Division Do You Work In?",
                "options": [
                    "Procurement",
                    "Manufacturing",
                    "Research and Development",
                    "Human Resources",
                    "Public Affairs/Publicity/Advertising",
                    "Mergers and Acquisitions",
                ],
            },
            {
                "key": "ethics",
                "label": "Corporate Culture",
                "options": [
                    "Publicly civic-minded with strict compliance policies.",
                    "Straightforward, honest commercial enterprise.",
                    "Mostly clean, with rare questionable operations.",
                    "Pragmatic—bends regulations when profits demand it.",
                    "Aggressive and profit-first, tolerant of shady ops.",
                    "Predatory—routinely runs black-ops and illegal schemes.",
                ],
            },
            {
                "key": "boss",
                "label": "Relationship with Your Boss",
                "options": [
                    "Mentors you closely, though their rivals watch you too.",
                    "Gives total autonomy and prefers plausible deniability.",
                    "Relentless micromanager constantly hovering over your desk.",
                    "Volatile and paranoid—unpredictable mood swings.",
                    "Supportive ally who shields you from office politics.",
                    "Threatened by your rapid rise and plotting your downfall.",
                ],
            },
            {
                "key": "hq",
                "label": "Where is Your Corp Based?",
                "options": [
                    "One city",
                    "Several cities",
                    "Statewide",
                    "National",
                    "International, offices in a few major cities",
                    "International, offices everywhere",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning for Your Group?",
                "options": [
                    "Rival Corp in the same industry.",
                    "Law enforcement is watching you.",
                    "Local Media wants to bring you down.",
                    "Different divisions in your own company are feuding with each other.",
                    "Local government doesn't like your Corp.",
                    "International Corporations are eyeing you for a hostile takeover.",
                ],
            },
        ],
    },
    "Fixer": {
        "ability": "Operator",
        "ability_summary": "Source hard-to-find gear, haggle +/-10% prices, speak street dialects fluently, and organize Night Markets so your crew gets paid and geared up.",
        "tagline": "Dealer, broker, smuggler, and Night Market kingpin.",
        "best_for": "Players who want connections, black-market access, street diplomacy, and always knowing a guy.",
        "key_stats": ["COOL", "EMP", "INT"],
        "page": 159,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Primary Sidearm",
                "options": [
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                    "Mustang Arms \"Mark III\" (Heavy Pistol)",
                ],
            },
            {
                "type": "choice",
                "label": "Backup Sidearm",
                "options": [
                    "Mustang Arms \"Mark III\" (Heavy Pistol)",
                    "Novak Model 75 (Heavy Pistol)",
                    "Militech \"Boomer Buster\" (Very Heavy Pistol)",
                ],
            },
            {
                "type": "choice",
                "label": "Concealed Blade (Light Melee)",
                "options": [
                    "Combat Knife (Light Melee)",
                    "Switchblade / Stiletto (Light Melee)",
                ],
            },
            {"type": "fixed", "item": "Basic Pistol Ammunition", "qty": 100},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": ["Agent", "Bug Detector", "Computer", "Disposable Cellphone x2", "Urban Flash & Leisurewear Wardrobe"],
        "starting_cyberware": [
            {"name": "Cyberaudio Suite", "hl": 7, "install": "Clinic", "notes": "Houses audio mods & Internal Agent."},
            {"name": "Internal Agent", "hl": 3, "install": "Mall", "notes": "Encrypted subdermal phone/HUD."},
            {"name": "Subdermal Pocket", "hl": 3, "install": "Clinic", "notes": "Concealed body compartment."},
        ],
        "cyberware_choice": {
            "label": "Negotiation Mod",
            "options": [
                {"name": "Voice Stress Analyzer", "hl": 3, "install": "Mall", "notes": "+2 Human Perception & Interrogation lie reads."},
                {"name": "Amplified Hearing", "hl": 3, "install": "Mall", "notes": "+2 Perception hearing checks."},
            ],
        },
        "starting_hl": 16,
        "role_lifepath": [
            {
                "key": "type",
                "label": "What Kind of Fixer are You?",
                "options": [
                    "Broker deals between rival gangs.",
                    "Procure rare or atypical resources for exclusive clientele.",
                    "Specialize in brokering Solo or Tech services as an agent.",
                    "Supply a regular resource for the Night Markets, like food, medicines, or drugs.",
                    "Procure highly illegal resources, like street drugs or milspec weapons.",
                    "Supply resources for Techs and Medtechs, like parts and medical supplies.",
                    "Operate several successful Night Markets, although not as owner.",
                    "Broker use contracts for heavy machinery, military vehicles, and aircraft.",
                    "Broker deals as a fence for scavengers raiding Corps or Combat Zones.",
                    "Act as an exclusive agent for a Media, Rockerboy, or a Nomad Pack.",
                ],
            },
            {
                "key": "office",
                "label": "Base of Operations",
                "options": [
                    "No fixed address—always operating on the move.",
                    "Reserved corner booth in a neighborhood bar.",
                    "Strictly encrypted Data Pool handles and dead drops.",
                    "Back office inside a warehouse, shop, or street clinic.",
                    "Condemned building rigged with alarms.",
                    "Crowded lobby of a local cube hotel.",
                ],
            },
            {
                "key": "partner",
                "label": "Got a Partner or Work Alone?",
                "options": [
                    "Work alone",
                    "Family member",
                    "Old friend",
                    "Possible romantic partner as well",
                    "Mentor",
                    "Secret partner with mob/gang connections",
                    "Secret partner with Corporate connections",
                ],
            },
            {
                "key": "clients",
                "label": "Who are Your Side Clients?",
                "options": [
                    "Local Rockerboys or Medias who use you to get them gigs or contacts.",
                    "Local gangers who also protect your work area or home.",
                    "Corporate Execs who use you for \"black project\" procurement work.",
                    "Local Solos or other combat types who use you to get them jobs or contacts.",
                    "Local Nomads and Fixers who use you to set up transactions or deals.",
                    "Local politicos or Execs who depend on you for finding out information.",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning for You?",
                "options": [
                    "Combat Zone gangers who want you to work for them exclusively.",
                    "Rival Fixers trying to steal your clients.",
                    "Execs who want you to work for them exclusively.",
                    "Enemy of a former client who wants to clean up \"loose ends\"—like you.",
                    "Old client who thinks you screwed them over.",
                    "Rival Fixer trying to beat you out for resources and parts.",
                ],
            },
        ],
    },
    "Nomad": {
        "ability": "Moto",
        "ability_summary": "Add Moto rank (+4) to all Drive/Pilot checks and command a custom Pack vehicle (Compact Groundcar, Gyrocopter, Jetski, or Roadbike, plus Upgrades) starting with your character.",
        "tagline": "Road warrior, smuggler, and family-backed vehicle ace.",
        "best_for": "Players who want high-speed chases, armored rides, wilderness survival, and clan backup.",
        "key_stats": ["REF", "DEX", "COOL"],
        "page": 161,
        "starting_weapons": [
            {
                "type": "choice",
                "label": "Primary Sidearm",
                "options": [
                    "Mustang Arms \"Mark III\" (Heavy Pistol)",
                    "Novak Model 75 (Heavy Pistol)",
                    "Sternmeyer P-35 (Very Heavy Pistol)",
                    "Federated Arms X-9mm (Very Heavy Pistol)",
                ],
            },
            {
                "type": "choice",
                "label": "Close Backup",
                "options": [
                    "Combat Machete (Heavy Melee)",
                    "Street Katana (Heavy Melee)",
                    "Mustang Arms \"Mark III\" (Heavy Pistol)",
                    "Novak Model 75 (Heavy Pistol)",
                ],
            },
            {"type": "fixed", "item": "Basic Pistol Ammunition", "qty": 100},
        ],
        "starting_armor": ["Light Armorjack Body Armor (SP 11)", "Light Armorjack Head Armor (SP 11)"],
        "starting_outfit": [
            "Agent",
            "Flashlight",
            "Handcuffs",
            "Inflatable Bed & Sleep-bag",
            "Medtech/Repair Kit (Techtool)",
            "Radio Communicator x2",
            "Rope (60m)",
            "Tent and Camping Equipment",
            "Bohemian Jewelry",
            "Nomad Leathers Wardrobe",
        ],
        "starting_cyberware": [
            {"name": "Neural Link", "hl": 7, "install": "Clinic", "notes": "Allows direct vehicle/weapon neural interfaces."},
        ],
        "cyberware_choice": {
            "label": "Road Mod",
            "options": [
                {"name": "Interface Plugs", "hl": 7, "install": "Clinic", "notes": "Plug directly into Moto vehicles to steer with your mind."},
                {"name": "Wolvers", "hl": 7, "install": "Clinic", "notes": "Concealed knuckle blades (3d6 dmg, ROF 2)."},
            ],
        },
        "starting_hl": 14,
        "role_lifepath": [
            {
                "key": "pack_size",
                "label": "How Big is Your Pack?",
                "options": [
                    "A single extended tribe or family",
                    "A couple dozen members",
                    "Forty or fifty members",
                    "A hundred or more members",
                    "A Blood Family (hundreds of members)",
                    "An Affiliated Family (made of several Blood Families)",
                ],
            },
            {
                "key": "domain",
                "label": "Is Your Pack Based on Land, Air, or Sea?",
                "options": [
                    "Land",
                    "Air",
                    "Sea",
                ],
            },
            {
                "key": "specialty",
                "label": "What Does Your Pack Do?",
                "options": [
                    "Gogang",
                    "Passenger transport",
                    "Chautauqua/school",
                    "Traveling show/carnival",
                    "Migrant farmers",
                    "Cargo transport",
                    "Shipment protection",
                    "Smuggling",
                    "Mercenary army",
                    "Construction work gang",
                    "Air piracy / Aircraft protection",
                    "Sea piracy / Submarine warfare",
                ],
            },
            {
                "key": "pack_role",
                "label": "What Do You Do for Your Pack?",
                "options": [
                    "Scout (negotiator)",
                    "Outrider (protection, weapons)",
                    "Transport pilot/driver",
                    "Loadmaster (large cargo mover, trucker)",
                    "Solo smuggler",
                    "Procurement (fuel, vehicles, etc.)",
                ],
            },
            {
                "key": "philosophy",
                "label": "Pack Code & Outlook",
                "options": [
                    "Helpful neighbors trying to build goodwill across routes",
                    "Straight-dealing family transport business",
                    "Generally honest, bending rules only in emergencies",
                    "Pragmatic—cuts legal corners when survival demands it",
                    "Hard-edged and self-interested when profit is on the line",
                    "Predatory highway raiders preying on weaker travelers",
                ],
            },
            {
                "key": "enemy",
                "label": "Who's Gunning for Your Pack?",
                "options": [
                    "Organized Crime",
                    "Boostergangs",
                    "Drug Runners",
                    "Dirty Politicians",
                    "Rival Packs in the same businesses",
                    "Dirty Cops",
                ],
            },
            {
                "key": "why_city",
                "label": "Why Are You in Night City?",
                "options": [
                    "Pack liaison scouting work and securing cargo/construction contracts",
                    "Exiled after an internal clan dispute",
                    "Sending money and supplies back to support the Pack",
                    "Hunting whoever hit a Pack convoy or family member",
                    "Working off a family debt or fulfilling an alliance with an Edgerunner",
                    "Just needed personal freedom from the highway and clan hierarchy",
                ],
            },
        ],
    },
}

CULTURAL_REGIONS: list[dict[str, Any]] = [
    {"region": "North American", "languages": ["Chinese", "Cree", "Creole", "English", "French", "Navajo", "Spanish"]},
    {"region": "South/Central American", "languages": ["Creole", "English", "German", "Guarani", "Mayan", "Portuguese", "Quechua", "Spanish"]},
    {"region": "Western European", "languages": ["Dutch", "English", "French", "German", "Italian", "Norwegian", "Portuguese", "Spanish"]},
    {"region": "Eastern European", "languages": ["English", "Finnish", "Polish", "Romanian", "Russian", "Ukrainian"]},
    {"region": "Middle Eastern/North African", "languages": ["Arabic", "Berber", "English", "Farsi", "French", "Hebrew", "Turkish"]},
    {"region": "Sub-Saharan African", "languages": ["Arabic", "English", "French", "Hausa", "Lingala", "Oromo", "Portuguese", "Swahili", "Twi", "Yoruba"]},
    {"region": "South Asian", "languages": ["Bengali", "Dari", "English", "Hindi", "Nepali", "Sinhalese", "Tamil", "Urdu"]},
    {"region": "South East Asian", "languages": ["Arabic", "Burmese", "English", "Filipino", "Hindi", "Indonesian", "Khmer", "Malayan", "Vietnamese"]},
    {"region": "East Asian", "languages": ["Cantonese Chinese", "English", "Japanese", "Korean", "Mandarin Chinese", "Mongolian"]},
    {"region": "Oceania/Pacific Islander", "languages": ["English", "French", "Hawaiian", "Maori", "Pama-Nyungan", "Tahitian"]},
]

LIFEPATH_TABLES: dict[str, list[str]] = {
    "personality": [
        "Quiet and guarded",
        "Defiant and quick-tempered",
        "Proud and standoffish",
        "Impulsive and volatile",
        "Anxious and detail-obsessed",
        "Steady and grounded",
        "Flippant and carefree",
        "Calculating and sly",
        "Analytical and cool-headed",
        "Warm and sociable",
    ],
    "clothing_style": [
        "Generic Chic (Everyday practical streetwear)",
        "Leisurewear (Athletic, flexible street comfort)",
        "Urban Flash (Neon-accented techwear)",
        "Businesswear (Sharp corporate tailoring)",
        "High Fashion (Custom luxury couture)",
        "Bohemian (Retro, handcrafted, free-spirited)",
        "Bag Lady Chic (Layered, weathered survivalist)",
        "Gang Colors (Bold crew patches and heavy boots)",
        "Nomad Leathers (Road-worn hides and utility gear)",
        "Asia Pop (Vibrant, trend-forward street pop)",
    ],
    "hairstyle": [
        "Mohawk",
        "Long and unkempt",
        "Short and spiked",
        "Untamed and messy",
        "Shaved bald",
        "Striped dye",
        "Neon bright colors",
        "Clean and cropped",
        "Short curls",
        "Long and straight",
    ],
    "affectation": [
        "Tattoos",
        "Mirrorshades",
        "Ritual scars",
        "Studded gloves",
        "Nose rings",
        "Piercings",
        "Decorative nail implants",
        "Heavy combat boots or heels",
        "Fingerless gloves",
        "Custom cosmetic contacts",
    ],
    "value_most": [
        "Eurobucks",
        "Honor",
        "Keeping your word",
        "Truthfulness",
        "Knowledge",
        "Payback",
        "Love",
        "Power",
        "Family",
        "Friendship",
    ],
    "feelings_about_people": [
        "Keeps a neutral distance.",
        "Takes people case by case.",
        "Generally likes most folks.",
        "Distrusts almost everyone.",
        "Views people strictly as useful leverage.",
        "Believes every individual has worth.",
        "Treats anyone in the way as an obstacle.",
        "Relies on nobody—trust gets you killed.",
        "Cynical misanthrope fed up with society.",
        "Genuinely optimistic about people.",
    ],
    "valued_person": [
        "A parent",
        "A sibling",
        "A partner",
        "A close friend",
        "Yourself",
        "A loyal pet",
        "A mentor or teacher",
        "A public figure",
        "A personal role model",
        "Nobody",
    ],
    "valued_possession": [
        "A firearm or blade",
        "A trusty tool",
        "A signature jacket or garment",
        "An old photo",
        "A worn journal",
        "A rare recording",
        "An instrument",
        "A piece of jewelry",
        "A childhood keepsake",
        "An important letter",
    ],
    "family_background": [
        "Corporate Executives — Grew up behind private security walls with elite schooling and luxury.",
        "Corporate Managers — Comfortable suburban upbringing with private academies and steady perks.",
        "Corporate Technicians — Middle-tier conapt or corporate-suburb life with technical training.",
        "Nomad Pack — Raised on the highway among trailers, convoys, and tight-knit road kin.",
        "Gang Crew — Harsh childhood in contested turf learning street survival early.",
        "Combat Zone Survivors — Fortified squatter block life with scavenged rations and self-defense.",
        "Street Homeless — Grew up moving between parked cars, alleys, and makeshift shelters.",
        "Megabuilding Residents — Packed high-rise life surviving on cheap Kibble and crowded corridors.",
        "Frontier Reclaimers — Raised rebuilding ruined towns outside the metro perimeter.",
        "Edgerunner Kids — Constant moves between safehouses and high-roller suites depending on gigs.",
    ],
    "childhood_environment": [
        "Growing up unsupervised on the city streets.",
        "Inside a walled, guarded corporate enclave.",
        "Traveling constantly with a mobile Nomad convoy.",
        "Raised around Nomad shipping, air, or rail routes.",
        "In a fading neighborhood fighting off street gangs.",
        "Deep inside a ruined Combat Zone squat.",
        "Inside a towering corporate or city megabuilding.",
        "Among frontier towns rebuilt by Reclaimers.",
        "On an offshore floating Drift community.",
        "Atop a luxury corporate high-rise above the smog.",
    ],
    "family_crisis": [
        "Betrayal wiped out the family's assets.",
        "Bad deals and mismanagement ruined the household.",
        "Forced into exile from their former home or employer.",
        "Family members detained while only you slipped away.",
        "Everyone else vanished, leaving you behind.",
        "Lost the family in a violent attack and barely survived.",
        "Tied up in an ongoing syndicate or underground feud.",
        "Scattered across different regions by hard times.",
        "Burdened by a generations-old blood rivalry.",
        "Left holding a massive family debt to pay off.",
    ],
    "life_goal": [
        "Clear a tarnished street reputation.",
        "Climb to real power and influence.",
        "Earn enough to escape street life for good.",
        "Make rivals pay in kind.",
        "Leave a painful past behind.",
        "Track down whoever ruined your old life.",
        "Reclaim what was stolen from you.",
        "Protect the people still counting on you.",
        "Make a lasting name across Night City.",
        "Command respect and fear on the streets.",
    ],
    "friend_relationship": [
        "Like an older sibling",
        "Like a younger sibling",
        "A teacher or mentor",
        "A longtime work partner",
        "An ex-lover on good terms",
        "A former rival turned ally",
        "A parental figure",
        "A childhood friend",
        "A reliable street contact",
        "Someone sharing your exact goals",
    ],
    "enemy_who": [
        "Former friend",
        "Ex-lover",
        "Estranged relative",
        "Childhood rival",
        "Former subordinate",
        "Former employer",
        "Ex-partner or coworker",
        "Corporate executive",
        "City official",
        "Boosterganger",
    ],
    "enemy_cause": [
        "Cost the other serious street cred or status.",
        "Led to the loss of someone close.",
        "Triggered a bitter public humiliation.",
        "Called the other a coward or fraud.",
        "Walked out or betrayed a shared deal.",
        "Rejected a major job or romantic offer.",
        "Immediate, irreconcilable personal hostility.",
        "Clashed over the same romantic interest.",
        "Undercut each other in business.",
        "Framed the other for a crime.",
    ],
    "enemy_backup": [
        "Alone and rarely goes out of their way.",
        "Strictly solo.",
        "With one trusted associate.",
        "Backed by a small handful of friends.",
        "Backed by half a dozen tough allies.",
        "An entire street gang.",
        "Corrupt local cops or security.",
        "A crime boss or mid-sized firm.",
        "A major corporate division.",
        "Heavy municipal or agency backing.",
    ],
    "sweet_revenge": [
        "Ignore them and stay clear.",
        "Avoid contact unless forced.",
        "Attack furiously on sight.",
        "Go straight for a brutal physical beatdown.",
        "Sabotage them quietly from the shadows.",
        "Undermine their deals indirectly.",
        "Call them out publicly and relentlessly.",
        "Tear into them verbally every chance you get.",
        "Frame them for a job they never pulled.",
        "Hunt them down to finish things permanently.",
    ],
    "tragic_love": [
        "Lost in a sudden fatal accident.",
        "Disappeared without a trace.",
        "Simply drifted apart over time.",
        "Personal vendettas tore the relationship apart.",
        "Taken hostage by enemies.",
        "Lost to severe cyberpsychosis or breakdown.",
        "Ended their own life under immense pressure.",
        "Killed during an ambush or firefight.",
        "Stolen away by a bitter rival.",
        "Locked away or forced into exile.",
    ],
}

FASHION_ITEMS: list[dict[str, Any]] = [
    {"name": "Generic Chic Outfit", "cost_eb": 140, "style": "Generic Chic", "summary": "Everyday Night City street clothes (top, bottoms, jacket, footwear)."},
    {"name": "Leisurewear Outfit", "cost_eb": 270, "style": "Leisurewear", "summary": "Athletic, comfortable street/training gear with mirrorshades."},
    {"name": "Urban Flash Outfit", "cost_eb": 320, "style": "Urban Flash", "summary": "LED-trimmed tech streetwear with jacket & footwear."},
    {"name": "Nomad Leathers Outfit", "cost_eb": 320, "style": "Nomad Leathers", "summary": "Rugged weathered jacket, boots, and tribal roadwear."},
    {"name": "Asia Pop Outfit", "cost_eb": 320, "style": "Asia Pop", "summary": "Neon-bright costume streetwear and flashy lenses."},
    {"name": "Bohemian Outfit", "cost_eb": 170, "style": "Bohemian", "summary": "Retro, folksy, free-spirited jacket and accessories."},
    {"name": "Bag Lady Chic Outfit", "cost_eb": 70, "style": "Bag Lady Chic", "summary": "Layered ragged street camo that blends into the slums."},
    {"name": "Gang Colors Outfit", "cost_eb": 140, "style": "Gang Colors", "summary": "Aggressive patched jacket and tough street boots."},
    {"name": "Businesswear Jacket + Suit", "cost_eb": 800, "style": "Businesswear", "summary": "Corporate suit projection: authority and boardroom presence."},
    {"name": "High Fashion Designer Top", "cost_eb": 500, "style": "High Fashion", "summary": "Exclusive haute couture designer top crafted from luxury fabrics."},
    {"name": "Bag Lady Chic Jacket", "cost_eb": 20, "style": "Bag Lady Chic", "summary": "Rough, weather-beaten salvaged jacket."},
    {"name": "Nomad Leathers Jacket", "cost_eb": 100, "style": "Nomad Leathers", "summary": "Heavy fringed rawhide jacket."},
    {"name": "Urban Flash Mirrorshades", "cost_eb": 100, "style": "Urban Flash", "summary": "High-tech color-cycling polarized mirrorshades."},
    {"name": "Bohemian Jewelry", "cost_eb": 100, "style": "Bohemian", "summary": "Handcrafted retro beadwork and brass rings."},
    {"name": "High Fashion Contact Lenses", "cost_eb": 1000, "style": "High Fashion", "summary": "Exclusive designer vanity iris patterns."},
]


def _skill_group(skill_name: str) -> str:
    base = skill_name.split("(", 1)[0].strip()
    for group, names in _SKILL_GROUPS.items():
        if base in names or skill_name in names:
            return group
    return "Other"


_BASIC_BASES = {
    "athletics",
    "brawling",
    "concentration",
    "conversation",
    "education",
    "evasion",
    "first aid",
    "human perception",
    "language",
    "local expert",
    "perception",
    "persuasion",
    "stealth",
}

_BASIC_DEFAULT_SPECS = {
    "language": "Language (Streetslang)",
    "local expert": "Local Expert (Your Home)",
}


def build_creation_reference(rules_path: str | Path | None) -> dict[str, Any]:
    """Assemble structured Corebook creation data, templates, lifepath, and shop items."""
    path = Path(rules_path).expanduser() if rules_path else None
    rules_indexed = bool(path and path.is_file())

    templates: dict[str, list[list[int]]] = {}
    role_skills: dict[str, dict[str, int]] = {}
    skills_list: list[dict[str, Any]] = []
    shop_items: dict[str, list[dict[str, Any]]] = {
        "weapon": build_corebook_weapons(),
        "armor": build_corebook_armor(),
        "cyberware": [],
        "gear": [],
        "program": [],
        "hardware": build_corebook_hardware(),
        "vehicle": build_corebook_vehicles(),
        "drug": build_corebook_drugs(),
        "ammo": [],
        "attachment": [],
        "service": [],
        "housing": [],
    }

    if rules_indexed and path is not None:
        catalog = source_skills_catalog(path)
        lib_skills = {
            entry["name"].casefold(): entry
            for entry in list_category(path, "skill")
        }
        for role in ROLES:
            try:
                templates[role] = _template(path, role)
            except ValueError:
                pass
            try:
                role_skills[role] = _role_skills(path, role, catalog)
            except ValueError:
                pass
        for name, meta in sorted(catalog.items(), key=lambda kv: kv[0].casefold()):
            lib_entry = lib_skills.get(name.casefold())
            norm_key = _norm_skill(name)
            skills_list.append({
                "name": name,
                "stat": meta["stat"],
                "cost": meta["cost"],
                "basic": norm_key in BASIC or norm_key in _BASIC_BASES,
                "basic_skill_name": _BASIC_DEFAULT_SPECS.get(norm_key, name),
                "specializable": name.casefold() in {"language", "local expert", "science", "play instrument", "martial arts"},
                "group": _skill_group(name),
                "printed_page": meta.get("printed_page"),
                "summary": (lib_entry or {}).get("summary") or f"{name} ({meta['stat']})",
                "description": (lib_entry or {}).get("description") or f"{name} is governed by {meta['stat']} (IP/creation multiplier x{meta['cost']}).",
            })
        for cat_name in ("cyberware", "gear", "program"):
            entries = list_category(path, cat_name)
            cleaned: list[dict[str, Any]] = []
            seen: set[str] = set()
            for entry in entries:
                key = entry["name"].casefold()
                if key in seen:
                    continue
                seen.add(key)
                stats = dict(entry.get("stats") or {})
                cost_eb = stats.get("cost_eb")
                if not isinstance(cost_eb, int):
                    continue
                if cat_name == "cyberware":
                    stats["hl"] = parse_hl_int(stats.get("humanity_loss"))
                cleaned.append({
                    "id": entry["id"],
                    "name": entry["name"],
                    "category": cat_name,
                    "cost_eb": cost_eb,
                    "summary": entry.get("summary") or "",
                    "description": entry.get("description") or "",
                    "printed_page": entry.get("printed_page"),
                    "stats": stats,
                })
            cleaned.sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
            shop_items[cat_name] = cleaned

    # Fallback and augment shop catalogs from canonical Corebook GM builders
    if not shop_items["cyberware"]:
        cw_items: list[dict[str, Any]] = []
        for entry in build_corebook_cyberware_additions():
            stats = dict(entry.get("stats") or {})
            cost_eb = entry.get("cost_eb") if isinstance(entry.get("cost_eb"), int) else stats.get("cost_eb", 0)
            if "hl" not in stats:
                stats["hl"] = parse_hl_int(stats.get("humanity_loss"))
            cw_items.append({
                "id": entry.get("id", f"corebook:cyberware:{entry['name'].lower().replace(' ', '_')}"),
                "name": entry["name"],
                "category": "cyberware",
                "cost_eb": cost_eb,
                "summary": entry.get("summary") or "",
                "description": entry.get("description") or "",
                "printed_page": entry.get("printed_page"),
                "stats": stats,
            })
        cw_items.sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
        shop_items["cyberware"] = cw_items

    if not shop_items["gear"]:
        shop_items["gear"] = sorted(
            build_corebook_gear(),
            key=lambda item: (item.get("cost_eb", 0), item["name"].casefold()),
        )

    if not shop_items["program"]:
        prog_items: list[dict[str, Any]] = []
        for entry in build_corebook_net_catalog():
            if entry.get("category") == "program":
                stats = dict(entry.get("stats") or {})
                cost_eb = entry.get("cost_eb") if isinstance(entry.get("cost_eb"), int) else stats.get("cost_eb", 0)
                prog_items.append({
                    "id": entry.get("id", f"corebook:program:{entry['name'].lower().replace(' ', '_')}"),
                    "name": entry["name"],
                    "category": "program",
                    "cost_eb": cost_eb,
                    "summary": entry.get("summary") or "",
                    "description": entry.get("description") or "",
                    "printed_page": entry.get("printed_page"),
                    "stats": stats,
                })
        prog_items.sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
        shop_items["program"] = prog_items

    need_ammo = not shop_items["ammo"]
    need_attachment = not shop_items["attachment"]
    if need_ammo or need_attachment:
        for entry in build_corebook_ammo_attachments_exotics():
            cat = entry.get("category")
            if (cat == "ammo" and need_ammo) or (cat == "attachment" and need_attachment):
                stats = dict(entry.get("stats") or {})
                cost_eb = entry.get("cost_eb") if isinstance(entry.get("cost_eb"), int) else stats.get("cost_eb", 0)
                shop_items[cat].append({
                    "id": entry.get("id", f"corebook:{cat}:{entry['name'].lower().replace(' ', '_')}"),
                    "name": entry["name"],
                    "category": cat,
                    "cost_eb": cost_eb,
                    "summary": entry.get("summary") or "",
                    "description": entry.get("description") or "",
                    "printed_page": entry.get("printed_page"),
                    "stats": stats,
                })
        shop_items["ammo"].sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
        shop_items["attachment"].sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))

    need_service = not shop_items["service"]
    need_housing = not shop_items["housing"]
    fashion_matrix: list[dict[str, Any]] = []
    for entry in build_corebook_services_housing_fashion():
        cat = entry.get("category")
        stats = dict(entry.get("stats") or {})
        cost_eb = entry.get("cost_eb") if isinstance(entry.get("cost_eb"), int) else stats.get("cost_eb", 0)
        if (cat == "service" and need_service) or (cat == "housing" and need_housing):
            shop_items[cat].append({
                "id": entry.get("id", f"corebook:{cat}:{entry['name'].lower().replace(' ', '_')}"),
                "name": entry["name"],
                "category": cat,
                "cost_eb": cost_eb,
                "summary": entry.get("summary") or "",
                "description": entry.get("description") or "",
                "printed_page": entry.get("printed_page"),
                "stats": stats,
            })
        elif cat == "fashion":
            fashion_matrix.append({
                "id": entry.get("id", f"corebook:fashion:{entry['name'].lower().replace(' ', '_')}"),
                "name": entry["name"],
                "cost_eb": cost_eb,
                "style": str(stats.get("style") or "Generic Chic"),
                "garment": str(stats.get("garment") or ""),
                "summary": entry.get("summary") or "",
            })
    shop_items["service"].sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
    shop_items["housing"].sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
    fashion_matrix.sort(key=lambda item: (item["style"].casefold(), item["cost_eb"], item["name"].casefold()))

    housing_tiers = [
        {"id": "cargo_container", "name": "Cargo Container", "monthly_eb": 1000, "summary": "Standard starting studio container (Month 1 rent paid at creation, p. 377)."},
        {"id": "cube", "name": "Cube Hotel", "monthly_eb": 500, "summary": "Tiny rented sleeping pod in a crowded megabuilding stack."},
        {"id": "street", "name": "Living on The Street", "monthly_eb": 0, "summary": "No rent, sleeping rough or in squats with constant hazard."},
        {"id": "vehicle", "name": "Living in a Vehicle", "monthly_eb": 0, "summary": "Nomad or compact road setup; requires an owned or clan vehicle."},
        {"id": "studio", "name": "Studio Apartment", "monthly_eb": 1500, "summary": "Private one-room apartment in a Moderate Zone block."},
        {"id": "two_bedroom", "name": "Two-Bedroom Apartment", "monthly_eb": 2500, "summary": "Spacious apartment suitable for crew ops or gear storage."},
        {"id": "upscale_conapt", "name": "Upscale Conapt", "monthly_eb": 7500, "summary": "Guarded corporate-grade condo with amenities and privacy."},
        {"id": "luxury_penthouse", "name": "Luxury Penthouse", "monthly_eb": 15000, "summary": "Top-floor Night City elite residence with private security."},
        {"id": "corporate", "name": "Corporate Conapt (Exec Perk)", "monthly_eb": 0, "summary": "Complimentary Exec corporate housing (requires Exec Role, p. 153).", "exec_only": True},
    ]
    lifestyles = [
        {"id": "Kibble", "name": "Kibble", "monthly_eb": 100, "summary": "Dry packaged nutrition; cheap survival baseline (Month 1 included, p. 377)."},
        {"id": "Generic Prepak", "name": "Generic Prepak", "monthly_eb": 300, "summary": "Microwavable prepak meals and basic street coffee."},
        {"id": "Good Prepak", "name": "Good Prepak", "monthly_eb": 600, "summary": "Decent restaurant takeout, nightlife drinks, and clean groceries."},
        {"id": "Fresh Food", "name": "Fresh Food", "monthly_eb": 1500, "summary": "Rare real produce, fresh meat, and high-society dining."},
    ]

    roles_payload = []
    for role in ROLES:
        info = dict(ROLE_INFO[role])
        info["name"] = role
        info["templates"] = templates.get(role, [])
        info["skills"] = role_skills.get(role, {})
        roles_payload.append(info)

    campaign_presets = build_campaign_presets()

    return {
        "rules_indexed": rules_indexed,
        "stat_names": list(STATS),
        "stats": STAT_INFO,
        "methods": CREATION_METHODS,
        "roles": roles_payload,
        "skills": skills_list,
        "cultural_regions": CULTURAL_REGIONS,
        "lifepath_tables": LIFEPATH_TABLES,
        "shop": shop_items,
        "fashion": FASHION_ITEMS,
        "fashion_matrix": fashion_matrix,
        "housing_tiers": housing_tiers,
        "lifestyles": lifestyles,
        "campaign_presets": campaign_presets,
        "difficult_skills": [
            "Autofire",
            "Demolitions",
            "Electronics/Security Tech",
            "Heavy Weapons",
            "Martial Arts",
            "Paramedic",
            "Pilot Air Vehicle",
        ],
        "threat_ratings": campaign_presets.get("threat_ratings", []),
        "zone_types": campaign_presets.get("zone_types", []),
        "screamsheets": campaign_presets.get("screamsheets", []),
        "difficulty_values": cgd.DV_TABLE,
    }
