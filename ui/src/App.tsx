import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { BookOpen, Compass, GripVertical, MessageSquare, User } from "lucide-react";
import {
  compressCampaignMemory,
  deleteCampaign,
  deleteChatMessage,
  exportChatBranch,
  fetchAuthStatus,
  fetchCampaignContext,
  fetchChatTree,
  fetchHealth,
  fetchLLMSettings,
  fetchSkillsCatalog,
  getClientId,
  getStoredPlayerName,
  getStoredViewRoleOverride,
  listCampaigns,
  logoutAuth,
  regenerateChatTurn,
  sendPresence,
  setPrimaryCampaign,
  setStoredPlayerName,
  setStoredViewRoleOverride,
  startCampaignSession,
  streamChatTurn,
  subscribeCampaignEvents,
  switchChatBranch,
  syncChatRevisions,
  updateCharacterProfile,
  updateChatMessage,
} from "./api";
import { AuthGateModal } from "./components/AuthGateModal";
import nightCityBackdrop from "./assets/night-city-backdrop.jpg";
import { CampaignCreatorModal } from "./components/CampaignCreatorModal";
import { CampaignPanel } from "./components/CampaignPanel";
import { CharacterCreatorModal } from "./components/CharacterCreatorModal";
import { CharacterPanel } from "./components/CharacterPanel";
import { ChatPane, type StreamingTurnState } from "./components/ChatPane";
import { CommandPalette } from "./components/CommandPalette";
import { CoopModal } from "./components/CoopModal";
import { LibraryPanel } from "./components/LibraryPanel";
import {
  SettingsModal,
  type SettingsTab,
  type UiFontWeight,
  type UiTextScale,
} from "./components/SettingsModal";
import { TopBar } from "./components/TopBar";
import type {
  ActiveTurnInfo,
  AuthStatus,
  CampaignContext,
  CampaignRecord,
  ChatMessageNode,
  ChatTreeResponse,
  CoopPlayer,
  HealthStatus,
  LLMSettings,
  LibraryEntry,
} from "./types";

type RightTab = "character" | "campaign" | "library";

const STORAGE_CAMPAIGN_KEY = "redgm:activeCampaignId";
const STORAGE_CLAIMED_CHAR_KEY = "redgm:claimedCharId";

function userCampaignStorageKey(username?: string | null): string {
  return username ? `${STORAGE_CAMPAIGN_KEY}:${username.toLowerCase()}` : STORAGE_CAMPAIGN_KEY;
}

function userClaimedCharStorageKey(username?: string | null, campaignId?: string | null): string {
  if (username && campaignId) {
    return `${STORAGE_CLAIMED_CHAR_KEY}:${username.toLowerCase()}:${campaignId}`;
  }
  return STORAGE_CLAIMED_CHAR_KEY;
}

function safeStorageGet(key: string): string | null {
  try {
    return typeof window !== "undefined" && typeof window.localStorage?.getItem === "function"
      ? window.localStorage.getItem(key)
      : null;
  } catch {
    return null;
  }
}

function safeStorageSet(key: string, id: string): void {
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.setItem === "function") {
      window.localStorage.setItem(key, id);
    }
  } catch {
    // ignore storage errors
  }
}

function getInitialUrlCampaignId(): string | null {
  try {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("campaign");
  } catch {
    return null;
  }
}

