import type {
  ActiveTurnInfo,
  AllSettingsResponse,
  AuthAccountSummary,
  AuthStatus,
  CampaignContext,
  CampaignRecord,
  CharacterRecord,
  ChatTreeResponse,
  CoopPlayer,
  CorebookJobStatus,
  CorebookStatusResponse,
  CreationAiAssistRequest,
  CreationAiAssistResponse,
  CreationReference,
  HealthStatus,
  LLMSettings,
  LibraryCategory,
  LibraryEntry,
  NetworkInfo,
  PromptSettings,
  PublicSettingsResponse,
  RuntimeServerInfo,
  ServerSettings,
  TurnStreamCallbacks,
  WorldClock,
} from "./types";

const STORAGE_CLIENT_ID = "redgm:clientId";
const STORAGE_PLAYER_NAME = "redgm:playerName";
const STORAGE_ROOM_PIN = "redgm:roomPin";
const STORAGE_AUTH_TOKEN = "redgm:authToken";

function safeStorageGet(key: string): string | null {
  try {
    return typeof window !== "undefined" && typeof window.localStorage?.getItem === "function"
      ? window.localStorage.getItem(key)
      : null;
  } catch {
    return null;
  }
}

function safeStorageSet(key: string, value: string): void {
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.setItem === "function") {
      window.localStorage.setItem(key, value);
    }
  } catch {
    // ignore storage errors
  }
}

let cachedClientId: string | null = null;
export function getClientId(): string {
  if (cachedClientId) return cachedClientId;
  const existing = safeStorageGet(STORAGE_CLIENT_ID);
  if (existing) {
    cachedClientId = existing;
    return existing;
  }
  const created =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  cachedClientId = created;
  safeStorageSet(STORAGE_CLIENT_ID, created);
  return created;
}

export function getStoredPlayerName(): string {
  return safeStorageGet(STORAGE_PLAYER_NAME) || "Host";
}

export function setStoredPlayerName(name: string): void {
  safeStorageSet(STORAGE_PLAYER_NAME, name.trim() || "Player");
}

export function getStoredRoomPin(): string {
  return safeStorageGet(STORAGE_ROOM_PIN) || "";
}

export function setStoredRoomPin(pin: string): void {
  safeStorageSet(STORAGE_ROOM_PIN, pin.trim());
}

export function getStoredAuthToken(): string {
  return safeStorageGet(STORAGE_AUTH_TOKEN) || "";
}

export function setStoredAuthToken(token: string): void {
  const cleaned = token.trim();
  if (!cleaned) {
    try {
      if (typeof window !== "undefined" && typeof window.localStorage?.removeItem === "function") {
        window.localStorage.removeItem(STORAGE_AUTH_TOKEN);
        return;
      }
    } catch {
      // fall through
    }
  }
  safeStorageSet(STORAGE_AUTH_TOKEN, cleaned);
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    "X-RedGM-Client-Id": getClientId(),
    ...extra,
  };
  const token = getStoredAuthToken();
  if (token) headers["X-RedGM-Token"] = token;
  const pin = getStoredRoomPin();
  if (pin) headers["X-RedGM-Pin"] = pin;
  return headers;
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const mergedHeaders = {
    ...authHeaders(),
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  const resp = await fetch(url, { ...init, credentials: init?.credentials ?? "same-origin", headers: mergedHeaders });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(typeof data?.detail === "string" ? data.detail : `Request failed (${resp.status})`);
    const typed = err as Error & { pinRequired?: boolean; authRequired?: boolean; status?: number };
    typed.pinRequired = Boolean(data?.pin_required);
    typed.authRequired = Boolean(data?.auth_required);
    typed.status = resp.status;
    throw err;
  }
  return data as T;
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return jsonFetch<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function makeOpId(prefix: string): string {
  const rand = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID().slice(0, 12)
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return `${prefix}:${rand}`;
}

export async function fetchHealth(): Promise<HealthStatus> {
  return jsonFetch<HealthStatus>("/health");
}

