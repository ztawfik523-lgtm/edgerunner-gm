export type StatName =
  | "INT"
  | "REF"
  | "DEX"
  | "TECH"
  | "COOL"
  | "WILL"
  | "LUCK"
  | "MOVE"
  | "BODY"
  | "EMP";

export const STAT_NAMES: StatName[] = [
  "INT",
  "REF",
  "DEX",
  "TECH",
  "COOL",
  "WILL",
  "LUCK",
  "MOVE",
  "BODY",
  "EMP",
];

export type LibraryCategory =
  | "skill"
  | "weapon"
  | "armor"
  | "cyberware"
  | "program"
  | "hardware"
  | "gear"
  | "fashion"
  | "role"
  | "rule"
  | "npc"
  | "faction"
  | "location"
  | "vehicle"
  | "drug"
  | "ammo"
  | "attachment"
  | "housing"
  | "service"
  | "streetslang"
  | "mook"
  | "encounter"
  | "screamsheet";

export const LIBRARY_CATEGORIES: LibraryCategory[] = [
  "skill",
  "weapon",
  "armor",
  "cyberware",
  "program",
  "hardware",
  "gear",
  "fashion",
  "role",
  "rule",
  "npc",
  "faction",
  "location",
  "vehicle",
  "drug",
  "ammo",
  "attachment",
  "housing",
  "service",
  "streetslang",
  "mook",
  "encounter",
  "screamsheet",
];

export interface HealthStatus {
  status: string;
  rules_indexed: boolean;
  lan_enabled?: boolean;
  pin_required?: boolean;
  auth_enabled?: boolean;
  db_path?: string;
  indexed_pages?: number;
  detail?: string;
}

export interface CoopPlayer {
  client_id: string;
  player_name: string;
  character_id?: string | null;
  is_host?: boolean;
}

export interface ActiveTurnInfo {
  client_id: string;
  player_name: string;
  started_at?: number;
}

export interface NetworkInfo {
  bind_host: string;
  port: number;
  lan_enabled: boolean;
  pin_required: boolean;
  public_url?: string;
  lan_ips: string[];
  join_urls: string[];
  roster: CoopPlayer[];
  active_turn: ActiveTurnInfo | null;
}

export type AuthRole = "admin" | "user" | "open" | "anon";

export interface AuthStatus {
  auth_enabled: boolean;
  pin_only_mode: boolean;
  authenticated: boolean;
  role: AuthRole;
  username: string | null;
  admin_configured: boolean;
  user_configured: boolean;
  user_passcode_configured: boolean;
  allow_guest_users: boolean;
  allow_self_signup?: boolean;
  can_bootstrap: boolean;
  require_character_to_speak?: boolean;
}

export interface AuthAccountSummary {
  username: string;
  role: "admin" | "user";
  created_at: string;
  source: string;
}

export interface PromptSettings {
  system_persona: string;
  intro_prompt?: string;
  world_rules_prefix: string;
  player_message_template?: string;
  player_dialogue_rules?: string;
  player_narration_rules?: string;
  multiplayer_rules?: string;
  planner_extra: string;
  narrator_extra: string;
  chronicler_extra: string;
  archivist_extra: string;
  creation_assist_persona?: string;
  creation_assist_extra?: string;
  narrator_core_rules?: string;
  planner_core_rules?: string;
  chronicler_core_rules?: string;
  archivist_core_rules?: string;
}

export interface CorebookJobStatus {
  status: "idle" | "running" | "completed" | "error";
  stage: string;
  percent: number;
  current: number;
  total: number;
  filename: string | null;
  message: string;
  warning: string | null;
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
}

export interface CorebookStatusResponse {
  rules_indexed: boolean;
  indexed_pages: number;
  pdf_page_count: number;
  source_filename?: string | null;
  semantic_available: boolean;
  semantic_indexed: boolean;
  db_path?: string;
  job: CorebookJobStatus;
}

export interface ServerSettings {
  bind_host: string;
  port: number;
  allowed_origins: string[];
  public_url: string;
}

export interface RuntimeServerInfo {
  active_host: string;
  active_port: number;
  in_docker: boolean;
  restart_supported: boolean;
  restart_required: boolean;
}