export function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignRecord[]>([]);
  const [activeCampaignId, setActiveCampaignId] = useState<string | null>(null);
  const [campaignContext, setCampaignContext] = useState<CampaignContext | null>(null);
  const [chatTree, setChatTree] = useState<ChatTreeResponse | null>(null);
  const [corebookSkills, setCorebookSkills] = useState<
    Record<string, { stat: string; cost: number; specializable: boolean }>
  >({});

  const [rightTab, setRightTab] = useState<RightTab>("character");
  const [selectedLibraryEntry, setSelectedLibraryEntry] = useState<LibraryEntry | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsInitialTab, setSettingsInitialTab] = useState<SettingsTab>("connection");
  const [campaignCreatorOpen, setCampaignCreatorOpen] = useState(false);
  const [campaignCreatorEdit, setCampaignCreatorEdit] = useState<CampaignRecord | null>(null);
  const [characterCreatorOpen, setCharacterCreatorOpen] = useState(false);
  const [preferredCharacterId, setPreferredCharacterId] = useState<string>("");
  const [coopOpen, setCoopOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [mobilePane, setMobilePane] = useState<"chat" | "dashboard">("chat");
  const [isDesktop, setIsDesktop] = useState<boolean>(() =>
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? true
      : window.matchMedia("(min-width: 768px)").matches,
  );
  const [streaming, setStreaming] = useState<StreamingTurnState | null>(null);
  const [peerStreaming, setPeerStreaming] = useState<StreamingTurnState | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [viewAsUser, setViewAsUser] = useState<boolean>(() => getStoredViewRoleOverride() === "user");
  const requireCharacterToSpeak = Boolean(
    llmSettings?.require_character_to_speak ?? authStatus?.require_character_to_speak ?? true,
  );
  const [uiScale, setUiScale] = useState<UiTextScale>(() => {
    const raw = safeStorageGet("redgm:uiScale");
    return raw === "large" || raw === "xl" ? raw : "standard";
  });
  const [uiWeight, setUiWeight] = useState<UiFontWeight>(() => {
    const raw = safeStorageGet("redgm:uiWeight");
    return raw === "normal" || raw === "bold" ? raw : "semibold";
  });
  const [activeChannelId, setActiveChannelId] = useState<string>("main");

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.dataset.uiScale = uiScale;
    document.documentElement.dataset.uiWeight = uiWeight;
    safeStorageSet("redgm:uiScale", uiScale);
    safeStorageSet("redgm:uiWeight", uiWeight);
  }, [uiScale, uiWeight]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(min-width: 768px)");
    const onChange = (ev: MediaQueryListEvent) => setIsDesktop(ev.matches);
    setIsDesktop(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Co-op / Speaker state
  const [playerName, setPlayerName] = useState<string>(getStoredPlayerName);
  const [claimedCharId, setClaimedCharId] = useState<string>(() => safeStorageGet(STORAGE_CLAIMED_CHAR_KEY) || "");
  const [speakerId, setSpeakerId] = useState<string>(() => safeStorageGet(STORAGE_CLAIMED_CHAR_KEY) || "");
  const [overclock, setOverclock] = useState(false);
  const [protectOthers, setProtectOthers] = useState(false);
  const [compressingMemory, setCompressingMemory] = useState(false);
  const [roster, setRoster] = useState<CoopPlayer[]>([]);
  const [activeTurn, setActiveTurn] = useState<ActiveTurnInfo | null>(null);
  const [activeTurnsMap, setActiveTurnsMap] = useState<Record<string, ActiveTurnInfo>>({});

  const abortRef = useRef<AbortController | null>(null);
  const activeCampaignIdRef = useRef<string | null>(activeCampaignId);
  const activeChannelIdRef = useRef<string>(activeChannelId);
  const lastSyncSeqRef = useRef<number>(0);
  const userPinnedMainRef = useRef<boolean>(false);
  const speakerPinnedGeneralRef = useRef<boolean>(false);
  const selfClientId = getClientId();

  useEffect(() => {
    activeCampaignIdRef.current = activeCampaignId;
    lastSyncSeqRef.current = 0;
    userPinnedMainRef.current = false;
    speakerPinnedGeneralRef.current = false;
  }, [activeCampaignId]);

  useEffect(() => {
    activeChannelIdRef.current = activeChannelId;
  }, [activeChannelId]);

  const notify = useCallback((msg: string) => {
    setToast(msg);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(t);
  }, [toast]);

  // Global Ctrl+K / Cmd+K shortcut
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loadCampaignData = useCallback(async (campId: string, chanId?: string) => {
    const targetChan = chanId ?? activeChannelIdRef.current ?? "main";
    const [ctx, tree] = await Promise.all([
      fetchCampaignContext(campId),
      fetchChatTree(campId, targetChan),
    ]);
    if (activeCampaignIdRef.current && activeCampaignIdRef.current !== campId) return;
    setCampaignContext(ctx);
    setChatTree(tree);
  }, []);

  const refreshInitial = useCallback(async () => {
    try {
      const [h, auth] = await Promise.all([
        fetchHealth().catch(() => null),
        fetchAuthStatus().catch(() => null),
      ]);
      if (h) setHealth(h);
      setAuthStatus(auth);

      if (auth && (auth.can_bootstrap || (auth.auth_enabled && !auth.authenticated))) {
        setLlmSettings(null);
        setCampaigns([]);
        setActiveCampaignId(null);
        setCampaignContext(null);
        setChatTree(null);
        return;
      }

      if (auth?.authenticated && auth.username) {
        setPlayerName(auth.username);
        setStoredPlayerName(auth.username);
      }

      const canAdminLlm =
        !auth || !auth.auth_enabled || auth.role === "admin" || auth.role === "open";
      const [llm, campList, skillsData] = await Promise.all([
        canAdminLlm ? fetchLLMSettings().catch(() => null) : Promise.resolve(null),
        listCampaigns().catch(() => []),
        fetchSkillsCatalog().catch(() => ({ skills: {}, rules_indexed: false })),
      ]);
      setLlmSettings(llm);
      setCampaigns(campList);
      setCorebookSkills(skillsData.skills ?? {});

      const urlCamp = getInitialUrlCampaignId();
      const campKey = userCampaignStorageKey(auth?.username);
      const remembered = safeStorageGet(campKey);
      const chosen =
        campList.find((c) => c.id === urlCamp)?.id ??
        campList.find((c) => c.id === remembered)?.id ??
        campList.find((c) => c.is_primary)?.id ??
        campList[0]?.id ??
        null;
      setActiveCampaignId(chosen);
      if (chosen) {
        safeStorageSet(campKey, chosen);
        await loadCampaignData(chosen);
      } else {
        setCampaignContext(null);
        setChatTree(null);
      }
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to initialize app");
    }
  }, [loadCampaignData, notify]);

  useEffect(() => {
    void refreshInitial();
  }, [refreshInitial]);

  // Keep claimed / speaker character aligned when campaign characters load
  useEffect(() => {
    const chars = campaignContext?.characters ?? [];
    if (chars.length === 0) {
      setSpeakerId("");
      return;
    }
    const isUserView = (authStatus?.authenticated && authStatus.role === "user") || viewAsUser;
    const me = (authStatus?.username ?? "").trim().toLowerCase();
    const allowedChars = isUserView
      ? chars.filter((c) => {
          const owner = String(c.detail?.owner_username ?? "").trim().toLowerCase();
          return (me && owner === me) || !owner;
        })
      : chars;

    if (speakerPinnedGeneralRef.current && (!isUserView || !requireCharacterToSpeak)) {
      setSpeakerId("");
      return;
    }

    const scopedClaim = activeCampaignId
      ? safeStorageGet(userClaimedCharStorageKey(authStatus?.username, activeCampaignId)) || ""
      : "";
    const effectiveClaim =
      (scopedClaim && allowedChars.some((c) => c.id === scopedClaim) ? scopedClaim : "") ||
      (claimedCharId && allowedChars.some((c) => c.id === claimedCharId) ? claimedCharId : "");

    if (effectiveClaim) {
      if (effectiveClaim !== claimedCharId) setClaimedCharId(effectiveClaim);
      setSpeakerId((prev) => (prev && allowedChars.some((c) => c.id === prev) ? prev : effectiveClaim));
    } else if (isUserView) {
      const myOwned = me
        ? chars.find((c) => String(c.detail?.owner_username ?? "").trim().toLowerCase() === me)
        : undefined;
      if (myOwned) {
        setClaimedCharId(myOwned.id);
        setSpeakerId((prev) => (prev && allowedChars.some((c) => c.id === prev) ? prev : myOwned.id));
      } else {
        setSpeakerId((prev) => (prev && allowedChars.some((c) => c.id === prev) ? prev : ""));
      }
    } else {
      setSpeakerId((prev) => (prev && chars.some((c) => c.id === prev) ? prev : chars[0].id));
    }
  }, [campaignContext?.characters, claimedCharId, activeCampaignId, authStatus?.username, authStatus?.authenticated, authStatus?.role, viewAsUser, requireCharacterToSpeak]);

  // Keep activeChannelId aligned when party splits or reunites (without trapping clicks on Main Table)
  useEffect(() => {
    const grouping = campaignContext?.party_grouping;
    if (!grouping || grouping.mode !== "split") {
      userPinnedMainRef.current = false;
      if (activeChannelId !== "main") {
        setActiveChannelId("main");
        setPeerStreaming(null);
        if (activeCampaignId) {
          void fetchChatTree(activeCampaignId, "main").then(setChatTree).catch(() => {});
        }
      }
      return;
    }
    const targetChar = speakerId || claimedCharId;
    const assignedChan = targetChar ? grouping.char_channel_map?.[targetChar] : undefined;
    const validIds = new Set(["main", ...grouping.channels.map((ch) => ch.id)]);
    if (!userPinnedMainRef.current && assignedChan && validIds.has(assignedChan) && activeChannelId === "main") {
      setActiveChannelId(assignedChan);
      setPeerStreaming(null);
      if (activeCampaignId) {
        void fetchChatTree(activeCampaignId, assignedChan).then(setChatTree).catch(() => {});
      }
    } else if (!validIds.has(activeChannelId)) {
      const nextChan = assignedChan || grouping.channels[0]?.id || "main";
      setActiveChannelId(nextChan);
      setPeerStreaming(null);
      if (activeCampaignId) {
        void fetchChatTree(activeCampaignId, nextChan).then(setChatTree).catch(() => {});
      }
    }
  }, [campaignContext?.party_grouping, speakerId, claimedCharId, activeChannelId, activeCampaignId]);

  // Live Co-op presence heartbeat + SSE subscription + real-time peer streaming
  useEffect(() => {
    if (!activeCampaignId) {
      setRoster([]);
      setActiveTurn(null);
      setActiveTurnsMap({});
      setPeerStreaming(null);
      return;
    }

    let syncTimer: ReturnType<typeof setTimeout> | null = null;
    const scheduleSync = (delayMs = 60) => {
      if (syncTimer) return;
      syncTimer = setTimeout(() => {
        syncTimer = null;
        if (!abortRef.current) {
          void loadCampaignData(activeCampaignId, activeChannelIdRef.current);
          void listCampaigns().then(setCampaigns).catch(() => {});
        }
      }, delayMs);
    };

    const ping = () => {
      void sendPresence(activeCampaignId, {
        player_name: playerName,
        character_id: claimedCharId || null,
      })
        .then((res) => {
          if (Array.isArray(res?.players)) setRoster(res.players);
          if ("active_turn" in res) setActiveTurn(res.active_turn ?? null);
          if (res?.active_turns) setActiveTurnsMap(res.active_turns);
          if (typeof res?.sync_seq === "number" && res.sync_seq > lastSyncSeqRef.current) {
            lastSyncSeqRef.current = res.sync_seq;
            if (!abortRef.current) {
              scheduleSync(40);
            }
          }
        })
        .catch(() => {
          // ignore offline / mocked environment
        });
    };
    ping();
    const heartbeat = setInterval(ping, 8000);

    const onVisibility = () => {
      if (typeof document !== "undefined" && document.visibilityState === "visible" && !abortRef.current) {
        ping();
        scheduleSync(40);
      }
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }

    const unsubscribe = subscribeCampaignEvents(activeCampaignId, {
      onPresence: (data) => {
        if (Array.isArray(data.players)) setRoster(data.players);
        setActiveTurn(data.active_turn ?? null);
        if (data.active_turns) setActiveTurnsMap(data.active_turns);
        if (typeof data.sync_seq === "number" && data.sync_seq > lastSyncSeqRef.current) {
          lastSyncSeqRef.current = data.sync_seq;
          if (!abortRef.current) scheduleSync(40);
        }
      },
      onTurnLock: (turn, turns) => {
        setActiveTurn(turn);
        if (turns) setActiveTurnsMap(turns);
        const curChan = activeChannelIdRef.current || "main";
        const chanTurn = turns ? turns[curChan] : (curChan === "main" ? turn : null);
        if (!chanTurn) {
          setPeerStreaming(null);
        }
      },
      onPeerUserMessage: (data) => {
        if (data.client_id === selfClientId) return;
        const evChan = data.channel_id || "main";
        if (evChan !== (activeChannelIdRef.current || "main")) return;
        const msg = data.message;
        if (!msg || !msg.id) return;
        setChatTree((prev) => {
          if (!prev || prev.campaign_id !== activeCampaignId) return prev;
          if (prev.active_branch.some((m) => m.id === msg.id)) return prev;
          return {
            ...prev,
            nodes: prev.nodes.some((m) => m.id === msg.id) ? prev.nodes : [...prev.nodes, msg],
            active_branch: [...prev.active_branch, msg],
            active_leaf_id: msg.id,
          };
        });
      },
      onPeerStream: (data) => {
        if (data.client_id === selfClientId) return;
        const evChan = data.channel_id || "main";
        if (evChan !== (activeChannelIdRef.current || "main")) return;
        setPeerStreaming((prev) => {
          const base: StreamingTurnState = prev ?? {
            userText: data.user_text || "",
            speakerName: data.speaker_name,
            speakerColor: data.speaker_color,
            speakerPortraitUrl: data.speaker_portrait_url,
            text: "",
            citations: [],
            rolls: [],
            patches: [],
            libraryAdded: [],
            warnings: [],
            overclock: Boolean(data.overclock),
            truncateFromId: data.truncate_from_id,
            startedAt: Date.now(),
          };
          switch (data.event) {
            case "rule_citation":
              return { ...base, citations: ((data.data?.entries as LibraryEntry[]) ?? base.citations) };
            case "dice_roll":
              return { ...base, rolls: [...base.rolls, data.data as unknown as StreamingTurnState["rolls"][number]] };
            case "state_patch":
              return { ...base, patches: [...base.patches, data.data as unknown as StreamingTurnState["patches"][number]] };
            case "library_added":
              return { ...base, libraryAdded: [...base.libraryAdded, data.data as unknown as LibraryEntry] };
            case "warning":
              return { ...base, warnings: [...base.warnings, String(data.data?.message ?? "")] };
            case "text_delta":
              return { ...base, text: base.text + String(data.data?.delta ?? "") };
            default:
              return base;
          }
        });
      },
      onPeerTurnDone: (data) => {
        if (data.client_id === selfClientId) return;
        const evChan = String(data.channel_id || "main");
        if (evChan === (activeChannelIdRef.current || "main")) {
          setPeerStreaming(null);
        }
        scheduleSync(30);
      },
      onSync: (_kind, meta) => {
        if (typeof meta?.sync_seq === "number" && meta.sync_seq > lastSyncSeqRef.current) {
          lastSyncSeqRef.current = meta.sync_seq;
        }
        if (abortRef.current) return;
        scheduleSync(50);
      },
      onPing: (data) => {
        if (typeof data?.sync_seq === "number" && data.sync_seq > lastSyncSeqRef.current) {
          lastSyncSeqRef.current = data.sync_seq;
          if (!abortRef.current) scheduleSync(50);
        }
      },
    });

    return () => {
      clearInterval(heartbeat);
      if (syncTimer) clearTimeout(syncTimer);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
      unsubscribe();
    };
  }, [activeCampaignId, playerName, claimedCharId, loadCampaignData, selfClientId]);

  const handleSelectCampaign = async (id: string) => {
    abortRef.current?.abort();
    activeCampaignIdRef.current = id;
    activeChannelIdRef.current = "main";
    setActiveChannelId("main");
    setPeerStreaming(null);
    setOverclock(false);
    setActiveCampaignId(id);
    setSelectedLibraryEntry((cur) => (cur?.source === "homebrew" ? null : cur));
    safeStorageSet(userCampaignStorageKey(authStatus?.username), id);
    try {
      await loadCampaignData(id, "main");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to load campaign");
    }
  };

  const handleSelectChannel = async (channelId: string) => {
    if (!activeCampaignId) return;
    userPinnedMainRef.current = channelId === "main";
    activeChannelIdRef.current = channelId;
    setActiveChannelId(channelId);
    setPeerStreaming(null);
    try {
      const tree = await fetchChatTree(activeCampaignId, channelId);
      setChatTree(tree);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to switch scene channel");
    }
  };

  const handleSetPrimaryCampaign = async (id: string) => {
    try {
      await setPrimaryCampaign(id);
      const updatedList = await listCampaigns();
      setCampaigns(updatedList);
      if (activeCampaignId === id) {
        await loadCampaignData(id);
      }
      notify("Updated primary campaign.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Could not set primary campaign");
    }
  };

  const handleDeleteCampaign = async (id: string) => {
    try {
      const res = await deleteCampaign(id);
      const updatedList = await listCampaigns();
      setCampaigns(updatedList);
      if (activeCampaignId === id) {
        const nextId = updatedList.find((c) => c.is_primary)?.id ?? updatedList[0]?.id ?? null;
        if (nextId) {
          await handleSelectCampaign(nextId);
        } else {
          setActiveCampaignId(null);
          setCampaignContext(null);
          setChatTree(null);
        }
      }
      notify(`Deleted campaign "${res.name}".`);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Could not delete campaign");
    }
  };

  const handleStartSession = async () => {
    if (!campaignContext) return;
    try {
      await startCampaignSession(campaignContext.campaign.id, campaignContext.campaign.revision);
      await loadCampaignData(campaignContext.campaign.id);
      const updatedList = await listCampaigns();
      setCampaigns(updatedList);
      notify("Started new session and refilled party LUCK.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to start session");
    }
  };

  const handleExportChat = async () => {
    if (!activeCampaignId) return;
    try {
      const data = await exportChatBranch(activeCampaignId, chatTree?.active_leaf_id ?? undefined, activeChannelId);
      const blob = new Blob([data.markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const slug = (data.campaign.name || "campaign").toLowerCase().replace(/[^a-z0-9]+/g, "-");
      a.download = `${slug}-session-${data.campaign.session_number}.md`;
      a.click();
      URL.revokeObjectURL(url);
      notify("Exported story log as Markdown.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Export failed");
    }
  };

  const refreshActiveCampaign = async () => {
    if (!activeCampaignId) return;
    await loadCampaignData(activeCampaignId, activeChannelIdRef.current);
    const updatedList = await listCampaigns();
    setCampaigns(updatedList);
  };

  const runStreamedAction = async (
    userText: string,
    overclock: boolean,
    speakerName: string | undefined,
    executor: (
      callbacks: Parameters<typeof streamChatTurn>[1],
      signal: AbortSignal,
    ) => Promise<void>,
    truncateFromId?: string,
    targetCampaignId?: string,
  ) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming({
      userText,
      speakerName,
      text: "",
      citations: [],
      rolls: [],
      patches: [],
      libraryAdded: [],
      warnings: [],
      overclock,
      truncateFromId,
      startedAt: Date.now(),
    });

    try {
      await executor(
        {
          onCitation: (entries) => {
            setStreaming((prev) => (prev ? { ...prev, citations: entries } : prev));
          },
          onDiceRoll: (roll) => {
            setStreaming((prev) =>
              prev ? { ...prev, rolls: [...prev.rolls, roll] } : prev,
            );
          },
          onStatePatch: (patch) => {
            setStreaming((prev) =>
              prev ? { ...prev, patches: [...prev.patches, patch] } : prev,
            );
          },
          onLibraryAdded: (entry) => {
            setStreaming((prev) =>
              prev ? { ...prev, libraryAdded: [...prev.libraryAdded, entry] } : prev,
            );
          },
          onWarning: (message) => {
            setStreaming((prev) =>
              prev ? { ...prev, warnings: [...prev.warnings, message] } : prev,
            );
          },
          onTextDelta: (delta) => {
            setStreaming((prev) =>
              prev ? { ...prev, text: prev.text + delta } : prev,
            );
          },
          onDone: (data) => {
            if (data.gm_deferred) {
              notify("Posted to party table (GM held — click Resolve GM Turn when ready).");
            }
          },
          onError: (detail) => {
            notify(`GM Error: ${detail}`);
          },
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        notify(err instanceof Error ? err.message : "Turn failed");
      }
    } finally {
      const refreshCampId = targetCampaignId ?? activeCampaignId;
      if (refreshCampId) {
        await loadCampaignData(refreshCampId).catch(() => {});
      }
      abortRef.current = null;
      setStreaming(null);
    }
  };

  const handleSendTurn = async (
    text: string,
    opts: {
      overclock: boolean;
      luckSpend?: number;
      speakerCharacterId?: string;
      speakerName?: string;
      gmMode?: "auto" | "force_gm" | "hold_gm";
    },
  ) => {
    if (!activeCampaignId) return;
    await runStreamedAction(text, opts.overclock, opts.speakerName, (callbacks, signal) =>
      streamChatTurn(
        {
          campaign_id: activeCampaignId,
          user_text: text,
          channel_id: activeChannelId,
          overclock: opts.overclock,
          luck_spend: opts.luckSpend || undefined,
          speaker_character_id: opts.speakerCharacterId,
          speaker_name: opts.speakerName,
          gm_mode: opts.gmMode,
        },
        callbacks,
        signal,
      ),
    );
  };

  const handleEditUserMessage = async (
    msg: ChatMessageNode,
    newText: string,
    overclock: boolean,
    luckSpend?: number,
  ) => {
    if (!activeCampaignId) return;
    await runStreamedAction(
      newText,
      overclock,
      msg.metadata?.speaker_name,
      (callbacks, signal) =>
        streamChatTurn(
          {
            campaign_id: activeCampaignId,
            user_text: newText,
            channel_id: activeChannelId,
            parent_id: msg.parent_id,
            replace_message_id: msg.id,
            branch_from_root: msg.parent_id === null,
            overclock,
            luck_spend: luckSpend || undefined,
            speaker_character_id: msg.metadata?.speaker_character_id,
            speaker_name: msg.metadata?.speaker_name,
          },
          callbacks,
          signal,
        ),
      msg.id,
    );
  };

  const handleUpdateMessageInPlace = async (msg: ChatMessageNode, newText: string) => {
    if (!activeCampaignId) return;
    try {
      const updated = await updateChatMessage(activeCampaignId, msg.id, newText);
      setChatTree(updated);
      notify("Updated message text.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to edit message");
    }
  };

  const handleDeleteMessage = async (msg: ChatMessageNode, scope: "single" | "branch" = "branch") => {
    if (!activeCampaignId) return;
    try {
      const updated = await deleteChatMessage(activeCampaignId, msg.id, scope);
      setChatTree(updated);
      notify(scope === "single" ? "Deleted message." : "Deleted message branch.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to delete message");
    }
  };

  const handleCompressMemory = async () => {
    if (!activeCampaignId || compressingMemory) return;
    setCompressingMemory(true);
    try {
      const res = await compressCampaignMemory({
        campaign_id: activeCampaignId,
        leaf_id: chatTree?.active_leaf_id ?? undefined,
      });
      await refreshActiveCampaign();
      notify(
        `Compressed ${res.compressed_messages} turns into ${res.library_upserted.length} library dossier(s).`,
      );
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to compress memory");
    } finally {
      setCompressingMemory(false);
    }
  };

  const handleRegenerate = async (msg: ChatMessageNode, guidance?: string) => {
    if (!activeCampaignId) return;
    await runStreamedAction(
      "",
      Boolean(msg.metadata?.overclock),
      undefined,
      (callbacks, signal) =>
        regenerateChatTurn(
          {
            campaign_id: activeCampaignId,
            message_id: msg.id,
            guidance,
          },
          callbacks,
          signal,
        ),
      msg.id,
    );
  };

  const handleSwitchBranch = async (messageId: string) => {
    if (!activeCampaignId) return;
    try {
      const updated = await switchChatBranch(activeCampaignId, messageId);
      setChatTree(updated);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to switch branch");
    }
  };

  const handleInspectEntry = (entry: LibraryEntry) => {
    setSelectedLibraryEntry(entry);
    setRightTab("library");
    setMobilePane("dashboard");
  };

  const activeCampaign = campaignContext?.campaign ?? campaigns.find((c) => c.id === activeCampaignId) ?? null;
  const authBlocked = Boolean(
    authStatus && (authStatus.can_bootstrap || (authStatus.auth_enabled && !authStatus.authenticated)),
  );
  const isTrueAdmin =
    !authStatus || !authStatus.auth_enabled || authStatus.role === "admin" || authStatus.role === "open";
  const isEffectiveAdmin = isTrueAdmin && !viewAsUser;
  const canManageCampaigns = isEffectiveAdmin;

  const handleToggleViewAsUser = async () => {
    const next = !viewAsUser;
    setViewAsUser(next);
    setStoredViewRoleOverride(next ? "user" : null);
    await refreshInitial();
    notify(next ? "Switched to Player Mode (User View)." : "Switched back to Admin (GM) Mode.");
  };

  const handleSyncRevisions = async () => {
    if (!activeCampaignId) return;
    try {
      const res = await syncChatRevisions(activeCampaignId, activeChannelId);
      setChatTree(res);
      notify("Synced branch state with live campaign revisions.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to sync branch state");
    }
  };

  const handleUpdateCharacterColor = async (characterId: string, color: string) => {
    if (!campaignContext) return;
    const charRec = campaignContext.characters.find((c) => c.id === characterId);
    try {
      await updateCharacterProfile(
        campaignContext.campaign.id,
        characterId,
        charRec?.revision ?? 0,
        { color },
        "Update character chat tag color",
      );
      await refreshActiveCampaign();
      notify("Updated character chat tag color.");
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to update character color");
    }
  };

  const handleSignOut = async () => {
    setViewAsUser(false);
    setStoredViewRoleOverride(null);
    await logoutAuth();
    setSettingsOpen(false);
    await refreshInitial();
    notify("Signed out.");
  };

  const dashboardContent = (
    <div className="flex h-full min-h-0 min-w-0 w-full flex-col bg-[#0c101a]/88 backdrop-blur-[2px]">
      <div className="flex border-b border-slate-800/90 bg-[#0d111a]/95 px-2 pt-1 sm:pt-1.5">
        {(
          [
            { id: "character", label: "Character", icon: User },
            { id: "campaign", label: "Campaign", icon: Compass },
            { id: "library", label: "Rulebook", icon: BookOpen },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setRightTab(id)}
            className={`inline-flex flex-1 items-center justify-center gap-1.5 border-b-2 px-2.5 py-1.5 text-xs font-semibold transition sm:flex-none sm:justify-start sm:px-3.5 sm:py-2 ${
              rightTab === id
                ? "border-rose-500 text-slate-100"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Icon className="h-3.5 w-3.5 text-cyan-400" />
            {label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {rightTab === "character" && campaignContext && (
          <CharacterPanel
            campaignId={campaignContext.campaign.id}
            campaignRevision={campaignContext.campaign.revision}
            soloRevision={campaignContext.solo.revision}
            characters={campaignContext.characters}
            corebookSkills={corebookSkills}
            roster={roster}
            selfClientId={selfClientId}
            isAdmin={isEffectiveAdmin}
            currentUsername={authStatus?.username}
            activeChannelId={activeChannelId}
            overclock={overclock}
            onToggleOverclock={() => setOverclock((v) => !v)}
            selectedSpeakerId={speakerId}
            onSelectSpeakerId={(id) => {
              speakerPinnedGeneralRef.current = id === "";
              setSpeakerId(id);
            }}
            requireCharacterToSpeak={requireCharacterToSpeak}
            protectOthers={protectOthers}
            preferredSelectedId={preferredCharacterId}
            onOpenCreateCharacter={() => setCharacterCreatorOpen(true)}
            onRefresh={refreshActiveCampaign}
            onNotify={notify}
          />
        )}
        {rightTab === "character" && !campaignContext && (
          <div className="p-6 text-center text-xs text-slate-400">
            Select or create a campaign to manage characters.
          </div>
        )}

        {rightTab === "campaign" && (
          <CampaignPanel
            context={campaignContext}
            campaigns={campaigns}
            canManageCampaigns={canManageCampaigns}
            isAdmin={isEffectiveAdmin}
            currentUsername={authStatus?.username}
            activeLeafId={chatTree?.active_leaf_id ?? null}
            onSelectCampaign={handleSelectCampaign}
            onSetPrimaryCampaign={handleSetPrimaryCampaign}
            onDeleteCampaign={handleDeleteCampaign}
            onOpenNewCampaign={() => {
              setCampaignCreatorEdit(null);
              setCampaignCreatorOpen(true);
            }}
            onOpenEditCampaign={
              campaignContext
                ? () => {
                    setCampaignCreatorEdit(campaignContext.campaign);
                    setCampaignCreatorOpen(true);
                  }
                : undefined
            }
            onStartSession={handleStartSession}
            onExportChat={handleExportChat}
            onCompressMemory={handleCompressMemory}
            compressingMemory={compressingMemory}
            onRefresh={refreshActiveCampaign}
            onNotify={notify}
          />
        )}

        {rightTab === "library" && (
          <LibraryPanel
            campaignId={activeCampaignId}
            rulesIndexed={Boolean(health?.rules_indexed)}
            selectedEntry={selectedLibraryEntry}
            onSelectEntry={setSelectedLibraryEntry}
            onNotify={notify}
          />
        )}
      </div>
    </div>
  );

  const channelActiveTurn = activeTurnsMap[activeChannelId] ?? (activeChannelId === "main" ? activeTurn : null);

  const chatPaneNode = (
    <ChatPane
      campaignId={activeCampaignId}
      campaign={activeCampaign}
      partyGrouping={campaignContext?.party_grouping}
      activeChannelId={activeChannelId}
      onChangeChannelId={handleSelectChannel}
      messages={chatTree?.active_branch ?? []}
      streaming={streaming ?? peerStreaming}
      isPeerStreaming={!streaming && Boolean(peerStreaming)}
      characters={campaignContext?.characters ?? []}
      selectedSpeakerId={speakerId}
      overclock={overclock}
      onClearOverclock={() => setOverclock(false)}
      activeTurn={channelActiveTurn}
      selfClientId={selfClientId}
      isAdmin={isEffectiveAdmin}
      currentUsername={authStatus?.username}
      requireCharacterToSpeak={requireCharacterToSpeak}
      onOpenCreateCharacter={() => setCharacterCreatorOpen(true)}
      onUpdateCharacterColor={handleUpdateCharacterColor}
      onSend={handleSendTurn}
      onEditUserMessage={handleEditUserMessage}
      onUpdateMessageInPlace={handleUpdateMessageInPlace}
      onDeleteMessage={handleDeleteMessage}
      onRegenerate={handleRegenerate}
      onSwitchBranch={handleSwitchBranch}
      onStopStream={() => abortRef.current?.abort()}
      onCompressMemory={handleCompressMemory}
      compressingMemory={compressingMemory}
      onInspectEntry={handleInspectEntry}
      onNotify={notify}
    />
  );

  const customBannerUrl =
    campaignContext?.campaign?.state?.discoveries?.["__banner_url"] ||
    campaignContext?.campaign?.state?.discoveries?.["Banner URL"] ||
    "";

  return (
    <div className="relative flex h-dvh w-full flex-col overflow-hidden bg-[#07090f] text-slate-100">
      {/* Atmospheric Night City Backdrop */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <img
          src={customBannerUrl || nightCityBackdrop}
          alt=""
          className="h-full w-full object-cover opacity-25 saturate-110"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-[#07090f]/80 via-[#080b13]/72 to-[#06080d]/92" />
        <div className="cyber-grid-overlay absolute inset-0 opacity-75" />
        <div className="cyber-scanlines absolute inset-0 opacity-55" />
      </div>

      <div className="relative z-10 flex h-full min-h-0 w-full flex-col overflow-hidden">
      <TopBar
        health={health}
        llmSettings={llmSettings}
        revisionMismatch={Boolean(chatTree?.revision_mismatch)}
        coopCount={roster.length}
        authStatus={authStatus}
        viewAsUser={viewAsUser}
        onToggleViewAsUser={() => void handleToggleViewAsUser()}
        onSyncRevisions={handleSyncRevisions}
        onOpenCoop={() => setCoopOpen(true)}
        onOpenSettings={() => {
          setSettingsInitialTab(isEffectiveAdmin ? "connection" : "display");
          setSettingsOpen(true);
        }}
        onOpenCorebookSettings={() => {
          setSettingsInitialTab("corebook");
          setSettingsOpen(true);
        }}
        onOpenAuth={() => setAuthModalOpen(true)}
        onSignOut={() => void handleSignOut()}
      />

      {/* Mobile pane switcher */}
      <div className="flex shrink-0 border-b border-slate-800 bg-[#0d111a] md:hidden">
        <button
          type="button"
          onClick={() => setMobilePane("chat")}
          className={`flex-1 py-1.5 text-xs font-semibold ${
            mobilePane === "chat" ? "border-b-2 border-cyan-400 text-cyan-300" : "text-slate-400"
          }`}
        >
          <MessageSquare className="mr-1.5 inline h-3.5 w-3.5" />
          Story Chat
        </button>
        <button
          type="button"
          onClick={() => setMobilePane("dashboard")}
          className={`flex-1 py-1.5 text-xs font-semibold ${
            mobilePane === "dashboard" ? "border-b-2 border-rose-500 text-rose-300" : "text-slate-400"
          }`}
        >
          <User className="mr-1.5 inline h-3.5 w-3.5" />
          Tabletop HUD
        </button>
      </div>

      {isDesktop ? (
        <main className="flex min-h-0 flex-1 overflow-hidden">
          <PanelGroup direction="horizontal" autoSaveId="redgm-split-layout">
            <Panel defaultSize={58} minSize={32}>
              {chatPaneNode}
            </Panel>

            <PanelResizeHandle className="flex w-1.5 items-center justify-center bg-slate-900 hover:bg-cyan-600/40 transition-colors">
              <GripVertical className="h-4 w-3 text-slate-600" />
            </PanelResizeHandle>

            <Panel defaultSize={42} minSize={28}>
              {dashboardContent}
            </Panel>
          </PanelGroup>
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 overflow-hidden">
          {mobilePane === "chat" ? chatPaneNode : dashboardContent}
        </main>
      )}

      <CampaignCreatorModal
        open={campaignCreatorOpen}
        editCampaign={campaignCreatorEdit}
        onClose={() => {
          setCampaignCreatorOpen(false);
          setCampaignCreatorEdit(null);
        }}
        onCreated={async (id, name, options) => {
          const updatedList = await listCampaigns();
          setCampaigns(updatedList);
          await handleSelectCampaign(id);
          notify(`Created campaign "${name}".`);
          if (options?.launchIntro) {
            setCampaignCreatorOpen(false);
            setCampaignCreatorEdit(null);
            await runStreamedAction(
              "Begin the opening scene and welcome the crew.",
              false,
              undefined,
              (callbacks, signal) =>
                streamChatTurn(
                  {
                    campaign_id: id,
                    user_text: "Begin the opening scene and welcome the crew.",
                    is_intro: true,
                  },
                  callbacks,
                  signal,
                ),
              undefined,
              id,
            );
            await loadCampaignData(id, "main");
          }
        }}
        onUpdated={async (id, name) => {
          const updatedList = await listCampaigns();
          setCampaigns(updatedList);
          await loadCampaignData(id);
          notify(`Updated campaign "${name}".`);
        }}
        onNotify={notify}
      />

      {campaignContext && (
        <CharacterCreatorModal
          open={characterCreatorOpen}
          campaignId={campaignContext.campaign.id}
          campaignRevision={campaignContext.campaign.revision}
          soloRevision={campaignContext.solo.revision}
          onClose={() => setCharacterCreatorOpen(false)}
          onCreated={async (id, charName) => {
            setPreferredCharacterId(id);
            setClaimedCharId(id);
            setSpeakerId(id);
            safeStorageSet(userClaimedCharStorageKey(authStatus?.username, campaignContext.campaign.id), id);
            await refreshActiveCampaign();
            setCharacterCreatorOpen(false);
            notify(`Created ${charName} and attached to campaign.`);
          }}
          onNotify={notify}
        />
      )}

      <CoopModal
        open={coopOpen}
        campaignId={activeCampaignId}
        campaignName={activeCampaign?.name ?? null}
        characters={campaignContext?.characters ?? []}
        isAdmin={isEffectiveAdmin}
        currentUsername={authStatus?.username}
        playerName={playerName}
        claimedCharId={claimedCharId}
        protectOthers={protectOthers}
        roster={roster}
        activeTurn={activeTurn}
        onChangePlayerName={(name) => {
          setPlayerName(name);
          setStoredPlayerName(name);
        }}
        onChangeClaimedChar={(id) => {
          setClaimedCharId(id);
          safeStorageSet(userClaimedCharStorageKey(authStatus?.username, activeCampaignId), id);
          if (id) setSpeakerId(id);
        }}
        onChangeProtectOthers={setProtectOthers}
        onClose={() => setCoopOpen(false)}
        onNotify={notify}
      />

      <SettingsModal
        open={settingsOpen}
        initialTab={settingsInitialTab}
        isAdmin={isEffectiveAdmin}
        settings={llmSettings}
        authStatus={authStatus}
        uiScale={uiScale}
        uiWeight={uiWeight}
        onChangeUiScale={setUiScale}
        onChangeUiWeight={setUiWeight}
        onClose={() => setSettingsOpen(false)}
        onSaved={(updated) => {
          setLlmSettings(updated);
          notify(`Saved AI settings (${updated.model}).`);
        }}
        onAuthChanged={refreshInitial}
        onCorebookIndexed={async () => {
          const [h, skillsData] = await Promise.all([
            fetchHealth().catch(() => null),
            fetchSkillsCatalog().catch(() => ({ skills: {}, rules_indexed: false })),
          ]);
          if (h) setHealth(h);
          setCorebookSkills(skillsData.skills ?? {});
        }}
        onNotify={notify}
      />

      <AuthGateModal
        open={authBlocked || authModalOpen}
        blocking={authBlocked}
        authStatus={authStatus}
        onAuthenticated={refreshInitial}
        onClose={() => setAuthModalOpen(false)}
      />

      <CommandPalette
        open={searchOpen}
        campaignId={activeCampaignId}
        onClose={() => setSearchOpen(false)}
        onSelectEntry={handleInspectEntry}
      />

      {toast && (
        <button
          type="button"
          role="status"
          title="Click to dismiss"
          onClick={() => setToast(null)}
          className="fixed bottom-4 right-4 z-50 cursor-pointer rounded-lg border border-cyan-500/40 bg-[#101828] px-4 py-2.5 text-left text-xs font-medium text-slate-100 shadow-xl hover:border-cyan-400"
        >
          {toast}
        </button>
      )}
      </div>
    </div>
  );
}

export default App;
