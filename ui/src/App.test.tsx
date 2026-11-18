import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

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
    fireEvent.click(screen.getByRole("button", { name: /llama3/i }));
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
    expect(screen.getByText(/Corebook Not Indexed/i)).toBeInTheDocument();
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

    // Open Co-op modal and verify LAN join URL renders
    fireEvent.click(screen.getByTitle(/Co-op players/i));
    await waitFor(() => {
      expect(screen.getByText("http://192.168.1.42:8765/?campaign=camp-qol")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByLabelText("Close co-op settings"));

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

    fireEvent.click(screen.getByRole("button", { name: /llama3/i }));
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

    fireEvent.change(screen.getByPlaceholderText("player"), { target: { value: "edge" } });
    fireEvent.change(screen.getByPlaceholderText(/Enter password/i), { target: { value: "player-pass" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign In as Player/i }));

    await waitFor(() => {
      expect(screen.getByText("USER")).toBeInTheDocument();
    });
    // Regular User does not see the Admin AI/Settings button
    expect(screen.queryByRole("button", { name: /Configure AI|llama3/i })).not.toBeInTheDocument();

    // Switch to Admin via TopBar Admin Login button
    fireEvent.click(screen.getByRole("button", { name: /Admin Login/i }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /Cyberpunk RED GM Access/i })).toBeInTheDocument();
    });
    fireEvent.change(screen.getByPlaceholderText("admin"), { target: { value: "netwatch" } });
    fireEvent.change(screen.getByPlaceholderText(/Enter password/i), { target: { value: "admin-pass" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign In as Admin/i }));

    await waitFor(() => {
      expect(screen.getByText("ADMIN")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /llama3/i })).toBeInTheDocument();
    });

    // TopBar 2-mode toggle switches directly between GM Quality and GM Balanced
    const balancedBtn = screen.getByRole("button", { name: /^GM Balanced$/i });
    expect(screen.getByRole("button", { name: /^GM Quality$/i })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(balancedBtn);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/settings/llm",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ gm_thinking_mode: "balanced" }),
        }),
      );
    });
    expect(screen.getByRole("button", { name: /^GM Balanced$/i })).toHaveAttribute("aria-pressed", "true");

    // Open Admin Control Center -> Prompts & Network tabs
    fireEvent.click(screen.getByRole("button", { name: /llama3/i }));
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /AI Game Master Connection/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Prompts$/i }));
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

    // AI Generate from Scratch + AI Expand + AI Generate Contacts
    fireEvent.click(screen.getByRole("button", { name: /AI Generate from Scratch/i }));
    await waitFor(() => {
      expect((screen.getByPlaceholderText(/Write a few sentences about your life/i) as HTMLTextAreaElement).value).toContain(
        "Raised in Watson",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: /AI Generate Contacts/i }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("Takemura Jin")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Bricks Jr.")).toBeInTheDocument();
    });

    fireEvent.change(
      screen.getByPlaceholderText(/Owes 200 eb to Mama Welles/i),
      { target: { value: "Ran recon out of Kabuki; owes Dakota Smith one clean favor." } },
    );
    fireEvent.click(screen.getByRole("button", { name: /AI Expand \/ Improve Established History/i }));
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
    fireEvent.click(screen.getByRole("button", { name: /Exotic & Heavy/i }));
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
      expect(screen.getAllByText("Rina Ash").length).toBeGreaterThan(0);
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
    await waitFor(() => {
      expect(screen.getByTitle(/Open Campaign Architect/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle(/Open Campaign Architect/i));
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
});
