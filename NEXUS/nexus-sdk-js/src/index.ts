import axios, { AxiosInstance } from 'axios';

export interface NexusSDKConfig {
  /** Client token accepted by the FastAPI facade when NEXUS_API_TOKEN is set. */
  apiKey?: string;
  baseURL?: string;
  timeout?: number;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ChatCompletionOptions {
  model?: string;
  maxTokens?: number;
  temperature?: number;
  timeoutSeconds?: number;
}

export interface ChatCompletion {
  id: string;
  object: 'chat.completion';
  created: number;
  model: string;
  choices: Array<{
    index: number;
    message: { role: 'assistant'; content: string };
    finish_reason: string;
  }>;
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
}

export class NexusAPIError extends Error {
  constructor(message: string, public statusCode: number, public payload?: unknown) {
    super(message);
    this.name = 'NexusAPIError';
  }
}

function errorMessage(payload: any): string {
  let detail = payload?.error ?? payload?.detail;
  if (detail && typeof detail === 'object' && 'error' in detail) {
    detail = detail.error;
  }
  if (detail && typeof detail === 'object') {
    detail = detail.message ?? detail.detail ?? JSON.stringify(detail);
  }
  return String(detail || 'NEXUS request failed');
}

function validateBaseURL(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new TypeError('baseURL must be a valid HTTP(S) origin');
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname.toLowerCase());
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password
      || !['', '/'].includes(parsed.pathname) || parsed.search || parsed.hash
      || (parsed.protocol === 'http:' && !loopback)) {
    throw new TypeError('baseURL must be a plain HTTPS origin unless it targets loopback');
  }
  return value.replace(/\/$/, '');
}

export class NexusClient {
  private readonly client: AxiosInstance;

  constructor(config: NexusSDKConfig = {}) {
    this.client = axios.create({
      baseURL: validateBaseURL(config.baseURL || 'http://127.0.0.1:8000'),
      timeout: config.timeout ?? 300_000,
      maxRedirects: 0,
      proxy: false,
      headers: {
        Accept: 'application/json',
        ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
      },
    });
  }

  async chat(messages: string | ChatMessage[], options: ChatCompletionOptions = {}): Promise<ChatCompletion> {
    const normalized = typeof messages === 'string' ? [{ role: 'user' as const, content: messages }] : messages;
    const timeoutSeconds = options.timeoutSeconds ?? 300;
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 1800) {
      throw new RangeError('timeoutSeconds must be an integer from 1 to 1800');
    }
    try {
      const response = await this.client.post<ChatCompletion>('/v1/chat/completions', {
        model: options.model ?? '',
        messages: normalized,
        max_tokens: options.maxTokens ?? 256,
        temperature: options.temperature ?? 0.3,
        timeout_s: timeoutSeconds,
      }, { timeout: Math.max(this.client.defaults.timeout ?? 300_000, (timeoutSeconds + 10) * 1000) });
      return response.data;
    } catch (error: any) {
      if (error.response) {
        const payload = error.response.data;
        throw new NexusAPIError(errorMessage(payload), error.response.status, payload);
      }
      throw error;
    }
  }

  async query(query: string, options: ChatCompletionOptions = {}): Promise<ChatCompletion> {
    return this.chat(query, options);
  }

  async infer(task: string, options: ChatCompletionOptions = {}): Promise<ChatCompletion> {
    return this.chat(task, options);
  }

  async *chatStream(_messages: ChatMessage[]): AsyncGenerator<string, void, unknown> {
    throw new NexusAPIError('Streaming is not supported by the H0 gateway.', 501);
  }
}

export default NexusClient;
