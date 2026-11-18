import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { clearAllDrafts } from "./draftStorage";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sseResponse(events: Array<{ event: string; data: unknown }>): Response {
  const payload = events
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
    .join("");
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(payload));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("Cyberpunk RED GM UI", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    clearAllDrafts();
  });

  it("loads campaign, character stats, and streams an Overclock turn", async () => {
    const campaign = {
      id: "camp-1",
      name: "Watson Hustle",
      revision: 2,
      session_number: 1,
      character_ids: ["char-1"],
      state: {
        scene: "Afterlife Back Booth",
        summary: "Meeting Rogue",
        npcs: { Rogue: "Fixer" },
        objectives: {},
        discoveries: {},
        unresolved: {},
      },
    };
    const char = {
      id: "char-1",
      name: "Vee Mercer",
      stats: {
        INT: 6,
        REF: 8,
        DEX: 6,
        TECH: 5,
        COOL: 6,
        WILL: 6,
        LUCK: 6,
        MOVE: 6,
        BODY: 6,
        EMP: 6,
      },
      skills: { Handgun: 6 },
      hp: 40,
      max_hp: 40,
      humanity: 60,
      luck_remaining: 6,
      money: 500,
      inventory: { "Medium Pistol": 1 },
      revision: 1,
    };
    let branchState: {
      campaign_id: string;
      nodes: unknown[];
      active_branch: unknown[];
      active_leaf_id: string | null;
      current_revisions: { campaign_revision: number; solo_revision: number };
      revision_mismatch: boolean;
    } = {
      campaign_id: "camp-1",
      nodes: [],
      active_branch: [],
      active_leaf_id: null,
      current_revisions: { campaign_revision: 2, solo_revision: 0 },
      revision_mismatch: false,
    };

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") {
        return jsonResponse({ status: "ok", rules_indexed: true, indexed_pages: 456 });
      }
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.4,
          max_tokens: 1200,
          timeout_s: 60,
          mode: "two_pass",
        });
      }
      if (url === "/v1/skills") {
        return jsonResponse({
          skills: { Handgun: { stat: "REF", cost: 1, specializable: false } },
          rules_indexed: true,
        });
      }
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse(branchState);
      }
      if (url.startsWith("/v1/library")) {
        return jsonResponse({
          items: [
            {
              id: "corebook:skill:handgun",
              name: "Handgun",
              category: "skill",
              source: "corebook",
              created_by: "corebook",
              summary: "Firing pistol-sized firearms.",
              description: "Firing pistol-sized firearms.",
              stats: { stat: "REF" },
              tags: ["skill"],
              printed_page: 83,
            },
          ],
        });
      }
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [char],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      if (url === "/v1/chat/turn") {
        const userMsg = {
          id: "u1",
          campaign_id: "camp-1",
          parent_id: null,
          role: "user",
          content: "Draw and fire",
          raw_content: "Draw and fire",
          model: "",
          campaign_revision: 2,
          solo_revision: 0,
          metadata: { overclock: true },
          is_active: true,
          created_at: "2026-11-15T00:00:00Z",
        };
        const asstMsg = {
          id: "a1",
          campaign_id: "camp-1",
          parent_id: "u1",
          role: "assistant",
          content: "Your shot clips the drone.",
          raw_content: "Your shot clips the drone.",
          model: "llama3",
          campaign_revision: 2,
          solo_revision: 0,
          metadata: {
            rolls: [
              {
                actor: "Vee Mercer",
                skill: "Handgun",
                stat: "REF",
                dv: 13,
                total: 22,
                success: true,
                overclock: true,
              },
            ],
            citation_cards: [
              {
                id: "corebook:skill:handgun",
                name: "Handgun",
                category: "skill",
                source: "corebook",
                created_by: "corebook",
                summary: "Firing pistols.",
                description: "Firing pistols.",
                stats: {},
                tags: [],
                printed_page: 83,
              },
            ],
          },
          is_active: true,
          created_at: "2026-11-15T00:00:01Z",
        };
        branchState = {
          ...branchState,
          nodes: [userMsg, asstMsg],
          active_branch: [userMsg, asstMsg],
          active_leaf_id: "a1",
        };
        return sseResponse([
          { event: "text_delta", data: { delta: "Your shot clips the drone." } },
          {
            event: "turn_done",
            data: {
              turn_id: "t1",
              user_message: userMsg,
              assistant_message: asstMsg,
              citations: [],
              rolls: [],
              state_patches: [],
              library_added: [],
              warnings: [],
              compression_recommended: false,
            },
          },
        ]);
      }
      return jsonResponse({});
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText(/HP 40 \/ 40/i).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/500 eb/i).length).toBeGreaterThan(0);

    // Toggle Overclock and submit action
    fireEvent.click(screen.getAllByRole("button", { name: /Overclock/i })[0]);
    const box = screen.getAllByPlaceholderText(/Describe your action/i)[0];
    fireEvent.change(box, { target: { value: "Draw and fire" } });
    fireEvent.click(screen.getAllByRole("button", { name: /^Send$/i })[0]);

    await waitFor(() => {
      expect(screen.getAllByText(/Your shot clips the drone\./i).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/22 vs DV 13/i).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/chat/turn",
      expect.objectContaining({ method: "POST" }),
    );

    // Switch to Campaign tab and Rulebook tab
    fireEvent.click(screen.getByRole("button", { name: /^Campaign$/i }));
    expect(screen.getByDisplayValue("Afterlife Back Booth")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Rulebook$/i }));
    await waitFor(() => {
      expect(screen.getByText(/Firing pistol-sized firearms/i)).toBeInTheDocument();
    });

    // Open AI Connection settings modal
    fireEvent.click(screen.getByRole("button", { name: /^Settings$/i }));
    expect(screen.getByText(/AI Game Master Connection/i)).toBeInTheDocument();
  });

  it("shows branch mismatch warning, swipe pager, regenerate, and Ctrl+K search", async () => {
    const campaign = {
      id: "camp-2",
      name: "Kabuki Nights",
      revision: 3,
      session_number: 2,
      character_ids: [],
      state: {
        scene: "Kabuki Market",
        summary: "",
        npcs: {},
        objectives: {},
        discoveries: {},
        unresolved: {},
      },
    };
    const u1 = {
      id: "u1",
      campaign_id: "camp-2",
      parent_id: null,
      role: "user",
      content: "Inspect the vendor stall",
      raw_content: "Inspect the vendor stall",
      model: "",
      campaign_revision: 1,
      solo_revision: 0,
      metadata: {},
      is_active: true,
      created_at: "2026-11-15T00:00:00Z",
      sibling_index: 0,
      sibling_count: 1,
      sibling_ids: ["u1"],
    };
    const a1 = {
      id: "a1",
      campaign_id: "camp-2",
      parent_id: "u1",
      role: "assistant",
      content: "Branch A outcome.",
      raw_content: "Branch A outcome.",
      model: "llama3",
      campaign_revision: 1,
      solo_revision: 0,
      metadata: {},
      is_active: true,
      created_at: "2026-11-15T00:00:01Z",
      sibling_index: 0,
      sibling_count: 2,
      sibling_ids: ["a1", "a2"],
    };
    const a2 = {
      ...a1,
      id: "a2",
      content: "Branch B outcome.",
      raw_content: "Branch B outcome.",
      sibling_index: 1,
    };

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: false });
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.4,
          max_tokens: 1200,
          timeout_s: 60,
          mode: "two_pass",
        });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: false });
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: "camp-2",
          nodes: [u1, a1, a2],
          active_branch: [u1, a1],
          active_leaf_id: "a1",
          current_revisions: { campaign_revision: 3, solo_revision: 0 },
          revision_mismatch: true,
        });
      }
      if (url === "/v1/chat/branch") {
        return jsonResponse({
          campaign_id: "camp-2",
          nodes: [u1, a1, a2],
          active_branch: [u1, a2],
          active_leaf_id: "a2",
          current_revisions: { campaign_revision: 3, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url.startsWith("/v1/library")) {
        return jsonResponse({
          items: [
            {
              id: "homebrew:camp-2:gear:cyber-optic",
              name: "Kiroshi Mono-Optic",
              category: "cyberware",
              source: "homebrew",
              created_by: "user",
              summary: "Custom night-vision optic.",
              description: "Custom night-vision optic.",
              stats: { cost_eb: 500 },
              tags: ["cyberware"],
            },
          ],
        });
      }
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      return jsonResponse({});
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText(/Branch A outcome\./i).length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/Branch State Differs/i)).toBeInTheDocument();
    expect(screen.getByText(/No BYOC/i)).toBeInTheDocument();
    expect(screen.getAllByText("1/2").length).toBeGreaterThan(0);

    // Switch branch via next arrow
    fireEvent.click(screen.getAllByTitle("Next branch")[0]);
    await waitFor(() => {
      expect(screen.getAllByText(/Branch B outcome\./i).length).toBeGreaterThan(0);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/chat/branch",
      expect.objectContaining({ method: "POST" }),
    );

    // Open Ctrl+K palette and search
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search Corebook skills/i)).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText(/Kiroshi Mono-Optic/i)).toBeInTheDocument();
    });
  });

  it("supports QoL message deletion, in-place editing, guided retry, and Co-op modal", async () => {
    const campaign = {
      id: "camp-qol",
      name: "Co-op Edge",
      revision: 1,
      session_number: 2,
      character_ids: [],
      state: { scene: "Kabuki", summary: "", npcs: {}, objectives: {}, discoveries: {}, unresolved: {} },
    };
    const u1 = {
      id: "u1",
      campaign_id: "camp-qol",
      parent_id: null,
      role: "user",
      content: "Check perimeter",
      raw_content: "Check perimeter",
      model: "",
      campaign_revision: 1,
      solo_revision: 0,
      metadata: { speaker_name: "Vee" },
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
    };
    const a1 = {
      id: "a1",
      campaign_id: "camp-qol",
      parent_id: "u1",
      role: "assistant",
      content: "Rain slicks the chrome.",
      raw_content: "Rain slicks the chrome.",
      model: "llama3",
      campaign_revision: 1,
      solo_revision: 0,
      metadata: {},
      is_active: true,
      created_at: "2026-01-01T00:00:01Z",
    };

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: true, lan_enabled: true });
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.4,
          max_tokens: 1200,
          timeout_s: 60,
          mode: "two_pass",
        });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: true });
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: "camp-qol",
          nodes: [u1, a1],
          active_branch: [u1, a1],
          active_leaf_id: "a1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url === "/v1/chat/message/update") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        const updatedA1 = { ...a1, content: body.content, metadata: { edited: true } };
        return jsonResponse({
          campaign_id: "camp-qol",
          nodes: [u1, updatedA1],
          active_branch: [u1, updatedA1],
          active_leaf_id: "a1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url === "/v1/chat/delete") {
        return jsonResponse({
          campaign_id: "camp-qol",
          nodes: [u1],
          active_branch: [u1],
          active_leaf_id: "u1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url.startsWith("/v1/network/info")) {
        return jsonResponse({
          bind_host: "0.0.0.0",
          port: 8765,
          lan_enabled: true,
          pin_required: false,
          lan_ips: ["192.168.1.42"],
          join_urls: ["http://192.168.1.42:8765/?campaign=camp-qol"],
          roster: [{ client_id: "c1", player_name: "Host", character_id: null }],
          active_turn: null,
        });
      }
      if (url.startsWith("/v1/campaigns/") && url.endsWith("/presence")) {
        return jsonResponse({ players: [{ client_id: "c1", player_name: "Host" }], active_turn: null });
      }
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      return jsonResponse({});
    });

    render(<App />);
    await waitFor(() => {
      expect(screen.getAllByText(/Rain slicks the chrome\./i).length).toBeGreaterThan(0);
    });

    // Open Party modal and verify LAN join URL renders
    fireEvent.click(screen.getByTitle(/Party players/i));
    await waitFor(() => {
      expect(screen.getByText("http://192.168.1.42:8765/?campaign=camp-qol")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByLabelText("Close party settings"));

    // Edit assistant message in place
    const editButtons = screen.getAllByLabelText("Edit text in-place");
    fireEvent.click(editButtons[1]);
    const textboxes = screen.getAllByRole("textbox");
    const editBox = textboxes.find((el) => (el as HTMLTextAreaElement).value === "Rain slicks the chrome.");
    expect(editBox).toBeDefined();
    fireEvent.change(editBox!, { target: { value: "Neon flickers overhead." } });
    fireEvent.click(screen.getByText("Save Text"));

    await waitFor(() => {
      expect(screen.getAllByText(/Neon flickers overhead\./i).length).toBeGreaterThan(0);
    });

    // Two-step inline delete message
    const delButtons = screen.getAllByLabelText("Delete message");
    fireEvent.click(delButtons[1]);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/chat/delete",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("renders inline color flair in messages and keeps scroll position when scrolled up", async () => {
    const campaign = {
      id: "camp-color",
      name: "Color & Scroll",
      revision: 1,
      session_number: 1,
      character_ids: [],
      state: {
        scene: "Watson Docks",
        summary: "",
        npcs: {},
        objectives: {},
        discoveries: {},
        unresolved: {},
      },
    };
    const u1 = {
      id: "cu1",
      campaign_id: "camp-color",
      parent_id: null,
      role: "user" as const,
      content: "Scan [[cyan:Arasaka Crate]] now.",
      metadata: {},
      sibling_ids: ["cu1"],
      sibling_index: 0,
      created_at: "2026-01-01T00:00:00Z",
    };
    const a1 = {
      id: "ca1",
      campaign_id: "camp-color",
      parent_id: "cu1",
      role: "assistant" as const,
      content: "Warning: [[rose:Adam Smasher]] signal nearby. Ignore `[[cyan:raw code]]`.",
      metadata: {},
      sibling_ids: ["ca1"],
      sibling_index: 0,
      created_at: "2026-01-01T00:00:01Z",
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: true, indexed_pages: 456 });
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          temperature: 0.4,
          max_tokens: 1200,
          mode: "two_pass",
        });
      }
      if (url === "/v1/library/skills/corebook") return jsonResponse({ skills: {} });
      if (url.startsWith("/v1/library?") || url === "/v1/library") return jsonResponse({ items: [] });
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: "camp-color",
          nodes: [u1, a1],
          active_branch: [u1, a1],
          active_leaf_id: "ca1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url.startsWith("/v1/network/info")) {
        return jsonResponse({
          bind_host: "127.0.0.1",
          port: 8765,
          lan_enabled: false,
          pin_required: false,
          lan_ips: [],
          join_urls: [],
          roster: [],
          active_turn: null,
        });
      }
      if (url.startsWith("/v1/campaigns/") && url.endsWith("/presence")) {
        return jsonResponse({ players: [], active_turn: null });
      }
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      return jsonResponse({});
    });

    const { container } = render(<App />);
    await waitFor(() => {
      expect(screen.getByText("Arasaka Crate")).toBeInTheDocument();
    });

    const userColored = container.querySelector('[data-cpr-color="cyan"]');
    const gmColored = container.querySelector('[data-cpr-color="rose"]');
    expect(userColored?.textContent).toBe("Arasaka Crate");
    expect(gmColored?.textContent).toBe("Adam Smasher");
    expect(screen.getByText("[[cyan:raw code]]")).toBeInTheDocument();

    // Open color swatch bar & insert a highlight token
    fireEvent.click(screen.getByRole("button", { name: "Color" }));
    fireEvent.click(screen.getByRole("button", { name: "Amber" }));
    expect((screen.getByPlaceholderText("Describe your action...") as HTMLTextAreaElement).value).toContain(
      "[[amber:highlighted text]]",
    );

    // Simulate user scrolling up away from bottom
    const scroller = screen.getByTestId("chat-scroll-container") as HTMLDivElement;
    Object.defineProperty(scroller, "scrollHeight", { value: 1200, configurable: true });
    Object.defineProperty(scroller, "clientHeight", { value: 300, configurable: true });
    scroller.scrollTop = 120;
    fireEvent.scroll(scroller);

    const jumpBtn = await screen.findByRole("button", { name: /Jump to latest/i });
    expect(jumpBtn).toBeInTheDocument();
    expect(scroller.scrollTop).toBe(120);

    fireEvent.click(jumpBtn);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Jump to latest/i })).not.toBeInTheDocument();
    });
    expect(scroller.scrollTop).toBe(1200);

    // Inline popovers are mutually exclusive & Escape closes Edit / Modals cleanly
    fireEvent.click(screen.getAllByLabelText("Edit text in-place")[0]);
    expect(screen.getByText("Save Text")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("Save Text")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Settings$/i }));
    expect(screen.getByRole("dialog", { name: /AI Game Master Connection/i })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /AI Game Master Connection/i })).not.toBeInTheDocument();
  });

  it("supports pre-roll LUCK stepper, world clocks, and compress-to-library controls", async () => {
    let clocksState = [
      { id: "ncpd-heat", name: "NCPD Heat", filled: 1, segments: 4, category: "heat", visibility: "public", note: "Patrol arrives" },
    ];
    const campaign = {
      id: "camp-1",
      name: "Kabuki Run",
      session_number: 1,
      revision: 1,
      state: {
        scene: "Watson alley",
        summary: "Tracking a courier.",
        npcs: {},
        objectives: {},
        discoveries: {},
        unresolved: {},
      },
      created_at: "2026-11-15T00:00:00Z",
      updated_at: "2026-11-15T00:00:00Z",
    };
    const char = {
      id: "char-1",
      name: "Vee Mercer",
      role: "Solo",
      stats: { INT: 6, REF: 8, DEX: 7, TECH: 5, COOL: 6, WILL: 6, LUCK: 6, MOVE: 6, BODY: 6, EMP: 6 },
      skills: { Handgun: 6 },
      hp: 40,
      max_hp: 40,
      humanity: 60,
      luck_remaining: 6,
      money: 500,
      inventory: {},
      revision: 1,
    };
    let branchState: {
      campaign_id: string;
      nodes: unknown[];
      active_branch: unknown[];
      active_leaf_id: string;
      current_revisions: { campaign_revision: number; solo_revision: number };
      revision_mismatch: boolean;
    } = {
      campaign_id: "camp-1",
      nodes: [],
      active_branch: [],
      active_leaf_id: "a0",
      current_revisions: { campaign_revision: 1, solo_revision: 0 },
      revision_mismatch: false,
    };

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ ok: true, rules_indexed: true, rules_entries: 1200 });
      if (url === "/v1/network/info") return jsonResponse({ host_urls: [], pin_required: false, roster: [], active_turn: null });
      if (url.startsWith("/v1/campaigns/camp-1/clocks")) {
        if ((init?.method ?? "GET") === "POST") {
          const body = JSON.parse(String(init?.body ?? "{}"));
          if (body.action === "tick") {
            clocksState = clocksState.map((c) =>
              c.id === body.id ? { ...c, filled: Math.max(0, Math.min(c.segments, c.filled + body.delta)) } : c,
            );
          }
        }
        return jsonResponse({ campaign_id: "camp-1", clocks: clocksState });
      }
      if (url === "/v1/chat/compress") {
        return jsonResponse({
          campaign: { ...campaign, revision: 2 },
          library_upserted: [{ id: "homebrew:npc:kira", name: "Kira", category: "npc" }],
          compressed_messages: 4,
          clocks: clocksState,
          warnings: [],
        });
      }
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.4,
          max_tokens: 1200,
          timeout_s: 60,
          mode: "two_pass",
        });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: true });
      if (url.startsWith("/v1/chat/tree")) return jsonResponse(branchState);
      if (url.startsWith("/v1/library")) return jsonResponse({ items: [] });
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [char],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 90 }, characters: {} },
            },
          });
        }
      }
      if (url === "/v1/chat/turn") {
        const reqBody = JSON.parse(String(init?.body ?? "{}"));
        const userMsg = {
          id: "u1",
          campaign_id: "camp-1",
          parent_id: null,
          role: "user",
          content: reqBody.user_text,
          raw_content: reqBody.user_text,
          model: "",
          campaign_revision: 1,
          solo_revision: 0,
          metadata: { luck_spend: reqBody.luck_spend },
          is_active: true,
          created_at: "2026-11-15T00:00:00Z",
        };
        const asstMsg = {
          id: "a1",
          campaign_id: "camp-1",
          parent_id: "u1",
          role: "assistant",
          content: "Clean hit.",
          raw_content: "Clean hit.",
          model: "llama3",
          campaign_revision: 1,
          solo_revision: 0,
          metadata: {
            rolls: [
              { actor: "Vee Mercer", skill: "Handgun", stat: "REF", dv: 13, total: 18, luck_spent: reqBody.luck_spend, success: true, dice: [5] },
            ],
          },
          is_active: true,
          created_at: "2026-11-15T00:00:01Z",
        };
        branchState = { ...branchState, nodes: [userMsg, asstMsg], active_branch: [userMsg, asstMsg], active_leaf_id: "a1" };
        return sseResponse([
          { event: "text_delta", data: { delta: "Clean hit." } },
          { event: "turn_done", data: { turn_id: "t1", user_message: userMsg, assistant_message: asstMsg, citations: [], rolls: [], state_patches: [], library_added: [], warnings: [], compression_recommended: false } },
        ]);
      }
      return jsonResponse({});
    });

    render(<App />);
    await waitFor(() => {
      expect(screen.getAllByText(/HP 40 \/ 40/i).length).toBeGreaterThan(0);
    });

    // Verify redesigned CharacterPanel tabs (Skills & Roll / Gear / Log)
    fireEvent.click(screen.getByRole("button", { name: /^Gear \(0\)$/i }));
    expect(screen.getByText(/Empty gear bag\./i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Log$/i }));
    await waitFor(() => {
      expect(screen.getByText(/Recent Audit History/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /^Skills & Roll$/i }));
    expect(screen.getByText(/Authoritative Skill Check/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Increase Luck spend" }));
    expect(screen.getByText("+1/6")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Describe your action/i), { target: { value: "Take aim" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/i }));

    await waitFor(() => {
      expect(screen.getAllByText(/LUCK \+1/i).length).toBeGreaterThan(0);
    });
    const turnCall = fetchMock.mock.calls.find(([url]) => url === "/v1/chat/turn");
    expect(JSON.parse(String(turnCall?.[1]?.body))).toMatchObject({ luck_spend: 1 });

    fireEvent.click(screen.getByRole("button", { name: /^Campaign$/i }));
    await waitFor(() => {
      expect(screen.getByText("NCPD Heat")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Increment NCPD Heat" }));
    await waitFor(() => {
      expect(screen.getByText("2/4")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Compress to Library/i }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/v1/chat/compress", expect.objectContaining({ method: "POST" }));
    });
  });

  it("enforces User vs Admin sign-in and exposes Prompts & Network settings for Admin", async () => {
    let signedInRole: "anon" | "user" | "admin" = "anon";
    let savedPrompts = {
      system_persona: "Default Night City persona",
      world_rules_prefix: "",
      planner_extra: "",
      narrator_extra: "",
      chronicler_extra: "",
      archivist_extra: "",
    };
    let savedServer = {
      bind_host: "127.0.0.1",
      port: 8765,
      allowed_origins: [] as string[],
      public_url: "",
    };

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") {
        return jsonResponse({ status: "ok", rules_indexed: true, auth_enabled: true });
      }
      if (url === "/v1/auth/status") {
        return jsonResponse({
          auth_enabled: true,
          pin_only_mode: false,
          authenticated: signedInRole !== "anon",
          role: signedInRole,
          username: signedInRole === "admin" ? "netwatch" : signedInRole === "user" ? "edge" : null,
          admin_configured: true,
          user_configured: true,
          user_passcode_configured: false,
          allow_guest_users: false,
          can_bootstrap: false,
        });
      }
      if (url === "/v1/auth/login" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        signedInRole = body.mode === "admin" ? "admin" : "user";
        return jsonResponse({
          token: `tok-${signedInRole}`,
          role: signedInRole,
          username: body.username || signedInRole,
          expires_in: 3600,
        });
      }
      if (url === "/v1/skills") {
        return jsonResponse({ skills: { Handgun: { stat: "REF", cost: 1, specializable: false } }, rules_indexed: true });
      }
      if (url === "/v1/game" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        if (body.action === "list_campaigns") return jsonResponse({ action: "list_campaigns", result: [] });
      }
      if (url === "/v1/settings/llm" && (!init || init.method !== "POST")) {
        if (signedInRole !== "admin") return jsonResponse({ detail: "Admin access required" }, 403);
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.75,
          max_tokens: 1200,
          timeout_s: 90,
          mode: "two_pass",
          gm_thinking_mode: "quality",
        });
      }
      if (url === "/v1/settings/llm" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.75,
          max_tokens: 1200,
          timeout_s: 90,
          mode: "two_pass",
          gm_thinking_mode: body.gm_thinking_mode ?? "quality",
        });
      }
      if (url === "/v1/settings/all") {
        return jsonResponse({
          llm: {
            base_url: "http://127.0.0.1:11434/v1",
            model: "llama3",
            has_api_key: false,
            api_key_masked: "",
            temperature: 0.75,
            max_tokens: 1200,
            timeout_s: 90,
            mode: "two_pass",
            gm_style: "grounded",
            narrator_length: "standard",
            gm_thinking_mode: "quality",
            enable_chronicler: true,
            history_window: 14,
            compression_threshold: 14,
            citation_limit: 4,
            default_time_step_minutes: 0,
          },
          prompts: savedPrompts,
          prompt_defaults: { ...savedPrompts },
          server: savedServer,
          auth_policy: {
            allow_guest_users: false,
            user_passcode_configured: false,
            admin_configured: true,
            user_configured: true,
            accounts: [{ username: "netwatch", role: "admin", created_at: "2026-01-01", source: "file" }],
          },
          runtime: {
            active_host: "127.0.0.1",
            active_port: 8765,
            in_docker: false,
            restart_supported: true,
            restart_required: false,
          },
        });
      }
      if (url === "/v1/settings/prompts" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        savedPrompts = { ...savedPrompts, ...body };
        return jsonResponse({ prompts: savedPrompts, prompt_defaults: savedPrompts });
      }
      if (url === "/v1/settings/server" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        savedServer = { ...savedServer, ...body };
        return jsonResponse({
          server: savedServer,
          active_host: "127.0.0.1",
          active_port: 8765,
          in_docker: false,
          restart_supported: true,
          restart_required: true,
        });
      }
      return jsonResponse({});
    });

    render(<App />);

    // Initially blocked on User Sign-In gate
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /Cyberpunk RED GM Access/i })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "edge" } });
    fireEvent.change(screen.getByPlaceholderText(/Enter password/i), { target: { value: "player-pass" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign In as Player/i }));

    await waitFor(() => {
      expect(screen.getByText("edge")).toBeInTheDocument();
    });
    // Regular User can open User Settings (Display + Account) without Admin tabs
    fireEvent.click(screen.getByRole("button", { name: /^Settings$/i }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /User Settings/i })).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /^Display$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Account$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Prompts$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Network$/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Close settings/i }));

    // Switch to Admin via TopBar Admin Login button
    fireEvent.click(screen.getByRole("button", { name: /Admin Login/i }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /Cyberpunk RED GM Access/i })).toBeInTheDocument();
    });
    fireEvent.change(screen.getByPlaceholderText(/Enter admin username/i), { target: { value: "netwatch" } });
    fireEvent.change(screen.getByPlaceholderText(/Enter password/i), { target: { value: "admin-pass" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign In as Admin/i }));

    await waitFor(() => {
      expect(screen.getByText("netwatch")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^Settings$/i })).toBeInTheDocument();
    });

    // Open Admin Control Center -> Turn & Tuning (with Turn Architecture + Chronicler + GM Mode), Prompts, & Network tabs
    fireEvent.click(screen.getByRole("button", { name: /^Settings$/i }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /AI Game Master Connection/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Turn & Tuning/i }));
    expect(screen.getByText(/Turn Architecture & Chronicler/i)).toBeInTheDocument();
    const balancedBtn = screen.getByRole("button", { name: /GM Balanced/i });
    expect(screen.getByRole("button", { name: /GM Quality/i })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(balancedBtn);
    expect(balancedBtn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Save Turn Tuning/i }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/settings/llm",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"gm_thinking_mode":"balanced"'),
        }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: /^Settings$/i }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /AI Game Master Connection/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Prompts$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /GM Voice & Persona/i }));
    const personaBox = await screen.findByDisplayValue("Default Night City persona");
    fireEvent.change(personaBox, { target: { value: "Gritty 2045 fixer tone" } });
    fireEvent.click(screen.getByRole("button", { name: /Save Prompts/i }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/v1/settings/prompts", expect.objectContaining({ method: "POST" }));
    });

    fireEvent.click(screen.getByRole("button", { name: /^Network$/i }));
    fireEvent.click(screen.getByRole("button", { name: /0\.0\.0\.0 \(LAN \/ Public\)/i }));
    fireEvent.change(screen.getByDisplayValue("8765"), { target: { value: "9090" } });
    fireEvent.click(screen.getByRole("button", { name: /Save Network Settings/i }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/v1/settings/server", expect.objectContaining({ method: "POST" }));
    });
  });

  it("opens full sheet Character Creator with beginner info, lifepath, backstory, and Bio tab editing", async () => {
    const campaign = {
      id: "camp-cc",
      name: "Watson Origin",
      revision: 1,
      session_number: 1,
      character_ids: [] as string[],
      state: { scene: "Charter Hill", summary: "", npcs: {}, objectives: {}, discoveries: {}, unresolved: {} },
    };
    let createdChar: Record<string, unknown> | null = null;

    const refPayload = {
      rules_indexed: true,
      stat_names: ["INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP"],
      stats: {
        INT: { name: "Intelligence", short: "Knowledge", mechanics: "Perception and deduction.", tip: "Great for Netrunners." },
        REF: { name: "Reflexes", short: "Ranged aim", mechanics: "Initiative and ranged shots.", tip: "Critical for Solos." },
        DEX: { name: "Dexterity", short: "Agility", mechanics: "Evasion and melee.", tip: "Helps you dodge bullets." },
        TECH: { name: "Technique", short: "Tinkering", mechanics: "Hardware and cybertech.", tip: "Great for Techs and Medtechs." },
        COOL: { name: "Cool", short: "Poise", mechanics: "Street presence and persuasion.", tip: "Helps in social encounters." },
        WILL: { name: "Willpower", short: "Grit", mechanics: "Mental toughness and HP.", tip: "Boosts HP and Concentration." },
        LUCK: { name: "Luck", short: "Fortune", mechanics: "Spend before rolling.", tip: "Saves clutch rolls." },
        MOVE: { name: "Movement", short: "Speed", mechanics: "Combat movement.", tip: "MOVE × 2m per Move Action." },
        BODY: { name: "Body", short: "Physique", mechanics: "Stamina, HP, and Death Saves.", tip: "Keeps you alive." },
        EMP: { name: "Empathy", short: "Humanity", mechanics: "Reading people & Humanity = EMP × 10.", tip: "Limits how much chrome fits safely." },
      },
      methods: [
        { id: "streetrat", name: "Streetrat (Templates)", badge: "Beginner", summary: "Quick official build", rules: "Roll 1d10 on your Role table." },
        { id: "edgerunner", name: "Edgerunner (Fast & Dirty)", badge: "Flexible", summary: "Roll STATs & tune skills", rules: "Roll 10 STAT columns & tune 86 skill pts." },
        { id: "complete_package", name: "Complete Package (Calculated)", badge: "Pro", summary: "Full 62/86/2550", rules: "62 STAT pts, 86 skill pts, 2,550 eb." },
        { id: "freeform", name: "Freeform / Custom Sheet", badge: "Custom", summary: "No budget locks", rules: "Unconstrained custom character." },
      ],
      roles: [
        {
          name: "Solo",
          ability: "Combat Awareness",
          ability_summary: "Allocate points each turn into threat detection, initiative, or precision.",
          tagline: "Elite mercenary",
          best_for: "Great first character for direct combat.",
          key_stats: ["REF", "DEX", "BODY"],
          page: 144,
          templates: [[6, 8, 7, 4, 6, 7, 6, 6, 7, 5]],
          skills: {
            Athletics: 2,
            Brawling: 2,
            Concentration: 2,
            Conversation: 2,
            Education: 2,
            Evasion: 6,
            "First Aid": 6,
            Handgun: 6,
            "Human Perception": 2,
            Perception: 6,
            Persuasion: 2,
            Stealth: 2,
          },
          starting_weapons: [{ type: "fixed", item: "Heavy Pistol", qty: 1 }],
          starting_armor: ["Light Armorjack Body (SP 11)", "Light Armorjack Head (SP 11)"],
          starting_outfit: ["Agent"],
          starting_cyberware: [{ name: "Neural Link", hl: 7, install: "Clinic", notes: "Socket" }],
          starting_hl: 7,
          role_lifepath: [{ key: "Type", label: "Solo Type", options: ["Bodyguard", "Street Enforcer"] }],
        },
      ],
      skills: [
        { name: "Handgun", stat: "REF", cost: 1, basic: false, basic_skill_name: "Handgun", specializable: false, group: "Ranged", summary: "Firing pistols.", description: "Aim and shoot pistols." },
        { name: "Athletics", stat: "DEX", cost: 1, basic: true, basic_skill_name: "Athletics", specializable: false, group: "Body", summary: "Running and climbing.", description: "Physical agility." },
      ],
      cultural_regions: [{ region: "North American", languages: ["Streetslang", "English", "Spanish"], notes: "NUSA & Night City." }],
      lifepath_tables: {
        personalities: ["Shy and secretive", "Arrogant and proud"],
        clothing_styles: ["Generic Chic", "Urban Flash"],
        hairstyles: ["Mohawk", "Neat, short"],
        affectations: ["Tattoos", "Mirrorshades"],
        values: ["Honor", "Money"],
        feelings_about_people: ["I stay neutral."],
        valued_people: ["A friend"],
        valued_possessions: ["A weapon"],
        family_backgrounds: ["Edgerunners"],
        childhood_environments: ["Ran on the Street"],
        family_crises: ["Betrayed and lost everything."],
        life_goals: ["Get off The Street."],
        enemy_causes: ["Saved someone's life"],
        enemy_backup: ["Just themselves"],
        enemy_revenge: ["Avoid them"],
        friend_relationships: ["Like an older sibling"],
        love_tragedies: ["Lover vanished"],
      },
      shop: {
        weapon: [
          {
            id: "w-malorian",
            name: "Malorian Arms 3516 (Exotic VH Pistol)",
            category: "weapon",
            cost_eb: 10000,
            summary: "5d6 dmg · ROF 1 · 4 shots · Exotic VH Pistol.",
            description: "Custom Johnny Silverhand hand cannon.",
            printed_page: 348,
            stats: { subtype: "exotic", quality: "Exotic", weapon_class: "Very Heavy Pistol", damage: "5d6" },
          },
          {
            id: "w-ronin",
            name: "Militech \"Ronin\" Light Assault (Assault Rifle)",
            category: "weapon",
            cost_eb: 500,
            summary: "5d6 dmg · Standard quality Assault Rifle.",
            description: "Reliable Night City street carbine.",
            printed_page: 342,
            stats: { subtype: "ranged", quality: "Standard", weapon_class: "Assault Rifle", damage: "5d6" },
          },
        ],
        armor: [
          {
            id: "a-haj-body",
            name: "Heavy Armorjack Body Armor (SP 13)",
            category: "armor",
            cost_eb: 500,
            summary: "SP 13 · Body · -2 Armor Penalty.",
            description: "Reinforced Kevlar + laminated plates.",
            printed_page: 350,
            stats: { sp: 13, location: "body" },
          },
        ],
        cyberware: [
          {
            id: "c-neural-link",
            name: "Neural Link",
            category: "cyberware",
            cost_eb: 500,
            summary: "Wired nervous system interface.",
            description: "Foundation Neuralware slot.",
            printed_page: 360,
            stats: { humanity_loss: "7 (2d6)", hl: 7, install: "Clinic" },
          },
        ],
        gear: [],
        program: [],
        hardware: [
          {
            id: "h-cyberdeck",
            name: "Cyberdeck (7 Slots)",
            category: "hardware",
            cost_eb: 500,
            summary: "Standard NET terminal with 7 hardware/program slots.",
            description: "Standard 7-slot Cyberdeck.",
            printed_page: 353,
            stats: { subtype: "cyberdeck" },
          },
        ],
        vehicle: [
          {
            id: "corebook:vehicle:roadbike",
            name: "Roadbike",
            category: "vehicle",
            cost_eb: 20000,
            summary: "Land · 35 SDP · 2 Seats · 20 MOVE / 60 MPH",
            description: "Two-wheeled street bike.",
            printed_page: 190,
            stats: { subtype: "Land Vehicle" },
          },
        ],
        drug: [
          {
            id: "corebook:drug:black-lace",
            name: "Black Lace (Street Drug)",
            category: "drug",
            cost_eb: 50,
            summary: "Ignore Seriously Wounded penalties for 24h.",
            description: "Heavy combat narcotic.",
            printed_page: 357,
            stats: { subtype: "Street Drug" },
          },
        ],
      },
      fashion: [{ name: "Urban Flash Jacket", style: "Urban Flash", slot: "Top", cost_eb: 100 }],
    };

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: true, indexed_pages: 456 });
      if (url === "/v1/settings/llm") {
        return jsonResponse({ base_url: "http://127.0.0.1:11434/v1", model: "llama3", has_api_key: false, api_key_masked: "", temperature: 0.4, max_tokens: 1200, timeout_s: 60, mode: "two_pass", gm_thinking_mode: "quality" });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: { Handgun: { stat: "REF", cost: 1, specializable: false } }, rules_indexed: true });
      if (url === "/v1/creation/reference") return jsonResponse(refPayload);
      if (url === "/v1/creation/ai-assist") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.target === "bio" && body.mode === "scratch") {
          return jsonResponse({
            target: "bio",
            mode: "scratch",
            concept: "Neon Kabuki Marksman",
            summary: "Raised in Watson; knows every back-alley shortcut.",
            established_history: "Worked three escort runs with Rogue's crew.",
            appearance: "Scuffed Heavy Armorjack and neon visor.",
          });
        }
        if (body.target === "bio" && body.mode === "expand") {
          const field = body.field ?? "all";
          return jsonResponse({
            target: "bio",
            mode: "expand",
            field: body.field,
            ...(field === "all" || field === "concept" ? { concept: "Neon Kabuki Marksman" } : {}),
            ...(field === "all" || field === "summary"
              ? { summary: `${body.current?.summary ?? ""} Never misses a payday in Kabuki.` }
              : {}),
            ...(field === "all" || field === "established_history"
              ? { established_history: `${body.current?.established_history ?? ""} Verified on the Afterlife board.` }
              : {}),
            ...(field === "all" || field === "appearance" ? { appearance: "Scuffed Heavy Armorjack and neon visor." } : {}),
          });
        }
        return jsonResponse({
          target: "contacts",
          mode: body.mode ?? "scratch",
          friends: [{ name: "Takemura Jin", relationship: "Ex-partner", note: "Fixes jammed irons cheap." }],
          enemies: [{ who: "Maelstrom boss", name: "Bricks Jr.", wronged: "They wronged me", cause: "Stole your courier crate", backup: "6 boostergangers", revenge: "Ambush at Totentanz" }],
          tragic_love_affairs: [{ name: "Sora", outcome: "Vanished on an Arasaka orbital shuttle." }],
        });
      }
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({ campaign_id: "camp-cc", nodes: [], active_branch: [], active_leaf_id: null, current_revisions: { campaign_revision: campaign.revision, solo_revision: createdChar ? 1 : 0 }, revision_mismatch: false });
      }
      if (url.startsWith("/v1/library")) return jsonResponse({ items: [] });
      if (url === "/v1/game" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "list_characters") {
          return jsonResponse({ result: createdChar ? [createdChar] : [] });
        }
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: createdChar ? [createdChar] : [],
              clocks: [],
              solo: {
                revision: createdChar ? 1 : 0,
                runtime: { encounter: null, runs: {}, clock_minutes: 0 },
                characters: {},
              },
            },
          });
        }
        if (body.action === "create_player_character") {
          createdChar = {
            id: "char-vee",
            name: body.arguments.name,
            stats: { INT: 6, REF: 8, DEX: 7, TECH: 4, COOL: 6, WILL: 7, LUCK: 6, MOVE: 6, BODY: 7, EMP: 5 },
            skills: { Handgun: 6, Athletics: 2 },
            hp: 45,
            max_hp: 45,
            humanity: 43,
            luck_remaining: 6,
            money: 500,
            inventory: body.arguments.starting_gear.inventory,
            revision: 1,
            detail: {
              roles: [{ role: "Solo", rank: 4 }],
              creation: { method: "streetrat" },
              backstory: body.arguments.backstory,
              lifepath: body.arguments.lifepath,
              cyberware: body.arguments.starting_gear.cyberware,
              equipped_weapon: body.arguments.starting_gear.equipped_weapon,
              equipped_armor: body.arguments.starting_gear.equipped_armor,
            },
          };
          campaign.character_ids = ["char-vee"];
          return jsonResponse({
            result: { committed: true, revision: 1, result: { character_id: "char-vee" } },
          });
        }
        if (body.action === "update_character_profile" && createdChar) {
          createdChar = {
            ...createdChar,
            revision: 2,
            detail: {
              ...(createdChar.detail as Record<string, unknown>),
              backstory: body.arguments.profile.backstory,
              appearance: body.arguments.profile.appearance,
            },
          };
          return jsonResponse({ result: createdChar });
        }
        return jsonResponse({ result: {} });
      }
      return jsonResponse({});
    });

    render(<App />);
    const openBtn = await screen.findByRole("button", { name: /Open Character Sheet Creator/i });
    fireEvent.click(openBtn);

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /Edgerunner Character Sheet Creator/i })).toBeInTheDocument();
    });

    // Hovering Role card shows Live Rulebook Inspector description
    const soloRoleBtn = screen.getByText("Solo").closest("button");
    expect(soloRoleBtn).toBeTruthy();
    fireEvent.mouseEnter(soloRoleBtn!);
    await waitFor(() => {
      expect(screen.getAllByText(/Great first character/i).length).toBeGreaterThan(0);
    });

    fireEvent.change(screen.getByPlaceholderText("e.g. Vee Mercer"), { target: { value: "Rina Ash" } });
    fireEvent.click(screen.getByRole("button", { name: /4\. Backstory & Lifepath/i }));

    fireEvent.click(screen.getByRole("button", { name: /Roll Full Lifepath/i }));

    // Generate from Scratch + Improve/Regen + Generate Contacts
    fireEvent.click(screen.getByRole("button", { name: /Generate from Scratch/i }));
    await waitFor(() => {
      expect((screen.getByPlaceholderText(/Write a few sentences about your life/i) as HTMLTextAreaElement).value).toContain(
        "Raised in Watson",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: /Generate Contacts/i }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("Takemura Jin")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Bricks Jr.")).toBeInTheDocument();
    });

    fireEvent.change(
      screen.getByPlaceholderText(/Owes 200 eb to Mama Welles/i),
      { target: { value: "Ran recon out of Kabuki; owes Dakota Smith one clean favor." } },
    );
    fireEvent.click(screen.getByRole("button", { name: /Improve Established History/i }));
    await waitFor(() => {
      expect((screen.getByPlaceholderText(/Owes 200 eb to Mama Welles/i) as HTMLTextAreaElement).value).toContain(
        "Verified on the Afterlife board.",
      );
    });
    // Per-field expand must leave Backstory untouched
    expect((screen.getByPlaceholderText(/Write a few sentences about your life/i) as HTMLTextAreaElement).value).toBe(
      "Raised in Watson; knows every back-alley shortcut.",
    );

    // Check Step 3 Specialization + Step 5 Exotic Weapons, Hardware, Armor SP=13 & Cyberware HL=7 in Freeform/Complete Package
    fireEvent.click(screen.getByRole("button", { name: /1\. Identity & Role/i }));
    fireEvent.click(screen.getByRole("button", { name: /Complete Package \(Calculated\)/i }));
    fireEvent.click(screen.getByRole("button", { name: /3\. Skills/i }));
    fireEvent.change(screen.getByPlaceholderText(/e\.g\. Japanese, Arabic, Cantonese/i), { target: { value: "Japanese" } });
    fireEvent.click(screen.getByRole("button", { name: /\+ Add Specialization/i }));
    expect(screen.getByText("Language (Japanese)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /5\. Gear & Cyberware/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Exotic$/i }));
    expect(screen.getByText("Malorian Arms 3516 (Exotic VH Pistol)")).toBeInTheDocument();
    // Sort catalog & Bag toggle
    expect(screen.getByLabelText("Sort catalog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^hardware$/i }));
    expect(screen.getByText("Cyberdeck (7 Slots)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^armor$/i }));
    fireEvent.click(screen.getByRole("button", { name: "+500eb" }));
    fireEvent.click(screen.getByRole("button", { name: /^cyberware$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Foundations$/i }));
    fireEvent.click(screen.getByRole("button", { name: "+500eb" }));
    expect(screen.getByRole("button", { name: /Bag \(2\)/i })).toBeInTheDocument();
    // Switch back to Streetrat to verify template submission cleanly too
    fireEvent.click(screen.getByRole("button", { name: /6\. Sheet Preview/i }));
    expect(screen.getByText(/Heavy Armorjack Body Armor \(SP 13\)/i)).toBeInTheDocument();
    expect(screen.getByText(/HUM 53\/60/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /1\. Identity & Role/i }));
    fireEvent.click(screen.getByRole("button", { name: /Streetrat \(Templates\)/i }));

    fireEvent.click(screen.getByRole("button", { name: /6\. Sheet Preview/i }));
    fireEvent.click(screen.getByRole("button", { name: /Create & Attach to Campaign/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /Edgerunner Character Sheet Creator/i })).not.toBeInTheDocument();
      expect(screen.getAllByText("Rina Ash").length).toBeGreaterThan(0);
      expect(screen.getByText("EMP")).toBeInTheDocument();
    });

    const createCall = fetchMock.mock.calls.find(
      ([url, init]) => url === "/v1/game" && String(init?.body).includes("create_player_character"),
    );
    expect(createCall).toBeTruthy();
    const createPayload = JSON.parse(String(createCall?.[1]?.body));
    expect(createPayload.arguments.backstory.established_history).toContain("Dakota Smith");

    // Hovering EMP stat on live sheet displays beginner formula guidance
    fireEvent.mouseEnter(screen.getByText("EMP").closest("button")!);
    expect(screen.getByText(/Max Humanity = EMP × 10/i)).toBeInTheDocument();

    // Switch to Bio tab and edit backstory
    fireEvent.click(screen.getByRole("button", { name: /^Bio$/i }));
    expect(screen.getByText(/Ran recon out of Kabuki/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Edit Bio/i }));
    fireEvent.change(screen.getByPlaceholderText(/Prior gigs, owed favors/i), {
      target: { value: "Owed a solid by Viktor Vector after 2044." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save Bio/i }));

    await waitFor(() => {
      expect(screen.getByText(/Owed a solid by Viktor Vector after 2044\./i)).toBeInTheDocument();
    });
  });

  it("opens Corebook Campaign Architect from TopBar New button and bootstraps world data", async () => {
    const bootstrapped: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: true, indexed_pages: 456 });
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "llama3",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.4,
          max_tokens: 1200,
          timeout_s: 60,
          mode: "two_pass",
          gm_thinking_mode: "quality",
        });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: true });
      if (url === "/v1/creation/reference") {
        return jsonResponse({
          rules_indexed: true,
          stat_names: ["INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP"],
          stats: {},
          methods: [],
          roles: [],
          skills: [],
          cultural_regions: [],
          lifepath_tables: {},
          shop: { weapon: [], armor: [], cyberware: [], gear: [], program: [], hardware: [], vehicle: [], drug: [] },
          fashion: [],
          campaign_presets: {
            districts: [{ name: "Watson Development", threat_rating: "Moderate", summary: "Kabuki & Little China.", printed_page: 308 }],
            factions: [{ name: "Tyger Claws", type: "Crime Syndicate", summary: "Japantown syndicate.", printed_page: 308 }],
            caper_styles: [{
              id: "heist",
              name: "Corporate Data / Cargo Heist",
              printed_page: 395,
              summary: "Tight-window extraction.",
              default_beats: { hook: "Fixer offer", developments: "Complication", cliffhanger: "Lockdown", climax: "Escape", resolution: "Payout" },
            }],
            screamsheet_hooks: ["RED SKY BLACKOUT: Rolling power outages hit Watson."],
          },
        });
      }
      if (url.startsWith("/v1/campaigns/") && url.endsWith("/bootstrap")) {
        const body = JSON.parse(String(init?.body ?? "{}"));
        bootstrapped.push(body);
        return jsonResponse({
          campaign: {
            id: "camp-new",
            name: "Kabuki Neon",
            session_number: 1,
            revision: 2,
            state: { scene: body.scene ?? "", summary: body.summary ?? "", npcs: body.npcs ?? {}, objectives: body.objectives ?? {}, discoveries: {}, unresolved: body.unresolved ?? {} },
          },
          clocks: [],
        });
      }
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") {
          return jsonResponse({ action: "list_campaigns", result: [] });
        }
        if (body.action === "create_campaign") {
          return jsonResponse({
            action: "create_campaign",
            result: {
              id: "camp-new",
              name: body.arguments.name,
              session_number: 1,
              revision: 1,
              state: { scene: "", summary: "", npcs: {}, objectives: {}, discoveries: {}, unresolved: {} },
            },
          });
        }
        if (body.action === "campaign_context") {
          return jsonResponse({
            action: "campaign_context",
            result: {
              campaign: { id: "camp-new", name: "Kabuki Neon", session_number: 1, revision: 2, state: { scene: "Rain", summary: "Set in Watson", npcs: {}, objectives: {}, discoveries: {}, unresolved: {} } },
              characters: [],
              solo: { runtime: { clock_minutes: 0, runs: {} } },
            },
          });
        }
      }
      if (url.startsWith("/v1/chat/tree") || url.startsWith("/v1/campaigns/")) {
        return jsonResponse({ messages: [], active_branch: [], active_leaf_id: null, clocks: [], players: [], active_turn: null });
      }
      if (url.startsWith("/v1/library")) return jsonResponse({ results: [] });
      return jsonResponse({});
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /^Campaign$/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /New Campaign/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /New Campaign/i }));
    expect(screen.getByRole("dialog", { name: /Campaign Creator/i })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/e\.g\. Chrome over Kabuki/i), {
      target: { value: "Kabuki Neon" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply Preset Scaffold/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Create Campaign$/i }));

    await waitFor(() => {
      expect(bootstrapped.length).toBe(1);
    });
    expect(String((bootstrapped[0] as { summary?: string }).summary)).toContain("Watson Development");
  });

  it("hides the regenerated message while streaming and supports per-field Campaign AI improve", async () => {
    const campaign = {
      id: "camp-regen",
      name: "Regen Check",
      revision: 1,
      session_number: 1,
      character_ids: [],
      state: { scene: "Little China", summary: "", npcs: {}, objectives: {}, discoveries: {}, unresolved: {} },
    };
    const u1 = {
      id: "ru1",
      campaign_id: "camp-regen",
      parent_id: null,
      role: "user" as const,
      content: "Check the back door.",
      raw_content: "Check the back door.",
      model: "",
      campaign_revision: 1,
      solo_revision: 0,
      metadata: {},
      is_active: true,
      created_at: "2026-11-15T00:00:00Z",
      sibling_index: 0,
      sibling_count: 1,
      sibling_ids: ["ru1"],
    };
    const a1 = {
      id: "ra1",
      campaign_id: "camp-regen",
      parent_id: "ru1",
      role: "assistant" as const,
      content: "Old GM reply that must disappear during regenerate.",
      raw_content: "Old GM reply that must disappear during regenerate.",
      model: "llama3",
      campaign_revision: 1,
      solo_revision: 0,
      metadata: {},
      is_active: true,
      created_at: "2026-11-15T00:00:01Z",
      sibling_index: 0,
      sibling_count: 1,
      sibling_ids: ["ra1"],
    };
    const a2 = {
      ...a1,
      id: "ra2",
      content: "Fresh GM reply after regen.",
      raw_content: "Fresh GM reply after regen.",
      sibling_index: 1,
      sibling_count: 2,
      sibling_ids: ["ra1", "ra2"],
    };

    let regenerated = false;
    let releaseStream: (() => void) | null = null;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: false });
      if (url === "/v1/settings/llm") {
        return jsonResponse({ base_url: "http://127.0.0.1:11434/v1", model: "llama3", has_api_key: false, api_key_masked: "", temperature: 0.4, max_tokens: 1200, timeout_s: 60, mode: "two_pass", gm_thinking_mode: "quality" });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: false });
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: "camp-regen",
          nodes: regenerated ? [u1, a1, a2] : [u1, a1],
          active_branch: regenerated ? [u1, a2] : [u1, a1],
          active_leaf_id: regenerated ? "ra2" : "ra1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url === "/v1/chat/regenerate") {
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          async start(controller) {
            controller.enqueue(
              encoder.encode('event: text_delta\ndata: {"delta":"Fresh GM reply "}\n\n'),
            );
            await streamGate;
            regenerated = true;
            controller.enqueue(
              encoder.encode('event: text_delta\ndata: {"delta":"after regen."}\n\n'),
            );
            controller.enqueue(
              encoder.encode('event: turn_done\ndata: {"turn_id":"t-2","user_message":{},"assistant_message":{}}\n\n'),
            );
            controller.close();
          },
        });
        return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      if (url === "/v1/creation/ai-assist") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return jsonResponse({
          target: "campaign",
          mode: "expand",
          field: body.field,
          opening_scene: `${body.current?.opening_scene ?? ""} Neon steam rises from the grate.`,
        });
      }
      if (url.startsWith("/v1/library")) return jsonResponse({ items: [] });
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      return jsonResponse({});
    });

    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Old GM reply that must disappear during regenerate\./i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Regenerate reply/i }));

    // Immediately while streaming: old message is hidden, streaming bubble is shown, user message stays visible
    await waitFor(() => {
      expect(screen.getByText(/GM Streaming/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Old GM reply that must disappear during regenerate\./i)).not.toBeInTheDocument();
    expect(screen.getByText(/Check the back door\./i)).toBeInTheDocument();

    releaseStream!();
    await waitFor(() => {
      expect(screen.getByText(/Fresh GM reply after regen\./i)).toBeInTheDocument();
      expect(screen.getByText("2/2")).toBeInTheDocument();
    });
  });

  it("supports Corebook PDF upload with progress bar and advanced built-in prompt editing in Settings", async () => {
    let rulesIndexed = false;
    let pollCount = 0;

    // Mock XMLHttpRequest for uploadCorebookPdf
    const OriginalXHR = globalThis.XMLHttpRequest;
    class MockXHR {
      status = 202;
      responseText = JSON.stringify({
        started: true,
        job: {
          status: "running",
          stage: "extracting",
          percent: 30,
          current: 1,
          total: 2,
          filename: "CPR-Corebook.pdf",
          message: "Reading page 1 of 2...",
          warning: null,
          error: null,
          started_at: 1,
          finished_at: null,
        },
      });
      withCredentials = false;
      upload: { onprogress?: (ev: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onabort: (() => void) | null = null;
      open() {}
      setRequestHeader() {}
      send() {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
        setTimeout(() => {
          this.onload?.();
        }, 0);
      }
    }
    globalThis.XMLHttpRequest = MockXHR as unknown as typeof XMLHttpRequest;

    try {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/health") {
          return jsonResponse({ status: "ok", rules_indexed: rulesIndexed, indexed_pages: rulesIndexed ? 2 : 0 });
        }
        if (url === "/v1/auth/status") {
          return jsonResponse({
            auth_enabled: false,
            pin_only_mode: false,
            authenticated: true,
            role: "open",
            username: null,
            admin_configured: false,
            user_configured: false,
            user_passcode_configured: false,
            allow_guest_users: false,
            can_bootstrap: true,
          });
        }
        if (url === "/v1/settings/llm") {
          return jsonResponse({
            base_url: "http://127.0.0.1:11434/v1",
            model: "llama3",
            has_api_key: false,
            api_key_masked: "",
            temperature: 0.75,
            planner_temperature: 0.1,
            creation_temperature: 0.85,
            max_tokens: 1200,
            timeout_s: 90,
            mode: "two_pass",
            enable_highlights: true,
            allow_ai_homebrew: true,
            auto_compress_prompt: true,
          });
        }
        if (url === "/v1/settings/all") {
          return jsonResponse({
            llm: {
              base_url: "http://127.0.0.1:11434/v1",
              model: "llama3",
              has_api_key: false,
              api_key_masked: "",
              temperature: 0.75,
              planner_temperature: 0.1,
              creation_temperature: 0.85,
              max_tokens: 1200,
              timeout_s: 90,
              mode: "two_pass",
              enable_highlights: true,
              allow_ai_homebrew: true,
              auto_compress_prompt: true,
            },
            prompts: {
              system_persona: "Default GM",
              world_rules_prefix: "",
              planner_extra: "",
              narrator_extra: "",
              chronicler_extra: "",
              archivist_extra: "",
              creation_assist_persona: "Default Co-Writer",
              creation_assist_extra: "",
              narrator_core_rules: "Default Core Rules",
              planner_core_rules: "Default Planner Rules",
              chronicler_core_rules: "Default Chronicler Rules",
              archivist_core_rules: "Default Archivist Rules",
            },
            prompt_defaults: {
              system_persona: "Default GM",
              world_rules_prefix: "",
              planner_extra: "",
              narrator_extra: "",
              chronicler_extra: "",
              archivist_extra: "",
              creation_assist_persona: "Default Co-Writer",
              creation_assist_extra: "",
              narrator_core_rules: "Default Core Rules",
              planner_core_rules: "Default Planner Rules",
              chronicler_core_rules: "Default Chronicler Rules",
              archivist_core_rules: "Default Archivist Rules",
            },
            server: { bind_host: "127.0.0.1", port: 8765, allowed_origins: [], public_url: "" },
            auth_policy: {
              allow_guest_users: false,
              allow_self_signup: true,
              user_passcode_configured: false,
              admin_configured: false,
              user_configured: false,
              accounts: [],
            },
            runtime: {
              active_host: "127.0.0.1",
              active_port: 8765,
              in_docker: false,
              restart_supported: true,
              restart_required: false,
            },
          });
        }
        if (url === "/v1/corebook/status") {
          pollCount += 1;
          if (pollCount >= 2) {
            rulesIndexed = true;
            return jsonResponse({
              rules_indexed: true,
              indexed_pages: 2,
              pdf_page_count: 2,
              source_filename: "CPR-Corebook.pdf",
              semantic_available: false,
              semantic_indexed: false,
              job: {
                status: "completed",
                stage: "done",
                percent: 100,
                current: 2,
                total: 2,
                filename: "CPR-Corebook.pdf",
                message: "Corebook ready (2 pages).",
                warning: null,
                error: null,
                started_at: 1,
                finished_at: 2,
              },
            });
          }
          return jsonResponse({
            rules_indexed: false,
            indexed_pages: 0,
            pdf_page_count: 0,
            source_filename: null,
            semantic_available: false,
            semantic_indexed: false,
            job: {
              status: "idle",
              stage: "idle",
              percent: 0,
              current: 0,
              total: 0,
              filename: null,
              message: "",
              warning: null,
              error: null,
              started_at: null,
              finished_at: null,
            },
          });
        }
        if (url === "/v1/skills") {
          return jsonResponse({ skills: {}, rules_indexed: rulesIndexed });
        }
        if (url === "/v1/game") {
          const body = JSON.parse(String(initOptionsOrEmpty(undefined)));
          void body;
          return jsonResponse({ result: [] });
        }
        return jsonResponse({});
      });
      void fetchMock;

      render(<App />);
      const noCorebookBtn = await screen.findByRole("button", { name: /No BYOC/i });
      fireEvent.click(noCorebookBtn);

      await waitFor(() => {
        expect(screen.getByText(/BYOC — Bring Your Own Corebook/i)).toBeInTheDocument();
      });

      const fileInput = screen.getByLabelText(/Upload Corebook PDF file/i) as HTMLInputElement;
      const pdfFile = new File(["%PDF-1.4 test"], "CPR-Corebook.pdf", { type: "application/pdf" });
      fireEvent.change(fileInput, { target: { files: [pdfFile] } });

      await waitFor(() => {
        expect(screen.getByRole("progressbar")).toBeInTheDocument();
        expect(screen.getAllByText(/BYOC Ready \(2 pages\)/i).length).toBeGreaterThanOrEqual(1);
      });

      // Open Prompts tab, verify separated sections + Chronicler toggle, and expand Advanced built-in prompts
      fireEvent.click(screen.getByRole("button", { name: /^Prompts$/i }));
      expect(screen.getByText(/Player Dialogue, Narration & Multi-Player Handling/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Chronicler: ON/i })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Advanced: Full Built-In System Rules/i }));
      fireEvent.click(await screen.findByRole("button", { name: /Built-In World Realism, Fog-of-War/i }));
      expect(await screen.findByDisplayValue("Default Core Rules")).toBeInTheDocument();
    } finally {
      globalThis.XMLHttpRequest = OriginalXHR;
    }
  });

  it("supports Introductory First Message, generation telemetry, draft persistence, GM secret spoiler, and lockable campaign AI", async () => {
    const campaign = {
      id: "camp-ui-new",
      name: "Night Market Run",
      revision: 1,
      session_number: 1,
      character_ids: [],
      state: { scene: "", summary: "", npcs: {}, objectives: {}, discoveries: {}, unresolved: {} },
    };
    let activeBranch: unknown[] = [];
    const turnBodies: Array<Record<string, unknown>> = [];
    const assistBodies: Array<Record<string, unknown>> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: false });
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "nvidia/nemotron",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.75,
          max_tokens: 1200,
          intro_max_tokens: 4096,
          timeout_s: 60,
          mode: "two_pass",
          gm_thinking_mode: "balanced",
        });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: false });
      if (url === "/v1/creation/reference") {
        return jsonResponse({
          rules_indexed: false,
          stat_names: ["INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP"],
          stats: {},
          methods: [],
          roles: [],
          skills: [],
          cultural_regions: [],
          lifepath_tables: {},
          shop: { weapon: [], armor: [], cyberware: [], gear: [], program: [], hardware: [], vehicle: [], drug: [] },
          fashion: [],
          campaign_presets: {
            districts: [
              { name: "Watson Development", threat_rating: "Moderate", summary: "Kabuki.", printed_page: 298 },
              { name: "Old Combat Zone", threat_rating: "Combat", summary: "Lawless warzone.", printed_page: 300 },
            ],
            factions: [
              { name: "Arasaka", type: "Megacorp", summary: "Corp.", printed_page: 267 },
              { name: "Maelstrom", type: "Combat Gang", summary: "Boosters.", printed_page: 308 },
              { name: "Tyger Claws", type: "Combat Gang", summary: "Syndicate.", printed_page: 309 },
            ],
            caper_styles: [
              {
                id: "heist",
                name: "Corporate Data / Cargo Heist",
                printed_page: 395,
                summary: "Infiltration.",
                default_beats: { hook: "H", developments: "D", cliffhanger: "C", climax: "X", resolution: "R" },
              },
              {
                id: "street-turf",
                name: "Street Turf & Night Market Hustle",
                printed_page: 398,
                summary: "Turf.",
                default_beats: { hook: "H2", developments: "D2", cliffhanger: "C2", climax: "X2", resolution: "R2" },
              },
            ],
            screamsheet_hooks: ["HOOK ONE"],
          },
        });
      }
      if (url === "/v1/creation/ai-assist") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        assistBodies.push(body);
        if (body.mode === "scratch" && !body.field && !body.campaign?.lock_choices) {
          return jsonResponse({
            target: "campaign",
            mode: "scratch",
            name: "Combat Zone Courier",
            district: "Old Combat Zone",
            caper_style: "Street Turf & Night Market Hustle",
            factions: ["Maelstrom"],
            summary: "Auto-picked Combat Zone hustle.",
            opening_scene: "Neon flickers over rusted barriers.",
            npcs: { "Rafa (Fixer)": "Brokers clean water." },
            objectives: { "Deliver Meds": "Cross the perimeter." },
            beat_chart: { hook: "H", developments: "D", cliffhanger: "C", climax: "X", resolution: "R" },
            gm_secrets: "Secretly a Militech trap.",
          });
        }
        return jsonResponse({
          target: "campaign",
          mode: body.mode,
          field: body.field,
          name: "Locked Run",
          summary: "Locked summary.",
          opening_scene: "Fresh regenerated scene.",
          npcs: { "NPC 1": "One", "NPC 2": "Two", "NPC 3": "Three" },
          objectives: { "Obj 1": "First" },
          gm_secrets: "Regenerated hidden twist.",
        });
      }
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: campaign.id,
          nodes: activeBranch,
          active_branch: activeBranch,
          active_leaf_id: activeBranch.length ? "intro-a1" : null,
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url === "/v1/chat/turn") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        turnBodies.push(body);
        const userMsg = {
          id: "intro-u1",
          campaign_id: campaign.id,
          parent_id: null,
          role: "user",
          content: body.user_text,
          raw_content: body.user_text,
          model: "",
          campaign_revision: 1,
          solo_revision: 0,
          metadata: { is_intro: true },
          is_active: true,
          created_at: "2026-11-18T00:00:00Z",
        };
        const asstMsg = {
          id: "intro-a1",
          campaign_id: campaign.id,
          parent_id: "intro-u1",
          role: "assistant",
          content: "Welcome to Cyberpunk RED in 2045.",
          raw_content: "Welcome to Cyberpunk RED in 2045.",
          model: "nvidia/nemotron",
          campaign_revision: 1,
          solo_revision: 0,
          metadata: {
            is_intro: true,
            generation_stats: { elapsed_seconds: 3.4, tokens_per_second: 42.5, completion_tokens: 145, estimated: false },
          },
          is_active: true,
          created_at: "2026-11-18T00:00:03Z",
        };
        activeBranch = [userMsg, asstMsg];
        return sseResponse([
          { event: "text_delta", data: { delta: "Welcome to Cyberpunk RED in 2045." } },
          { event: "turn_done", data: { turn_id: "t-intro", user_message: userMsg, assistant_message: asstMsg } },
        ]);
      }
      if (url.startsWith("/v1/library")) return jsonResponse({ items: [] });
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      return jsonResponse({});
    });

    render(<App />);

    // Introductory screen removed; Campaign tab holds Story & Rules & Roles, and GM mode button cycles cleanly
    const smartGmBtn = await screen.findByRole("button", { name: /GM turn mode: Smart GM/i });
    expect(screen.queryByRole("button", { name: /Introductory First Message/i })).not.toBeInTheDocument();
    fireEvent.click(smartGmBtn);
    expect(screen.getByRole("button", { name: /GM turn mode: Party Chat/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /GM turn mode: Party Chat/i }));
    expect(screen.getByRole("button", { name: /GM turn mode: Force GM/i })).toBeInTheDocument();

    // Character Creator: closing preserves typed name across reopen
    fireEvent.click(screen.getByRole("button", { name: /Open Character Sheet Creator/i }));
    fireEvent.change(screen.getByPlaceholderText("e.g. Vee Mercer"), { target: { value: "Marek Kovic" } });
    fireEvent.click(screen.getByRole("button", { name: /Close character creator/i }));
    fireEvent.click(screen.getByRole("button", { name: /Open Character Sheet Creator/i }));
    expect(screen.getByDisplayValue("Marek Kovic")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Close character creator/i }));

    // Campaign Creator (from Campaign sidepanel): Auto Generate picks district/style/factions + GM Secrets hidden until Unspoil + Draft persists across close
    fireEvent.click(screen.getByRole("button", { name: /^Campaign$/i }));
    expect(screen.getByRole("button", { name: /Rules & Roles/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^New Campaign$/i }));
    fireEvent.click(screen.getByRole("button", { name: /Generate from Scratch/i }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("Combat Zone Courier")).toBeInTheDocument();
    });
    expect(screen.getByText(/CLASSIFIED \/\/ SPOILER SHIELDED/i)).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Secretly a Militech trap.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Unspoil GM Secrets"));
    expect(screen.getByDisplayValue("Secretly a Militech trap.")).toBeInTheDocument();

    // Per-field Regen works alongside Improve
    fireEvent.click(screen.getByRole("button", { name: /Regenerate Opening Scene/i }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("Fresh regenerated scene.")).toBeInTheDocument();
    });

    // Lock Choices sends lock_choices=true & counts
    fireEvent.click(screen.getByRole("button", { name: /Lock Choices/i }));
    fireEvent.change(screen.getByLabelText("Locked starting NPCs count"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Locked starting Objectives count"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate from Scratch/i }));
    await waitFor(() => {
      const lastCall = assistBodies[assistBodies.length - 1] as { campaign?: { lock_choices?: boolean; npc_count?: number; objective_count?: number } };
      expect(lastCall.campaign?.lock_choices).toBe(true);
      expect(lastCall.campaign?.npc_count).toBe(3);
      expect(lastCall.campaign?.objective_count).toBe(1);
    });

    // Closing Campaign Creator preserves draft upon reopen (with GM secrets hidden again)
    fireEvent.click(screen.getByRole("button", { name: /Close Campaign Creator/i }));
    fireEvent.click(screen.getByRole("button", { name: /^New Campaign$/i }));
    expect(screen.getByDisplayValue("Fresh regenerated scene.")).toBeInTheDocument();
    expect(screen.getByText(/Draft Restored/i)).toBeInTheDocument();
    expect(screen.getByText(/CLASSIFIED \/\/ SPOILER SHIELDED/i)).toBeInTheDocument();
    void turnBodies;
  });

  it("supports Orientation Briefing, Admin-only GM Ops submenu, Admin-to-Player switch, Handle vs Hidden Real Name, and Selected Only gear filter", async () => {
    const campaign = {
      id: "camp-orient-1",
      name: "Kabuki Blackout",
      revision: 1,
      session_number: 1,
      character_ids: ["char-alice"],
      state: {
        scene: "Rain lashes the neon awnings of Kabuki Roundabout.",
        summary: "An Arasaka courier vanished inside Sector 4.",
        npcs: { "Tala Nguyen": "Netrunner broker" },
        objectives: { "Intercept the Ghostwing Rig": "19 minutes remaining" },
        discoveries: {},
        unresolved: {},
      },
    };
    const aliceChar = {
      id: "char-alice",
      name: "Ghostwire",
      revision: 1,
      hp: 35,
      max_hp: 40,
      money: 500,
      humanity: 50,
      max_humanity: 60,
      luck_remaining: 6,
      stats: { INT: 6, REF: 8, DEX: 7, TECH: 5, COOL: 6, WILL: 6, LUCK: 6, MOVE: 6, BODY: 6, EMP: 6 },
      skills: { Handgun: 6, Stealth: 4 },
      inventory: { "Heavy Pistol": 1 },
      cyberware: [],
      detail: {
        handle: "Ghostwire",
        real_name: "Elena Vance",
        real_name_hidden: true,
        color: "violet",
        owner_username: "alice",
        roles: [{ name: "Solo", rank: 4, ability: "Combat Awareness" }],
      },
    };
    const branchMessages = [
      {
        id: "m-u1",
        campaign_id: campaign.id,
        parent_id: null,
        role: "user",
        content: "I scan the rooftop perimeter.",
        raw_content: "I scan the rooftop perimeter.",
        model: "",
        campaign_revision: 1,
        solo_revision: 0,
        metadata: {
          speaker_character_id: "char-alice",
          speaker_name: "Ghostwire",
          rolls: [
            {
              actor: "Ghostwire",
              stat: "INT",
              skill: "Perception",
              dv: 13,
              die: 8,
              total: 18,
              success: true,
              critical_success: false,
              critical_failure: false,
              reason: "Rooftop scan",
            },
          ],
        },
        is_active: true,
        created_at: "2026-11-18T00:00:00Z",
      },
      {
        id: "m-a1",
        campaign_id: campaign.id,
        parent_id: "m-u1",
        role: "assistant",
        content: "Two Tyger Claws spotters crouch behind the AC vents.",
        raw_content: "Two Tyger Claws spotters crouch behind the AC vents.",
        model: "nemotron",
        campaign_revision: 1,
        solo_revision: 0,
        metadata: {
          citation_cards: [{ id: "cb-1", title: "Perception", category: "skill", source: "corebook", printed_page: 139, summary: "Spotting hidden threats." }],
          patches: [{ target: "campaign", before: { scene: "Alley" }, after: { scene: "Kabuki Rooftop" }, reason: "Move" }],
          warnings: ["Simulated planner warning"],
        },
        is_active: true,
        created_at: "2026-11-18T00:00:02Z",
      },
    ];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: true, indexed_pages: 456 });
      if (url === "/v1/auth/status") {
        return jsonResponse({
          auth_enabled: true,
          pin_only_mode: false,
          authenticated: true,
          role: "admin",
          username: "admin",
          admin_configured: true,
          user_configured: true,
          user_passcode_configured: false,
          allow_guest_users: false,
          can_bootstrap: false,
          require_character_to_speak: true,
        });
      }
      if (url === "/v1/settings/llm") {
        return jsonResponse({
          base_url: "http://127.0.0.1:11434/v1",
          model: "nemotron",
          has_api_key: false,
          api_key_masked: "",
          temperature: 0.75,
          max_tokens: 1200,
          timeout_s: 60,
          mode: "two_pass",
          require_character_to_speak: true,
        });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: true });
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: campaign.id,
          nodes: branchMessages,
          active_branch: branchMessages,
          active_leaf_id: "m-a1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url.startsWith("/v1/library")) return jsonResponse({ items: [] });
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [aliceChar],
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
      }
      return jsonResponse({});
    });

    render(<App />);

    // 1. Inline dice roll is shown under the player message, and GM Ops submenu is collapsed by default for Admin
    await waitFor(() => {
      expect(screen.getByText(/Two Tyger Claws spotters crouch/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Perception \(INT\)/i)).toBeInTheDocument();
    expect(screen.getByText(/18 vs DV 13/i)).toBeInTheDocument();
    expect(screen.queryByText(/Kabuki Rooftop/i)).not.toBeInTheDocument();

    // Expanding GM Ops reveals citations, state patches, and warnings for Admin
    const gmOpsBtn = screen.getByRole("button", { name: /GM Ops/i });
    fireEvent.click(gmOpsBtn);
    expect(screen.getByText(/Kabuki Rooftop/i)).toBeInTheDocument();

    // 2. Campaign tab displays Story, Objectives, and Rules & Roles for Admin, then Read-Only view for Player
    fireEvent.click(screen.getByRole("button", { name: /^Campaign$/i }));
    expect(screen.getByText(/World Clocks & Heat/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Rules & Roles/i }));
    expect(screen.getByText(/The 10 Iconic Roles/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Story & Briefing/i }));

    // 3. Instant icon-only Admin -> Player Mode switch hides GM Ops, Campaign editors, Clocks, and enforces character ownership
    fireEvent.click(screen.getByRole("button", { name: /Switch to Player Mode/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Player Mode \(Switch to Admin\)/i })).toBeInTheDocument();
    });
    // GM Ops button and Campaign Admin controls are completely hidden from normal players
    expect(screen.queryByRole("button", { name: /GM Ops/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/World Clocks & Heat/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Unresolved Threads/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^New Campaign$/i })).not.toBeInTheDocument();
    // Since "admin" in User View does not own "Ghostwire" (owned by "alice"), speaking is locked until creating/claiming a character
    expect(screen.getByText(/Admin requires an active Edgerunner sheet to speak in chat/i)).toBeInTheDocument();
  });

  it("renders full objective names, custom color wheel, gender+pronouns, weapon genre/tier multi-select + sort, and live peer streaming", async () => {
    class MockEventSource {
      static instances: MockEventSource[] = [];
      listeners = new Map<string, Array<(ev: MessageEvent) => void>>();
      url: string;
      constructor(url: string) {
        this.url = url;
        MockEventSource.instances.push(this);
      }
      addEventListener(type: string, cb: (ev: MessageEvent) => void) {
        const list = this.listeners.get(type) ?? [];
        list.push(cb);
        this.listeners.set(type, list);
      }
      emit(type: string, data: unknown) {
        const ev = { data: JSON.stringify(data) } as MessageEvent;
        for (const cb of this.listeners.get(type) ?? []) cb(ev);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", MockEventSource);

    const campaign = {
      id: "camp-new-1",
      name: "Zhirafa Heist",
      revision: 1,
      session_number: 1,
      is_primary: true,
      character_ids: ["char-1", "char-2"],
      state: {
        scene: "La Casita Rooftop",
        summary: "Night falls over Heywood Glen.",
        npcs: { "Drone-Mother": "Rigger, Heywood — Neutral 0" },
        objectives: {
          "Clear Sibling Debt": "Resolve sibling's gambling debt with Jace either by completing the heist or paying off the note before dawn.",
          "Fence Prototype Rig": "Deliver Aguila-7 safely.",
        },
        discoveries: {},
        unresolved: {},
      },
    };
    let char1 = {
      id: "char-1",
      name: "Vee",
      stats: { INT: 6, REF: 7, DEX: 6, TECH: 5, COOL: 6, WILL: 6, LUCK: 6, MOVE: 6, BODY: 5, EMP: 6 },
      skills: { Handgun: 6 },
      hp: 35,
      max_hp: 35,
      humanity: 60,
      luck_remaining: 6,
      money: 500,
      inventory: { "Microwaver (Exotic)": 1 },
      revision: 1,
      detail: { handle: "Vee", color: "cyan", roles: [{ role: "Solo", rank: 4 }] },
    };
    const char2 = {
      id: "char-2",
      name: "Kira",
      stats: { INT: 7, REF: 6, DEX: 6, TECH: 7, COOL: 5, WILL: 6, LUCK: 5, MOVE: 6, BODY: 5, EMP: 6 },
      skills: { Interface: 6 },
      hp: 35,
      max_hp: 35,
      humanity: 60,
      luck_remaining: 5,
      money: 500,
      inventory: {},
      revision: 1,
      detail: { handle: "Kira", color: "rose", roles: [{ role: "Netrunner", rank: 4 }] },
    };
    const branchMsgs: Array<Record<string, unknown>> = [
      {
        id: "m1",
        campaign_id: campaign.id,
        channel_id: "main",
        parent_id: null,
        role: "assistant",
        content: "Opening table scene.",
        raw_content: "Opening table scene.",
        model: "nemotron",
        campaign_revision: 1,
        solo_revision: 0,
        metadata: {},
        is_active: true,
        created_at: "2026-11-18T08:00:00Z",
      },
    ];

    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url === "/health") return jsonResponse({ status: "ok", rules_indexed: true, auth_enabled: false });
      if (url === "/v1/auth/status") {
        return jsonResponse({
          auth_enabled: false,
          pin_only_mode: false,
          authenticated: true,
          role: "open",
          username: null,
          admin_configured: false,
          user_configured: false,
          user_passcode_configured: false,
          allow_guest_users: true,
          can_bootstrap: false,
          require_character_to_speak: false,
        });
      }
      if (url === "/v1/settings/llm") {
        return jsonResponse({ base_url: "http://127.0.0.1:11434/v1", model: "nemotron", mode: "two_pass" });
      }
      if (url === "/v1/skills") return jsonResponse({ skills: {}, rules_indexed: true });
      if (url.startsWith("/v1/campaigns/") && url.endsWith("/presence")) {
        return jsonResponse({ players: [], active_turn: null, sync_seq: 1 });
      }
      if (url.startsWith("/v1/campaigns/") && url.endsWith("/clocks")) {
        return jsonResponse({ campaign_id: campaign.id, clocks: [] });
      }
      if (url.startsWith("/v1/chat/tree")) {
        return jsonResponse({
          campaign_id: campaign.id,
          channel_id: "main",
          channels: ["main", "scene-dock"],
          nodes: branchMsgs,
          active_branch: branchMsgs,
          active_leaf_id: "m1",
          current_revisions: { campaign_revision: 1, solo_revision: 0 },
          revision_mismatch: false,
        });
      }
      if (url === "/v1/creation/reference") {
        return jsonResponse({
          rules_indexed: true,
          stat_names: ["INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP"],
          stats: {
            INT: { name: "Intelligence", short: "Knowledge", mechanics: "Perception.", tip: "" },
            REF: { name: "Reflexes", short: "Ranged aim", mechanics: "Initiative.", tip: "" },
            DEX: { name: "Dexterity", short: "Agility", mechanics: "Evasion.", tip: "" },
            TECH: { name: "Technique", short: "Tech", mechanics: "Repairs.", tip: "" },
            COOL: { name: "Cool", short: "Poise", mechanics: "Persuasion.", tip: "" },
            WILL: { name: "Willpower", short: "Grit", mechanics: "HP.", tip: "" },
            LUCK: { name: "Luck", short: "Fortune", mechanics: "Clutch.", tip: "" },
            MOVE: { name: "Movement", short: "Speed", mechanics: "Move.", tip: "" },
            BODY: { name: "Body", short: "Physique", mechanics: "Death save.", tip: "" },
            EMP: { name: "Empathy", short: "Humanity", mechanics: "Cyberware.", tip: "" },
          },
          methods: [
            { id: "streetrat", name: "Streetrat (Templates)", badge: "Beginner", summary: "Quick official build", rules: "Roll 1d10." },
            { id: "complete_package", name: "Complete Package (Calculated)", badge: "Pro", summary: "Full 62/86/2550", rules: "Custom buy." },
          ],
          roles: [
            {
              name: "Solo",
              ability: "Combat Awareness",
              ability_summary: "Tactical edge",
              tagline: "Combat specialist",
              best_for: "Combat",
              key_stats: ["REF"],
              page: 29,
              templates: [[6, 8, 7, 5, 6, 6, 6, 6, 7, 5]],
              skills: { Handgun: 6 },
              starting_weapons: [{ type: "fixed", item: "Heavy Pistol", qty: 1 }],
              starting_armor: ["Light Armorjack Body (SP 11)"],
              starting_outfit: ["Agent"],
              starting_cyberware: [],
              starting_hl: 0,
              role_lifepath: [],
            },
          ],
          skills: [
            { name: "Handgun", stat: "REF", cost: 1, basic: false, basic_skill_name: "Handgun", specializable: false, group: "Ranged", summary: "Pistols & SMGs", description: "Handgun skill." },
          ],
          cultural_regions: [{ region: "North American", languages: ["Streetslang", "English", "Spanish"], notes: "NC" }],
          lifepath_tables: {
            personalities: ["Stable and serious"],
            clothing_styles: ["Urban Flash"],
            hairstyles: ["Short and spiked"],
            affectations: ["Mirrorshades"],
            values: ["Your word"],
            feelings_about_people: ["Wary"],
            valued_people: ["A friend"],
            valued_possessions: ["A weapon"],
            family_backgrounds: ["Edgerunners"],
            childhood_environments: ["Streets"],
            family_crises: ["Betrayal"],
            life_goals: ["Survive"],
            enemy_causes: ["Saved someone"],
            enemy_backup: ["Just themselves"],
            enemy_revenge: ["Avoid them"],
            friend_relationships: ["Like a sibling"],
            love_tragedies: ["Lover vanished"],
          },
          shop: {
            weapon: [
              {
                id: "w-poor-pistol",
                name: "Dai Lung Streetmaster (Poor Medium Pistol)",
                category: "weapon",
                cost_eb: 20,
                summary: "Budget Medium Pistol",
                description: "Jams on 1",
                stats: { subtype: "Poor / Budget", weapon_class: "pistol", quality: "Poor (Jams on 1)", skill: "Handgun", damage: "2d6" },
              },
              {
                id: "w-microwaver",
                name: "Microwaver (Exotic)",
                category: "weapon",
                cost_eb: 500,
                summary: "Exotic · Disabled Cyberware · Handgun",
                description: "Exotic Very Heavy Pistol",
                stats: { subtype: "Exotic", weapon_class: "pistol", quality: "Exotic", skill: "Handgun", damage: "EMP Effect" },
              },
              {
                id: "w-shotgun",
                name: "Militech Bulldog (Excellent Shotgun)",
                category: "weapon",
                cost_eb: 1000,
                summary: "+1 Attack Check",
                description: "Excellent Shotgun",
                stats: { subtype: "Excellent (+1 Hit)", weapon_class: "shotgun", quality: "Excellent (+1 Attack)", skill: "Shoulder Arms", damage: "5d6" },
              },
            ],
            armor: [],
            cyberware: [],
            gear: [],
            program: [],
            hardware: [],
            vehicle: [],
            drug: [],
            attachment: [],
            ammo: [],
          },
          fashion: [],
        });
      }
      if (url === "/v1/library") return jsonResponse({ items: [] });
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: [char1, char2],
              npc_profiles: {
                "Drone-Mother": { handle: "Drone-Mother", real_name: "Marta Koval", real_name_hidden: true },
              },
              party_grouping: {
                mode: "split",
                characters: [
                  { id: "char-1", handle: "Vee", location: "Zhirafa Dock", channel_id: "scene-dock" },
                  { id: "char-2", handle: "Kira", location: "La Casita Rooftop", channel_id: "scene-rooftop" },
                ],
                channels: [
                  { id: "scene-dock", name: "Zhirafa Dock", location: "Zhirafa Dock", character_ids: ["char-1"], handles: ["Vee"] },
                  { id: "scene-rooftop", name: "La Casita Rooftop", location: "La Casita Rooftop", character_ids: ["char-2"], handles: ["Kira"] },
                ],
                char_channel_map: { "char-1": "scene-dock", "char-2": "scene-rooftop" },
                active_channel_id: "scene-dock",
                active_location: "Zhirafa Dock",
                prompt_summary: "SPLIT",
              },
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
        if (body.action === "update_character_profile") {
          char1 = {
            ...char1,
            revision: char1.revision + 1,
            detail: { ...char1.detail, color: body.arguments.profile.color },
          };
          return jsonResponse({ result: char1 });
        }
      }
      return jsonResponse({});
    });

    render(<App />);

    // 1. Objective names are rendered cleanly in Campaign tab without truncation
    fireEvent.click(await screen.findByRole("button", { name: /^Campaign$/i }));
    expect(screen.getByText(/Clear Sibling Debt/)).toBeInTheDocument();
    expect(screen.getByText(/Fence Prototype Rig/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Character$/i }));

    // 2. Split Scene channel bar appears
    expect(screen.getByText(/Scene Channels:/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zhirafa Dock \(Vee\)/i })).toBeInTheDocument();

    // 3. Color wheel sets custom hex color
    fireEvent.click(screen.getByRole("button", { name: /^Color$/i }));
    const colorInput = screen.getByLabelText(/Custom name tag color wheel/i);
    fireEvent.change(colorInput, { target: { value: "#ff00aa" } });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/game",
        expect.objectContaining({
          body: expect.stringContaining("#ff00aa"),
        }),
      );
    });

    // 4. Live peer streaming renders incoming peer message + streaming GM text
    const es = MockEventSource.instances[MockEventSource.instances.length - 1];
    es.emit("peer_user_message", {
      campaign_id: campaign.id,
      channel_id: "scene-dock",
      client_id: "peer-client-99",
      message: {
        id: "m-peer-u1",
        campaign_id: campaign.id,
        channel_id: "scene-dock",
        parent_id: "m1",
        role: "user",
        content: "I scan the dock lock.",
        raw_content: "I scan the dock lock.",
        model: "",
        campaign_revision: 1,
        solo_revision: 0,
        metadata: { speaker_name: "Vee", speaker_character_id: "char-1" },
        is_active: true,
        created_at: "2026-11-18T08:01:00Z",
      },
    });
    expect(await screen.findByText(/I scan the dock lock\./i)).toBeInTheDocument();

    es.emit("peer_stream", {
      campaign_id: campaign.id,
      channel_id: "scene-dock",
      client_id: "peer-client-99",
      speaker_name: "Vee",
      event: "text_delta",
      data: { delta: "The maglock hums softly under your scanner." },
    });
    expect(await screen.findByText(/The maglock hums softly under your scanner\./i)).toBeInTheDocument();

    // 5. Character Creator: Gender + Pronouns, Street Origins & Background, Genre + Tier filters + Sort by Tier
    const newButtons = screen.getAllByRole("button", { name: /^New$/i });
    fireEvent.click(newButtons[newButtons.length - 1]);
    expect(await screen.findByLabelText(/^Gender$/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /4\. Backstory & Lifepath/i }));
    expect(screen.getByText(/Street Origins & Background/i)).toBeInTheDocument();
    expect(screen.queryByText(/Corebook Lifepath Tables/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Roll d10, Pick, or Type Custom/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /5\. Gear & Cyberware/i }));
    // Switch to Complete Package so shop catalog shows
    fireEvent.click(screen.getByRole("button", { name: /1\. Identity & Role/i }));
    fireEvent.click(screen.getByRole("button", { name: /Complete Package/i }));
    fireEvent.click(screen.getByRole("button", { name: /5\. Gear & Cyberware/i }));

    // Select Pistols & SMGs genre AND Exotic tier -> Microwaver (Exotic) appears, Poor Pistol & Shotgun hidden
    fireEvent.click(screen.getByRole("button", { name: /^Pistols & SMGs$/i }));
    expect(screen.getByText(/Microwaver \(Exotic\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Dai Lung Streetmaster/i)).toBeInTheDocument();
    expect(screen.queryByText(/Militech Bulldog/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Exotic$/i }));
    expect(screen.getByText(/Microwaver \(Exotic\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/Dai Lung Streetmaster/i)).not.toBeInTheDocument();

    // Clear tier filter & sort by Tier: Exotic -> Poor
    fireEvent.click(screen.getByRole("button", { name: /^All Tiers$/i }));
    fireEvent.change(screen.getByLabelText(/Sort catalog/i), { target: { value: "tier_desc" } });
    const catalogText = document.body.textContent ?? "";
    expect(catalogText.indexOf("Microwaver (Exotic)")).toBeLessThan(catalogText.indexOf("Dai Lung Streetmaster"));
  });

  it("gates character deletion behind claiming for players and supports equipping weapons and armor", async () => {
    const campaign = {
      id: "camp-eq",
      name: "Night Ops",
      revision: 1,
      session_number: 1,
      state: { scene: "Watson", npcs: {}, discoveries: {}, objectives: {}, summary: "" },
      character_ids: ["char-eq-1"],
    };
    let currentChar = {
      id: "char-eq-1",
      name: "Rook",
      revision: 1,
      hp: 35,
      max_hp: 35,
      humanity: 60,
      luck_remaining: 6,
      money: 500,
      stats: { INT: 6, REF: 6, DEX: 6, TECH: 6, COOL: 6, WILL: 6, LUCK: 6, MOVE: 6, BODY: 6, EMP: 6 },
      skills: { Handgun: 4 },
      inventory: { "Heavy Pistol": 1, "Light Armorjack Body (SP 11)": 1 },
      detail: { handle: "Rook" } as Record<string, unknown>,
    };
    const profileUpdates: Array<Record<string, unknown>> = [];
    let deletedCalled = false;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url === "/health") {
        return jsonResponse({ status: "ok", rules_indexed: true, pass_count: 100 });
      }
      if (url === "/v1/auth/status") {
        return jsonResponse({
          auth_enabled: true,
          setup_required: false,
          authenticated: true,
          role: "user",
          username: "alice",
          pin_only_mode: false,
        });
      }
      if (url === "/v1/settings") {
        return jsonResponse({
          turn_settings: { require_character_to_speak: true },
          prompts: {},
          runtime: { gm_style: "grounded", narrator_length: "standard" },
        });
      }
      if (url === "/v1/creation/reference") {
        return jsonResponse({
          skills: { Handgun: { stat: "REF", cost: 1, specializable: false } },
          roles: {},
          shop: { weapon: [], armor: [], cyberware: [], gear: [], program: [], hardware: [], vehicle: [], drug: [] },
        });
      }
      if (url === "/v1/library") return jsonResponse({ items: [] });
      if (url === "/v1/game") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (body.action === "list_campaigns") return jsonResponse({ result: [campaign] });
        if (body.action === "campaign_context") {
          return jsonResponse({
            result: {
              campaign,
              characters: deletedCalled ? [] : [currentChar],
              npc_profiles: {},
              party_grouping: { mode: "together", characters: [], channels: [], prompt_summary: "" },
              solo: { revision: 0, runtime: { encounter: null, runs: {}, clock_minutes: 0 }, characters: {} },
            },
          });
        }
        if (body.action === "update_character_profile") {
          const prof = body.arguments.profile as Record<string, unknown>;
          profileUpdates.push(prof);
          currentChar = {
            ...currentChar,
            revision: currentChar.revision + 1,
            detail: { ...currentChar.detail, ...prof },
          };
          return jsonResponse({ result: currentChar });
        }
        if (body.action === "delete_character") {
          deletedCalled = true;
          return jsonResponse({ result: { deleted: true, id: "char-eq-1", name: "Rook" } });
        }
        return jsonResponse({ result: {} });
      }
      if (url.includes("/chat/tree")) {
        return jsonResponse({
          active_leaf_id: null,
          messages: [],
          branches: [],
          channels: [{ id: "main", name: "Main Table", location: "" }],
        });
      }
      if (url.includes("/coop/state")) {
        return jsonResponse({ players: [], protect_others: false });
      }
      return jsonResponse({});
    });

    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    // Open Character tab (in mobile/narrow or desktop rail)
    const delBtn = await screen.findByRole("button", { name: /Delete Rook/i });
    expect(delBtn).toBeDisabled();

    // Claim sheet -> Delete becomes enabled
    fireEvent.click(screen.getByRole("button", { name: /Claim Sheet/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Delete Rook/i })).not.toBeDisabled());

    // Switch to Gear tab and equip Heavy Pistol and Light Armorjack Body
    fireEvent.click(screen.getByRole("button", { name: /Gear \(2\)/i }));
    const equipButtons = screen.getAllByRole("button", { name: /^Equip$/i });
    fireEvent.click(equipButtons[0]);
    await waitFor(() =>
      expect(profileUpdates.some((p) => p.equipped_weapon === "Heavy Pistol")).toBe(true),
    );

    const equipBodyBtn = screen.getByRole("button", { name: /^Equip$/i });
    fireEvent.click(equipBodyBtn);
    await waitFor(() =>
      expect(
        profileUpdates.some(
          (p) =>
            typeof p.equipped_armor === "object" &&
            p.equipped_armor !== null &&
            (p.equipped_armor as { name?: string }).name === "Light Armorjack Body (SP 11)" &&
            (p.equipped_armor as { sp?: number }).sp === 11,
        ),
      ).toBe(true),
    );

    // Delete character with confirmation
    fireEvent.click(screen.getByRole("button", { name: /Delete Rook/i }));
    fireEvent.click(screen.getByRole("button", { name: /Confirm Delete/i }));
    await waitFor(() => expect(deletedCalled).toBe(true));
  });
});

function initOptionsOrEmpty(x: unknown) {
  return x ?? "{}";
}
