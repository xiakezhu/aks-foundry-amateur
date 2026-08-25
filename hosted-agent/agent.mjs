#!/usr/bin/env node
/**
 * One-shot Pi agent. Reads JSON {prompt, session_id} from stdin,
 * writes JSON {text, session_id} to stdout.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { stdin as input } from "node:process";
import { Agent } from "@earendil-works/pi-agent-core";
import {
  Type,
  contentText,
  createModels,
  createProvider,
  envApiKeyAuth,
} from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";

const PROVIDER_ID = "foundry-openai-compatible";
const SESSION_DIR = process.env.PI_SESSION_DIR || "/tmp/pi-sessions";

const SYSTEM_PROMPT = [
  "You are a small example Pi agent hosted on Microsoft Foundry.",
  "Answer directly when no tool is needed.",
  "Use get_current_time when the user asks about the current date or time.",
  "Keep replies concise. You have no file or shell tools.",
].join(" ");

function requiredEnv(name, aliases = []) {
  for (const key of [name, ...aliases]) {
    const value = process.env[key]?.trim();
    if (value) return value;
  }
  throw new Error(`Missing ${[name, ...aliases].join(" or ")}`);
}

const getCurrentTimeTool = {
  label: "Current Time",
  name: "get_current_time",
  description: "Get the current date and time",
  parameters: Type.Object({
    timezone: Type.Optional(
      Type.String({
        description: "Optional IANA timezone, e.g. America/Los_Angeles or Asia/Shanghai",
      }),
    ),
  }),
  execute: async (_toolCallId, args) => {
    const date = new Date();
    let text;
    if (args.timezone) {
      text = date.toLocaleString("en-US", {
        timeZone: args.timezone,
        dateStyle: "full",
        timeStyle: "long",
      });
    } else {
      text = date.toISOString();
    }
    return {
      content: [{ type: "text", text }],
      details: { utcTimestamp: date.getTime(), timezone: args.timezone || "UTC" },
    };
  },
};

async function readStdin() {
  const chunks = [];
  for await (const chunk of input) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  if (!raw) throw new Error("empty stdin");
  return JSON.parse(raw);
}

function lastAssistantText(messages) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message?.role !== "assistant") continue;
    const text = contentText(message.content || []).trim();
    if (text) return text;
    if (message.errorMessage) return `agent error: ${message.errorMessage}`;
  }
  return "";
}

async function loadMessages(sessionId) {
  const path = join(SESSION_DIR, `${sessionId}.json`);
  try {
    const parsed = JSON.parse(await readFile(path, "utf8"));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function saveMessages(sessionId, messages) {
  await mkdir(SESSION_DIR, { recursive: true });
  await writeFile(join(SESSION_DIR, `${sessionId}.json`), JSON.stringify(messages), "utf8");
}

function createRuntime() {
  const baseUrl = requiredEnv("OPENAI_BASE_URL");
  const modelId = requiredEnv("OPENAI_MODEL");
  const model = {
    id: modelId,
    name: modelId,
    api: "openai-completions",
    provider: PROVIDER_ID,
    baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 4096,
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
    },
  };
  const provider = createProvider({
    id: PROVIDER_ID,
    name: "OpenAI-compatible",
    baseUrl,
    auth: { apiKey: envApiKeyAuth("OpenAI-compatible API key", ["OPENAI_API_KEY", "LLM_API_KEY"]) },
    models: [model],
    api: openAICompletionsApi(),
  });
  const models = createModels();
  models.setProvider(provider);
  const resolved = models.getModel(PROVIDER_ID, modelId);
  if (!resolved) throw new Error(`Unable to configure model ${modelId}`);
  return { models, model: resolved };
}

async function main() {
  const body = await readStdin();
  const prompt = String(body.prompt || "").trim();
  if (!prompt) throw new Error("prompt is required");
  const sessionId = String(body.session_id || "default");

  const { models, model } = createRuntime();
  const messages = await loadMessages(sessionId);
  const agent = new Agent({
    initialState: {
      systemPrompt: SYSTEM_PROMPT,
      model,
      tools: [getCurrentTimeTool],
      messages,
    },
    streamFn: models.streamSimple.bind(models),
  });

  await agent.prompt(prompt);
  const nextMessages = agent.state.messages;
  await saveMessages(sessionId, nextMessages);
  const text = lastAssistantText(nextMessages) || "(empty Pi response)";
  process.stdout.write(`${JSON.stringify({ text, session_id: sessionId })}\n`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.stdout.write(`${JSON.stringify({ error: error instanceof Error ? error.message : String(error) })}\n`);
  process.exitCode = 1;
});