export async function fetchLLMSettings(): Promise<LLMSettings> {
  return jsonFetch<LLMSettings>("/v1/settings/llm");
}

export async function saveLLMSettings(
  updates: Partial<LLMSettings> & { api_key?: string; clear_api_key?: boolean },
): Promise<LLMSettings> {
  return postJson<LLMSettings>("/v1/settings/llm", updates);
}

export async function testLLMSettings(payload: {
  base_url: string;
  api_key?: string;
}): Promise<{ ok: boolean; status_code: number; models: string[]; detail: string }> {
  return postJson("/v1/settings/llm/test", payload);
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  return jsonFetch<AuthStatus>("/v1/auth/status");
}

export async function setupInitialAuth(payload: {
  admin_username: string;
  admin_password: string;
  user_username?: string;
  user_password?: string;
  user_passcode?: string;
  allow_guest_users?: boolean;
  allow_self_signup?: boolean;
}): Promise<{ token: string; role: "admin" | "user"; username: string; expires_in: number }> {
  const res = await postJson<{ token: string; role: "admin" | "user"; username: string; expires_in: number }>(
    "/v1/auth/setup",
    payload,
  );
  if (res.token) setStoredAuthToken(res.token);
  return res;
}

export async function loginAuth(payload: {
  mode: "admin" | "user" | "auto";
  username?: string;
  password: string;
}): Promise<{ token: string; role: "admin" | "user"; username: string; expires_in: number }> {
  const res = await postJson<{ token: string; role: "admin" | "user"; username: string; expires_in: number }>(
    "/v1/auth/login",
    payload,
  );
  if (res.token) setStoredAuthToken(res.token);
  return res;
}

export async function registerAuth(payload: {
  username: string;
  password: string;
}): Promise<{ token: string; role: "admin" | "user"; username: string; expires_in: number }> {
  const res = await postJson<{ token: string; role: "admin" | "user"; username: string; expires_in: number }>(
    "/v1/auth/register",
    payload,
  );
  if (res.token) setStoredAuthToken(res.token);
  return res;
}

export async function logoutAuth(): Promise<void> {
  setStoredAuthToken("");
  await postJson("/v1/auth/logout", {}).catch(() => undefined);
}

export async function fetchAuthAccounts(): Promise<{
  accounts: AuthAccountSummary[];
  allow_guest_users: boolean;
  user_passcode_configured: boolean;
}> {
  return jsonFetch("/v1/auth/accounts");
}

export async function updateAuthAccounts(payload: {
  action?: "upsert_account" | "policy";
  username?: string;
  password?: string;
  role?: "admin" | "user";
  allow_guest_users?: boolean;
  allow_self_signup?: boolean;
  user_passcode?: string;
  clear_user_passcode?: boolean;
  revoke_all_tokens?: boolean;
}): Promise<{
  accounts: AuthAccountSummary[];
  allow_guest_users: boolean;
  allow_self_signup?: boolean;
  user_passcode_configured: boolean;
}> {
  return postJson("/v1/auth/accounts", payload);
}

export async function deleteAuthAccount(username: string): Promise<{
  accounts: AuthAccountSummary[];
  allow_guest_users: boolean;
  user_passcode_configured: boolean;
}> {
  return jsonFetch(`/v1/auth/accounts/${encodeURIComponent(username)}`, { method: "DELETE" });
}

export async function fetchPublicSettings(): Promise<PublicSettingsResponse> {
  return jsonFetch<PublicSettingsResponse>("/v1/settings/public");
}

export async function fetchAllSettings(): Promise<AllSettingsResponse> {
  return jsonFetch<AllSettingsResponse>("/v1/settings/all");
}

export async function savePromptSettings(
  updates: Partial<PromptSettings> & { reset?: boolean },
): Promise<{ prompts: PromptSettings; prompt_defaults: PromptSettings }> {
  return postJson("/v1/settings/prompts", updates);
}

export async function saveServerSettings(
  updates: Partial<ServerSettings>,
): Promise<{ server: ServerSettings } & RuntimeServerInfo> {
  return postJson("/v1/settings/server", updates);
}

