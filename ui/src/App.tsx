import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { BookOpen, Compass, GripVertical, MessageSquare, User } from "lucide-react";
import {
  compressCampaignMemory,
  createCampaign,
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
  listCampaigns,
  logoutAuth,
  regenerateChatTurn,
  saveLLMSettings,
  sendPresence,
  setPrimaryCampaign,
  setStoredPlayerName,
  startCampaignSession,
  streamChatTurn,
  subscribeCampaignEvents,
  switchChatBranch,
  updateChatMessage,
} from "./api";
import { AuthGateModal } from "./components/AuthGateModal";
import nightCityBackdrop from "./assets/night-city-backdrop.jpg";
import { CampaignCreatorModal } from "./components/CampaignCreatorModal";
import { CampaignPanel } from "./components/CampaignPanel";
import { CharacterPanel } from "./components/CharacterPanel";
import { ChatPane, type StreamingTurnState } from "./components/ChatPane";
import { CommandPalette } from "./components/CommandPalette";
import { CoopModal } from "./components/CoopModal";
import { LibraryPanel } from "./components/LibraryPanel";
import { SettingsModal, type SettingsTab } from "./components/SettingsModal";
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
  const [coopOpen, setCoopOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [mobilePane, setMobilePane] = useState<"chat" | "dashboard">("chat");
  const [isDesktop, setIsDesktop] = useState<boolean>(() =>
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? true
      : window.matchMedia("(min-width: 768px)").matches,
  );
  const [streaming, setStreaming] = useState<StreamingTurnState | null>(null);
  const [toast, setToast] = useState<string | null>(null);

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
  const [protectOthers, setProtectOthers] = useState(false);
  const [compressingMemory, setCompressingMemory] = useState(false);
  const [roster, setRoster] = useState<CoopPlayer[]>([]);
  const [activeTurn, setActiveTurn] = useState<ActiveTurnInfo | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const activeCampaignIdRef = useRef<string | null>(activeCampaignId);
  const selfClientId = getClientId();

  useEffect(() => {
    activeCampaignIdRef.current = activeCampaignId;
  }, [activeCampaignId]);

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

  const loadCampaignData = useCallback(async (campId: string) => {
    const [ctx, tree] = await Promise.all([
      fetchCampaignContext(campId),
      fetchChatTree(campId),
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
    const scopedClaim = activeCampaignId
      ? safeStorageGet(userClaimedCharStorageKey(authStatus?.username, activeCampaignId)) || ""
      : "";
    const effectiveClaim = (scopedClaim && chars.some((c) => c.id === scopedClaim) ? scopedClaim : "") ||
      (claimedCharId && chars.some((c) => c.id === claimedCharId) ? claimedCharId : "");

    if (effectiveClaim) {
      if (effectiveClaim !== claimedCharId) setClaimedCharId(effectiveClaim);
      setSpeakerId(effectiveClaim);
    } else if (authStatus?.authenticated && authStatus.role === "user") {
      // Signed-in players shouldn't all default to the same first character; let them claim/create one.
      setSpeakerId((prev) => (prev && chars.some((c) => c.id === prev) ? prev : ""));
    } else if (!speakerId || !chars.some((c) => c.id === speakerId)) {
      setSpeakerId(chars[0].id);
    }
  }, [campaignContext?.characters, claimedCharId, speakerId, activeCampaignId, authStatus?.username, authStatus?.authenticated, authStatus?.role]);

  // Live Co-op presence heartbeat + SSE subscription
  useEffect(() => {
    if (!activeCampaignId) {
      setRoster([]);
      setActiveTurn(null);
      return;
    }

    const ping = () => {
      void sendPresence(activeCampaignId, {
        player_name: playerName,
        character_id: claimedCharId || null,
      })
        .then((res) => {
          if (Array.isArray(res?.players)) setRoster(res.players);
          if ("active_turn" in res) setActiveTurn(res.active_turn ?? null);
        })
        .catch(() => {
          // ignore offline / mocked environment
        });
    };
    ping();
    const heartbeat = setInterval(ping, 20000);

    let syncTimer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribeCampaignEvents(activeCampaignId, {
      onPresence: (data) => {
        if (Array.isArray(data.players)) setRoster(data.players);
        setActiveTurn(data.active_turn ?? null);
      },
      onTurnLock: (turn) => setActiveTurn(turn),
      onSync: () => {
        if (abortRef.current || syncTimer) return;
        syncTimer = setTimeout(() => {
          syncTimer = null;
          if (!abortRef.current) {
            void loadCampaignData(activeCampaignId);
            void listCampaigns().then(setCampaigns).catch(() => {});
          }
        }, 200);
      },
    });

    return () => {
      clearInterval(heartbeat);
      if (syncTimer) clearTimeout(syncTimer);
      unsubscribe();
    };
  }, [activeCampaignId, playerName, claimedCharId, loadCampaignData]);

  const handleSelectCampaign = async (id: string) => {
    abortRef.current?.abort();
    activeCampaignIdRef.current = id;
    setActiveCampaignId(id);
    setSelectedLibraryEntry((cur) => (cur?.source === "homebrew" ? null : cur));
    safeStorageSet(userCampaignStorageKey(authStatus?.username), id);
    try {
      await loadCampaignData(id);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Failed to load campaign");
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

  const handleCreateCampaign = async (name: string) => {
    try {
      const created = await createCampaign(name);
      const updatedList = await listCampaigns();
      setCampaigns(updatedList);
      await handleSelectCampaign(created.id);
      notify(`Created campaign "${created.name}".`);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Could not create campaign");
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
      const data = await exportChatBranch(activeCampaignId, chatTree?.active_leaf_id ?? undefined);
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
    await loadCampaignData(activeCampaignId);
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
      if (activeCampaignId) {
        await refreshActiveCampaign().catch(() => {});
      }
      abortRef.current = null;
      setStreaming(null);
    }
  };

  const handleSendTurn = async (
    text: string,
    opts: { overclock: boolean; luckSpend?: number; speakerCharacterId?: string; speakerName?: string },
  ) => {
    if (!activeCampaignId) return;
    await runStreamedAction(text, opts.overclock, opts.speakerName, (callbacks, signal) =>
      streamChatTurn(
        {
          campaign_id: activeCampaignId,
          user_text: text,
          overclock: opts.overclock,
          luck_spend: opts.luckSpend || undefined,
          speaker_character_id: opts.speakerCharacterId,
          speaker_name: opts.speakerName,
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
            parent_id: msg.parent_id,
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
  const canManageCampaigns =
    !authStatus || !authStatus.auth_enabled || authStatus.role === "admin" || authStatus.role === "open";

  const handleSignOut = async () => {
    await logoutAuth();
    setSettingsOpen(false);
    await refreshInitial();
    notify("Signed out.");
  };

  const dashboardContent = (
    <div className="flex h-full flex-col bg-[#0c101a]/88 backdrop-blur-[2px]">
      <div className="flex border-b border-slate-800/90 bg-[#0d111a]/95 px-2 pt-1.5">
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
            className={`inline-flex items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-semibold transition ${
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

      <div className="flex-1 overflow-y-auto">
        {rightTab === "character" && campaignContext && (
          <CharacterPanel
            campaignId={campaignContext.campaign.id}
            campaignRevision={campaignContext.campaign.revision}
            soloRevision={campaignContext.solo.revision}
            characters={campaignContext.characters}
            corebookSkills={corebookSkills}
            roster={roster}
            selfClientId={selfClientId}
            protectOthers={protectOthers}
            onRefresh={refreshActiveCampaign}
            onNotify={notify}
          />
        )}
        {rightTab === "character" && !campaignContext && (
          <div className="p-6 text-center text-xs text-slate-400">
            Select or create a campaign to manage characters.
          </div>
        )}

        {rightTab === "campaign" && campaignContext && (
          <CampaignPanel
            context={campaignContext}
            campaigns={campaigns}
            canManageCampaigns={canManageCampaigns}
            activeLeafId={chatTree?.active_leaf_id ?? null}
            onSelectCampaign={handleSelectCampaign}
            onSetPrimaryCampaign={handleSetPrimaryCampaign}
            onDeleteCampaign={handleDeleteCampaign}
            onOpenNewCampaign={() => {
              setCampaignCreatorEdit(null);
              setCampaignCreatorOpen(true);
            }}
            onOpenEditCampaign={() => {
              setCampaignCreatorEdit(campaignContext.campaign);
              setCampaignCreatorOpen(true);
            }}
            onCompressMemory={handleCompressMemory}
            compressingMemory={compressingMemory}
            onRefresh={refreshActiveCampaign}
            onNotify={notify}
          />
        )}
        {rightTab === "campaign" && !campaignContext && (
          <div className="p-6 text-center text-xs text-slate-400">
            Select or create a campaign to view scene notes.
          </div>
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

  const chatPaneNode = (
    <ChatPane
      campaignId={activeCampaignId}
      messages={chatTree?.active_branch ?? []}
      streaming={streaming}
      characters={campaignContext?.characters ?? []}
      selectedSpeakerId={speakerId}
      activeTurn={activeTurn}
      selfClientId={selfClientId}
      onChangeSpeakerId={setSpeakerId}
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

  return (
    <div className="relative flex h-screen w-screen flex-col overflow-hidden bg-[#07090f] text-slate-100">
      {/* Atmospheric Night City Backdrop */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
        <img
          src={nightCityBackdrop}
          alt=""
          className="h-full w-full object-cover opacity-25 saturate-110"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-[#07090f]/80 via-[#080b13]/72 to-[#06080d]/92" />
        <div className="cyber-grid-overlay absolute inset-0 opacity-75" />
        <div className="cyber-scanlines absolute inset-0 opacity-55" />
      </div>

      <div className="relative z-10 flex h-full w-full flex-col overflow-hidden">
      <TopBar
        health={health}
        campaigns={campaigns}
        activeCampaign={activeCampaign}
        llmSettings={llmSettings}
        revisionMismatch={Boolean(chatTree?.revision_mismatch)}
        coopCount={roster.length}
        authStatus={authStatus}
        onSelectCampaign={handleSelectCampaign}
        onCreateCampaign={handleCreateCampaign}
        onOpenNewCampaign={() => {
          setCampaignCreatorEdit(null);
          setCampaignCreatorOpen(true);
        }}
        onStartSession={handleStartSession}
        onExportChat={handleExportChat}
        onOpenCoop={() => setCoopOpen(true)}
        onOpenSettings={() => {
          setSettingsInitialTab("connection");
          setSettingsOpen(true);
        }}
        onOpenCorebookSettings={() => {
          setSettingsInitialTab("corebook");
          setSettingsOpen(true);
        }}
        onToggleThinkingMode={async (nextMode) => {
          try {
            const updated = await saveLLMSettings({ gm_thinking_mode: nextMode });
            setLlmSettings(updated);
            notify(
              nextMode === "balanced"
                ? "Switched to GM Balanced (same writing, less waiting)."
                : "Switched to GM Quality (full thinking on all passes).",
            );
          } catch (err) {
            notify(err instanceof Error ? err.message : "Failed to switch GM mode");
          }
        }}
        onOpenSearch={() => setSearchOpen(true)}
        onOpenAuth={() => setAuthModalOpen(true)}
        onSignOut={() => void handleSignOut()}
      />

      {/* Mobile pane switcher */}
      <div className="flex border-b border-slate-800 bg-[#0d111a] md:hidden">
        <button
          type="button"
          onClick={() => setMobilePane("chat")}
          className={`flex-1 py-2 text-xs font-semibold ${
            mobilePane === "chat" ? "border-b-2 border-cyan-400 text-cyan-300" : "text-slate-400"
          }`}
        >
          <MessageSquare className="mr-1.5 inline h-3.5 w-3.5" />
          Story Chat
        </button>
        <button
          type="button"
          onClick={() => setMobilePane("dashboard")}
          className={`flex-1 py-2 text-xs font-semibold ${
            mobilePane === "dashboard" ? "border-b-2 border-rose-500 text-rose-300" : "text-slate-400"
          }`}
        >
          <User className="mr-1.5 inline h-3.5 w-3.5" />
          Tabletop HUD
        </button>
      </div>

      {isDesktop ? (
        <main className="flex flex-1 overflow-hidden">
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
        <main className="flex flex-1 overflow-hidden">
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
        onCreated={async (id, name) => {
          const updatedList = await listCampaigns();
          setCampaigns(updatedList);
          await handleSelectCampaign(id);
          notify(`Created campaign "${name}".`);
        }}
        onUpdated={async (id, name) => {
          const updatedList = await listCampaigns();
          setCampaigns(updatedList);
          await loadCampaignData(id);
          notify(`Updated campaign "${name}".`);
        }}
        onNotify={notify}
      />

      <CoopModal
        open={coopOpen}
        campaignId={activeCampaignId}
        campaignName={activeCampaign?.name ?? null}
        characters={campaignContext?.characters ?? []}
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
        settings={llmSettings}
        authStatus={authStatus}
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
