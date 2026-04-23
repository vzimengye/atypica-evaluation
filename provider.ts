import "server-only"; // To prevent accidental usage in Client Components

import { createOpenAICompatible } from "@ai-sdk/openai-compatible";

/**
 * PPIO 派欧云 — OpenAI-compatible provider.
 * Docs: https://ppio.com/docs/model/llm.md
 * Base URL: https://api.ppio.com/openai
 */
const ppio = createOpenAICompatible({
  name: "ppio",
  apiKey: process.env.PPIO_API_KEY,
  baseURL: "https://api.ppio.com/openai",
  includeUsage: true,
  supportsStructuredOutputs: true,
});

/**
 * Mapping: developer-facing model name → PPIO PA model ID.
 * Source: PPIO 模型列表 (chat/completions models only).
 */
const MODEL_MAP = {
  // ── OpenAI ──
  "gpt-5.2": "pa/gpt-5.2",
  "gpt-5.2-chat-latest": "pa/gpt-5.2-chat-latest",
  "gpt-5.1": "pa/gpt-5.1",
  "gpt-5.1-chat-latest": "pa/gpt-5.1-chat-latest",
  "gpt-5": "pa/gpt-5",
  "gpt-5-mini": "pa/gpt-5-mini",
  "gpt-5-nano": "pa/gpt-5-nano",
  "gpt-5-chat-latest": "pa/gpt-5-chat-latest",
  "gpt-4.1": "pa/gt-4.1",
  "gpt-4.1-nano": "pa/gt-4.1-n",
  "gpt-4.1-mini": "pa/gt-4.1-m",
  "gpt-4o": "pa/gt-4p",
  "gpt-4o-mini": "pa/gt-4p-m",
  "o1": "pa/p1",
  "o1-mini": "pa/p1-m",
  "o3-mini": "pa/p3-m",
  "o3": "pa/p3",
  "o4-mini": "pa/o4-mini",

  // ── Anthropic ──
  "claude-sonnet-4-6": "pa/claude-sonnet-4-6",
  "claude-opus-4-6": "pa/claude-opus-4-6",
  "claude-opus-4-5": "pa/claude-opus-4-5-20251101",
  "claude-sonnet-4-5": "pa/claude-sonnet-4-5-20250929",
  "claude-haiku-4-5": "pa/claude-haiku-4-5-20251001",
  "claude-opus-4-1": "pa/claude-opus-4-1-20250805",
  "claude-sonnet-4": "pa/cd-st-4-20250514",
  "claude-opus-4": "pa/cd-op-4-20250514",
  "claude-3-7-sonnet": "pa/cd-3-7-st-20250219",
  "claude-3-5-sonnet": "pa/cd-3-5-st-20241022",
  "claude-3-5-haiku": "pa/cd-3-5-hk-20241022",
  "claude-3-haiku": "pa/cd-3-hk-20240307",

  // ── Google ──
  "gemini-2.5-flash": "pa/gmn-2.5-fls",
  "gemini-2.5-pro": "pa/gmn-2.5-pr",
  "gemini-2.5-flash-lite": "pa/gmn-2.5-fls-lt",
  "gemini-2.0-flash": "pa/gmn-2.0-fls-20250609",
  "gemini-2.0-flash-lite": "pa/gmn-2.0-fls-lt",
  "gemini-2.5-flash-preview-05-20": "pa/gmn-2.5-fls-pw-05-20",
  "gemini-2.5-pro-preview-06-05": "pa/gmn-2.5-pr-pw-06-05",
  "gemini-2.5-flash-lite-preview-06-17": "pa/gmn-2.5-fls-lt-pw-06-17",
  "gemini-2.5-flash-lite-preview-09-2025": "pa/gemini-2.5-flash-lite-preview",
  "gemini-3-pro-preview": "pa/gemini-3-pro-preview",
  "gemini-3-flash": "pa/gemini-3-flash-preview",
  "gemini-3-flash-preview": "pa/gemini-3-flash-preview",
  "gemini-3.1-pro-preview": "pa/gemini-3.1-pro-preview",

  // ── Grok ──
  "grok-4-1-fast-non-reasoning": "pa/grok-4-1-fast-non-reasoning",
  "grok-4-1-fast-reasoning": "pa/grok-4-1-fast-reasoning",
  "grok-4": "pa/grk-4",
  "grok-4-fast-reasoning": "pa/grok-4-fast-reasoning",
  "grok-4-fast-non-reasoning": "pa/grok-4-fast-non-reasoning",
  "grok-code-fast-1": "pa/grok-code-fast-1",
  "grok-3": "pa/grk-3",
  "grok-3-mini": "pa/grok-3-mini",

  // ── 豆包 (Doubao) ──
  "doubao-seed-1-8": "pa/doubao-seed-1-8-251228",
  "doubao-seed-1.6": "pa/doubao-seed-1.6",
  "doubao-seed-1.6-thinking": "pa/doubao-seed-1.6-thinking",
  "doubao-seed-1.6-flash": "pa/doubao-seed-1.6-flash",
  "doubao-1-5-pro-32k": "pa/doubao-1-5-pro-32k-250115",
  "doubao-1.5-pro-32k-character": "pa/doubao-1.5-pro-32k-character-250715",
} as const satisfies Record<string, string>;

export type LLMModelName = keyof typeof MODEL_MAP;

export const defaultProviderOptions = (
  llm?: LLMModelName, // eslint-disable-line @typescript-eslint/no-unused-vars
) => {
  return {};
};

export function llm(modelName: LLMModelName) {
  const paModelId = MODEL_MAP[modelName];
  return ppio(paModelId);
}