export async function restartServer(): Promise<{
  restarting: boolean;
  bind_host: string;
  port: number;
  in_docker: boolean;
}> {
  return postJson("/v1/settings/server/restart", {});
}

export async function fetchCorebookStatus(): Promise<CorebookStatusResponse> {
  return jsonFetch<CorebookStatusResponse>("/v1/corebook/status");
}

export function uploadCorebookPdf(
  file: File,
  options?: { runSemantic?: boolean; onUploadProgress?: (percent: number) => void },
): Promise<{ started: boolean; job: CorebookJobStatus }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const params = new URLSearchParams();
    if (options?.runSemantic) params.set("run_semantic", "true");
    if (file.name) params.set("filename", file.name);
    const qs = params.toString();
    xhr.open("POST", `/v1/corebook/upload${qs ? `?${qs}` : ""}`);
    xhr.withCredentials = true;

    const headers = authHeaders({
      "Content-Type": "application/pdf",
      "X-Filename": encodeURIComponent(file.name || "Corebook.pdf"),
    });
    for (const [k, v] of Object.entries(headers)) {
      xhr.setRequestHeader(k, v);
    }

    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && ev.total > 0) {
        const pct = Math.min(100, Math.round((ev.loaded / ev.total) * 100));
        options?.onUploadProgress?.(pct);
      }
    };

    xhr.onload = () => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as { started: boolean; job: CorebookJobStatus });
      } else {
        const detail = typeof data.detail === "string" ? data.detail : `Upload failed (${xhr.status})`;
        reject(new Error(detail));
      }
    };

    xhr.onerror = () => {
      reject(new Error("Network error while uploading the PDF."));
    };
    xhr.onabort = () => {
      reject(new Error("PDF upload was cancelled."));
    };

    xhr.send(file);
  });
}

export async function gameAction<T = unknown>(
  action: string,
  args: Record<string, unknown> = {},
  campaignId?: string,
): Promise<T> {
  const payload: Record<string, unknown> = { action, arguments: args };
  if (campaignId) payload.campaign_id = campaignId;
  const resp = await postJson<{ action: string; result: T }>("/v1/game", payload);
  return resp.result;
}

export async function listCampaigns(): Promise<CampaignRecord[]> {
  return gameAction<CampaignRecord[]>("list_campaigns", {});
}

export async function createCampaign(name: string): Promise<CampaignRecord> {
  return gameAction<CampaignRecord>("create_campaign", {
    name,
    operation_id: makeOpId("camp-create"),
  });
}

export async function setPrimaryCampaign(campaignId: string): Promise<{ campaign: CampaignRecord }> {
  return postJson<{ campaign: CampaignRecord }>(`/v1/campaigns/${encodeURIComponent(campaignId)}/primary`, {});
}

export async function deleteCampaign(campaignId: string): Promise<{ deleted: boolean; id: string; name: string }> {
  return jsonFetch<{ deleted: boolean; id: string; name: string }>(
    `/v1/campaigns/${encodeURIComponent(campaignId)}`,
    { method: "DELETE" },
  );
}

export async function fetchCampaignContext(campaignId: string): Promise<CampaignContext> {
  return gameAction<CampaignContext>("campaign_context", {}, campaignId);
}

export async function startCampaignSession(
  campaignId: string,
  expectedRevision: number,
  reason = "Start new game session",
): Promise<CampaignRecord> {
  return gameAction<CampaignRecord>(
    "start_session",
    {
      expected_revision: expectedRevision,
      reason,
      operation_id: makeOpId("session"),
    },
    campaignId,
  );
}

export async function updateCampaignState(
  campaignId: string,
  expectedRevision: number,
  changes: Record<string, unknown>,
  reason: string,
): Promise<CampaignRecord> {
  return gameAction<CampaignRecord>(
    "update_campaign",
    {
      expected_revision: expectedRevision,
      changes,
      reason,
      operation_id: makeOpId("camp-upd"),
    },
    campaignId,
  );
}

