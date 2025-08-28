import axios, { AxiosInstance, AxiosResponse } from 'axios';
import { EventEmitter } from 'events';

interface NexusSDKConfig {
  apiKey: string;
  baseURL?: string;
  timeout?: number;
}

interface QueryOptions {
  maxResults?: number;
  minConfidence?: number;
  includeSources?: boolean;
}

interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}

class NexusClient {
  private client: AxiosInstance;
  private eventEmitter: EventEmitter;

  constructor(config: NexusSDKConfig) {
    this.client = axios.create({
      baseURL: config.baseURL || 'https://api.nexus.ai',
      timeout: config.timeout || 30000,
      headers: {
        'X-API-Key': config.apiKey,
        'Content-Type': 'application/json'
      }
    });

    this.eventEmitter = new EventEmitter();
  }

  async query(query: string, options: QueryOptions = {}): Promise<any> {
    try {
      const response = await this.client.post('/v1/cognitive/query', {
        query,
        ...options
      });

      return response.data;
    } catch (error) {
      this.handleError(error);
    }
  }

  async *chatStream(messages: ChatMessage[]): AsyncGenerator<string, void, unknown> {
    try {
      const response = await this.client.post('/v1/cognitive/chat', {
        messages,
        stream: true
      }, {
        responseType: 'stream'
      });

      for await (const chunk of response.data) {
        yield chunk.toString();
      }
    } catch (error) {
      this.handleError(error);
    }
  }

  async uploadKnowledge(content: string, metadata: any = {}): Promise<string> {
    try {
      const response = await this.client.post('/v1/knowledge/upload', {
        content,
        metadata
      });

      return response.data.knowledge_id;
    } catch (error) {
      this.handleError(error);
    }
  }

  on(event: string, listener: (...args: any[]) => void): void {
    this.eventEmitter.on(event, listener);
  }

  private handleError(error: any): never {
    if (error.response) {
      throw new NexusAPIError(
        error.response.data?.error || 'API request failed',
        error.response.status
      );
    } else {
      throw new Error(error.message);
    }
  }
}

class NexusAPIError extends Error {
  constructor(message: string, public statusCode: number) {
    super(message);
    this.name = 'NexusAPIError';
  }
}

// Ejemplo de uso
export async function exampleUsage() {
  const client = new NexusClient({
    apiKey: 'your_api_key_here'
  });

  // Consulta de conocimiento
  const result = await client.query('What is quantum computing?');
  console.log(result);

  // Chat en streaming
  const messages: ChatMessage[] = [{
    role: 'user',
    content: 'Explain AI safety',
    timestamp: new Date()
  }];

  for await (const chunk of client.chatStream(messages)) {
    process.stdout.write(chunk);
  }
}

export default NexusClient;