export interface LLMSettings {
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  temperature: number;
  planner_temperature?: number;
  creation_temperature?: number;
  max_tokens: number;
  intro_max_tokens?: number;
  timeout_s: number;
  mode: "two_pass" | "single_pass_tagged";
  top_p?: number;
  presence_penalty?: number;
  frequency_penalty?: number;
  enable_chronicler?: boolean;
  enable_highlights?: boolean;
  allow_ai_homebrew?: boolean;
  auto_compress_prompt?: boolean;
  retry_attempts?: number;
  history_window?: number;
  compression_threshold?: number;
  citation_limit?: number;
  gm_style?: "grounded" | "cinematic" | "grit_dark" | "spy_thriller" | "full_action" | "lethal" | "noir_mystery" | "sandbox";
  narrator_length?: "auto" | "concise" | "standard" | "detailed" | "novel";
  narrator_pacing?: "balanced" | "reactive" | "tactical" | "roleplay" | "slow_burn";
  gm_thinking_mode?: "quality" | "balanced";
  require_character_to_speak?: boolean;
  default_time_step_minutes?: number;
}

export interface AllSettingsResponse {
  llm: LLMSettings;
  prompts: PromptSettings;
  prompt_defaults: PromptSettings;
  server: ServerSettings;
  auth_policy: {
    allow_guest_users: boolean;
    allow_self_signup?: boolean;
    user_passcode_configured: boolean;
    admin_configured: boolean;
    user_configured: boolean;
    accounts: AuthAccountSummary[];
  };
  runtime: RuntimeServerInfo;
}

export interface PublicSettingsResponse {
  role: AuthRole;
  username: string | null;
  auth_enabled: boolean;
  mode: "two_pass" | "single_pass_tagged";
  gm_style: string;
  narrator_length: string;
  narrator_pacing?: string;
  gm_thinking_mode?: "quality" | "balanced";
  require_character_to_speak?: boolean;
  enable_chronicler: boolean;
  enable_highlights?: boolean;
  allow_ai_homebrew?: boolean;
  auto_compress_prompt?: boolean;
  history_window: number;
  compression_threshold: number;
  citation_limit: number;
  default_time_step_minutes: number;
}

export interface CharacterRecord {
  id: string;
  name: string;
  stats: Record<StatName, number>;
  skills: Record<string, number>;
  hp: number;
  max_hp: number;
  humanity: number;
  luck_remaining: number;
  money: number;
  inventory: Record<string, number>;
  revision: number;
  detail?: Record<string, unknown>;
}

export interface CampaignNarrativeState {
  scene: string;
  summary: string;
  npcs: Record<string, string>;
  objectives: Record<string, string>;
  discoveries: Record<string, string>;
  unresolved: Record<string, string>;
}

export interface CampaignRecord {
  id: string;
  name: string;
  revision: number;
  session_number: number;
  is_primary?: boolean;
  character_ids: string[];
  state: CampaignNarrativeState;
}

export interface SoloRuntime {
  encounter: {
    active?: boolean;
    round?: number;
    turn_index?: number;
    queue?: string[];
  } | null;
  runs: Record<
    string,
    {
      connected?: boolean;
      current_floor_id?: string;
      actions_remaining?: number;
      floors?: Array<{ id: string; label?: string; kind?: string; visited?: boolean }>;
    }
  >;
  clock_minutes: number;
}

export interface NpcIdentityProfile {
  handle: string;
  real_name?: string;
  real_name_hidden?: boolean;
}

export interface PartyChannelInfo {
  id: string;
  name: string;
  location: string;
  character_ids: string[];
  handles: string[];
}

export interface PartyGroupingState {
  mode: "together" | "split";
  characters: Array<{ id: string; handle: string; location: string; channel_id: string }>;
  channels: PartyChannelInfo[];
  char_channel_map: Record<string, string>;
  active_channel_id: string;
  active_location: string;
  prompt_summary: string;
}

export interface CampaignMeta {
  district?: string;
  zone_type?: string;
  threat_rating?: string;
  caper_style?: string;
  factions?: string[];
  faction_details?: Array<{ name: string; disposition: string; turf?: string }>;
  screamsheet_hook?: string;
  locations?: Array<{ name: string; district?: string; security?: string; notes?: string }>;
  gig?: {
    title?: string;
    client?: string;
    target?: string;
    payout_eb?: number;
    deadline?: string;
    notes?: string;
  };
}