export async function undoCampaignChange(
  campaignId: string,
  expectedRevision: number,
  reason = "Undo latest narrative change",
): Promise<CampaignRecord> {
  return gameAction<CampaignRecord>(
    "undo_campaign",
    {
      expected_revision: expectedRevision,
      reason,
      operation_id: makeOpId("camp-undo"),
    },
    campaignId,
  );
}

export async function fetchCreationReference(): Promise<CreationReference> {
  return jsonFetch<CreationReference>("/v1/creation/reference");
}

export async function assistCharacterCreation(
  payload: CreationAiAssistRequest,
): Promise<CreationAiAssistResponse> {
  return postJson<CreationAiAssistResponse>("/v1/creation/ai-assist", payload);
}

export interface CampaignBootstrapPayload {
  scene?: string;
  summary?: string;
  npcs?: Record<string, string>;
  objectives?: Record<string, string>;
  discoveries?: Record<string, string>;
  unresolved?: Record<string, string>;
  gm_secrets?: string | Record<string, string>;
  opening_clock?: {
    name: string;
    segments: number;
    note?: string;
  };
}

export async function bootstrapCampaign(
  campaignId: string,
  payload: CampaignBootstrapPayload,
): Promise<{ campaign: CampaignRecord; clocks: WorldClock[] }> {
  return postJson<{ campaign: CampaignRecord; clocks: WorldClock[] }>(
    `/v1/campaigns/${encodeURIComponent(campaignId)}/bootstrap`,
    payload,
  );
}

export async function createAndAttachCharacter(
  campaignId: string,
  campaignRevision: number,
  payload: {
    name: string;
    stats: Record<string, number>;
    skills: Record<string, number>;
    money?: number;
    inventory?: Record<string, number>;
    detail?: Record<string, unknown>;
    humanity?: number;
  },
): Promise<CharacterRecord> {
  const created = await gameAction<CharacterRecord>("create_character", {
    ...payload,
    operation_id: makeOpId("char-create"),
  });
  await gameAction(
    "attach_character",
    {
      character_id: created.id,
      expected_revision: campaignRevision,
      reason: `Attach ${created.name}`,
      operation_id: makeOpId("char-attach"),
    },
    campaignId,
  );
  return created;
}

export async function createRulesPlayerCharacter(
  campaignId: string,
  soloRevision: number,
  payload: {
    name: string;
    role: string;
    method: "streetrat" | "edgerunner" | "complete_package";
    template_rolls?: number[];
    stats?: Record<string, number>;
    skills?: Record<string, number>;
    specializations?: Record<string, string>;
    role_choices?: Record<string, unknown>;
    cultural_language?: string;
    lifepath: Record<string, unknown>;
    backstory?: Record<string, unknown>;
    starting_gear?: Record<string, unknown>;
  },
): Promise<{ character_id: string }> {
  const res = await gameAction<{
    committed: boolean;
    revision: number;
    result: { character_id: string };
  }>(
    "create_player_character",
    {
      ...payload,
      expected_revision: soloRevision,
      reason: `Create ${payload.name} (${payload.role})`,
      operation_id: makeOpId("solo-create"),
    },
    campaignId,
  );
  return { character_id: res.result.character_id };
}

export async function updateCharacterProfile(
  campaignId: string,
  characterId: string,
  expectedRevision: number,
  profile: {
    backstory?: Record<string, unknown>;
    lifepath?: Record<string, unknown>;
    appearance?: string | Record<string, unknown>;
    roles?: Array<Record<string, unknown>>;
  },
  reason = "Update character bio and lifepath",
): Promise<CharacterRecord> {
  return gameAction<CharacterRecord>(
    "update_character_profile",
    {
      character_id: characterId,
      expected_revision: expectedRevision,
      profile,
      reason,
      operation_id: makeOpId("char-prof"),
    },
    campaignId,
  );
}

