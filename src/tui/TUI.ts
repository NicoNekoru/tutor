import blessed from 'blessed';
import { clear, move } from 'blessed/contrib';
import { Orchestrator } from '../orchestrator/Orchestrator';
import { WorkspaceManager } from '../workspace/WorkspaceManager';
import { SearchResult } from '../schemas/types';

export class TutorTUI {
  private screen: blessed.Widgets.Screen;
  private mainBox: blessed.Widgets.BoxElement;
  private navigationBox: blessed.Widgets.BoxElement;
  private contextBox: blessed.Widgets.BoxElement;
  private toolsBox: blessed.Widgets.BoxElement;
  private inputLine: blessed.Widgets.TextAreaElement;
  private chatBox: blessed.Widgets.TextAreaElement;

  private orchestrator: Orchestrator;
  private ws: WorkspaceManager;
  private currentContext: SearchResult[] = [];
  private chatHistory: Array<{ role: string; content: string }> = [];

  constructor(orchestrator: Orchestrator, ws: WorkspaceManager) {
    this.orchestrator = orchestrator;
    this.ws = ws;

    this.screen = blessed.screen({
      smartCSR: true,
      fullUnicode: true,
      cursor: {
        artificial: true,
        shape: 'block',
        blink: true,
      },
    });

    this.layout();
    this.setupKeybindings();

    this.chatBox.setContent(
      'Welcome to the Tutor App!\n\nInitializing session...'.split('\n')
    );
  }

  private layout(): void {
    const width = this.screen.width;
    const height = this.screen.height;

    // Navigation pane (left, 25 width)
    this.navigationBox = blessed.box({
      top: 0,
      left: 0,
      width: 25,
      height: height - 1,
      tags: true,
      border: {
        type: 'line',
      },
      style: {
        fg: 'white',
        bg: 'blue',
        border: {
          fg: '#f0f0f0',
        },
      },
    });
    this.navigationBox.setContent(
      [
        '{bold}Navigation',
        '',
        'Course: combinatorics',
        'Current: Lesson 1',
        '',
        '{bold}Topics',
        '  counting principles',
        '  bijections',
        '  inclusion-exclusion',
        '',
        '{bold}Commands',
        '  :help  :syllabus',
        '  :lesson next',
        '  :search <query>',
        '  :context',
      ].join('\n')
    );

    // Main dialogue pane (center)
    this.chatBox = blessed.textarea({
      top: 0,
      left: 25,
      width: Math.floor(width * 0.5) - 25,
      height: Math.floor(height * 0.7),
      border: {
        type: 'line',
      },
      scrollable: true,
      alwaysScroll: true,
      mouse: true,
      keys: true,
      input: false,
      tags: true,
      style: {
        fg: 'white',
        bg: 'black',
        border: {
          fg: '#f0f0f0',
        },
      },
    });

    // Context inspector (right-top)
    this.contextBox = blessed.box({
      top: 0,
      left: Math.floor(width * 0.5),
      width: width - Math.floor(width * 0.5) - 1,
      height: Math.floor(height * 0.4),
      border: {
        type: 'line',
      },
      scrollable: true,
      tags: true,
      style: {
        fg: 'white',
        bg: 'cyan',
        border: {
          fg: '#f0f0f0',
        },
      },
    });
    this.contextBox.setContent('{bold}Context Inspector\n\n(no context yet)');

    // Scratch/tools pane (right-bottom)
    this.toolsBox = blessed.box({
      top: Math.floor(height * 0.4),
      left: Math.floor(width * 0.5),
      width: width - Math.floor(width * 0.5) - 1,
      height: Math.floor(height * 0.6) - Math.floor(height * 0.4) - 2,
      border: {
        type: 'line',
      },
      scrollable: true,
      tags: true,
      style: {
        fg: 'white',
        bg: 'magenta',
        border: {
          fg: '#f0f0f0',
        },
      },
    });
    this.toolsBox.setContent('{bold}Tools / Events\n\n(waiting for actions...)');

    // Input line at bottom
    this.inputLine = blessed.textarea({
      bottom: 0,
      left: 0,
      width: width - 1,
      height: 3,
      border: {
        type: 'line',
      },
      inputOnFocus: true,
      tags: true,
      style: {
        fg: 'white',
        bg: 'black',
        border: {
          fg: '#f0f0f0',
        },
      },
    });

    this.screen.append(
      this.navigationBox,
      this.chatBox,
      this.contextBox,
      this.toolsBox,
      this.inputLine
    );

    this.inputLine.focus();
  }

