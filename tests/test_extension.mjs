// Contract smoke test with a fake SillyTavern context; not a browser/provider test.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';

const tools = new Map(); const commands = new Map(); const listeners = new Map(); const prompts = [];
const notices = [];
globalThis.toastr = {
    info(text, title, options) { notices.push({ kind: 'info', text, title, options }); },
    error(text, title, options) { notices.push({ kind: 'error', text, title, options }); },
};
let chatId = 'chat-a'; let metadata = {}; let requested; let post; let backend = async (_url, _options) => ({ ok: true, json: async () => ({ result: {} }) });
globalThis.crypto ||= webcrypto;
const eventSource = { on: (event, fn) => { const list = listeners.get(event) || new Set(); list.add(fn); listeners.set(event, list); }, removeListener: (event, fn) => listeners.get(event)?.delete(fn), emit: event => { for (const fn of listeners.get(event) || []) fn(); } };
const context = { getCurrentChatId: () => chatId, groupId: null, characterId: 'pc', characters: { pc: { avatar: 'pc.png' } }, get chatMetadata() { return metadata; }, saveMetadata() {}, setExtensionPrompt: (...args) => prompts.push(args), eventSource, eventTypes: { CHAT_CHANGED: 'chat-changed' }, registerFunctionTool: tool => tools.set(tool.name, tool), unregisterFunctionTool: name => tools.delete(name), SlashCommandParser: { addCommandObject: x => commands.set(x.name, x) }, SlashCommand: { fromProps: x => x }, SlashCommandArgument: { fromProps: x => x } };
globalThis.SillyTavern = { getContext: () => context };
const source = await readFile(new URL('../sillytavern-extension/index.js', import.meta.url), 'utf8');
const extension = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
globalThis.fetch = async (url, options) => { requested = url; if (options?.method === 'POST') post = options; return backend(url, options); };