export async function updateCharacterState(
  campaignId: string,
  characterId: string,
  expectedRevision: number,
  changes: { hp?: number; money?: number; humanity?: number; inventory?: Record<string, number> },
  reason: string,
): Promise<CharacterRecord> {
  return gameAction<CharacterRecord>(
    "update_character",
    {
      character_id: characterId,
      expected_revision: expectedRevision,
      changes,
      reason,
      operation_id: makeOpId("char-upd"),
    },
    campaignId,
  );
}

export async function undoCharacterChange(
  campaignId: string,
  characterId: string,
  expectedRevision: number,
  reason = "Undo latest character change",
): Promise<CharacterRecord> {
  return gameAction<CharacterRecord>(
    "undo",
    {
      character_id: characterId,
      expected_revision: expectedRevision,
      reason,
      operation_id: makeOpId("char-undo"),
    },
    campaignId,
  );
}

export async function fetchCharacterHistory(
  campaignId: string,
  characterId: string,
): Promise<Array<{ sequence: number; revision: number; reason: string; after: CharacterRecord }>> {
  return gameAction(
    "history",
    { character_id: characterId },
    campaignId,
  );
}

export async function rollQuickDice(
  count: number,
  sides: number,
  reason: string,
): Promise<{ dice: number[]; total: number; reason: string }> {
  return gameAction("roll_dice", {
    count,
    sides,
    reason,
    operation_id: makeOpId("roll"),
  });
}

export async function runSkillCheck(
  campaignId: string,
  args: {
    character_id: string;
    expected_revision: number;
    stat: string;
    skill: string | null;
    dv: number;
    modifier?: number;
    luck?: number;
    reason: string;
  },
): Promise<{
  total: number;
  success: boolean;
  die: number;
  explosion: number;
  wound_modifier: number;
  character: CharacterRecord;
}> {
  return gameAction(
    "skill_check",
    {
      ...args,
      operation_id: makeOpId("chk"),
    },
    campaignId,
  );
}

export async function searchLibrary(params: {
  q?: string;
  category?: LibraryCategory | "";
  campaignId?: string;
  includeCorebook?: boolean;
  includeHomebrew?: boolean;
  limit?: number;
}): Promise<LibraryEntry[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.category) qs.set("category", params.category);
  if (params.campaignId) qs.set("campaign_id", params.campaignId);
  if (params.includeCorebook !== undefined) qs.set("include_corebook", String(params.includeCorebook));
  if (params.includeHomebrew !== undefined) qs.set("include_homebrew", String(params.includeHomebrew));
  qs.set("limit", String(params.limit ?? 40));
  const data = await jsonFetch<{ items: LibraryEntry[] }>(`/v1/library?${qs.toString()}`);
  return data.items;
}

export async function fetchLibraryEntry(entryId: string, campaignId?: string): Promise<LibraryEntry> {
  const qs = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : "";
  const data = await jsonFetch<{ item: LibraryEntry }>(`/v1/library/${encodeURIComponent(entryId)}${qs}`);
  return data.item;
}

export async function addHomebrewEntry(payload: {
  campaign_id: string;
  name: string;
  category: LibraryCategory;
  summary: string;
  description: string;
  stats: Record<string, unknown>;
  tags: string[];
}): Promise<LibraryEntry> {
  const data = await postJson<{ item: LibraryEntry }>("/v1/library/homebrew", {
    ...payload,
    created_by: "user",
    operation_id: makeOpId("hb"),
  });
  return data.item;
}

export async function deleteHomebrewEntry(entryId: string, campaignId: string): Promise<void> {
  await jsonFetch(`/v1/library/homebrew/${encodeURIComponent(entryId)}?campaign_id=${encodeURIComponent(campaignId)}`, {
    method: "DELETE",
  });
}

export async function fetchCorebookPage(
  page: number,
  numbering: "printed" | "pdf" = "printed",
): Promise<{ pdf_page: number; printed_page: number | null; header: string; text: string; citation: string }> {
  return jsonFetch(`/v1/pages/${page}?numbering=${numbering}`);
}

