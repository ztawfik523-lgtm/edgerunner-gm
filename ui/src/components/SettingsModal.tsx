import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  FileText,
  Globe,
  HelpCircle,
  Loader2,
  PlugZap,
  RefreshCw,
  RotateCcw,
  Shield,
  Sliders,
  Trash2,
  Type,
  Upload,
  User,
  UserPlus,
  X,
  XCircle,
} from "lucide-react";
import {
  deleteAuthAccount,
  fetchAllSettings,
  fetchCorebookStatus,
  restartServer,
  saveLLMSettings,
  savePromptSettings,
  saveServerSettings,
  setupInitialAuth,
  testLLMSettings,
  updateAuthAccounts,
  updateMyAccount,
  uploadCorebookPdf,
} from "../api";
import type {
  AuthAccountSummary,
  AuthStatus,
  CorebookStatusResponse,
  LLMSettings,
  PromptSettings,
  RuntimeServerInfo,
  ServerSettings,
} from "../types";

export type SettingsTab =
  | "connection"
  | "corebook"
  | "tuning"
  | "prompts"
  | "network"
  | "access"
  | "display"
  | "account";

export type UiTextScale = "standard" | "large" | "xl";
export type UiFontWeight = "normal" | "semibold" | "bold";

export interface SettingsModalProps {
  open: boolean;
  initialTab?: SettingsTab;
  isAdmin?: boolean;
  settings: LLMSettings | null;
  authStatus?: AuthStatus | null;
  uiScale?: UiTextScale;
  uiWeight?: UiFontWeight;
  onChangeUiScale?: (scale: UiTextScale) => void;
  onChangeUiWeight?: (weight: UiFontWeight) => void;
  onClose: () => void;
  onSaved: (updated: LLMSettings) => void;
  onAuthChanged?: () => Promise<void> | void;
  onCorebookIndexed?: () => Promise<void> | void;
  onNotify?: (msg: string) => void;
}