await extension.init(); await extension.init();
context.characters[0] = context.characters.pc; context.characterId = 0;
assert.equal(tools.size, 11); assert.equal(listeners.get('chat-changed').size, 1);
assert.deepEqual([...tools.keys()].sort(), ['campaign_action','catalog_corebook','find_corebook_phrase','game_action','read_corebook_page','read_corebook_pages','read_corebook_section','roll_dice','search_corebook','skill_check','solo_action'].sort());
await assert.rejects(tools.get('game_action').action({ action: 'roll_dice', arguments: { count: 1, sides: 6, reason: 'dup', operation_id: 'dup-1' } }), /required/);
await assert.rejects(tools.get('game_action').action({ action: 'skill_check', arguments: {} }), /required/);
await tools.get('search_corebook').action({ query: 'page 130' });
assert.equal(requested, 'http://127.0.0.1:8765/v1/search?q=page%20130&limit=5');
await tools.get('read_corebook_section').action({ section_id: 'combat', offset: 0, limit: 12 });
assert.equal(requested, 'http://127.0.0.1:8765/v1/sections/combat?offset=0&limit=12');
await assert.rejects(tools.get('solo_action').action({ action: 'net_action', arguments: { campaign_id: 'wrong' } }), /campaign_id override/);
let postedActions = [];
let postedBodies = [];
backend = async (_url, options) => {
    const body = options?.body ? JSON.parse(options.body) : {};
    if (body.action) { postedActions.push(body.action); postedBodies.push(body); }
    if (body.action === 'create_campaign') return { ok: true, json: async () => ({ result: { id: 'camp-1', name: 'Night City' } }) };
    if (body.action === 'campaign_context') return { ok: true, json: async () => ({ result: { campaign: { id: 'camp-1', name: 'Night City', revision: 0, session_number: 1, state: {} }, characters: [{ id: 'pc1', name: 'V', revision: 2, hp: 20, max_hp: 30, luck_remaining: 3, stats: { LUCK: 8 }, money: 100 }], solo: { revision: 4, runtime: { encounter: { active: true, round: 2, queue: ['pc1', 'npc1'], turn_index: 1 }, runs: { 'run-1': {} }, clock_minutes: 15 } } } }) };
    return { ok: true, json: async () => ({ result: {} }) };
};
const created = await commands.get('red-campaign').callback({}, 'create Night City');
assert.equal(notices.at(-1).kind, 'info'); assert.equal(notices.at(-1).text, created);
assert.equal(notices.at(-1).title, 'Cyberpunk RED'); assert.equal(notices.at(-1).options.escapeHtml, true);
assert.equal(metadata.cyberpunk_red_gm.campaign_id, 'camp-1');
assert.deepEqual(JSON.parse(post.body), { action: 'campaign_context', arguments: { campaign_id: 'camp-1' }, campaign_id: 'camp-1' });
assert.match(prompts.at(-1)[1], /Current SOLO revision=4/);
assert.match(prompts.at(-1)[1], /Active solo runtime: encounter=active round=2 turn=2\/2 actor=npc1; netruns=run-1; clock_minutes=15\./);
postedActions = []; postedBodies = [];
await tools.get('roll_dice').action({ count: 2, sides: 6, reason: 'test', operation_id: 'roll-1' });
assert.deepEqual(postedActions, ['roll_dice', 'campaign_context']);
postedActions = []; postedBodies = [];
await tools.get('skill_check').action({ character_id: 'pc1', expected_revision: 2, stat: 'REF', skill: 'Evasion', dv: 13, operation_id: 'check-1', reason: 'test check', modifier: 2, luck: 1, complementary: true, extra_time: false });
assert.deepEqual(postedActions, ['skill_check', 'campaign_context']);
assert.deepEqual(postedBodies[0], { action: 'skill_check', arguments: { character_id: 'pc1', expected_revision: 2, stat: 'REF', skill: 'Evasion', dv: 13, operation_id: 'check-1', reason: 'test check', modifier: 2, luck: 1, complementary: true, extra_time: false }, campaign_id: 'camp-1' });
await tools.get('solo_action').action({ action: 'solo_context', arguments: {} });
assert.equal(postedActions.at(-1), 'solo_context');
postedActions = []; postedBodies = [];
await tools.get('solo_action').action({ action: 'end_encounter', arguments: { expected_revision: 4, reason: 'done', operation_id: 'solo-1' } });
assert.deepEqual(postedActions, ['end_encounter', 'campaign_context']);
await tools.get('game_action').action({ action: 'list_characters', arguments: {} });
assert.equal(JSON.parse(post.body).campaign_id, 'camp-1');
assert.match(prompts.at(-1)[1], /luck=3\/8/); assert.match(prompts.at(-1)[1], /hp=20\/30/);
await commands.get('red-campaign').callback({}, 'use camp-1');
// A copied metadata binding is deliberately not accepted on another branch.
chatId = 'chat-b'; metadata = structuredClone(metadata); eventSource.emit('chat-changed');
assert.equal(await commands.get('red-campaign').callback({}, 'status'), 'Copied campaign binding belongs to a different chat branch. Select or create a campaign explicitly.');
assert.equal(notices.at(-1).kind, 'error'); assert.match(notices.at(-1).text, /different chat branch/);
assert.match(await commands.get('red-campaign').callback({}, 'use camp-1'), /Bound campaign/);
assert.equal(metadata.cyberpunk_red_gm.chat_key, JSON.stringify(['character:pc.png', 'chat-b']));
// A late response from the previous chat must not update the new chat prompt.
const waiting = []; backend = () => new Promise(resolve => waiting.push(resolve));
chatId = 'chat-a'; metadata = { cyberpunk_red_gm: { campaign_id: 'camp-1', chat_key: JSON.stringify(['character:pc.png', 'chat-a']) } }; eventSource.emit('chat-changed');
const late = globalThis.redgmCampaignInterceptor();
// Same-chat concurrent snapshots: newest refresh wins even when the earlier response arrives last.
const sameChat = globalThis.redgmCampaignInterceptor();
waiting[2]({ ok: true, json: async () => ({ result: { campaign: { id: 'camp-1', name: 'N', revision: 2, session_number: 1, state: { scene: 'latest' } }, characters: [] } }) });
await sameChat;
const latestPrompt = prompts.at(-1)[1];
waiting[1]({ ok: true, json: async () => ({ result: { campaign: { id: 'camp-1', name: 'N', revision: 1, session_number: 1, state: { scene: 'stale' } }, characters: [] } }) });
await late; assert.equal(prompts.at(-1)[1], latestPrompt);
waiting[0]({ ok: true, json: async () => ({ result: { campaign: { id: 'camp-1', name: 'N', revision: 0, session_number: 1, state: {} }, characters: [] } }) });
chatId = 'chat-b'; metadata = {}; eventSource.emit('chat-changed');
assert.equal(prompts.at(-1)[1], '');
let aborted = null;
await globalThis.redgmCampaignInterceptor('chat-b', 10, value => { aborted = value; }, 'normal');
assert.equal(aborted, true); assert.match(prompts.at(-1)[1], /No selected campaign/); assert.match(notices.at(-1).text, /\/red-campaign create NAME/);
chatId = 'copied'; metadata = { cyberpunk_red_gm: { campaign_id: 'camp-1', chat_key: 'other' } };
aborted = null; await globalThis.redgmCampaignInterceptor('copied', 10, value => { aborted = value; }, 'normal');
assert.equal(aborted, true); assert.match(notices.at(-1).text, /Copied campaign binding/);
// Bound context with oversized narrative state remains capped and labelled.
chatId = 'huge'; metadata = { cyberpunk_red_gm: { campaign_id: 'camp-1', chat_key: JSON.stringify(['character:pc.png', 'huge']) } };
backend = async () => ({ ok: true, json: async () => ({ result: { campaign: { id: 'camp-1', name: 'x'.repeat(4000), revision: 1, session_number: 1, state: { scene: 's'.repeat(4000), summary: 'm'.repeat(4000), npcs: Object.fromEntries(Array.from({ length: 40 }, (_, i) => [`n${i}`, 'z'.repeat(100)])) } }, characters: [] } }) });
await globalThis.redgmCampaignInterceptor();
assert.ok(prompts.at(-1)[1].length <= 6000); assert.match(prompts.at(-1)[1], /Snapshot truncated; use campaign_context/);
let backendAbort = null; backend = async () => { throw new Error('offline'); };
await globalThis.redgmCampaignInterceptor('huge', 10, value => { backendAbort = value; }, 'normal');
assert.equal(backendAbort, true); assert.match(notices.at(-1).text, /backend unavailable; generation stopped/);
// The user's newer selection must win over a slower earlier request.
let releaseSelection;
backend = async (_url, options) => {
    const body = JSON.parse(options.body);
    if (body.action === 'get_campaign' && body.arguments.campaign_id === 'slow') return new Promise(resolve => { releaseSelection = resolve; });
    if (body.action === 'get_campaign') return { ok: true, json: async () => ({ result: { id: 'fast', name: 'Fast' } }) };
    return { ok: true, json: async () => ({ result: { campaign: { id: 'fast', name: 'Fast', revision: 1, session_number: 0, state: {} }, characters: [] } }) };
};
const slowSelection = commands.get('red-campaign').callback({}, 'use slow');
assert.match(await commands.get('red-campaign').callback({}, 'use fast'), /Bound campaign/);
releaseSelection({ ok: true, json: async () => ({ result: { id: 'slow', name: 'Slow' } }) });
assert.match(await slowSelection, /selection changed/);
assert.equal(metadata.cyberpunk_red_gm.campaign_id, 'fast');
// Verify __* discovery stripping, nested solo.runtime.runs[id].run unwrapping, updated actions, and auth/PIN headers.
chatId = 'chat-batch4c';
metadata = { cyberpunk_red_gm: { campaign_id: 'camp-4c', chat_key: JSON.stringify(['character:pc.png', 'chat-batch4c']) } };
globalThis.REDGM_API_TOKEN = 'tok-secret';
globalThis.REDGM_ROOM_PIN = '4321';
let lastHeaders = null;
backend = async (_url, options) => {
    lastHeaders = options?.headers || {};
    const body = options?.body ? JSON.parse(options.body) : {};
    if (body.action === 'campaign_context') {
        return {
            ok: true,
            json: async () => ({
                result: {
                    campaign: {
                        id: 'camp-4c',
                        name: 'Watson',
                        revision: 3,
                        session_number: 2,
                        state: {
                            discoveries: {
                                __campaign_meta: '{"district":"Watson"}',
                                __npc_identities: '{"Rogue":{"real_name_hidden":true}}',
                                public_clue: 'Militech crate manifest',
                            },
                        },
                    },
                    characters: [],
                    solo: {
                        revision: 7,
                        runtime: {
                            runs: {
                                'net-7': {
                                    run: { current_floor_id: 'f2', connected: true, actions_remaining: 3 },
                                },
                            },
                        },
                    },
                },
            }),
        };
    }
    return { ok: true, json: async () => ({ result: { ok: true } }) };
};
await globalThis.redgmCampaignInterceptor();
assert.equal(lastHeaders.Authorization, 'Bearer tok-secret');
assert.equal(lastHeaders['X-RedGM-Pin'], '4321');
const prompt4c = prompts.at(-1)[1];
assert.doesNotMatch(prompt4c, /__campaign_meta/);
assert.doesNotMatch(prompt4c, /__npc_identities/);
assert.match(prompt4c, /Militech crate manifest/);
assert.match(prompt4c, /netruns=net-7\(floor=f2,connected=true,actions=3\)/);
assert.ok(tools.get('game_action').parameters.properties.action.enum.includes('update_character_profile'));
assert.ok(tools.get('campaign_action').parameters.properties.action.enum.includes('rename_campaign'));
assert.ok(tools.get('solo_action').parameters.properties.action.enum.includes('advance_time'));
assert.ok(tools.get('solo_action').parameters.properties.action.enum.includes('gear_action'));
await tools.get('solo_action').action({ action: 'advance_time', arguments: { minutes: 10, expected_revision: 7, reason: 'wait', operation_id: 'op-t1' } });
delete globalThis.REDGM_API_TOKEN;
delete globalThis.REDGM_ROOM_PIN;

await extension.exit();
assert.equal(tools.size, 0); assert.equal(listeners.get('chat-changed').size, 0);
assert.equal(await globalThis.redgmCampaignInterceptor(), undefined);
const disabled = await commands.get('red-session').callback({}, '');
assert.equal(notices.at(-1).kind, 'error'); assert.equal(notices.at(-1).text, disabled);