export async function fetchSkillsCatalog(): Promise<{
  skills: Record<string, { stat: string; cost: number; specializable: boolean }>;
  rules_indexed: boolean;
}> {
  return jsonFetch("/v1/skills");
}

export async function fetchChatTree(campaignId: string): Promise<ChatTreeResponse> {
  return jsonFetch<ChatTreeResponse>(`/v1/chat/tree?campaign_id=${encodeURIComponent(campaignId)}`);
}

export async function switchChatBranch(campaignId: string, messageId: string): Promise<ChatTreeResponse> {
  return postJson<ChatTreeResponse>("/v1/chat/branch", {
    campaign_id: campaignId,
    message_id: messageId,
  });
}

export async function deleteChatMessage(
  campaignId: string,
  messageId: string,
  scope: "branch" | "single" = "branch",
): Promise<ChatTreeResponse> {
  return postJson<ChatTreeResponse>("/v1/chat/delete", {
    campaign_id: campaignId,
    message_id: messageId,
    scope,
  });
}

export async function updateChatMessage(
  campaignId: string,
  messageId: string,
  content: string,
): Promise<ChatTreeResponse> {
  return postJson<ChatTreeResponse>("/v1/chat/message/update", {
    campaign_id: campaignId,
    message_id: messageId,
    content,
  });
}

export async function exportChatBranch(
  campaignId: string,
  leafId?: string,
): Promise<{ campaign: CampaignRecord; markdown: string }> {
  const qs = new URLSearchParams({ campaign_id: campaignId });
  if (leafId) qs.set("leaf_id", leafId);
  return jsonFetch(`/v1/chat/export?${qs.toString()}`);
}

export async function fetchNetworkInfo(campaignId?: string): Promise<NetworkInfo> {
  const qs = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : "";
  return jsonFetch<NetworkInfo>(`/v1/network/info${qs}`);
}

export async function sendPresence(
  campaignId: string,
  payload: { player_name: string; character_id?: string | null; is_host?: boolean },
): Promise<{ players: CoopPlayer[]; active_turn: ActiveTurnInfo | null }> {
  return postJson(`/v1/campaigns/${encodeURIComponent(campaignId)}/presence`, {
    client_id: getClientId(),
    ...payload,
  });
}

export function subscribeCampaignEvents(
  campaignId: string,
  handlers: {
    onPresence?: (data: { players: CoopPlayer[]; active_turn: ActiveTurnInfo | null }) => void;
    onSync?: (kind: string) => void;
    onTurnLock?: (activeTurn: ActiveTurnInfo | null) => void;
  },
): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const params = new URLSearchParams();
  const pin = getStoredRoomPin();
  const token = getStoredAuthToken();
  if (pin) params.set("pin", pin);
  if (token) params.set("token", token);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const es = new EventSource(`/v1/campaigns/${encodeURIComponent(campaignId)}/events${qs}`);
  es.addEventListener("presence", (ev) => {
    try {
      const parsed = JSON.parse((ev as MessageEvent).data);
      handlers.onPresence?.(parsed);
    } catch {
      // ignore malformed frame
    }
  });
  es.addEventListener("sync", (ev) => {
    try {
      const parsed = JSON.parse((ev as MessageEvent).data);
      handlers.onSync?.(String(parsed?.kind ?? "all"));
    } catch {
      handlers.onSync?.("all");
    }
  });
  es.addEventListener("turn_started", (ev) => {
    try {
      const parsed = JSON.parse((ev as MessageEvent).data);
      handlers.onTurnLock?.(parsed?.active_turn ?? null);
    } catch {
      // ignore
    }
  });
  es.addEventListener("turn_finished", (ev) => {
    try {
      const parsed = JSON.parse((ev as MessageEvent).data);
      handlers.onTurnLock?.(parsed?.active_turn ?? null);
    } catch {
      handlers.onTurnLock?.(null);
    }
  });
  return () => es.close();
}

