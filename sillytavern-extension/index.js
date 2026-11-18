/* global SillyTavern, SlashCommand, SlashCommandParser, SlashCommandArgument */
const DEFAULT_BACKEND = 'http://127.0.0.1:8765';
const RULE_TOOLS = ['search_corebook', 'read_corebook_page', 'catalog_corebook', 'read_corebook_section', 'read_corebook_pages', 'find_corebook_phrase'];
const GLOBAL_KEY = '__cyberpunkRedCampaignExtension';
const CAMPAIGN_META = 'cyberpunk_red_gm';
const GAME_ACTIONS = ['create_character', 'list_characters', 'get_character', 'update_character', 'history', 'undo'];
const CAMPAIGN_ACTIONS = ['get_campaign', 'campaign_context', 'update_campaign', 'attach_character', 'start_session', 'campaign_history', 'undo_campaign'];
const state = globalThis[GLOBAL_KEY] || (globalThis[GLOBAL_KEY] = { enabled: false, generation: 0, serial: 0, tools: new Set(), listeners: [], interceptor: null });
state.selection ??= 0;

function backendUrl() { return DEFAULT_BACKEND; }
async function request(path, options = {}) {
    let response;
    try { response = await fetch(`${backendUrl()}${path}`, { headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) }, signal: AbortSignal.timeout(30000), ...options }); }
    catch (error) { throw new Error(`Corebook backend is unreachable (${error.message}). Check that the local API is running and browser CORS/mixed-content rules allow this request.`); }
    if (!response.ok) {
        let detail = '';
        try { const body = await response.json(); detail = body.detail || body.error || ''; if (body.request_id) detail += ` (request ${body.request_id})`; } catch (_) { /* non-JSON response */ }
        throw new Error(`Corebook backend returned HTTP ${response.status}${detail ? `: ${detail}` : ''}`);
    }
    try { const data = await response.json(); if (data.request_id) console.info('[Cyberpunk RED] Backend request completed:', data.request_id); return data; }
    catch (_) { throw new Error('Corebook backend returned invalid JSON.'); }
}
const getJson = (path) => request(path);
const postGame = (action, args, campaignId) => request('/v1/game', { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify({ action, arguments: args, ...(campaignId ? { campaign_id: campaignId } : {}) }) });
function current() {
    const c = SillyTavern.getContext();
    const chat = c.getCurrentChatId?.() ?? null;
    const owner = c.groupId != null ? `group:${c.groupId}` : `character:${c.characters?.[c.characterId]?.avatar ?? c.characterId ?? ''}`;
    return { c, chat, key: JSON.stringify([owner, chat]), metadata: c.chatMetadata };
}
function binding(snapshot = current()) {
    const saved = snapshot.metadata?.[CAMPAIGN_META];
    if (!saved?.campaign_id) return null;
    return saved.chat_key === snapshot.key ? saved.campaign_id : null;
}
async function persistCampaign(snapshot, campaignId, selection) {
    if (!state.enabled || selection !== state.selection || snapshot.chat == null || current().key !== snapshot.key || current().metadata !== snapshot.metadata) return false;
    const previous = snapshot.metadata[CAMPAIGN_META];
    snapshot.metadata[CAMPAIGN_META] = { campaign_id: campaignId, chat_key: snapshot.key };
    try { await snapshot.c.saveMetadata?.(); return state.enabled && selection === state.selection && current().key === snapshot.key && current().metadata === snapshot.metadata; }
    catch (error) { if (selection === state.selection && current().key === snapshot.key && current().metadata === snapshot.metadata && snapshot.metadata[CAMPAIGN_META]?.campaign_id === campaignId) { if (previous === undefined) delete snapshot.metadata[CAMPAIGN_META]; else snapshot.metadata[CAMPAIGN_META] = previous; } throw error; }
}
function clearPrompt() { try { SillyTavern.getContext().setExtensionPrompt('cyberpunk_red_campaign', '', 1, 0, false, 0); } catch (_) { /* context closing */ } }
function promptText(context) {
    const campaign = context.campaign;
    const chars = (context.characters || []).map(ch => `id=${ch.id} name=${ch.name} revision=${ch.revision} hp=${ch.hp}/${ch.max_hp} luck=${ch.luck_remaining}/${ch.stats?.LUCK} money=${ch.money}`);
    const soloRevision = context.solo?.revision;
    const instructions = `You are the GM. Use tools for persistent outcomes. Update memory on meaningful scene/fact changes, not every reply. Backend mechanical stats are authoritative; prose/summaries are not verified mechanics. Lorebooks are narrative aids. Swipes do not automatically undo state. No hidden extra LLM calls. Before uncertain rules, consult catalog_corebook and relevant section/page tools. Never invent mechanics, rolls, or state. A failed tool means stop and report recovery; unsupported rules do not count as success. Hooks are optional and refusal may lead elsewhere; do not escalate threats to force a plot. Narrative is not an authoritative record.${soloRevision != null ? ` Current SOLO revision=${soloRevision}; use this for solo_action expected_revision (not character/campaign revision).` : ''}`;
    const header = `Cyberpunk RED campaign id=${campaign.id} name=${String(campaign.name || '').slice(0, 200)}; session=${campaign.session_number}; revision=${campaign.revision}.`;
    const runtime = context.solo?.runtime;
    const runtimeParts = [];
    if (runtime?.encounter?.active) {
        const queue = Array.isArray(runtime.encounter.queue) ? runtime.encounter.queue : [];
        const turnIdx = Number.isInteger(runtime.encounter.turn_index) ? runtime.encounter.turn_index : 0;
        const actor = queue[turnIdx];
        runtimeParts.push(`encounter=active round=${runtime.encounter.round ?? 1} turn=${turnIdx + 1}/${queue.length}${actor ? ` actor=${actor}` : ''}`);
    }
    const runIds = Object.keys(runtime?.runs || {});
    if (runIds.length > 0) runtimeParts.push(`netruns=${runIds.join(',')}`);
    if ((runtime?.clock_minutes ?? 0) > 0) runtimeParts.push(`clock_minutes=${runtime.clock_minutes}`);
    const runtimeLine = runtimeParts.length ? `Active solo runtime: ${runtimeParts.join('; ')}.\n` : '';
    const marker = '[Snapshot truncated; use campaign_context for complete facts.]';
    const limit = 6000;
    let text = `${instructions}\n${header}\n${runtimeLine}Authoritative mechanical character records:\n`;
    if (text.length + marker.length > limit) text = `${instructions}\nCyberpunk RED campaign id=${campaign.id}; session=${campaign.session_number}; revision=${campaign.revision}.\n${runtimeLine}`;
    for (const line of chars) { if (text.length + line.length + 1 + marker.length > limit) break; text += `${line}\n`; }
    const sections = [['Saved narrative notes (not mechanically verified)', campaign.state?.summary], ['Scene data', campaign.state?.scene], ['Objectives data', JSON.stringify(campaign.state?.objectives || {})], ['Unresolved data', JSON.stringify(campaign.state?.unresolved || {})], ['NPC data', JSON.stringify(campaign.state?.npcs || {})], ['Discoveries data', JSON.stringify(campaign.state?.discoveries || {})]];
    for (const [label, value] of sections) {
        if (!value) continue;
        const available = limit - text.length - marker.length - label.length - 3;
        if (available <= 0) break;
        const body = String(value).slice(0, available);
        text += `\n${label}: ${body}`;
        if (body.length < String(value).length) break;
    }
    const output = `${text}\n${marker}`;
    return output.length <= limit ? output : `${text.slice(0, Math.max(0, limit - marker.length - 1))}\n${marker}`;
}
async function refresh(snapshot = current()) {
    const id = binding(snapshot); const generation = state.generation; const serial = ++state.serial;
    if (!id) { clearPrompt(); return null; }
    try {
        const data = await postGame('campaign_context', { campaign_id: id }, id);
        if (!state.enabled || generation !== state.generation || serial !== state.serial || current().key !== snapshot.key || current().metadata !== snapshot.metadata || binding(snapshot) !== id) return null;
        const result = data.result || data;
        snapshot.c.setExtensionPrompt('cyberpunk_red_campaign', promptText(result), 1, 0, false, 0);
        return result;
    } catch (error) {
        if (state.enabled && generation === state.generation && serial === state.serial && current().key === snapshot.key && current().metadata === snapshot.metadata) snapshot.c.setExtensionPrompt('cyberpunk_red_campaign', `Cyberpunk RED backend unavailable: ${error.message}. No authoritative campaign facts are available.`, 1, 0, false, 0);
        throw error;
    }
}
async function refreshAfterMutation(snapshot, id) {
    if (state.enabled && current().key === snapshot.key && binding(snapshot) === id) {
        try { await refresh(snapshot); } catch (_) { /* action result remains authoritative */ }
    }
}
function registerTool(tool) { const c = SillyTavern.getContext(); c.registerFunctionTool(tool); state.tools.add(tool.name); }
function registerTools() {
    const actionsDescription = 'Run character gameplay actions and save consequences directly without confirmation. Supported arguments: create_character(name, stats with exactly INT REF DEX TECH COOL WILL LUCK MOVE BODY EMP, optional skills={}, operation_id); get_character(character_id); list_characters(); update_character(character_id, expected_revision, changes limited to absolute hp/money/inventory values, reason, operation_id); history(character_id); undo(character_id, expected_revision, reason, operation_id). Use the dedicated roll_dice and skill_check tools for dice and skill checks. Always supply a unique operation_id for creates and mutations. Read current state before mutations. Reuse an id only for an identical retry. Resolve rules from Corebook evidence; never invent mappings, DVs, modifiers or outcomes.';
    registerTool({ name: RULE_TOOLS[0], displayName: 'Search Corebook', description: 'Find candidate local Cyberpunk RED Corebook passages with source hashes and page citations. Read the full relevant page before adjudicating exceptions or tables.', parameters: { type: 'object', properties: { query: { type: 'string' }, limit: { type: 'integer', minimum: 1, maximum: 20 } }, required: ['query'] }, action: async args => { if (typeof args?.query !== 'string' || args.query.trim().length < 2) throw new Error('Search query must contain at least two characters.'); const limit = args.limit ?? 5; if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw new Error('limit must be an integer from 1 to 20.'); return getJson(`/v1/search?q=${encodeURIComponent(args.query.trim())}&limit=${limit}`); } });
    registerTool({ name: RULE_TOOLS[1], displayName: 'Read Corebook Page', description: 'Read source text from a specific printed page of the local Cyberpunk RED Corebook.', parameters: { type: 'object', properties: { printed_page: { type: 'integer', minimum: 1, maximum: 456 } }, required: ['printed_page'] }, action: async args => { if (!Number.isInteger(args?.printed_page) || args.printed_page < 1 || args.printed_page > 456) throw new Error('printed_page must be an integer from 1 to 456.'); return getJson(`/v1/pages/${args.printed_page}`); } });
    registerTool({ name: 'catalog_corebook', displayName: 'Corebook Catalog', description: 'List source sections in the local Corebook catalog.', parameters: { type: 'object', properties: {}, required: [] }, action: () => getJson('/v1/catalog') });
    registerTool({ name: 'read_corebook_section', displayName: 'Read Corebook Section', description: 'Read a bounded range of source passages from a section.', parameters: { type: 'object', properties: { section_id: { type: 'string' }, offset: { type: 'integer', minimum: 0 }, limit: { type: 'integer', minimum: 1, maximum: 12 } }, required: ['section_id', 'offset', 'limit'] }, action: async a => { if (typeof a?.section_id !== 'string' || !a.section_id || !Number.isInteger(a.offset) || a.offset < 0 || !Number.isInteger(a.limit) || a.limit < 1 || a.limit > 12) throw new Error('Invalid section range.'); return getJson(`/v1/sections/${encodeURIComponent(a.section_id)}?offset=${a.offset}&limit=${a.limit}`); } });
    registerTool({ name: 'read_corebook_pages', displayName: 'Read Corebook Pages', description: 'Read 1–12 unique numbered Corebook pages; numbering is printed or pdf.', parameters: { type: 'object', properties: { page_numbers: { type: 'array', items: { type: 'integer', minimum: 1 }, minItems: 1, maxItems: 12, uniqueItems: true }, numbering: { type: 'string', enum: ['printed', 'pdf'] } }, required: ['page_numbers', 'numbering'] }, action: async a => { if (!Array.isArray(a?.page_numbers) || a.page_numbers.length < 1 || a.page_numbers.length > 12 || a.page_numbers.some(n => !Number.isInteger(n) || n < 1) || new Set(a.page_numbers).size !== a.page_numbers.length || !['printed', 'pdf'].includes(a.numbering)) throw new Error('Invalid page batch.'); return getJson(`/v1/page-batch?numbers=${a.page_numbers.join(',')}&numbering=${a.numbering}`); } });
    registerTool({ name: 'find_corebook_phrase', displayName: 'Find Corebook Phrase', description: 'Find exact phrase matches with source citations.', parameters: { type: 'object', properties: { q: { type: 'string' }, limit: { type: 'integer', minimum: 1 } }, required: ['q'] }, action: async a => { if (typeof a?.q !== 'string' || !a.q.trim()) throw new Error('q is required.'); return getJson(`/v1/phrase?q=${encodeURIComponent(a.q)}&limit=${a.limit ?? 10}`); } });
    registerTool({ name: 'game_action', displayName: 'Game Action', description: `${actionsDescription} create_character returns an unassigned character; attach it to the bound campaign with campaign_action.`, parameters: { type: 'object', properties: { action: { type: 'string', enum: GAME_ACTIONS }, arguments: { type: 'object' } }, required: ['action', 'arguments'] }, action: async args => { if (!GAME_ACTIONS.includes(args?.action) || !args.arguments || typeof args.arguments !== 'object' || Array.isArray(args.arguments)) throw new Error('action and an arguments object are required.'); const snapshot = current(); const id = binding(snapshot); if (!id) throw new Error('No campaign bound to this chat. Use /red-campaign create NAME or /red-campaign use ID.'); const result = await postGame(args.action, args.arguments, id); await refreshAfterMutation(snapshot, id); return result; } });
    registerTool({ name: 'campaign_action', displayName: 'Campaign Action', description: 'Read or update the currently bound campaign. get_campaign, campaign_context and campaign_history need no other arguments; attach_character requires character_id, expected_revision, reason, operation_id. update_campaign requires expected_revision, changes, reason, operation_id; scene/summary are strings and npcs/objectives/discoveries/unresolved are string maps. start_session requires expected_revision, reason, operation_id and is only for an explicit user request. undo_campaign requires expected_revision, reason, operation_id and undoes latest narrative change only. The bound campaign_id is inserted automatically.', parameters: { type: 'object', properties: { action: { type: 'string', enum: CAMPAIGN_ACTIONS }, arguments: { type: 'object' } }, required: ['action', 'arguments'] }, action: async args => {
        if (!CAMPAIGN_ACTIONS.includes(args?.action) || !args.arguments || typeof args.arguments !== 'object' || Array.isArray(args.arguments)) throw new Error('action and an arguments object are required.');
        const snapshot = current(); const id = binding(snapshot); if (!id) throw new Error('No campaign bound to this chat. Use /red-campaign create NAME or /red-campaign use ID.');
        if (Object.hasOwn(args.arguments, 'campaign_id') && args.arguments.campaign_id !== id) throw new Error('Cannot target a campaign other than the campaign bound to this chat.');
        const actionArgs = { ...args.arguments, campaign_id: id }; const result = await postGame(args.action, actionArgs, id);
        await refreshAfterMutation(snapshot, id);
        return result;
    } });
    registerTool({ name: 'roll_dice', displayName: 'Roll Dice', description: 'Roll actual backend dice. Failure means no roll or result occurred; do not substitute prose.', parameters: { type: 'object', properties: { count: { type: 'integer', minimum: 1, maximum: 100 }, sides: { type: 'integer', minimum: 2, maximum: 1000 }, reason: { type: 'string' }, operation_id: { type: 'string' } }, required: ['count', 'sides', 'reason', 'operation_id'], additionalProperties: false }, action: async a => { if (!Number.isInteger(a?.count) || a.count < 1 || a.count > 100 || !Number.isInteger(a.sides) || a.sides < 2 || a.sides > 1000 || !a.reason || !a.operation_id) throw new Error('Invalid dice roll arguments. No roll occurred.'); const s = current(), id = binding(s); if (!id) throw new Error('No campaign bound to this chat. No roll occurred.'); const result = await postGame('roll_dice', a, id); await refreshAfterMutation(s, id); return result; } });
    registerTool({ name: 'skill_check', displayName: 'Skill Check', description: 'Perform an authoritative backend check (rolls dice, spends declared LUCK atomically, and applies wound penalties automatically). Failure means no roll, result, or save occurred; do not substitute prose.', parameters: { type: 'object', properties: { character_id: { type: 'string' }, expected_revision: { type: 'integer', minimum: 0 }, stat: { type: 'string', enum: ['INT','REF','DEX','TECH','COOL','WILL','LUCK','MOVE','BODY','EMP'] }, skill: { anyOf: [{ type: 'string' }, { type: 'null' }] }, dv: { type: 'integer', minimum: 0 }, operation_id: { type: 'string' }, reason: { type: 'string' }, modifier: { type: 'integer' }, luck: { type: 'integer', minimum: 0 }, complementary: { type: 'boolean' }, extra_time: { type: 'boolean' } }, required: ['character_id','expected_revision','stat','skill','dv','operation_id','reason'], additionalProperties: false }, action: async a => { if (!a?.character_id || !Number.isInteger(a.expected_revision) || !['INT','REF','DEX','TECH','COOL','WILL','LUCK','MOVE','BODY','EMP'].includes(a.stat) || !(a.skill === null || typeof a.skill === 'string') || !Number.isInteger(a.dv) || a.dv < 0 || !a.operation_id || !a.reason || (a.modifier !== undefined && !Number.isInteger(a.modifier)) || (a.luck !== undefined && (!Number.isInteger(a.luck) || a.luck < 0)) || (a.complementary !== undefined && typeof a.complementary !== 'boolean') || (a.extra_time !== undefined && typeof a.extra_time !== 'boolean')) throw new Error('Invalid skill check arguments. No roll or save occurred.'); const s = current(), id = binding(s); if (!id) throw new Error('No campaign bound to this chat. No roll or save occurred. Use /red-campaign create NAME or /red-campaign use ID.'); const result = await postGame('skill_check', a, id); await refreshAfterMutation(s, id); return result; } });
    registerTool({ name: 'solo_action', displayName: 'Solo Action', description: 'Run solo action: solo_context, solo_history, undo_action, create_player_character, start_encounter, encounter_action, end_encounter, health_action, role_action, create_architecture, start_netrun, net_action. Supply arguments object. Mutations require expected_revision from solo_context result.solo.revision (not character/campaign revision), operation_id and reason. Use IDs belonging to bound backend. Never send campaign_id.', parameters: { type: 'object', properties: { action: { type: 'string', enum: ['solo_context','solo_history','undo_action','create_player_character','start_encounter','encounter_action','end_encounter','health_action','role_action','create_architecture','start_netrun','net_action'] }, arguments: { type: 'object' } }, required: ['action','arguments'], additionalProperties: false }, action: async a => { const allowed = ['solo_context','solo_history','undo_action','create_player_character','start_encounter','encounter_action','end_encounter','health_action','role_action','create_architecture','start_netrun','net_action']; if (!allowed.includes(a?.action) || !a.arguments || typeof a.arguments !== 'object' || Array.isArray(a.arguments)) throw new Error('Invalid solo action.'); if (Object.hasOwn(a.arguments, 'campaign_id')) throw new Error('campaign_id override is not allowed.'); const s = current(), id = binding(s); if (!id) throw new Error('No campaign bound to this chat.'); const result = await postGame(a.action, a.arguments, id); if (a.action !== 'solo_context' && a.action !== 'solo_history') await refreshAfterMutation(s, id); return result; } });
}
function uuid() { return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function announce(text, isError) {
    // A slash command's return value only feeds STscript's pipe (e.g. `| /echo`);
    // nothing displays it on its own. Toast directly, like built-in ST commands do.
    try { (isError ? globalThis.toastr?.error : globalThis.toastr?.info)?.(text, 'Cyberpunk RED', { timeOut: isError ? 10000 : 6000, escapeHtml: true }); } catch (_) { /* toastr unavailable */ }
    return text;
}
function registerSlash() {
    const api = SillyTavern.getContext();
    if (state.slashRegistered || !api.SlashCommandParser || !api.SlashCommand) return;
    const argument = api.SlashCommandArgument?.fromProps({ description: 'Campaign name or identifier', typeList: ['string'], isRequired: false });
    const callback = async (_args, value) => {
        if (!state.enabled) return announce('Cyberpunk RED extension is disabled.', true);
        const parts = String(value || '').trim().split(/\s+/, 2); const command = (parts[0] || 'status').toLowerCase(); const input = String(value || '').trim().slice(command.length).trim();
        const snapshot = current(); const old = snapshot.metadata?.[CAMPAIGN_META];
        const selection = ['create', 'use', 'unbind'].includes(command) ? ++state.selection : state.selection;
        try {
            if (command === 'list') { const data = await postGame('list_campaigns', {}); if (!state.enabled || current().key !== snapshot.key || current().metadata !== snapshot.metadata) return announce('Chat changed; result not applied.', true); return announce(JSON.stringify(data.result ?? data)); }
            if (snapshot.chat == null && ['create', 'use'].includes(command)) return announce('An active chat is required to bind a campaign.', true);
            if (command === 'create') { if (!input) return announce('Usage: /red-campaign create NAME', true); const data = await postGame('create_campaign', { name: input, operation_id: uuid() }); const id = (data.result || data).id; if (!id) throw new Error('Backend did not return a campaign id.'); if (!await persistCampaign(snapshot, id, selection)) return announce('Chat or selection changed; campaign was created but not bound here.', true); await refresh(snapshot); return announce(`Created and bound campaign ${id}.`); }
            if (command === 'use') { if (!input) return announce('Usage: /red-campaign use ID', true); const data = await postGame('get_campaign', { campaign_id: input }, input); if (!state.enabled || selection !== state.selection || current().key !== snapshot.key || current().metadata !== snapshot.metadata) return announce('Chat or selection changed; result not applied.', true); if (!await persistCampaign(snapshot, input, selection)) return announce('Chat or selection changed; campaign was not bound.', true); await refresh(snapshot); return announce(`Bound campaign ${(data.result || data).name || input}.`); }
            if (command === 'unbind') { if (!state.enabled || current().key !== snapshot.key || current().metadata !== snapshot.metadata) return announce('Chat changed; result not applied.', true); const previous = snapshot.metadata[CAMPAIGN_META]; delete snapshot.metadata[CAMPAIGN_META]; try { await snapshot.c.saveMetadata?.(); } catch (error) { if (selection === state.selection && current().key === snapshot.key && current().metadata === snapshot.metadata && !snapshot.metadata[CAMPAIGN_META]) snapshot.metadata[CAMPAIGN_META] = previous; throw error; } if (selection !== state.selection || current().key !== snapshot.key || current().metadata !== snapshot.metadata) return announce('Chat or selection changed; result not applied here.', true); clearPrompt(); return announce('Campaign unbound from this chat.'); }
            if (old?.campaign_id && old.chat_key !== snapshot.key) { clearPrompt(); return announce('Copied campaign binding belongs to a different chat branch. Select or create a campaign explicitly.', true); }
            const id = binding(snapshot); if (!id) return announce(old?.campaign_id ? 'Copied campaign binding belongs to a different chat branch. Select or create a campaign explicitly.' : 'No campaign bound. Use /red-campaign create NAME or /red-campaign use ID.', true);
            if (command === 'refresh') { await refresh(snapshot); return announce('Campaign context refreshed.'); }
            if (command === 'status') { const data = await refresh(snapshot); return announce(data ? JSON.stringify(data.campaign) : 'No campaign context available.'); }
            if (command === 'new-session') { const context = await refresh(snapshot); if (!context) throw new Error('Campaign unavailable.'); const data = await postGame('start_session', { campaign_id: id, expected_revision: context.campaign.revision, reason: 'User explicitly requested a new session', operation_id: uuid() }, id); await refresh(snapshot); return announce(JSON.stringify(data.result ?? data)); }
            if (command === 'history') { const data = await postGame('campaign_history', { campaign_id: id }, id); return announce(JSON.stringify(data.result ?? data)); }
            if (command === 'undo') { const data = await refresh(snapshot); if (!data) throw new Error('Campaign unavailable.'); const result = await postGame('undo_campaign', { campaign_id: id, expected_revision: data.campaign.revision, reason: 'User explicitly requested campaign undo', operation_id: uuid() }, id); await refresh(snapshot); return announce(JSON.stringify(result.result ?? result)); }
            return announce('Usage: /red-campaign list|create NAME|use ID|status|refresh|unbind', true);
        } catch (error) { return announce(`Cyberpunk RED: ${error.message}`, true); }
    };
    api.SlashCommandParser.addCommandObject(api.SlashCommand.fromProps({ name: 'red-campaign', callback, helpString: 'Manage chat-bound RED campaigns.', unnamedArgumentList: [argument].filter(Boolean) }));
    for (const [name, cmd] of [['red-session', 'new-session'], ['red-history', 'history'], ['red-undo', 'undo']]) api.SlashCommandParser.addCommandObject(api.SlashCommand.fromProps({ name, callback: (_args, value) => callback(_args, `${cmd}${value ? ` ${value}` : ''}`), helpString: `RED campaign ${cmd}.`, unnamedArgumentList: [argument].filter(Boolean) }));
    state.slashRegistered = true;
}
function onChatChanged() { state.generation++; state.selection++; clearPrompt(); const snapshot = current(); refresh(snapshot).catch(() => {}); }
function registerInterceptor() {
    const fn = async (_chat, _contextSize, abort, _type) => {
        if (!state.enabled) return;
        const snapshot = current(); const id = binding(snapshot);
        if (!id) {
            clearPrompt();
            try { snapshot.c.setExtensionPrompt('cyberpunk_red_campaign', 'No selected campaign. No rolls/saves authorized. Setup required.', 1, 0, false, 0); } catch (_) { /* context closing */ }
            announce(snapshot.metadata?.[CAMPAIGN_META]?.campaign_id ? 'Copied campaign binding belongs to another chat branch. Select explicitly with /red-campaign use ID, or create one with /red-campaign create NAME.' : 'No campaign selected. Run /red-campaign create NAME or /red-campaign use ID before gameplay.', true);
            if (typeof abort === 'function') abort(true);
            return;
        }
        try { await refresh(snapshot); }
        catch (error) {
            if (!state.enabled || current().key !== snapshot.key || binding(snapshot) !== id) return;
            announce(`Campaign backend unavailable; generation stopped. ${error.message}`, true);
            if (typeof abort === 'function') abort(true);
        }
    };
    globalThis.redgmCampaignInterceptor = fn; state.interceptor = fn;
}
export async function init() {
    if (state.enabled) return;
    state.enabled = true; registerTools(); registerSlash(); registerInterceptor();
    const c = SillyTavern.getContext(); const event = c.eventTypes?.CHAT_CHANGED;
    if (event && c.eventSource?.on) { c.eventSource.on(event, onChatChanged); state.listeners.push([c.eventSource, event, onChatChanged]); }
    onChatChanged();
}
export async function exit() {
    state.enabled = false; state.generation++; clearPrompt();
    for (const name of state.tools) { try { SillyTavern.getContext().unregisterFunctionTool(name); } catch (_) { /* context closing */ } }
    state.tools.clear(); for (const [source, event, fn] of state.listeners) source.removeListener?.(event, fn); state.listeners = [];
    if (state.interceptor) globalThis.redgmCampaignInterceptor = async () => {};
    state.interceptor = null;
}
