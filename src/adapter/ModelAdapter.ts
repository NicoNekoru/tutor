import { spawn } from 'child_process';
import { GenerateRequest, GenerateResult, ToolSpec, MessageRole } from '../schemas/types';

export interface ModelBackendConfig {
  command: string;
  args?: string[];
  env?: Record<string, string>;
  timeoutMs?: number;
}

// Abstract base class for model adapters
export abstract class BaseModelAdapter {
  abstract generate(request: GenerateRequest): Promise<GenerateResult>;
  abstract stream?(request: GenerateRequest): AsyncIterable<string>;

  protected async callBackend(
    payload: unknown,
    config: ModelBackendConfig
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      const { command, args = [], env = {}, timeoutMs = 60000 } = config;

      const proc = spawn(command, args, {
        env: { ...process.env, ...env },
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';

      proc.stdout.on('data', (data) => {
        stdout += data.toString();
      });

      proc.stderr.on('data', (data) => {
        stderr += data.toString();
      });

      const timeout = setTimeout(() => {
        proc.kill('SIGTERM');
        reject(new Error(`Model backend timeout after ${timeoutMs}ms`));
      }, timeoutMs);

      proc.on('close', (code) => {
        clearTimeout(timeout);
        if (code !== 0) {
          reject(
            new Error(`Model backend exited with code ${code}: ${stderr}`)
          );
        } else {
          resolve(stdout);
        }
      });

      proc.on('error', (err) => {
        clearTimeout(timeout);
        reject(err);
      });

      // Write payload to stdin
      proc.stdin.write(JSON.stringify(payload));
      proc.stdin.end();
    });
  }

  protected parseToolCalls(text: string): GenerateResult['toolCalls'] {
    // Basic parsing for tool call patterns (customize for your backend)
    // This is a placeholder; actual implementation depends on backend format
    return undefined;
  }
}

// Example: CLI-based adapter that expects JSON in/out
export class CLIModelAdapter extends BaseModelAdapter {
  private config: ModelBackendConfig;

  constructor(config: ModelBackendConfig) {
    super();
    this.config = config;
  }

  async generate(request: GenerateRequest): Promise<GenerateResult> {
    // Transform internal request format to backend format
    const payload = {
      messages: request.messages,
      tools: request.tools,
      response_format: request.responseFormat,
      temperature: request.temperature,
    };

    try {
      const stdout = await this.callBackend(payload, this.config);
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
}

// Adapter factory
export function createModelAdapter(config: ModelBackendConfig): BaseModelAdapter {
  return new CLIModelAdapter(config);
}