const PRESETS = [
  { label: "Ollama (Local)", base_url: "http://127.0.0.1:11434/v1", model: "llama3" },
  { label: "LM Studio / llama.cpp", base_url: "http://127.0.0.1:8080/v1", model: "local-model" },
  { label: "KoboldCpp", base_url: "http://127.0.0.1:5001/v1", model: "koboldcpp" },
  { label: "NVIDIA NIM", base_url: "https://integrate.api.nvidia.com/v1", model: "nvidia/nemotron-3-ultra-550b-a55b" },
  { label: "OpenRouter", base_url: "https://openrouter.ai/api/v1", model: "nvidia/llama-3.1-nemotron-70b-instruct" },
  { label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
];

interface CustomProviderPreset {
  label: string;
  base_url: string;
  model: string;
  mode: "two_pass" | "single_pass_tagged";
  timeout_s: number;
  retry_attempts: number;
}

interface TuningPreset {
  label: string;
  builtin?: boolean;
  gm_thinking_mode: "quality" | "balanced";
  gm_style: "grounded" | "cinematic" | "lethal" | "sandbox";
  narrator_length: "concise" | "standard" | "detailed";
  temperature: number;
  max_tokens: number;
  top_p: number;
  presence_penalty: number;
  frequency_penalty: number;
  history_window: number;
  compression_threshold: number;
  citation_limit: number;
  default_time_step_minutes: number;
  enable_chronicler: boolean;
}

const BUILTIN_TUNING_PRESETS: TuningPreset[] = [
  {
    label: "Nemotron 1M Deep Roleplay",
    builtin: true,
    gm_thinking_mode: "quality",
    gm_style: "grounded",
    narrator_length: "detailed",
    temperature: 0.75,
    max_tokens: 8192,
    top_p: 0.95,
    presence_penalty: 0.15,
    frequency_penalty: 0.1,
    history_window: 120,
    compression_threshold: 80,
    citation_limit: 12,
    default_time_step_minutes: 5,
    enable_chronicler: true,
  },
  {
    label: "Balanced & Fast",
    builtin: true,
    gm_thinking_mode: "balanced",
    gm_style: "grounded",
    narrator_length: "standard",
    temperature: 0.7,
    max_tokens: 4096,
    top_p: 0.95,
    presence_penalty: 0.1,
    frequency_penalty: 0.05,
    history_window: 40,
    compression_threshold: 30,
    citation_limit: 6,
    default_time_step_minutes: 5,
    enable_chronicler: true,
  },
  {
    label: "Gritty & Deterministic",
    builtin: true,
    gm_thinking_mode: "quality",
    gm_style: "lethal",
    narrator_length: "concise",
    temperature: 0.45,
    max_tokens: 4096,
    top_p: 0.9,
    presence_penalty: 0,
    frequency_penalty: 0.1,
    history_window: 30,
    compression_threshold: 25,
    citation_limit: 8,
    default_time_step_minutes: 5,
    enable_chronicler: true,
  },
];

const STORAGE_PROVIDER_PRESETS = "redgm:customProviderPresets";
const STORAGE_TUNING_PRESETS = "redgm:customTuningPresets";

function loadStoredList<T>(key: string): T[] {
  try {
    if (typeof window === "undefined" || typeof window.localStorage?.getItem !== "function") return [];
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveStoredList<T>(key: string, items: T[]): void {
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.setItem === "function") {
      window.localStorage.setItem(key, JSON.stringify(items));
    }
  } catch {
    // ignore storage errors
  }
}

function AutoSizeTextarea({
  value,
  onChange,
  minRows = 3,
  ariaLabel,
}: {
  value: string;
  onChange: (val: string) => void;
  minRows?: number;
  ariaLabel?: string;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, minRows * 20)}px`;
  }, [value, minRows]);

  const estimatedRows = Math.max(minRows, value ? value.split("\n").length : minRows);

  return (
    <textarea
      ref={ref}
      aria-label={ariaLabel}
      rows={estimatedRows}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ overflow: "hidden" }}
      className="w-full resize-none rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs leading-relaxed text-slate-100 focus:border-cyan-400 focus:outline-none"
    />
  );
}

const EMPTY_PROMPTS: PromptSettings = {
  system_persona: "",
  intro_prompt: "",
  world_rules_prefix: "",
  player_message_template: "",
  player_dialogue_rules: "",
  player_narration_rules: "",
  multiplayer_rules: "",
  planner_extra: "",
  narrator_extra: "",
  chronicler_extra: "",
  archivist_extra: "",
  creation_assist_persona: "",
  creation_assist_extra: "",
  narrator_core_rules: "",
  planner_core_rules: "",
  chronicler_core_rules: "",
  archivist_core_rules: "",
};

type PromptGroupId = "player" | "narrator" | "planner" | "chronicler" | "archivist" | "creator";

const PROMPT_FIELDS: Array<{
  key: keyof PromptSettings;
  group: PromptGroupId;
  sentTo: string;
  label: string;
  hint: string;
  rows: number;
  singleLine?: boolean;
  advanced?: boolean;
}> = [
  {
    key: "player_message_template",
    group: "player",
    sentTo: "Sent to: Planner, Narrator & Chronicler",
    label: "How Player Dialogue & Messages Are Sent (Format)",
    hint: "Template wrapping each player's turn when a character/speaker is active. Use {speaker} and {message} placeholders (defaults to [{speaker}]: {message}).",
    rows: 1,
    singleLine: true,
  },
  {
    key: "player_dialogue_rules",
    group: "player",
    sentTo: "Sent to: Rules Planner & GM Narrator",
    label: "How Player Dialogue, Actions & OOC Are Interpreted",
    hint: "Tells the AI how to distinguish spoken \"quotes\", physical actions, ((OOC table notes)), and [Rolled ...] tags.",
    rows: 4,
  },
  {
    key: "player_narration_rules",
    group: "player",
    sentTo: "Sent to: GM Narrator",
    label: "How the Player Is Narrated (Perspective & Agency)",
    hint: "Controls 2nd-person vs character-name framing, wound/injury descriptions, and strict anti-puppeting rules so the GM never plays your PC.",
    rows: 5,
  },
  {
    key: "multiplayer_rules",
    group: "player",
    sentTo: "Sent to: Rules Planner & GM Narrator",
    label: "How Multiple Players / Party Turns Are Handled",
    hint: "Defines how the AI handles active speaker attribution, keeps idle party members' agency intact, and tracks separate PC gear/HP/knowledge.",
    rows: 4,
  },
  {
    key: "system_persona",
    group: "narrator",
    sentTo: "Sent to: GM Narrator",
    label: "GM Voice & Persona",
    hint: "Who your Game Master is and the overall narrative voice of Night City.",
    rows: 3,
  },
  {
    key: "intro_prompt",
    group: "narrator",
    sentTo: "Sent to: Introductory Briefing API",
    label: "Introductory Briefing Prompt",
    hint: "System prompt used when generating an introductory Cyberpunk RED rules & roles overview via API.",
    rows: 5,
  },
  {
    key: "world_rules_prefix",
    group: "narrator",
    sentTo: "Sent to: Planner, Narrator & Creator",
    label: "House Rules & Setting Lore",
    hint: "Custom table rules, campaign premise, or setting lore injected across turn passes and character/campaign assist.",
    rows: 3,
  },
  {
    key: "narrator_extra",
    group: "narrator",
    sentTo: "Sent to: GM Narrator",
    label: "Extra Storytelling & Prose Notes",
    hint: "Extra instructions for pacing, NPC speech rhythm, sensory detail, or formatting.",
    rows: 3,
  },
  {
    key: "planner_extra",
    group: "planner",
    sentTo: "Sent to: Rules & Dice Planner (Pass 1)",
    label: "Extra Rules & Dice Referee Notes",
    hint: "Extra instructions for when to ask for skill checks, set difficulty (DV), award IP, or update HP/money/clocks.",
    rows: 3,
  },
  {
    key: "chronicler_extra",
    group: "chronicler",
    sentTo: "Sent to: Post-Turn Chronicler (Pass 3)",
    label: "Extra Session Note-Taker (Chronicler) Notes",
    hint: "Extra instructions for the background note-taker that logs newly seen NPCs, clues, scene moves, and elapsed time.",
    rows: 3,
  },
  {
    key: "archivist_extra",
    group: "archivist",
    sentTo: "Sent to: Archivist (Compress to Library)",
    label: "History Recap & Compression Notes",
    hint: "Extra instructions when compressing long chats into campaign summaries and Library dossiers.",
    rows: 2,
  },
  {
    key: "creation_assist_persona",
    group: "creator",
    sentTo: "Sent to: Character & Campaign Generator",
    label: "Character & Campaign Generator Persona",
    hint: "Role and grounding rules used when clicking AI Generate / Expand in the Character Creator or Campaign Creator.",
    rows: 4,
  },
  {
    key: "creation_assist_extra",
    group: "creator",
    sentTo: "Sent to: Character & Campaign Generator",
    label: "Character & Campaign Generator Extra Notes",
    hint: "Extra creative direction for AI-generated backstories, contacts, and campaign hooks.",
    rows: 2,
  },
  {
    key: "narrator_core_rules",
    group: "narrator",
    sentTo: "Sent to: GM Narrator",
    label: "Built-In World Realism, Fog-of-War & Roll Grounding Rules",
    hint: "Full built-in narrator instructions (Fog-of-War secrets, NPC naming/voice, street economy, and strict dice-ledger grounding).",
    rows: 8,
    advanced: true,
  },
  {
    key: "planner_core_rules",
    group: "planner",
    sentTo: "Sent to: Rules & Dice Planner (Pass 1)",
    label: "Built-In Rules Referee, Pacing & Clock Guidelines",
    hint: "Full built-in instructions for how the planner schedules rolls, IP awards, clocks, time, and NPC memory.",
    rows: 8,
    advanced: true,
  },
  {
    key: "chronicler_core_rules",
    group: "chronicler",
    sentTo: "Sent to: Post-Turn Chronicler (Pass 3)",
    label: "Built-In Post-Turn Note-Taker Guidelines",
    hint: "Full built-in rules controlling what the post-turn Chronicler logs into campaign memory.",
    rows: 5,
    advanced: true,
  },
  {
    key: "archivist_core_rules",
    group: "archivist",
    sentTo: "Sent to: Archivist (Compress to Library)",
    label: "Built-In Story Compression Guidelines",
    hint: "Full built-in rules controlling how Compress to Library summarizes old messages and builds dossiers.",
    rows: 4,
    advanced: true,
  },
];

export function SettingsModal({
  open,
  initialTab,
  isAdmin = true,
  settings,
  authStatus,
  uiScale = "standard",
  uiWeight = "semibold",
  onChangeUiScale,
  onChangeUiWeight,
  onClose,
  onSaved,
  onAuthChanged,
  onCorebookIndexed,
  onNotify,
}: SettingsModalProps) {
  const defaultTab: SettingsTab = isAdmin ? (initialTab ?? "connection") : "display";
  const [activeTab, setActiveTab] = useState<SettingsTab>(defaultTab);
  const [acctCurrentPassword, setAcctCurrentPassword] = useState("");
  const [acctNewUsername, setAcctNewUsername] = useState("");
  const [acctNewPassword, setAcctNewPassword] = useState("");
  const [acctConfirmPassword, setAcctConfirmPassword] = useState("");

  // Connection + Turn & Tuning state
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:11434/v1");
  const [model, setModel] = useState("llama3");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [temperature, setTemperature] = useState(0.75);
  const [plannerTemperature, setPlannerTemperature] = useState(0.1);
  const [creationTemperature, setCreationTemperature] = useState(0.85);
  const [maxTokens, setMaxTokens] = useState(1200);
  const [introMaxTokens, setIntroMaxTokens] = useState(4096);
  const [timeoutS, setTimeoutS] = useState(90);
  const [mode, setMode] = useState<"two_pass" | "single_pass_tagged">("two_pass");
  const [topP, setTopP] = useState(0.95);
  const [presencePenalty, setPresencePenalty] = useState(0);
  const [frequencyPenalty, setFrequencyPenalty] = useState(0);
  const [enableChronicler, setEnableChronicler] = useState(true);
  const [enableHighlights, setEnableHighlights] = useState(true);
  const [allowAiHomebrew, setAllowAiHomebrew] = useState(true);
  const [autoCompressPrompt, setAutoCompressPrompt] = useState(true);
  const [requireCharacterToSpeak, setRequireCharacterToSpeak] = useState(true);
  const [retryAttempts, setRetryAttempts] = useState(1);
  const [historyWindow, setHistoryWindow] = useState(14);
  const [compressionThreshold, setCompressionThreshold] = useState(14);
  const [citationLimit, setCitationLimit] = useState(4);
  const [gmStyle, setGmStyle] = useState<"grounded" | "cinematic" | "lethal" | "sandbox">("grounded");
  const [narratorLength, setNarratorLength] = useState<"concise" | "standard" | "detailed">("standard");
  const [gmThinkingMode, setGmThinkingMode] = useState<"quality" | "balanced">("quality");
  const [defaultTimeStep, setDefaultTimeStep] = useState(0);

  // Corebook PDF upload & indexing state
  const pdfInputRef = useRef<HTMLInputElement | null>(null);
  const [corebookStatus, setCorebookStatus] = useState<CorebookStatusResponse | null>(null);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [runSemanticOnUpload, setRunSemanticOnUpload] = useState(false);
  const [selectedPdfName, setSelectedPdfName] = useState<string | null>(null);
  const [showAdvancedPrompts, setShowAdvancedPrompts] = useState(false);
  const [expandedPrompts, setExpandedPrompts] = useState<Record<string, boolean>>({});
  const bodyScrollRef = useRef<HTMLDivElement | null>(null);

  // Saved Presets
  const [customProviderPresets, setCustomProviderPresets] = useState<CustomProviderPreset[]>(() =>
    loadStoredList<CustomProviderPreset>(STORAGE_PROVIDER_PRESETS),
  );
  const [savingProviderPreset, setSavingProviderPreset] = useState(false);
  const [providerPresetName, setProviderPresetName] = useState("");
  const [customTuningPresets, setCustomTuningPresets] = useState<TuningPreset[]>(() =>
    loadStoredList<TuningPreset>(STORAGE_TUNING_PRESETS),
  );
  const [savingTuningPreset, setSavingTuningPreset] = useState(false);
  const [tuningPresetName, setTuningPresetName] = useState("");

  // Prompts state
  const [prompts, setPrompts] = useState<PromptSettings>(EMPTY_PROMPTS);
  const [promptDefaults, setPromptDefaults] = useState<PromptSettings>(EMPTY_PROMPTS);

  // Network state
  const [serverCfg, setServerCfg] = useState<ServerSettings>({
    bind_host: "127.0.0.1",
    port: 8765,
    allowed_origins: [],
    public_url: "",
  });
  const [originsText, setOriginsText] = useState("");
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeServerInfo | null>(null);

  // Access & Auth state
  const [accounts, setAccounts] = useState<AuthAccountSummary[]>([]);
  const [allowGuests, setAllowGuests] = useState(false);
  const [allowSelfSignup, setAllowSelfSignup] = useState(true);
  const [passcodeConfigured, setPasscodeConfigured] = useState(false);
  const [newUserName, setNewUserName] = useState("");
  const [newUserPass, setNewUserPass] = useState("");
  const [newUserRole, setNewUserRole] = useState<"user" | "admin">("user");
  const [sharedPasscode, setSharedPasscode] = useState("");
  const [bootAdminUser, setBootAdminUser] = useState("");
  const [bootAdminPass, setBootAdminPass] = useState("");
  const [bootPlayerUser, setBootPlayerUser] = useState("");
  const [bootPlayerPass, setBootPlayerPass] = useState("");

  // Shared UI status
  const [loadingAll, setLoadingAll] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    detail: string;
    models: string[];
  } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const applyLlmFields = (s: LLMSettings) => {
    setBaseUrl(s.base_url);
    setModel(s.model);
    setApiKey("");
    setClearKey(false);
    setTemperature(s.temperature);
    setPlannerTemperature(s.planner_temperature ?? 0.1);
    setCreationTemperature(s.creation_temperature ?? 0.85);
    setMaxTokens(s.max_tokens);
    setIntroMaxTokens(s.intro_max_tokens ?? 4096);
    setTimeoutS(s.timeout_s ?? 90);
    setMode(s.mode);
    setTopP(s.top_p ?? 0.95);
    setPresencePenalty(s.presence_penalty ?? 0);
    setFrequencyPenalty(s.frequency_penalty ?? 0);
    setEnableChronicler(s.enable_chronicler ?? true);
    setEnableHighlights(s.enable_highlights ?? true);
    setAllowAiHomebrew(s.allow_ai_homebrew ?? true);
    setAutoCompressPrompt(s.auto_compress_prompt ?? true);
    setRequireCharacterToSpeak(s.require_character_to_speak ?? true);
    setRetryAttempts(s.retry_attempts ?? 1);
    setHistoryWindow(s.history_window ?? 14);
    setCompressionThreshold(s.compression_threshold ?? 14);
    setCitationLimit(s.citation_limit ?? 4);
    setGmStyle(s.gm_style ?? "grounded");
    setNarratorLength(s.narrator_length ?? "standard");
    setGmThinkingMode(s.gm_thinking_mode === "balanced" ? "balanced" : "quality");
    setDefaultTimeStep(s.default_time_step_minutes ?? 0);
  };

  useEffect(() => {
    if (!open) return;
    if (!isAdmin) {
      setActiveTab(initialTab === "account" ? "account" : "display");
    } else if (initialTab) {
      setActiveTab(initialTab);
    }
  }, [open, initialTab, isAdmin]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setNotice(null);
    setTestResult(null);
    setAcctCurrentPassword("");
    setAcctNewUsername(authStatus?.username ?? "");
    setAcctNewPassword("");
    setAcctConfirmPassword("");
    if (!isAdmin) {
      setLoadingAll(false);
      return;
    }
    if (settings) {
      applyLlmFields(settings);
    }
    let cancelled = false;
    setLoadingAll(true);
    fetchAllSettings()
      .then((all) => {
        if (cancelled || !all) return;
        if (all.llm) applyLlmFields(all.llm);
        if (all.prompts) setPrompts({ ...EMPTY_PROMPTS, ...all.prompts });
        if (all.prompt_defaults) setPromptDefaults({ ...EMPTY_PROMPTS, ...all.prompt_defaults });
        if (all.server) {
          setServerCfg(all.server);
          setOriginsText((all.server.allowed_origins || []).join("\n"));
        }
        if (all.runtime) setRuntimeInfo(all.runtime);
        if (all.auth_policy) {
          setAccounts(all.auth_policy.accounts || []);
          setAllowGuests(Boolean(all.auth_policy.allow_guest_users));
          setAllowSelfSignup(all.auth_policy.allow_self_signup ?? true);
          setPasscodeConfigured(Boolean(all.auth_policy.user_passcode_configured));
        }
      })
      .catch(() => {
        // Legacy / mocked environments may only implement /v1/settings/llm
      })
      .finally(() => {
        if (!cancelled) setLoadingAll(false);
      });
    fetchCorebookStatus()
      .then((cb) => {
        if (!cancelled && cb && typeof cb.rules_indexed === "boolean") {
          setCorebookStatus(cb);
        }
      })
      .catch(() => {
        // Ignore in mocked environments without /v1/corebook/status
      });
    return () => {
      cancelled = true;
    };
  }, [open, settings]);

  useEffect(() => {
    if (!open) return;
    if (corebookStatus?.job?.status !== "running") return;
    let cancelled = false;
    const timer = setInterval(() => {
      fetchCorebookStatus()
        .then((cb) => {
          if (cancelled || !cb || typeof cb.rules_indexed !== "boolean") return;
          setCorebookStatus(cb);
          if (cb.job?.status === "completed") {
            const msg = cb.job.warning || cb.job.message || "Corebook indexed and ready to play!";
            setNotice(msg);
            onNotify?.("Corebook loaded and ready!");
            void onCorebookIndexed?.();
          } else if (cb.job?.status === "error") {
            setError(cb.job.error || cb.job.message || "Corebook indexing failed.");
          }
        })
        .catch(() => undefined);
    }, 600);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [open, corebookStatus?.job?.status, onCorebookIndexed, onNotify]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    try {
      const res = await testLLMSettings({
        base_url: baseUrl,
        api_key: apiKey || undefined,
      });
      setTestResult({ ok: res.ok, detail: res.detail, models: res.models });
    } catch (err) {
      setTestResult({
        ok: false,
        detail: err instanceof Error ? err.message : "Test failed",
        models: [],
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveConnectionOrTuning = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload: Record<string, unknown> = {
        base_url: baseUrl,
        model,
        temperature,
        planner_temperature: plannerTemperature,
        creation_temperature: creationTemperature,
        max_tokens: maxTokens,
        intro_max_tokens: introMaxTokens,
        timeout_s: timeoutS,
        mode,
        top_p: topP,
        presence_penalty: presencePenalty,
        frequency_penalty: frequencyPenalty,
        enable_chronicler: enableChronicler,
        enable_highlights: enableHighlights,
        allow_ai_homebrew: allowAiHomebrew,
        auto_compress_prompt: autoCompressPrompt,
        require_character_to_speak: requireCharacterToSpeak,
        retry_attempts: retryAttempts,
        history_window: historyWindow,
        compression_threshold: compressionThreshold,
        citation_limit: citationLimit,
        gm_style: gmStyle,
        narrator_length: narratorLength,
        gm_thinking_mode: gmThinkingMode,
        default_time_step_minutes: defaultTimeStep,
      };
      if (clearKey) {
        payload.clear_api_key = true;
      } else if (apiKey.trim()) {
        payload.api_key = apiKey.trim();
      }
      const updated = await saveLLMSettings(payload);
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleCorebookFileSelected = async (file: File | null | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf") && file.type && file.type !== "application/pdf") {
      setError("Please select a PDF file (.pdf).");
      return;
    }
    setError(null);
    setNotice(null);
    setSelectedPdfName(file.name);
    setUploadingPdf(true);
    setUploadPercent(0);
    try {
      const res = await uploadCorebookPdf(file, {
        runSemantic: runSemanticOnUpload,
        onUploadProgress: (pct) => setUploadPercent(pct),
      });
      setCorebookStatus((prev) => ({
        rules_indexed: prev?.rules_indexed ?? false,
        indexed_pages: prev?.indexed_pages ?? 0,
        pdf_page_count: prev?.pdf_page_count ?? 0,
        source_filename: prev?.source_filename ?? file.name,
        semantic_available: prev?.semantic_available ?? false,
        semantic_indexed: prev?.semantic_indexed ?? false,
        db_path: prev?.db_path,
        job: res.job,
      }));
      const fresh = await fetchCorebookStatus().catch(() => null);
      if (fresh && typeof fresh.rules_indexed === "boolean") {
        setCorebookStatus(fresh);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload Corebook PDF");
    } finally {
      setUploadingPdf(false);
      if (pdfInputRef.current) {
        pdfInputRef.current.value = "";
      }
    }
  };

  const handleSavePrompts = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await savePromptSettings(prompts);
      setPrompts(res.prompts);
      setPromptDefaults(res.prompt_defaults);
      setNotice("Saved custom GM prompt instructions.");
      onNotify?.("Saved custom GM prompt instructions.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save prompts");
    } finally {
      setSaving(false);
    }
  };

  const handleResetPrompts = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await savePromptSettings({ reset: true });
      setPrompts(res.prompts);
      setPromptDefaults(res.prompt_defaults);
      setNotice("Reset prompts back to defaults.");
      onNotify?.("Reset prompts back to defaults.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset prompts");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleChroniclerInline = async () => {
    const next = !enableChronicler;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await saveLLMSettings({ enable_chronicler: next });
      setEnableChronicler(saved.enable_chronicler ?? next);
      onSaved(saved);
      const msg = next
        ? "Enabled Post-Turn Chronicler (auto-tracks NPCs, clues & time)."
        : "Disabled Post-Turn Chronicler (skips Pass 3 after narration).";
      setNotice(msg);
      onNotify?.(msg);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update Chronicler setting");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveNetwork = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const parsedOrigins = originsText
        .split(/[\n,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await saveServerSettings({
        bind_host: serverCfg.bind_host,
        port: serverCfg.port,
        public_url: serverCfg.public_url,
        allowed_origins: parsedOrigins,
      });
      setServerCfg(res.server);
      setOriginsText((res.server.allowed_origins || []).join("\n"));
      setRuntimeInfo({
        active_host: res.active_host,
        active_port: res.active_port,
        in_docker: res.in_docker,
        restart_supported: res.restart_supported,
        restart_required: res.restart_required,
      });
      setNotice(
        res.restart_required
          ? "Network settings saved. Click Restart Server to apply the new bind IP or port."
          : "Network settings saved and active.",
      );
      onNotify?.("Saved network settings.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save network settings");
    } finally {
      setSaving(false);
    }
  };

  const handleRestartServer = async () => {
    setRestarting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await restartServer();
      setNotice(
        `Server is restarting on ${res.bind_host}:${res.port}. Reload this browser tab on that address/port in a moment.`,
      );
      onNotify?.(`Restarting backend on ${res.bind_host}:${res.port}...`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restart server");
    } finally {
      setRestarting(false);
    }
  };

  const handleBootstrapAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanAdmin = bootAdminUser.trim();
    if (!cleanAdmin) {
      setError("Choose an Admin username.");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await setupInitialAuth({
        admin_username: cleanAdmin,
        admin_password: bootAdminPass,
        user_username: bootPlayerPass.trim() ? (bootPlayerUser.trim() || "player") : "",
        user_password: bootPlayerPass.trim(),
        user_passcode: sharedPasscode.trim(),
        allow_guest_users: allowGuests,
      });
      setBootAdminPass("");
      setBootPlayerPass("");
      setSharedPasscode("");
      const all = await fetchAllSettings().catch(() => null);
      if (all?.auth_policy) {
        setAccounts(all.auth_policy.accounts || []);
        setAllowGuests(Boolean(all.auth_policy.allow_guest_users));
        setPasscodeConfigured(Boolean(all.auth_policy.user_passcode_configured));
      }
      await onAuthChanged?.();
      setNotice("Access control enabled and signed in as Admin.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to enable auth");
    } finally {
      setSaving(false);
    }
  };

  const handleUpsertAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await updateAuthAccounts({
        action: "upsert_account",
        username: newUserName.trim(),
        password: newUserPass,
        role: newUserRole,
      });
      setAccounts(res.accounts);
      setNewUserName("");
      setNewUserPass("");
      await onAuthChanged?.();
      setNotice("Saved account credentials.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save account");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateAccessPolicy = async (revokeTokens = false, clearPasscode = false) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload: {
        action: "policy";
        allow_guest_users: boolean;
        allow_self_signup: boolean;
        user_passcode?: string;
        clear_user_passcode?: boolean;
        revoke_all_tokens?: boolean;
      } = {
        action: "policy",
        allow_guest_users: allowGuests,
        allow_self_signup: allowSelfSignup,
        revoke_all_tokens: revokeTokens,
      };
      if (clearPasscode) {
        payload.clear_user_passcode = true;
      } else if (sharedPasscode.trim()) {
        payload.user_passcode = sharedPasscode.trim();
      }
      const res = await updateAuthAccounts(payload);
      const updatedLlm = await saveLLMSettings({ require_character_to_speak: requireCharacterToSpeak }).catch(() => null);
      if (updatedLlm) {
        onSaved(updatedLlm);
      }
      setAccounts(res.accounts);
      setAllowGuests(res.allow_guest_users);
      setAllowSelfSignup(res.allow_self_signup ?? allowSelfSignup);
      setPasscodeConfigured(res.user_passcode_configured);
      setSharedPasscode("");
      await onAuthChanged?.();
      setNotice(
        clearPasscode
          ? "Cleared shared player passcode."
          : revokeTokens
            ? "Updated policy and signed out all existing sessions."
            : "Saved player access policy.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update policy");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleAccountRole = async (username: string, currentRole: "admin" | "user") => {
    const nextRole = currentRole === "admin" ? "user" : "admin";
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await updateAuthAccounts({
        action: "upsert_account",
        username,
        role: nextRole,
      });
      setAccounts(res.accounts);
      await onAuthChanged?.();
      setNotice(`Updated '${username}' to ${nextRole === "admin" ? "Admin" : "User"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update account role");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAccount = async (username: string) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await deleteAuthAccount(username);
      setAccounts(res.accounts);
      await onAuthChanged?.();
      setNotice(`Removed account '${username}'.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove account");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateMyAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    setError(null);
    setNotice(null);
    if (!acctCurrentPassword) {
      setError("Enter your current password to confirm changes.");
      return;
    }
    if (acctNewPassword && acctNewPassword !== acctConfirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    const cleanNewUser = acctNewUsername.trim();
    const curUser = (authStatus?.username ?? "").trim();
    const changingName = Boolean(cleanNewUser && cleanNewUser !== curUser);
    const changingPw = Boolean(acctNewPassword);
    if (!changingName && !changingPw) {
      setError("Enter a new username or a new password to update.");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateMyAccount({
        current_password: acctCurrentPassword,
        ...(changingName ? { new_username: cleanNewUser } : {}),
        ...(changingPw ? { new_password: acctNewPassword } : {}),
      });
      setAcctCurrentPassword("");
      setAcctNewPassword("");
      setAcctConfirmPassword("");
      setAcctNewUsername(updated.username);
      await onAuthChanged?.();
      setNotice(`Account updated (${updated.username}).`);
      onNotify?.(`Updated account settings (${updated.username}).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update account");
    } finally {
      setSaving(false);
    }
  };

  const togglePromptExpanded = (key: string, btnEl: HTMLButtonElement | null) => {
    const scrollEl = bodyScrollRef.current;
    const prevTop = btnEl ? btnEl.getBoundingClientRect().top : null;
    setExpandedPrompts((prev) => ({ ...prev, [key]: !prev[key] }));
    if (scrollEl && btnEl && prevTop !== null) {
      requestAnimationFrame(() => {
        const nextTop = btnEl.getBoundingClientRect().top;
        scrollEl.scrollTop += nextTop - prevTop;
      });
    }
  };

  const tabs: Array<{ id: SettingsTab; label: string; icon: typeof Cpu }> = isAdmin
    ? [
        { id: "connection", label: "Connection", icon: Cpu },
        { id: "corebook", label: "BYOC", icon: BookOpen },
        { id: "tuning", label: "Turn & Tuning", icon: Sliders },
        { id: "prompts", label: "Prompts", icon: FileText },
        { id: "network", label: "Network", icon: Globe },
        { id: "access", label: "Access", icon: Shield },
        { id: "display", label: "Display", icon: Type },
        ...(authStatus?.username ? [{ id: "account" as SettingsTab, label: "Account", icon: User }] : []),
      ]
    : [
        { id: "display", label: "Display", icon: Type },
        { id: "account", label: "Account", icon: User },
      ];

  const isIndexing = corebookStatus?.job?.status === "running";
  const combinedProgress = uploadingPdf
    ? Math.max(1, Math.round(uploadPercent * 0.25))
    : isIndexing
      ? Math.max(25, Math.min(100, 25 + Math.round((corebookStatus?.job?.percent ?? 0) * 0.75)))
      : 0;

  const dialogHeading = isAdmin ? "AI Game Master Connection" : "User Settings";
  const dialogSubtitle = isAdmin
    ? "Connect your AI model, upload your Corebook (BYOC), customize GM behavior & prompts, display readability, and manage players."
    : "Customize HUD text size & readability, or update your account username and password.";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-2 sm:p-4 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-label={dialogHeading}
    >
      <div className="cyber-cut cyber-panel-glow flex max-h-[92dvh] w-full max-w-4xl flex-col border border-cyan-500/30 bg-[#0b1019] shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 sm:px-5 sm:py-3.5">
          <div>
            <h2
              data-text={dialogHeading}
              className="cyber-glitch-title font-cyber-display text-sm font-bold tracking-wider text-slate-100 uppercase"
            >
              {dialogHeading}
            </h2>
            <p className="text-xs text-slate-400">
              {dialogSubtitle}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Navigation tabs */}
        <div className="flex items-center justify-between gap-1 overflow-x-auto border-b border-slate-800 bg-slate-950/70 px-4 py-2">
          <div className="flex items-center gap-1">
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setActiveTab(id);
                  setError(null);
                  setNotice(null);
                }}
                className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-[11px] font-semibold transition ${
                  activeTab === id
                    ? "border border-cyan-500/50 bg-cyan-500/15 text-cyan-200"
                    : "border border-transparent text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
          {loadingAll && (
            <span className="ml-2 inline-flex shrink-0 items-center gap-1 text-[11px] text-slate-400">
              <Loader2 className="h-3 w-3 animate-spin" /> Syncing...
            </span>
          )}
        </div>

        <div
          ref={bodyScrollRef}
          style={{ overflowAnchor: "none" }}
          className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4"
        >
          {notice && (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
              {notice}
            </div>
          )}
          {error && (
            <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </div>
          )}

          {activeTab === "connection" && (
            <form onSubmit={handleSaveConnectionOrTuning} className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span
                    className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-help"
                    title="One-click provider templates. Save your own custom endpoints & models below."
                  >
                    Provider Presets
                    <HelpCircle className="h-3 w-3 text-slate-500" />
                  </span>
                  {!savingProviderPreset ? (
                    <button
                      type="button"
                      onClick={() => {
                        setProviderPresetName("");
                        setSavingProviderPreset(true);
                      }}
                      className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[11px] font-medium text-cyan-200 hover:bg-cyan-500/20"
                    >
                      + Save Current as Preset
                    </button>
                  ) : (
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={providerPresetName}
                        onChange={(e) => setProviderPresetName(e.target.value)}
                        placeholder="Preset name..."
                        className="w-36 rounded border border-cyan-500/60 bg-slate-950 px-2 py-0.5 text-xs text-slate-100 focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          const label = providerPresetName.trim();
                          if (!label) return;
                          const next: CustomProviderPreset[] = [
                            ...customProviderPresets.filter((p) => p.label.toLowerCase() !== label.toLowerCase()),
                            {
                              label,
                              base_url: baseUrl.trim(),
                              model: model.trim(),
                              mode,
                              timeout_s: timeoutS,
                              retry_attempts: retryAttempts,
                            },
                          ];
                          setCustomProviderPresets(next);
                          saveStoredList(STORAGE_PROVIDER_PRESETS, next);
                          setSavingProviderPreset(false);
                          onNotify?.(`Saved provider preset "${label}".`);
                        }}
                        className="rounded bg-cyan-600 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-cyan-500"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setSavingProviderPreset(false)}
                        className="px-1 text-[11px] text-slate-400 hover:text-slate-200"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap gap-1.5">
                  {PRESETS.map((p) => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => {
                        setBaseUrl(p.base_url);
                        setModel(p.model);
                      }}
                      className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-cyan-500/60 hover:text-cyan-300"
                    >
                      {p.label}
                    </button>
                  ))}
                  {customProviderPresets.map((p) => (
                    <div
                      key={`custom-${p.label}`}
                      className="inline-flex items-center rounded border border-cyan-500/40 bg-cyan-950/30 text-xs text-cyan-200"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setBaseUrl(p.base_url);
                          setModel(p.model);
                          setMode(p.mode);
                          setTimeoutS(p.timeout_s);
                          setRetryAttempts(p.retry_attempts);
                        }}
                        className="px-2.5 py-1 hover:text-white"
                      >
                        {p.label}
                      </button>
                      <button
                        type="button"
                        title={`Delete preset ${p.label}`}
                        onClick={() => {
                          const next = customProviderPresets.filter((x) => x.label !== p.label);
                          setCustomProviderPresets(next);
                          saveStoredList(STORAGE_PROVIDER_PRESETS, next);
                        }}
                        className="border-l border-cyan-500/30 px-1.5 py-1 text-cyan-400 hover:text-rose-300"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <label
                  className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help"
                  title="Base URL of any OpenAI-compatible /chat/completions endpoint (local Ollama/LM Studio or cloud NIM/OpenRouter/OpenAI)."
                >
                  OpenAI-Compatible Base URL
                  <HelpCircle className="h-3 w-3 text-slate-500" />
                </label>
                <input
                  type="url"
                  required
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="http://127.0.0.1:11434/v1"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </div>

              <div>
                <label
                  className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help"
                  title="Exact model identifier expected by your provider (e.g. nvidia/nemotron-3-ultra-550b-a55b, gpt-4o-mini, llama3)."
                >
                  Model ID
                  <HelpCircle className="h-3 w-3 text-slate-500" />
                </label>
                <input
                  type="text"
                  required
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="llama3"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label
                    className="inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help"
                    title="Bearer token sent to your LLM provider. Stored privately on the server; leave blank to keep your saved key."
                  >
                    API Key{" "}
                    <HelpCircle className="h-3 w-3 text-slate-500" />
                    {settings?.has_api_key ? (
                      <span className="font-mono text-[11px] text-emerald-400">
                        (saved: {settings.api_key_masked})
                      </span>
                    ) : (
                      <span className="text-[11px] text-slate-500">(optional for local LLMs)</span>
                    )}
                  </label>
                  {settings?.has_api_key && (
                    <label className="flex items-center gap-1 text-xs text-rose-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={clearKey}
                        onChange={(e) => setClearKey(e.target.checked)}
                      />
                      Clear saved key
                    </label>
                  )}
                </div>
                <input
                  type="password"
                  disabled={clearKey}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={settings?.has_api_key ? "Leave blank to keep existing key" : "sk-..."}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 focus:border-cyan-400 focus:outline-none disabled:opacity-40"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="block" title="HTTP request timeout in seconds before aborting a slow or stalled model call (5–600s).">
                  <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                    Timeout (sec) <HelpCircle className="h-3 w-3 text-slate-500" />
                  </span>
                  <input
                    type="number"
                    min={5}
                    max={600}
                    step="any"
                    value={timeoutS}
                    onChange={(e) => setTimeoutS(parseFloat(e.target.value) || 90)}
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                  />
                </label>
                <label className="block" title="How many times to automatically retry transient API rate-limit (429) or overload (503) errors before failing the turn.">
                  <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                    Retry Attempts (0–5) <HelpCircle className="h-3 w-3 text-slate-500" />
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={5}
                    value={retryAttempts}
                    onChange={(e) => setRetryAttempts(parseInt(e.target.value, 10) || 0)}
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                  />
                </label>
              </div>

              {testResult && (
                <div
                  className={`rounded-md border px-3 py-2 text-xs ${
                    testResult.ok
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                      : "border-rose-500/40 bg-rose-500/10 text-rose-300"
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-medium">
                    {testResult.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                    {testResult.detail}
                  </div>
                  {testResult.models.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {testResult.models.slice(0, 12).map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => setModel(m)}
                          className="rounded bg-slate-900 px-2 py-0.5 font-mono text-[11px] text-cyan-300 hover:bg-slate-800"
                        >
                          {m}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="flex items-center justify-between pt-2">
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testing}
                  className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-200 hover:border-cyan-500/60"
                >
                  {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5 text-cyan-400" />}
                  Test Connection
                </button>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-md px-3 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="rounded-md bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                  >
                    {saving ? "Saving..." : "Save Settings"}
                  </button>
                </div>
              </div>
            </form>
          )}

          {activeTab === "corebook" && (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">
                      BYOC — Bring Your Own Corebook (Optional)
                    </h3>
                    <p className="mt-0.5 text-xs text-slate-400">
                      Upload your own Cyberpunk RED Corebook PDF to unlock official Roles, character builders, gear catalogs, and exact page citations. The file stays locally on your server.
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                      corebookStatus?.rules_indexed
                        ? "border border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                        : "border border-amber-500/40 bg-amber-500/15 text-amber-200"
                    }`}
                  >
                    {corebookStatus?.rules_indexed
                      ? `BYOC Ready (${corebookStatus.indexed_pages} pages)`
                      : "No BYOC Yet (Freeform Mode)"}
                  </span>
                </div>

                {corebookStatus?.rules_indexed && (
                  <div className="rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-300 space-y-1">
                    <div>
                      Loaded file:{" "}
                      <span className="font-mono text-cyan-300">
                        {corebookStatus.source_filename || "Cyberpunk RED Corebook.pdf"}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400">
                      {corebookStatus.indexed_pages} pages indexed
                      {corebookStatus.semantic_indexed ? " · topic meaning search active" : ""}
                    </div>
                  </div>
                )}

                <input
                  ref={pdfInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  aria-label="Upload Corebook PDF file"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    void handleCorebookFileSelected(file);
                  }}
                />

                {corebookStatus?.semantic_available && (
                  <label className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs text-slate-200 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={runSemanticOnUpload}
                      disabled={uploadingPdf || isIndexing}
                      onChange={(e) => setRunSemanticOnUpload(e.target.checked)}
                    />
                    <span>Also index rule meanings so search finds rules by topic, not just exact words (optional)</span>
                  </label>
                )}

                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (uploadingPdf || isIndexing) return;
                    const file = e.dataTransfer.files?.[0];
                    void handleCorebookFileSelected(file);
                  }}
                  className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-700 bg-slate-900/40 px-4 py-6 text-center transition hover:border-cyan-500/60"
                >
                  <Upload className="mb-2 h-7 w-7 text-cyan-400" />
                  <div className="text-xs font-medium text-slate-200">
                    {uploadingPdf || isIndexing
                      ? `Processing ${selectedPdfName || corebookStatus?.job?.filename || "Corebook PDF"}...`
                      : "Drag & drop your Cyberpunk RED Corebook PDF here, or click below"}
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {corebookStatus?.rules_indexed
                      ? "Uploading a new PDF safely replaces the existing rulebook database."
                      : "Without a PDF, you can still create Freeform characters and homebrew rules."}
                  </p>
                  <button
                    type="button"
                    disabled={uploadingPdf || isIndexing}
                    onClick={() => pdfInputRef.current?.click()}
                    className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-cyan-600 px-4 py-2 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
                  >
                    {uploadingPdf || isIndexing ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Working...
                      </>
                    ) : (
                      <>
                        <Upload className="h-3.5 w-3.5" />
                        {corebookStatus?.rules_indexed ? "Replace Corebook PDF" : "Upload Corebook PDF"}
                      </>
                    )}
                  </button>
                </div>

                {(uploadingPdf || isIndexing || corebookStatus?.job?.status === "completed") && (
                  <div
                    className="rounded-md border border-slate-800 bg-slate-900/80 p-3 space-y-2"
                    aria-live="polite"
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-slate-200">
                        {uploadingPdf
                          ? `Uploading PDF to server (${uploadPercent}%)...`
                          : corebookStatus?.job?.message || "Building Corebook database..."}
                      </span>
                      <span className="font-mono text-cyan-300">
                        {uploadingPdf || isIndexing ? `${combinedProgress}%` : "100%"}
                      </span>
                    </div>
                    <div
                      role="progressbar"
                      aria-valuenow={uploadingPdf || isIndexing ? combinedProgress : 100}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      className="h-2.5 w-full overflow-hidden rounded-full bg-slate-800"
                    >
                      <div
                        className={`h-full transition-all duration-300 ${
                          corebookStatus?.job?.status === "completed" && !uploadingPdf
                            ? "bg-emerald-500"
                            : "bg-cyan-500"
                        }`}
                        style={{
                          width: `${uploadingPdf || isIndexing ? combinedProgress : 100}%`,
                        }}
                      />
                    </div>
                    {isIndexing && (corebookStatus?.job?.total ?? 0) > 0 && (
                      <div className="text-[11px] text-slate-400">
                        Page {corebookStatus?.job?.current} of {corebookStatus?.job?.total}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-md px-3 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
                >
                  Close
                </button>
              </div>
            </div>
          )}

          {activeTab === "tuning" && (
            <form onSubmit={handleSaveConnectionOrTuning} className="space-y-4">
              {/* Tuning Presets */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span
                    className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-help"
                    title="Apply or save a full Turn & Tuning profile (thinking, tone, sampling, memory & context limits)."
                  >
                    Tuning Presets
                    <HelpCircle className="h-3 w-3 text-slate-500" />
                  </span>
                  {!savingTuningPreset ? (
                    <button
                      type="button"
                      onClick={() => {
                        setTuningPresetName("");
                        setSavingTuningPreset(true);
                      }}
                      className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[11px] font-medium text-cyan-200 hover:bg-cyan-500/20"
                    >
                      + Save Current as Preset
                    </button>
                  ) : (
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        value={tuningPresetName}
                        onChange={(e) => setTuningPresetName(e.target.value)}
                        placeholder="Preset name..."
                        className="w-36 rounded border border-cyan-500/60 bg-slate-950 px-2 py-0.5 text-xs text-slate-100 focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          const label = tuningPresetName.trim();
                          if (!label) return;
                          const next: TuningPreset[] = [
                            ...customTuningPresets.filter((p) => p.label.toLowerCase() !== label.toLowerCase()),
                            {
                              label,
                              gm_thinking_mode: gmThinkingMode,
                              gm_style: gmStyle,
                              narrator_length: narratorLength,
                              temperature,
                              max_tokens: maxTokens,
                              top_p: topP,
                              presence_penalty: presencePenalty,
                              frequency_penalty: frequencyPenalty,
                              history_window: historyWindow,
                              compression_threshold: compressionThreshold,
                              citation_limit: citationLimit,
                              default_time_step_minutes: defaultTimeStep,
                              enable_chronicler: enableChronicler,
                            },
                          ];
                          setCustomTuningPresets(next);
                          saveStoredList(STORAGE_TUNING_PRESETS, next);
                          setSavingTuningPreset(false);
                          onNotify?.(`Saved tuning preset "${label}".`);
                        }}
                        className="rounded bg-cyan-600 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-cyan-500"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setSavingTuningPreset(false)}
                        className="px-1 text-[11px] text-slate-400 hover:text-slate-200"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap gap-1.5">
                  {BUILTIN_TUNING_PRESETS.map((p) => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => {
                        setGmThinkingMode(p.gm_thinking_mode);
                        setGmStyle(p.gm_style);
                        setNarratorLength(p.narrator_length);
                        setTemperature(p.temperature);
                        setMaxTokens(p.max_tokens);
                        setTopP(p.top_p);
                        setPresencePenalty(p.presence_penalty);
                        setFrequencyPenalty(p.frequency_penalty);
                        setHistoryWindow(p.history_window);
                        setCompressionThreshold(p.compression_threshold);
                        setCitationLimit(p.citation_limit);
                        setDefaultTimeStep(p.default_time_step_minutes);
                        setEnableChronicler(p.enable_chronicler);
                      }}
                      className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-300 hover:border-cyan-500/60 hover:text-cyan-300"
                    >
                      {p.label}
                    </button>
                  ))}
                  {customTuningPresets.map((p) => (
                    <div
                      key={`custom-tune-${p.label}`}
                      className="inline-flex items-center rounded border border-cyan-500/40 bg-cyan-950/30 text-xs text-cyan-200"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setGmThinkingMode(p.gm_thinking_mode);
                          setGmStyle(p.gm_style);
                          setNarratorLength(p.narrator_length);
                          setTemperature(p.temperature);
                          setMaxTokens(p.max_tokens);
                          setTopP(p.top_p);
                          setPresencePenalty(p.presence_penalty);
                          setFrequencyPenalty(p.frequency_penalty);
                          setHistoryWindow(p.history_window);
                          setCompressionThreshold(p.compression_threshold);
                          setCitationLimit(p.citation_limit);
                          setDefaultTimeStep(p.default_time_step_minutes);
                          setEnableChronicler(p.enable_chronicler);
                        }}
                        className="px-2.5 py-1 hover:text-white"
                      >
                        {p.label}
                      </button>
                      <button
                        type="button"
                        title={`Delete preset ${p.label}`}
                        onClick={() => {
                          const next = customTuningPresets.filter((x) => x.label !== p.label);
                          setCustomTuningPresets(next);
                          saveStoredList(STORAGE_TUNING_PRESETS, next);
                        }}
                        className="border-l border-cyan-500/30 px-1.5 py-1 text-cyan-400 hover:text-rose-300"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              {/* Unified Turn Architecture & Chronicler */}
              <div className="rounded-lg border border-emerald-500/30 bg-slate-950/70 p-3 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span
                    className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-help"
                    title="Controls how many AI passes run each turn: Pass 1 (Rules Planner), Pass 2 (Streamed GM), and optional Pass 3 (Chronicler note-taker)."
                  >
                    Turn Architecture &amp; Chronicler
                    <HelpCircle className="h-3 w-3 text-slate-500" />
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${
                      enableChronicler
                        ? "bg-emerald-500/20 text-emerald-200"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    Chronicler {enableChronicler ? "ON" : "OFF"}
                  </span>
                </div>

                <div>
                  <label
                    className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help"
                    title="Two-Pass runs a dedicated JSON rules/dice Planner before streaming prose (most accurate). Single-Pass streams prose + <gm_ops> in one call (faster, fewer API calls)."
                  >
                    Turn Architecture
                    <HelpCircle className="h-3 w-3 text-slate-500" />
                  </label>
                  <select
                    value={mode}
                    onChange={(e) =>
                      setMode(e.target.value === "single_pass_tagged" ? "single_pass_tagged" : "two_pass")
                    }
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  >
                    <option value="two_pass">Two-Pass Planner + Streamed GM</option>
                    <option value="single_pass_tagged">Single-Pass Streamed GM</option>
                  </select>
                  <p className="mt-1 text-[11px] text-slate-400">
                    {mode === "two_pass"
                      ? "Best rules/dice accuracy: resolves checks & state before writing prose."
                      : "Faster single request: streams prose and embeds state ops at the end."}
                  </p>
                </div>

                <label
                  className="flex items-start gap-2 rounded-md border border-emerald-500/25 bg-emerald-950/15 p-2.5 text-xs text-slate-200 cursor-pointer"
                  title="Runs a background note-taker after each GM reply to log newly seen NPCs, clues, scene changes, and elapsed time."
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={enableChronicler}
                    onChange={(e) => setEnableChronicler(e.target.checked)}
                  />
                  <span>
                    Post-Turn Chronicler (Auto Note-Taker — Pass 3)
                    <span className="block text-[11px] text-slate-400">
                      Runs after narration to record newly seen NPCs, clues, scene moves, and elapsed time. Turn off to save 1 AI call per turn.
                    </span>
                  </span>
                </label>
              </div>

              {/* Group 1: GM Thinking & Style */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-help"
                    title="Controls reasoning depth, narrative tone, and response length."
                  >
                    GM Thinking &amp; Style
                    <HelpCircle className="h-3 w-3 text-slate-500" />
                  </span>
                  <span className="font-mono text-[11px] text-slate-400">
                    {gmThinkingMode === "balanced" ? "Balanced (~43s)" : "Quality (~73s)"}
                  </span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" role="group" aria-label="GM Thinking Profile">
                  <button
                    type="button"
                    aria-pressed={gmThinkingMode === "quality"}
                    onClick={() => setGmThinkingMode("quality")}
                    className={`rounded-md border px-3 py-2 text-left transition ${
                      gmThinkingMode === "quality"
                        ? "border-cyan-500/70 bg-cyan-500/15 text-cyan-100"
                        : "border-slate-800 bg-slate-900/70 text-slate-300 hover:border-slate-700"
                    }`}
                  >
                    <div className="text-xs font-semibold">GM Quality</div>
                    <div className="mt-0.5 text-[11px] text-slate-400">
                      Thinking ON for all 3 steps — strictest HP/prose sync &amp; zero roll leaks.
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-pressed={gmThinkingMode === "balanced"}
                    onClick={() => setGmThinkingMode("balanced")}
                    className={`rounded-md border px-3 py-2 text-left transition ${
                      gmThinkingMode === "balanced"
                        ? "border-amber-500/70 bg-amber-500/15 text-amber-100"
                        : "border-slate-800 bg-slate-900/70 text-slate-300 hover:border-slate-700"
                    }`}
                  >
                    <div className="text-xs font-semibold">GM Balanced</div>
                    <div className="mt-0.5 text-[11px] text-slate-400">
                      Same writing, less waiting — Thinking ON for rules/dice, OFF for story &amp; memory.
                    </div>
                  </button>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label
                    className="block"
                    title="Sets the GM's pacing, lethality, and dramatic emphasis across Night City scenes."
                  >
                    <span className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help">
                      GM Tone / Style <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <select
                      value={gmStyle}
                      onChange={(e) => setGmStyle(e.target.value as typeof gmStyle)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    >
                      <option value="grounded">Grounded Street-Level (Default)</option>
                      <option value="cinematic">Cinematic Action</option>
                      <option value="lethal">Lethal / High-Stakes</option>
                      <option value="sandbox">Open-Ended Sandbox</option>
                    </select>
                  </label>

                  <label
                    className="block"
                    title="Target paragraph length for each GM reply. Concise is snappy for combat; Detailed gives richer atmosphere."
                  >
                    <span className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help">
                      Narration Length <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <select
                      value={narratorLength}
                      onChange={(e) => setNarratorLength(e.target.value as typeof narratorLength)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    >
                      <option value="concise">Concise (1–2 paragraphs)</option>
                      <option value="standard">Standard (2–4 paragraphs)</option>
                      <option value="detailed">Detailed (3–5 paragraphs)</option>
                    </select>
                  </label>
                </div>
              </div>

              {/* Group 2: Sampling & Output */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 space-y-3">
                <div
                  className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-help"
                  title="Controls how creative vs deterministic the model's wording is, and how long each output can be."
                >
                  Sampling &amp; Output
                  <HelpCircle className="h-3 w-3 text-slate-500" />
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <label
                      className="mb-1 flex items-center justify-between text-xs font-medium text-slate-300 cursor-help"
                      title="Controls creativity in story prose (0.0 = predictable, 1.5 = wild & inventive)."
                    >
                      <span className="inline-flex items-center gap-1">
                        Story Temperature ({temperature.toFixed(2)})
                        <HelpCircle className="h-3 w-3 text-slate-500" />
                      </span>
                      <span className="font-mono text-[10px] text-slate-400">
                        {temperature >= 0.7 ? "Expressive" : temperature <= 0.4 ? "Blunt" : "Balanced"}
                      </span>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={1.5}
                      step={0.05}
                      value={temperature}
                      onChange={(e) => setTemperature(parseFloat(e.target.value))}
                      className="w-full accent-cyan-400"
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 flex items-center justify-between text-xs font-medium text-slate-300 cursor-help"
                      title="Temperature used for rules checks, state updates, and session memory (lower = stricter JSON & rules accuracy; 0.10 recommended)."
                    >
                      <span className="inline-flex items-center gap-1">
                        Rules Temp ({plannerTemperature.toFixed(2)})
                        <HelpCircle className="h-3 w-3 text-slate-500" />
                      </span>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={1.5}
                      step={0.05}
                      value={plannerTemperature}
                      onChange={(e) => setPlannerTemperature(parseFloat(e.target.value))}
                      className="w-full accent-cyan-400"
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 flex items-center justify-between text-xs font-medium text-slate-300 cursor-help"
                      title="Temperature used when generating character backstories, contacts, and campaign pitches."
                    >
                      <span className="inline-flex items-center gap-1">
                        Creator Temp ({creationTemperature.toFixed(2)})
                        <HelpCircle className="h-3 w-3 text-slate-500" />
                      </span>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={1.5}
                      step={0.05}
                      value={creationTemperature}
                      onChange={(e) => setCreationTemperature(parseFloat(e.target.value))}
                      className="w-full accent-cyan-400"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label
                      className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help"
                      title="Maximum output tokens the model can generate per response (does not limit input context). Reasoning models spend thinking tokens out of this budget — 4096–8192 is recommended."
                    >
                      Max Output Tokens
                      <HelpCircle className="h-3 w-3 text-slate-500" />
                    </label>
                    <input
                      type="number"
                      min={128}
                      max={65536}
                      step={1}
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 1200)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-300 cursor-help"
                      title="Dedicated output token limit for the Introductory First Message briefing so the full Cyberpunk RED guide never gets cut off."
                    >
                      Intro Message Token Limit
                      <HelpCircle className="h-3 w-3 text-slate-500" />
                    </label>
                    <input
                      type="number"
                      min={256}
                      max={65536}
                      step={1}
                      value={introMaxTokens}
                      onChange={(e) => setIntroMaxTokens(parseInt(e.target.value, 10) || 4096)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <label className="block" title="Nucleus sampling: limits token choices to the top cumulative probability mass (lower = more focused, 1.0 = full vocabulary).">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      Top-P <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={0.05}
                      max={1}
                      step="any"
                      value={topP}
                      onChange={(e) => setTopP(parseFloat(e.target.value) || 0.95)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                  <label className="block" title="Penalizes tokens that already appeared at least once, encouraging new topics and descriptions (-2 to 2).">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      Presence Penalty <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={-2}
                      max={2}
                      step="any"
                      value={presencePenalty}
                      onChange={(e) => setPresencePenalty(parseFloat(e.target.value) || 0)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                  <label className="block" title="Penalizes tokens proportionally to how often they already appeared, reducing repetitive phrasing (-2 to 2).">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      Frequency Penalty <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={-2}
                      max={2}
                      step="any"
                      value={frequencyPenalty}
                      onChange={(e) => setFrequencyPenalty(parseFloat(e.target.value) || 0)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                </div>
              </div>

              {/* Group 3: Context, Memory & World */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 space-y-3">
                <div
                  className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-help"
                  title="Controls how much chat history, rulebook lore, and automatic world-state tracking runs each turn."
                >
                  Context, Memory &amp; World
                  <HelpCircle className="h-3 w-3 text-slate-500" />
                </div>

                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <label className="block" title="How many recent chat messages are sent to the AI on each turn (Narrator uses up to 500; Planner uses up to 200).">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      History Window (4–500) <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={4}
                      max={500}
                      value={historyWindow}
                      onChange={(e) => setHistoryWindow(parseInt(e.target.value, 10) || 14)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                  <label className="block" title="Turns since last compression before the UI nudges you to compress older turns into Campaign Library dossiers & summary.">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      Compress After (6–1000) <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={6}
                      max={1000}
                      value={compressionThreshold}
                      onChange={(e) => setCompressionThreshold(parseInt(e.target.value, 10) || 14)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                  <label className="block" title="Number of Corebook & Campaign Library entries retrieved and injected into each turn's context (1–30).">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      Rule Citations (1–30) <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={citationLimit}
                      onChange={(e) => setCitationLimit(parseInt(e.target.value, 10) || 4)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                  <label className="block" title="In-game minutes automatically added to the Night City world clock per turn when the Chronicler doesn't specify an elapsed time.">
                    <span className="mb-1 inline-flex items-center gap-1 text-xs text-slate-300 cursor-help">
                      Default Time Step (m) <HelpCircle className="h-3 w-3 text-slate-500" />
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={1440}
                      value={defaultTimeStep}
                      onChange={(e) => setDefaultTimeStep(parseInt(e.target.value, 10) || 0)}
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                    />
                  </label>
                </div>

                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <label
                    className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-200 cursor-pointer"
                    title="Highlights key names, places, and amounts in color inside GM replies."
                  >
                    <input
                      type="checkbox"
                      checked={enableHighlights}
                      onChange={(e) => setEnableHighlights(e.target.checked)}
                    />
                    <span>Highlight key terms in color in GM replies</span>
                  </label>
                  <label
                    className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-200 cursor-pointer"
                    title="Lets the AI GM save new recurring NPCs, locations, and custom items directly into your Campaign Library."
                  >
                    <input
                      type="checkbox"
                      checked={allowAiHomebrew}
                      onChange={(e) => setAllowAiHomebrew(e.target.checked)}
                    />
                    <span>Allow AI to save new Library entries automatically</span>
                  </label>
                  <label
                    className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-200 cursor-pointer sm:col-span-2"
                    title="Shows a gentle reminder to compress old chat history into Library dossiers once a branch gets long."
                  >
                    <input
                      type="checkbox"
                      checked={autoCompressPrompt}
                      onChange={(e) => setAutoCompressPrompt(e.target.checked)}
                    />
                    <span>Show story compression reminders when chat grows</span>
                  </label>
                  <label
                    className="flex items-center gap-2 rounded-md border border-cyan-500/30 bg-cyan-950/15 px-3 py-2 text-xs text-slate-200 cursor-pointer sm:col-span-2"
                    title="When enabled (default), non-admin players must create or attach a character sheet before they can speak in chat. Turn off to allow characterless players/observers to speak freely."
                  >
                    <input
                      type="checkbox"
                      checked={requireCharacterToSpeak}
                      onChange={(e) => setRequireCharacterToSpeak(e.target.checked)}
                    />
                    <span>Require players to have a character before speaking in chat (Default: ON)</span>
                  </label>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-md px-3 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-md bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save Turn Tuning"}
                </button>
              </div>
            </form>
          )}

          {activeTab === "prompts" && (
            <form onSubmit={handleSavePrompts} className="space-y-5">
              {/* Pipeline Overview Banner */}
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-500/25 bg-slate-950/80 p-3 text-[11px] text-slate-300">
                <div>
                  <div className="mb-1.5 font-semibold uppercase tracking-wider text-cyan-300">
                    How AI Prompts Flow Each Turn
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
                    <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-cyan-200">
                      Player Turn Format
                    </span>
                    <span className="text-slate-500">→</span>
                    <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-amber-200">
                      1. Rules &amp; Dice Planner
                    </span>
                    <span className="text-slate-500">→</span>
                    <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-rose-200">
                      2. GM Story Narrator
                    </span>
                    <span className="text-slate-500">→</span>
                    <span
                      className={`rounded border px-2 py-0.5 ${
                        enableChronicler
                          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                          : "border-slate-700 bg-slate-900 text-slate-500 line-through"
                      }`}
                    >
                      3. Post-Turn Chronicler ({enableChronicler ? "ON" : "OFF"})
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      const next: Record<string, boolean> = {};
                      for (const f of PROMPT_FIELDS) next[f.key] = true;
                      setExpandedPrompts(next);
                    }}
                    className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-300 hover:border-cyan-500/50 hover:text-cyan-200"
                  >
                    Expand All
                  </button>
                  <button
                    type="button"
                    onClick={() => setExpandedPrompts({})}
                    className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-300 hover:border-slate-500 hover:text-slate-100"
                  >
                    Collapse All
                  </button>
                </div>
              </div>

              {(
                [
                  {
                    id: "player" as PromptGroupId,
                    title: "Player Dialogue, Narration & Multi-Player Handling",
                    desc: "Controls how player text/speech is formatted when sent to the AI, how the GM narrates your character without puppeting you, and how multiple Party players share the spotlight.",
                    border: "border-cyan-500/30",
                    heading: "text-cyan-300",
                  },
                  {
                    id: "narrator" as PromptGroupId,
                    title: "Pass 2 — GM Story Narrator & World",
                    desc: "Controls the GM's voice, tone, house lore, and storytelling style when writing the scene.",
                    border: "border-rose-500/30",
                    heading: "text-rose-300",
                  },
                  {
                    id: "planner" as PromptGroupId,
                    title: "Pass 1 — Rules & Dice Planner (JSON Referee)",
                    desc: "Runs silently before narration to schedule skill checks, DVs, clocks, XP/IP, and HP/eddie updates.",
                    border: "border-amber-500/30",
                    heading: "text-amber-300",
                  },
                  {
                    id: "chronicler" as PromptGroupId,
                    title: "Pass 3 — Post-Turn Chronicler (Session Note-Taker)",
                    desc: "Runs after narration to log newly seen NPCs, clues, scene moves, and elapsed time into Campaign State.",
                    border: "border-emerald-500/30",
                    heading: "text-emerald-300",
                  },
                  {
                    id: "archivist" as PromptGroupId,
                    title: "History Compression — Campaign Archivist",
                    desc: "Runs only when you click Compress to Library to condense long chat branches into dossiers and a crisp summary.",
                    border: "border-violet-500/30",
                    heading: "text-violet-300",
                  },
                  {
                    id: "creator" as PromptGroupId,
                    title: "Character & Campaign AI Generator",
                    desc: "Runs when you click AI Generate / Expand inside the Character Creator or Campaign Creator.",
                    border: "border-slate-700",
                    heading: "text-slate-200",
                  },
                ]
              ).map((section) => {
                const sectionFields = PROMPT_FIELDS.filter(
                  (f) => !f.advanced && f.group === section.id,
                );
                if (sectionFields.length === 0) return null;
                return (
                  <div
                    key={section.id}
                    className={`rounded-lg border ${section.border} bg-slate-950/65 p-4 space-y-3.5`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-800/80 pb-2.5">
                      <div>
                        <div className={`text-xs font-bold uppercase tracking-wider ${section.heading}`}>
                          {section.title}
                        </div>
                        <p className="mt-0.5 text-[11px] text-slate-400">{section.desc}</p>
                      </div>
                      {section.id === "chronicler" && (
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() => void handleToggleChroniclerInline()}
                          className={`shrink-0 rounded-md border px-2.5 py-1 font-mono text-[11px] font-semibold transition ${
                            enableChronicler
                              ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30"
                              : "border-slate-700 bg-slate-900 text-slate-400 hover:border-emerald-500/40 hover:text-emerald-200"
                          }`}
                        >
                          Chronicler: {enableChronicler ? "ON" : "OFF"}
                        </button>
                      )}
                    </div>

                    <div className="space-y-3">
                      {sectionFields.map((field) => {
                        const val = prompts[field.key] ?? "";
                        const defVal = promptDefaults[field.key] ?? "";
                        const isExpanded = Boolean(expandedPrompts[field.key]);
                        const isModified = val !== defVal;
                        const previewSample =
                          field.key === "player_message_template"
                            ? (val.trim() || "[{speaker}]: {message}")
                                .replace(/\{speaker\}/g, "Vee")
                                .replace(/\{message\}/g, '"How much for the shard?"')
                            : null;
                        return (
                          <div
                            key={field.key}
                            className="rounded-md border border-slate-800 bg-slate-900/55 transition"
                          >
                            <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                              <button
                                type="button"
                                aria-expanded={isExpanded}
                                onClick={(e) => togglePromptExpanded(field.key, e.currentTarget)}
                                className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left"
                              >
                                <div className="min-w-0 space-y-0.5">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-xs font-semibold text-slate-100">
                                      {field.label}
                                    </span>
                                    <span className="rounded bg-slate-800/90 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                                      {field.sentTo}
                                    </span>
                                    {isModified && (
                                      <span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 font-mono text-[9px] text-amber-200">
                                        Modified
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-[11px] text-slate-400">{field.hint}</p>
                                </div>
                                <span className="shrink-0 text-slate-400">
                                  {isExpanded ? (
                                    <ChevronUp className="h-4 w-4" />
                                  ) : (
                                    <ChevronDown className="h-4 w-4" />
                                  )}
                                </span>
                              </button>
                              {isModified && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    setPrompts((prev) => ({
                                      ...prev,
                                      [field.key]: defVal,
                                    }))
                                  }
                                  className="shrink-0 text-[11px] text-cyan-300 hover:underline"
                                >
                                  Revert
                                </button>
                              )}
                            </div>

                            {isExpanded && (
                              <div className="border-t border-slate-800/80 px-3 pb-3 pt-2.5 space-y-2">
                                {field.singleLine ? (
                                  <input
                                    type="text"
                                    aria-label={field.label}
                                    value={val}
                                    onChange={(e) =>
                                      setPrompts((prev) => ({ ...prev, [field.key]: e.target.value }))
                                    }
                                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                                  />
                                ) : (
                                  <AutoSizeTextarea
                                    ariaLabel={field.label}
                                    minRows={field.rows}
                                    value={val}
                                    onChange={(nextVal) =>
                                      setPrompts((prev) => ({ ...prev, [field.key]: nextVal }))
                                    }
                                  />
                                )}
                                {previewSample && (
                                  <div className="rounded border border-slate-800 bg-slate-900/70 px-2.5 py-1 font-mono text-[11px] text-slate-300">
                                    <span className="text-slate-500">Preview sent to AI: </span>
                                    {previewSample}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

              <div className="rounded-lg border border-slate-800 bg-slate-950/60">
                <button
                  type="button"
                  onClick={() => setShowAdvancedPrompts((prev) => !prev)}
                  className="flex w-full items-center justify-between px-3.5 py-2.5 text-left text-xs font-semibold text-slate-200 hover:text-cyan-200"
                >
                  <span>Advanced: Full Built-In System Rules (Narrator, Planner, Chronicler, Archivist)</span>
                  {showAdvancedPrompts ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </button>
                {showAdvancedPrompts && (
                  <div className="space-y-3 border-t border-slate-800 p-3.5">
                    <p className="text-[11px] text-amber-200/80">
                      These are the full default system rules sent to each pass. You can tweak banned NPC names, economy pacing, Fog-of-War rules, or anything else here—and click Revert or Reset All Prompts anytime.
                    </p>
                    {PROMPT_FIELDS.filter((f) => f.advanced).map((field) => {
                      const val = prompts[field.key] ?? "";
                      const defVal = promptDefaults[field.key] ?? "";
                      const isExpanded = Boolean(expandedPrompts[field.key]);
                      const isModified = val !== defVal;
                      return (
                        <div key={field.key} className="rounded-md border border-slate-800 bg-slate-900/55">
                          <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                            <button
                              type="button"
                              aria-expanded={isExpanded}
                              onClick={(e) => togglePromptExpanded(field.key, e.currentTarget)}
                              className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left"
                            >
                              <div className="min-w-0 space-y-0.5">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-xs font-semibold text-slate-200">{field.label}</span>
                                  <span className="rounded bg-slate-800/90 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">
                                    {field.sentTo}
                                  </span>
                                  {isModified && (
                                    <span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 font-mono text-[9px] text-amber-200">
                                      Modified
                                    </span>
                                  )}
                                </div>
                                <p className="text-[11px] text-slate-400">{field.hint}</p>
                              </div>
                              <span className="shrink-0 text-slate-400">
                                {isExpanded ? (
                                  <ChevronUp className="h-4 w-4" />
                                ) : (
                                  <ChevronDown className="h-4 w-4" />
                                )}
                              </span>
                            </button>
                            {isModified && (
                              <button
                                type="button"
                                onClick={() =>
                                  setPrompts((prev) => ({
                                    ...prev,
                                    [field.key]: defVal,
                                  }))
                                }
                                className="shrink-0 text-[11px] text-cyan-300 hover:underline"
                              >
                                Revert
                              </button>
                            )}
                          </div>
                          {isExpanded && (
                            <div className="border-t border-slate-800/80 px-3 pb-3 pt-2.5">
                              <AutoSizeTextarea
                                ariaLabel={field.label}
                                minRows={field.rows}
                                value={val}
                                onChange={(nextVal) =>
                                  setPrompts((prev) => ({ ...prev, [field.key]: nextVal }))
                                }
                              />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between pt-2">
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void handleResetPrompts()}
                  className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300 hover:border-amber-500/60 hover:text-amber-200"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset All Prompts
                </button>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-md px-3 py-2 text-xs text-slate-400 hover:text-slate-200"
                  >
                    Close
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="rounded-md bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                  >
                    {saving ? "Saving..." : "Save Prompts"}
                  </button>
                </div>
              </div>
            </form>
          )}

          {activeTab === "network" && (
            <form onSubmit={handleSaveNetwork} className="space-y-4">
              {runtimeInfo && (
                <div className="rounded-md border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
                  <div>
                    Active listener:{" "}
                    <span className="font-mono text-cyan-300">
                      {runtimeInfo.active_host}:{runtimeInfo.active_port}
                    </span>
                    {runtimeInfo.in_docker && (
                      <span className="ml-2 rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                        Docker
                      </span>
                    )}
                  </div>
                  {runtimeInfo.restart_required && (
                    <div className="mt-1 text-[11px] text-amber-300">
                      Saved IP/Port differs from active listener. Restart server to rebind.
                    </div>
                  )}
                </div>
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300">
                    Bind IP / Interface
                  </label>
                  <input
                    type="text"
                    required
                    value={serverCfg.bind_host}
                    onChange={(e) => setServerCfg((prev) => ({ ...prev, bind_host: e.target.value }))}
                    placeholder="127.0.0.1 or 0.0.0.0"
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                  <div className="mt-1.5 flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => setServerCfg((prev) => ({ ...prev, bind_host: "127.0.0.1" }))}
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:border-cyan-500/60"
                    >
                      127.0.0.1 (Local)
                    </button>
                    <button
                      type="button"
                      onClick={() => setServerCfg((prev) => ({ ...prev, bind_host: "0.0.0.0" }))}
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300 hover:border-cyan-500/60"
                    >
                      0.0.0.0 (LAN / Public)
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-300">Listen Port</label>
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    required
                    value={serverCfg.port}
                    onChange={(e) =>
                      setServerCfg((prev) => ({ ...prev, port: parseInt(e.target.value, 10) || 8765 }))
                    }
                    className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                  />
                </div>
              </div>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-300">
                  Public URL (for reverse-proxied Party join links, optional)
                </span>
                <input
                  type="url"
                  value={serverCfg.public_url}
                  onChange={(e) => setServerCfg((prev) => ({ ...prev, public_url: e.target.value }))}
                  placeholder="https://redgm.example.com"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-300">
                  Allowed Browser Origins (one exact http(s)://host[:port] per line)
                </span>
                <textarea
                  rows={3}
                  value={originsText}
                  onChange={(e) => setOriginsText(e.target.value)}
                  placeholder="https://redgm.example.com"
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                />
              </label>

              <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
                {runtimeInfo?.restart_supported ? (
                  <button
                    type="button"
                    disabled={restarting}
                    onClick={() => void handleRestartServer()}
                    className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/50 bg-amber-500/15 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                  >
                    {restarting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    Restart Server Now
                  </button>
                ) : (
                  <span className="text-[11px] text-slate-500">
                    Restart the process manually after saving IP/port when not running under `redkb.py serve`.
                  </span>
                )}

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-md px-3 py-2 text-xs text-slate-400 hover:text-slate-200"
                  >
                    Close
                  </button>
                  <button
                    type="submit"
                    disabled={saving}
                    className="rounded-md bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                  >
                    {saving ? "Saving..." : "Save Network Settings"}
                  </button>
                </div>
              </div>
            </form>
          )}

          {activeTab === "access" && (
            <div className="space-y-4">
              {authStatus?.can_bootstrap ? (
                <form onSubmit={handleBootstrapAuth} className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
                  <div className="text-xs font-semibold uppercase tracking-wider text-cyan-300">
                    Enable Admin &amp; User Sign-In
                  </div>
                  <p className="text-xs text-slate-400">
                    Currently running in open loopback mode. Set an Admin account below to protect server settings, prompts, and IP/port controls.
                  </p>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-xs text-slate-300">Admin Username</span>
                      <input
                        type="text"
                        required
                        value={bootAdminUser}
                        onChange={(e) => setBootAdminUser(e.target.value)}
                        placeholder="e.g. fixer_boss"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs text-slate-300">Admin Password (min 6)</span>
                      <input
                        type="password"
                        required
                        minLength={6}
                        value={bootAdminPass}
                        onChange={(e) => setBootAdminPass(e.target.value)}
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs text-slate-300">Initial Player Username</span>
                      <input
                        type="text"
                        value={bootPlayerUser}
                        onChange={(e) => setBootPlayerUser(e.target.value)}
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs text-slate-300">Initial Player Password (optional)</span>
                      <input
                        type="password"
                        value={bootPlayerPass}
                        onChange={(e) => setBootPlayerPass(e.target.value)}
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100"
                      />
                    </label>
                  </div>
                  <div className="flex items-center justify-end gap-2">
                    <button
                      type="submit"
                      disabled={saving}
                      className="inline-flex items-center gap-1.5 rounded-md bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
                    >
                      <Shield className="h-3.5 w-3.5" />
                      Enable Accounts
                    </button>
                  </div>
                </form>
              ) : (
                <>
                  <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3.5 space-y-2">
                    <div className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                      Configured Accounts
                    </div>
                    {accounts.length === 0 ? (
                      <p className="text-xs text-slate-400">No file-backed accounts listed (using env or PIN).</p>
                    ) : (
                      <div className="divide-y divide-slate-800/80">
                        {accounts.map((acc) => {
                          const adminCount = accounts.filter((a) => a.role === "admin").length;
                          const isLastAdmin = acc.role === "admin" && adminCount <= 1;
                          return (
                            <div key={acc.username} className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-semibold text-slate-100">{acc.username}</span>
                                <span
                                  className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                                    acc.role === "admin"
                                      ? "bg-rose-500/20 text-rose-300"
                                      : "bg-cyan-500/20 text-cyan-300"
                                  }`}
                                >
                                  {acc.role}
                                </span>
                                <span className="text-[11px] text-slate-500">({acc.source})</span>
                              </div>
                              {acc.source !== "env" && (
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    disabled={saving || isLastAdmin}
                                    title={
                                      isLastAdmin
                                        ? "At least one Admin account is required"
                                        : acc.role === "admin"
                                          ? "Demote to normal Player user"
                                          : "Grant Admin privileges"
                                    }
                                    onClick={() => void handleToggleAccountRole(acc.username, acc.role)}
                                    className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] font-medium transition disabled:opacity-40 ${
                                      acc.role === "admin"
                                        ? "border-slate-700 bg-slate-900 text-slate-300 hover:border-amber-500/60 hover:text-amber-200"
                                        : "border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20"
                                    }`}
                                  >
                                    <Shield className="h-3 w-3" />
                                    {acc.role === "admin" ? "Make User" : "Make Admin"}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={saving || isLastAdmin}
                                    onClick={() => void handleDeleteAccount(acc.username)}
                                    className="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10 disabled:opacity-40"
                                  >
                                    <Trash2 className="h-3 w-3" />
                                    Remove
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <form onSubmit={handleUpsertAccount} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3.5 space-y-3">
                    <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-300">
                      <UserPlus className="h-3.5 w-3.5 text-cyan-400" />
                      Add or Update Account
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      <input
                        type="text"
                        required
                        value={newUserName}
                        onChange={(e) => setNewUserName(e.target.value)}
                        placeholder="Username"
                        className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                      <input
                        type="password"
                        required
                        minLength={newUserRole === "admin" ? 6 : 4}
                        value={newUserPass}
                        onChange={(e) => setNewUserPass(e.target.value)}
                        placeholder={newUserRole === "admin" ? "Password (min 6)" : "Password (min 4)"}
                        className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                      <select
                        value={newUserRole}
                        onChange={(e) => setNewUserRole(e.target.value === "admin" ? "admin" : "user")}
                        className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      >
                        <option value="user">User (Play Only)</option>
                        <option value="admin">Admin (Full Access)</option>
                      </select>
                    </div>
                    <div className="flex justify-end">
                      <button
                        type="submit"
                        disabled={saving}
                        className="rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
                      >
                        Save Account
                      </button>
                    </div>
                  </form>

                  <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3.5 space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                      Player Policy &amp; Sessions
                    </div>
                    <label className="flex items-center gap-2 text-xs text-slate-200">
                      <input
                        type="checkbox"
                        checked={allowSelfSignup}
                        onChange={(e) => setAllowSelfSignup(e.target.checked)}
                      />
                      Allow new players to create their own accounts
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-200">
                      <input
                        type="checkbox"
                        checked={allowGuests}
                        onChange={(e) => setAllowGuests(e.target.checked)}
                      />
                      Allow passwordless guest player sign-in
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-200">
                      <input
                        type="checkbox"
                        checked={requireCharacterToSpeak}
                        onChange={(e) => setRequireCharacterToSpeak(e.target.checked)}
                      />
                      Require non-admin players to have a character before speaking in chat (Default: ON)
                    </label>
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-slate-400">
                          Update shared Player Passcode {passcodeConfigured ? "(currently set)" : "(none)"}
                        </span>
                        {passcodeConfigured && (
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => void handleUpdateAccessPolicy(false, true)}
                            className="text-[11px] text-rose-300 hover:underline"
                          >
                            Clear passcode
                          </button>
                        )}
                      </div>
                      <input
                        type="password"
                        value={sharedPasscode}
                        onChange={(e) => setSharedPasscode(e.target.value)}
                        placeholder="Leave blank to keep unchanged"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                      />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => void handleUpdateAccessPolicy(true)}
                        className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-500/20"
                      >
                        Revoke All Existing Tokens
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => void handleUpdateAccessPolicy(false)}
                        className="rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500"
                      >
                        Save Access Policy
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {activeTab === "display" && (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 space-y-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-cyan-300">
                    HUD Text Size
                  </div>
                  <p className="mt-0.5 text-xs text-slate-400">
                    Adjust overall font scale across chat messages, character sheets, and briefings (saved in this browser).
                  </p>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {(
                    [
                      { id: "standard", label: "Standard (100%)", desc: "Default compact HUD" },
                      { id: "large", label: "Large (110%)", desc: "Easier long-session reading" },
                      { id: "xl", label: "Extra Large (119%)", desc: "Maximum legibility" },
                    ] as const
                  ).map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => onChangeUiScale?.(opt.id)}
                      className={`rounded-lg border px-3 py-2.5 text-left transition ${
                        uiScale === opt.id
                          ? "border-cyan-400 bg-cyan-500/15 text-cyan-100"
                          : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-500"
                      }`}
                    >
                      <div className="text-xs font-bold">{opt.label}</div>
                      <div className="text-[11px] text-slate-400">{opt.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 space-y-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider text-cyan-300">
                    Font Thickness / Boldness
                  </div>
                  <p className="mt-0.5 text-xs text-slate-400">
                    Increase font weight so thin strokes feel fuller and sharper against dark panels.
                  </p>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {(
                    [
                      { id: "normal", label: "Slim (500)", desc: "Lighter HUD strokes" },
                      { id: "semibold", label: "Crisp (600)", desc: "Recommended default" },
                      { id: "bold", label: "Heavy (700)", desc: "Maximum stroke thickness" },
                    ] as const
                  ).map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => onChangeUiWeight?.(opt.id)}
                      className={`rounded-lg border px-3 py-2.5 text-left transition ${
                        uiWeight === opt.id
                          ? "border-cyan-400 bg-cyan-500/15 text-cyan-100"
                          : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-500"
                      }`}
                    >
                      <div className="text-xs font-bold">{opt.label}</div>
                      <div className="text-[11px] text-slate-400">{opt.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === "account" && (
            <div className="space-y-4">
              {!authStatus?.auth_enabled ? (
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-xs text-slate-300">
                  Account authentication is currently off (Open Table Mode). Enable Access &amp; Auth in Admin settings to use named user accounts.
                </div>
              ) : !authStatus.username || authStatus.username === "player" && authStatus.pin_only_mode ? (
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-xs text-slate-300">
                  You are currently connected as a guest / passcode player. Sign in or register a named account to manage your own username and password.
                </div>
              ) : (
                <form onSubmit={handleUpdateMyAccount} className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wider text-cyan-300">
                        Account Credentials ({authStatus.username})
                      </div>
                      <p className="mt-0.5 text-xs text-slate-400">
                        Change your login username or password. Owned character sheets stay linked to your account automatically.
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="block space-y-1 text-xs">
                      <span className="text-slate-300">Username</span>
                      <input
                        type="text"
                        value={acctNewUsername}
                        onChange={(e) => setAcctNewUsername(e.target.value)}
                        placeholder={authStatus.username}
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                      />
                    </label>
                    <label className="block space-y-1 text-xs">
                      <span className="text-slate-300">Current Password *</span>
                      <input
                        type="password"
                        value={acctCurrentPassword}
                        onChange={(e) => setAcctCurrentPassword(e.target.value)}
                        placeholder="Confirm current password"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                      />
                    </label>
                    <label className="block space-y-1 text-xs">
                      <span className="text-slate-300">New Password (optional)</span>
                      <input
                        type="password"
                        value={acctNewPassword}
                        onChange={(e) => setAcctNewPassword(e.target.value)}
                        placeholder="Leave blank to keep current"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                      />
                    </label>
                    <label className="block space-y-1 text-xs">
                      <span className="text-slate-300">Confirm New Password</span>
                      <input
                        type="password"
                        value={acctConfirmPassword}
                        onChange={(e) => setAcctConfirmPassword(e.target.value)}
                        placeholder="Repeat new password"
                        className="w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                      />
                    </label>
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={saving}
                      className="rounded-md bg-cyan-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
                    >
                      {saving ? "Updating..." : "Update Account"}
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