export interface SessionZeroConfig {
  gm_style?: string;
  narrator_length?: string;
  narrator_pacing?: string;
  lethality_dial?: string;
  economy_dial?: string;
  campaign_scope?: string;
  crew_concept?: string;
  lines_and_veils?: string;
  starting_clock_minutes?: number;
}

export interface CampaignContext {
  campaign: CampaignRecord;
  characters: CharacterRecord[];
  npc_profiles?: Record<string, NpcIdentityProfile & { personality?: string; speech_style?: string }>;
  party_grouping?: PartyGroupingState;
  campaign_meta?: CampaignMeta;
  session_zero?: SessionZeroConfig;
  clocks?: WorldClock[];
  gm_secrets?: Record<string, string>;
  solo: {
    revision: number;
    runtime: SoloRuntime;
    characters: Record<string, CharacterRecord>;
  };
}

export interface LibraryEntry {
  id: string;
  name: string;
  category: LibraryCategory;
  source: "corebook" | "homebrew";
  created_by: string;
  summary: string;
  description: string;
  stats: Record<string, unknown>;
  tags: string[];
  pdf_page?: number | null;
  printed_page?: number | null;
  campaign_id?: string | null;
}

export interface DiceRollResult {
  actor?: string;
  character_id?: string;
  skill?: string | null;
  stat?: string;
  dv?: number;
  modifier?: number;
  luck_spent?: number;
  overclock?: boolean;
  total: number;
  success?: boolean;
  die?: number;
  explosion?: number;
  critical_adjustment?: number;
  wound_modifier?: number;
  reason?: string;
  dice?: number[];
}

export interface WorldClock {
  id: string;
  name: string;
  filled: number;
  segments: number;
  category?: string;
  visibility?: "public" | "secret";
  note?: string;
}

export interface StatePatchEvent {
  target: "character" | "campaign" | "solo";
  character_id?: string;
  campaign_id?: string;
  name?: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  reason: string;
}

export interface GenerationStats {
  elapsed_seconds: number;
  tokens_per_second: number;
  completion_tokens?: number;
  estimated?: boolean;
}

export interface ChatMessageMetadata {
  turn_id?: string;
  mode?: string;
  is_intro?: boolean;
  generation_stats?: GenerationStats;
  overclock?: boolean;
  luck_spend?: number;
  speaker_character_id?: string;
  speaker_name?: string;
  speaker_color?: string;
  speaker_portrait_url?: string;
  gm_deferred?: boolean;
  defer_reason?: string;
  session_started?: number;
  party_transition?: string;
  manual_roll?: boolean;
  edited?: boolean;
  edited_at?: string;
  guidance?: string;
  rolls?: DiceRollResult[];
  patches?: StatePatchEvent[];
  library_added?: string[];
  citations?: string[];
  citation_cards?: LibraryEntry[];
  warnings?: string[];
}

export interface ChatMessageNode {
  id: string;
  campaign_id: string;
  channel_id?: string;
  parent_id: string | null;
  role: "user" | "assistant" | "system";
  content: string;
  raw_content: string;
  model: string;
  campaign_revision: number;
  solo_revision: number;
  metadata: ChatMessageMetadata;
  is_active: boolean;
  created_at: string;
  sibling_index?: number;
  sibling_count?: number;
  sibling_ids?: string[];
}

export interface ChatTreeResponse {
  campaign_id: string;
  channel_id?: string;
  channels?: string[];
  nodes: ChatMessageNode[];
  active_branch: ChatMessageNode[];
  active_leaf_id: string | null;
  current_revisions: {
    campaign_revision: number;
    solo_revision: number;
  };
  revision_mismatch: boolean;
}

export interface TurnStreamCallbacks {
  onCitation?: (entries: LibraryEntry[], dicePool: { d10: number[]; d6: number[] }) => void;
  onDiceRoll?: (roll: DiceRollResult) => void;
  onStatePatch?: (patch: StatePatchEvent) => void;
  onLibraryAdded?: (entry: LibraryEntry) => void;
  onWarning?: (message: string) => void;
  onTextDelta?: (delta: string) => void;
  onDone?: (data: {
    turn_id: string;
    user_message: ChatMessageNode;
    assistant_message: ChatMessageNode | null;
    gm_deferred?: boolean;
    defer_reason?: string;
    generation_stats?: GenerationStats;
    citations: LibraryEntry[];
    rolls: DiceRollResult[];
    state_patches: StatePatchEvent[];
    library_added: LibraryEntry[];
    warnings: string[];
    compression_recommended: boolean;
  }) => void;
  onError?: (detail: string) => void;
}