async function consumeSseStream(
  url: string,
  body: Record<string, unknown>,
  callbacks: TurnStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ client_id: getClientId(), player_name: getStoredPlayerName(), ...body }),
    signal,
  });
  if (!resp.ok) {
    const errJson = await resp.json().catch(() => ({}));
    throw new Error(typeof errJson?.detail === "string" ? errJson.detail : `Turn request failed (${resp.status})`);
  }
  if (!resp.body) {
    throw new Error("Server returned an empty response stream");
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleBlock = (block: string) => {
    let eventName = "";
    const dataLines: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    if (!eventName || dataLines.length === 0) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    switch (eventName) {
      case "rule_citation":
        callbacks.onCitation?.(
          (parsed.entries as LibraryEntry[]) ?? [],
          (parsed.dice_pool as { d10: number[]; d6: number[] }) ?? { d10: [], d6: [] },
        );
        break;
      case "dice_roll":
        callbacks.onDiceRoll?.(parsed as unknown as Parameters<NonNullable<TurnStreamCallbacks["onDiceRoll"]>>[0]);
        break;
      case "state_patch":
        callbacks.onStatePatch?.(parsed as unknown as Parameters<NonNullable<TurnStreamCallbacks["onStatePatch"]>>[0]);
        break;
      case "library_added":
        callbacks.onLibraryAdded?.(parsed as unknown as LibraryEntry);
        break;
      case "warning":
        callbacks.onWarning?.(String(parsed.message ?? ""));
        break;
      case "text_delta":
        callbacks.onTextDelta?.(String(parsed.delta ?? ""));
        break;
      case "turn_done":
        callbacks.onDone?.(parsed as unknown as Parameters<NonNullable<TurnStreamCallbacks["onDone"]>>[0]);
        break;
      case "error":
        callbacks.onError?.(String(parsed.detail ?? "Unknown turn error"));
        break;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx = buffer.indexOf("\n\n");
    while (idx !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (block.trim()) handleBlock(block);
      idx = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) {
    handleBlock(buffer);
  }
}

export async function compressCampaignMemory(params: {
  campaign_id: string;
  leaf_id?: string | null;
}): Promise<{
  campaign: CampaignContext["campaign"];
  library_upserted: LibraryEntry[];
  compressed_messages: number;
  clocks: WorldClock[];
  warnings: string[];
}> {
  return postJson("/v1/chat/compress", params);
}

export async function fetchCampaignClocks(
  campaignId: string,
  leafId?: string | null,
): Promise<{ campaign_id: string; clocks: WorldClock[] }> {
  const qs = leafId ? `?leaf_id=${encodeURIComponent(leafId)}` : "";
  return jsonFetch(`/v1/campaigns/${encodeURIComponent(campaignId)}/clocks${qs}`);
}

export async function mutateCampaignClock(
  campaignId: string,
  payload: {
    action: "upsert" | "tick" | "delete";
    id?: string;
    name?: string;
    filled?: number;
    segments?: number;
    delta?: number;
    category?: string;
    note?: string;
    leaf_id?: string | null;
  },
): Promise<{ campaign_id: string; clocks: WorldClock[] }> {
  return postJson(`/v1/campaigns/${encodeURIComponent(campaignId)}/clocks`, payload);
}

export async function streamChatTurn(
  params: {
    campaign_id: string;
    user_text: string;
    parent_id?: string | null;
    branch_from_root?: boolean;
    overclock?: boolean;
    luck_spend?: number;
    mode?: "two_pass" | "single_pass_tagged";
    speaker_character_id?: string;
    speaker_name?: string;
    is_intro?: boolean;
  },
  callbacks: TurnStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return consumeSseStream("/v1/chat/turn", params, callbacks, signal);
}

export async function regenerateChatTurn(
  params: {
    campaign_id: string;
    message_id: string;
    overclock?: boolean;
    luck_spend?: number;
    mode?: "two_pass" | "single_pass_tagged";
    guidance?: string;
  },
  callbacks: TurnStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return consumeSseStream("/v1/chat/regenerate", params, callbacks, signal);
}
