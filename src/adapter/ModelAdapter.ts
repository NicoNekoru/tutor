import { spawn } from 'child_process';
import { GenerateRequest, GenerateResult, ModelAdapter } from '../schemas/types';

export interface ModelBackendConfig {
  command: string;
  args?: string[];
  env?: Record<string, string>;
  timeoutMs?: number;
}

// CLI-based adapter that expects JSON in/out via subprocess
export class CLIModelAdapter implements ModelAdapter {
  private config: ModelBackendConfig;

  constructor(config: ModelBackendConfig) {
    this.config = config;
  }

  async generate(request: GenerateRequest): Promise<GenerateResult> {
    const payload = {
      messages: request.messages,
      tools: request.tools,
      response_format: request.responseFormat,
      temperature: request.temperature,
    };

    try {
      const stdout = await this.callBackend(payload);
      const result = JSON.parse(stdout);

      return {
        text: result.text,
        toolCalls: result.tool_calls,
        raw: result,
      };
    } catch (error) {
      console.error('Model adapter error:', error);
      return {
        text: `[Error: ${error instanceof Error ? error.message : String(error)}]`,
      };
    }
  }

  private callBackend(payload: unknown): Promise<string> {
    return new Promise((resolve, reject) => {
      const { command, args = [], env = {}, timeoutMs = 60000 } = this.config;

      const proc = spawn(command, args, {
        env: { ...process.env, ...env },
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';

      proc.stdout.on('data', (data: Buffer) => {
        stdout += data.toString();
      });

      proc.stderr.on('data', (data: Buffer) => {
        stderr += data.toString();
      });

      const timeout = setTimeout(() => {
        proc.kill('SIGTERM');
        reject(new Error(`Model backend timeout after ${timeoutMs}ms`));
      }, timeoutMs);

      proc.on('close', (code: number | null) => {
        clearTimeout(timeout);
        if (code !== 0) {
          reject(new Error(`Model backend exited with code ${code}: ${stderr}`));
        } else {
          resolve(stdout);
        }
      });

      proc.on('error', (err: Error) => {
        clearTimeout(timeout);
        reject(err);
      });

      proc.stdin.write(JSON.stringify(payload));
      proc.stdin.end();
    });
  }
}

// Simple echo adapter for testing without a model backend
export class EchoModelAdapter implements ModelAdapter {
  async generate(request: GenerateRequest): Promise<GenerateResult> {
    const lastUserMsg = [...request.messages].reverse().find((m) => m.role === 'user');
    return {
      text: `[Echo] Received: "${lastUserMsg?.content || '(no message)'}".\n\nThis is a placeholder response. Configure a model backend to get real tutoring responses.`,
    };
  }
}

export function createModelAdapter(config?: ModelBackendConfig): ModelAdapter {
  if (!config) {
    return new EchoModelAdapter();
  }
  return new CLIModelAdapter(config);
}