export interface CreationStatInfo {
  name: string;
  short: string;
  mechanics: string;
  tip: string;
}

export interface CreationMethodInfo {
  id: "streetrat" | "edgerunner" | "complete_package" | "freeform";
  name: string;
  badge: string;
  summary: string;
  rules: string;
}

export interface CreationRoleLifepathField {
  key: string;
  label: string;
  options: string[];
}

export interface CreationRoleWeaponEntry {
  type: "fixed" | "choice";
  item?: string;
  qty?: number;
  label?: string;
  options?: string[];
}

export interface CreationRoleCyberwareItem {
  name: string;
  hl: number;
  install: string;
  notes: string;
}

export interface CreationRoleInfo {
  name: string;
  ability: string;
  ability_summary: string;
  tagline: string;
  best_for: string;
  key_stats: StatName[];
  page: number;
  templates: number[][];
  skills: Record<string, number>;
  starting_weapons: CreationRoleWeaponEntry[];
  starting_armor: string[];
  starting_outfit: string[];
  outfit_choice?: { label: string; options: string[] };
  starting_cyberware: CreationRoleCyberwareItem[];
  cyberware_choice?: { label: string; options: CreationRoleCyberwareItem[] };
  cyberware_choice_2?: { label: string; options: CreationRoleCyberwareItem[] };
  starting_hl: number;
  role_lifepath: CreationRoleLifepathField[];
}

export interface CreationSkillInfo {
  name: string;
  stat: StatName;
  cost: number;
  basic: boolean;
  basic_skill_name?: string;
  specializable: boolean;
  group: string;
  printed_page?: number | null;
  summary: string;
  description: string;
}

export interface CreationShopItem {
  id: string;
  name: string;
  category:
    | "weapon"
    | "armor"
    | "cyberware"
    | "gear"
    | "program"
    | "hardware"
    | "vehicle"
    | "drug"
    | "ammo"
    | "attachment"
    | "service"
    | "housing";
  cost_eb: number;
  summary: string;
  description: string;
  printed_page?: number | null;
  stats: Record<string, unknown>;
}

export interface CreationFashionItem {
  name: string;
  cost_eb: number;
  style: string;
  garment?: string;
  summary: string;
}

export interface CreationHousingTier {
  id: string;
  name: string;
  monthly_eb: number;
  summary: string;
  exec_only?: boolean;
}

export interface CreationLifestyleTier {
  id: string;
  name: string;
  monthly_eb: number;
  summary: string;
}

export interface CampaignPresetCaperStyle {
  id: string;
  name: string;
  printed_page: number;
  summary: string;
  default_beats: {
    hook: string;
    developments: string;
    cliffhanger: string;
    climax: string;
    resolution: string;
  };
}

export interface CampaignPresets {
  districts: Array<{
    name: string;
    threat_rating: string;
    summary: string;
    printed_page: number;
    zone_type?: string;
  }>;
  factions: Array<{
    name: string;
    type: string;
    summary: string;
    printed_page: number;
  }>;
  caper_styles: CampaignPresetCaperStyle[];
  screamsheet_hooks: string[];
  zone_types?: Array<Record<string, unknown>>;
  threat_ratings?: Array<Record<string, unknown>>;
  screamsheets?: Array<Record<string, unknown>>;
}

export interface CreationReference {
  rules_indexed: boolean;
  stat_names: StatName[];
  stats: Record<StatName, CreationStatInfo>;
  methods: CreationMethodInfo[];
  roles: CreationRoleInfo[];
  skills: CreationSkillInfo[];
  cultural_regions: Array<{ region: string; languages: string[] }>;
  lifepath_tables: Record<string, string[]>;
  shop: Record<
    "weapon" | "armor" | "cyberware" | "gear" | "program" | "hardware" | "vehicle" | "drug",
    CreationShopItem[]
  > & {
    ammo?: CreationShopItem[];
    attachment?: CreationShopItem[];
    service?: CreationShopItem[];
    housing?: CreationShopItem[];
  };
  fashion: CreationFashionItem[];
  fashion_matrix?: CreationFashionItem[];
  housing_tiers?: CreationHousingTier[];
  lifestyles?: CreationLifestyleTier[];
  campaign_presets?: CampaignPresets;
  difficult_skills?: string[];
  threat_ratings?: Array<Record<string, unknown>>;
  zone_types?: Array<Record<string, unknown>>;
  screamsheets?: Array<Record<string, unknown>>;
  difficulty_values?: Record<string, number>;
}