  private setupKeybindings(): void {
    this.screen.key(['enter', 'return'], async (ch, key) => {
      const message = this.inputLine.getValue().trim();
      if (!message) return;

      // Add user message to chat
      this.appendChat('You', message);
      this.inputLine.setValue('');

      // Check for commands
      if (message.startsWith(':')) {
        await this.handleCommand(message.slice(1));
        return;
      }

      // Process through orchestrator
      try {
        const result = await this.orchestrator.processTurn(message);
        this.appendChat('Tutor', result.response);

        // Update context pane
        if (result.toolCalls) {
          this.toolsBox.setContent(
            `{bold}Tool Calls:\n${JSON.stringify(result.toolCalls, null, 2)}`
          );
        }
      } catch (error) {
        this.appendChat('System', `Error: ${error instanceof Error ? error.message : String(error)}`);
      }
    });

    this.screen.key(['C-c'], () => {
      this.screen.destroy();
      process.exit(0);
    });
  }

  private async handleCommand(cmd: string): Promise<void> {
    const [command, ...args] = cmd.split(' ');

    switch (command) {
      case 'help':
        this.showHelp();
        break;
      case 'syllabus':
        this.showSyllabus();
        break;
      case 'lesson':
        if (args[0] === 'next') {
          await this.nextLesson();
        } else if (args[0] === 'open' && args[1]) {
          await this.openLesson(args[1]);
        }
        break;
      case 'search':
        if (args[0]) {
          await this.search(args.join(' '));
        }
        break;
      case 'context':
        this.showContext();
        break;
      default:
        this.appendChat('System', `Unknown command: :${command}`);
    }
  }

  private showHelp(): void {
    this.chatBox.setContent(
      [
        '{bold}Commands:',
        '  :help          - Show this help',
        '  :syllabus      - Show course syllabus',
        '  :lesson next   - Advance to next lesson',
        '  :lesson open <id> - Open specific lesson',
        '  :search <query> - Search course materials',
        '  :context       - Show current context',
        '  :quit          - Exit',
      ].join('\n')
    );
  }

  private showSyllabus(): void {
    // TODO: Read syllabus.md and display
    this.chatBox.setContent('{bold}Syllabus\n\n(not implemented yet)');
  }

  private async nextLesson(): Promise<void> {
    this.chatBox.setContent('Advancing to next lesson... (not implemented yet)');
  }

  private async openLesson(lessonId: string): Promise<void> {
    this.chatBox.setContent(`Opening lesson ${lessonId}... (not implemented yet)`);
  }

  private async search(query: string): Promise<void> {
    // Perform search and show results in context pane
    const results = this.orchestrator['retrieval'].search(query, { topK: 5 });
    this.currentContext = results;
    this.showContext();
  }

  private showContext(): void {
    const lines = ['{bold}Current Context:', ''];
    for (const r of this.currentContext) {
      lines.push(
        `{cyan-fg}${r.chunkKind}{/} - ${r.heading || 'untitled'}`
      );
      lines.push(r.contentPreview.substring(0, 200));
      lines.push('---');
    }
    this.contextBox.setContent(lines.join('\n'));
  }

  private appendChat(speaker: string, message: string): void {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `{bold}${speaker}${timestamp ? ` [${timestamp}]` : ''}:{/}`;
    const current = this.chatBox.getContent() || '';
    this.chatBox.setContent(`${current}\n${prefix} ${message}`);
    this.chatBox.setScrollPerc(100); // Auto-scroll to bottom
    this.chatBox.screen.render();
  }

  start(): void {
    this.screen.render();
  }
}