export interface CreationFriendEntry {
  name: string;
  relationship: string;
  note: string;
}

export interface CreationEnemyEntry {
  who: string;
  name: string;
  wronged: string;
  cause: string;
  backup: string;
  revenge: string;
}

export interface CreationLoveAffairEntry {
  name: string;
  outcome: string;
}

export interface CreationAiAssistRequest {
  target: "bio" | "contacts" | "campaign";
  mode: "scratch" | "expand";
  field?: string;
  entry_index?: number;
  sub_field?: string;
  guidance?: string;
  character?: {
    name?: string;
    handle?: string;
    real_name?: string;
    real_name_hidden?: boolean;
    gender?: string;
    pronouns?: string;
    age?: string;
    role: string;
    method: string;
    stats: Record<string, number>;
    skills: Record<string, number>;
    lifepath: Record<string, unknown>;
    starting_gear?: Record<string, unknown>;
  };
  campaign?: {
    name?: string;
    district?: string;
    threat_rating?: string;
    caper_style?: string;
    factions?: string[];
    screamsheet_hook?: string;
    lock_choices?: boolean;
    npc_count?: number;
    objective_count?: number;
  };
  current: {
    name?: string;
    concept?: string;
    summary?: string;
    established_history?: string;
    appearance?: string;
    reputation_note?: string;
    trauma_hook?: string;
    addiction_hook?: string;
    debt_hook?: string;
    friends?: CreationFriendEntry[];
    enemies?: CreationEnemyEntry[];
    tragic_love_affairs?: CreationLoveAffairEntry[];
    opening_scene?: string;
    gm_secrets?: string;
    secret_entries?: Array<{ key: string; val: string }>;
    beats?: Record<string, string>;
    npcs?: Record<string, string>;
    objectives?: Record<string, string>;
    discoveries?: Record<string, string>;
    locations?: Array<{ name: string; district?: string; notes?: string }>;
    gig?: { title?: string; client?: string; target?: string; payout_eb?: number; deadline?: string; notes?: string };
    opening_clock?: { name?: string; segments?: number; note?: string };
  };
}

export interface CreationAiAssistResponse {
  target: "bio" | "contacts" | "campaign";
  mode: "scratch" | "expand";
  field?: string;
  entry_index?: number;
  sub_field?: string;
  value?: string;
  name?: string;
  district?: string;
  caper_style?: string;
  factions?: string[];
  concept?: string;
  summary?: string;
  established_history?: string;
  appearance?: string;
  reputation_note?: string;
  trauma_hook?: string;
  addiction_hook?: string;
  debt_hook?: string;
  friends?: CreationFriendEntry[];
  enemies?: CreationEnemyEntry[];
  tragic_love_affairs?: CreationLoveAffairEntry[];
  opening_scene?: string;
  npcs?: Record<string, string>;
  objectives?: Record<string, string>;
  discoveries?: Record<string, string>;
  locations?: Array<{ name: string; district?: string; security?: string; notes?: string }>;
  gig?: {
    title?: string;
    client?: string;
    target?: string;
    payout_eb?: number;
    deadline?: string;
    notes?: string;
  } | null;
  gig_title?: string;
  gig_client?: string;
  gig_target?: string;
  gig_deadline?: string;
  gig_notes?: string;
  clock_name?: string;
  clock_note?: string;
  beat_chart?: {
    hook?: string;
    developments?: string;
    cliffhanger?: string;
    climax?: string;
    resolution?: string;
  };
  gm_secrets?: string;
  opening_clock?: {
    name: string;
    segments: number;
    note: string;
  } | null;
  citations?: Array<{ printed_page?: number | null; pdf_page?: number | null }>;
}
