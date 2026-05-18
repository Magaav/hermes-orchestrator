import { filterCommands, DEFAULT_CHAT_COMMANDS } from "./chat-commands.js";
import { renderTokensToHtml } from "./chat-renderer.js";
import { getSlashCommandContext, tokenizeChatMarkdown } from "./chat-tokenizer.js";

function count(tokens, type) {
  let total = 0;
  for (const token of tokens || []) {
    if (token.type === type) total += 1;
    if (token.children) total += count(token.children, type);
  }
  return total;
}

function first(tokens, type) {
  for (const token of tokens || []) {
    if (token.type === type) return token;
    const child = first(token.children, type);
    if (child) return child;
  }
  return null;
}

function htmlFor(raw) {
  return renderTokensToHtml(tokenizeChatMarkdown(raw));
}

function assert(condition, message) {
  if (!condition) throw new Error(message || "Assertion failed");
}

function assertToken(raw, type, expectedValue) {
  const token = first(tokenizeChatMarkdown(raw), type);
  assert(token, `${raw} should include ${type}`);
  if (expectedValue !== undefined) assert(token.value === expectedValue, `${type} value should be ${expectedValue}`);
}

export const CHAT_COMPOSER_TEST_CASES = [
  {
    id: "inline-code-immediate",
    name: "`test` renders immediately without trailing space",
    run() {
      assertToken("`test`", "inline_code", "test");
      assert(htmlFor("`test`").includes("<code>test</code>"), "inline code html missing");
    },
  },
  {
    id: "inline-code-adjacent",
    name: "Adjacent inline code spans preserve source",
    run() {
      const tokens = tokenizeChatMarkdown("`test``hello`");
      assert(count(tokens, "inline_code") === 2, "expected two inline code spans");
      assert(tokens.map((token) => token.raw).join("") === "`test``hello`", "raw tokens changed");
    },
  },
  {
    id: "empty-inline-code",
    name: "Empty inline code stays stable",
    run() {
      assertToken("``", "inline_code", "");
      assert(htmlFor("``").includes("<code></code>"), "empty inline code should render safely");
    },
  },
  {
    id: "unclosed-inline-code",
    name: "Unclosed inline code remains plain",
    run() {
      assert(count(tokenizeChatMarkdown("`test"), "inline_code") === 0, "unclosed start rendered");
      assert(count(tokenizeChatMarkdown("test`"), "inline_code") === 0, "unclosed end rendered");
    },
  },
  {
    id: "unicode-inline-code",
    name: "Inline code preserves unicode and emoji",
    run() {
      assertToken("`áéíçã 日本語 emoji 🚀`", "inline_code", "áéíçã 日本語 emoji 🚀");
    },
  },
  {
    id: "code-block-single-line",
    name: "Single-line code block renders without trailing space",
    run() {
      assertToken("```test```", "code_block", "test");
      assert(htmlFor("```test```").includes("<pre><code>test</code></pre>"), "code block html missing");
    },
  },
  {
    id: "code-block-multiline",
    name: "Multiline code block preserves whitespace",
    run() {
      assertToken("```\n  a\n\nb\n```", "code_block", "\n  a\n\nb\n");
    },
  },
  {
    id: "code-block-literal-markers",
    name: "Formatting and links inside code blocks are literal",
    run() {
      const tokens = tokenizeChatMarkdown("```**x** https://example.com `y` ```");
      assert(count(tokens, "code_block") === 1, "code block missing");
      assert(count(tokens, "bold") === 0, "bold parsed inside code block");
      assert(count(tokens, "link") === 0, "link parsed inside code block");
    },
  },
  {
    id: "unclosed-code-block",
    name: "Unclosed code block is plain and safe",
    run() {
      const tokens = tokenizeChatMarkdown("```test");
      assert(count(tokens, "code_block") === 0, "unclosed code block rendered");
      assert(tokens.map((token) => token.raw).join("") === "```test", "unclosed raw changed");
    },
  },
  {
    id: "bold-italic-strike",
    name: "Bold, italic, and strike render immediately",
    run() {
      const tokens = tokenizeChatMarkdown("**bold** *italic* ~~strike~~");
      assert(count(tokens, "bold") === 1, "bold missing");
      assert(count(tokens, "italic") === 1, "italic missing");
      assert(count(tokens, "strike") === 1, "strike missing");
    },
  },
  {
    id: "unclosed-formatting",
    name: "Unclosed formatting remains safe",
    run() {
      assert(count(tokenizeChatMarkdown("**bold"), "bold") === 0, "unclosed bold rendered");
      assert(count(tokenizeChatMarkdown("*italic"), "italic") === 0, "unclosed italic rendered");
      assert(count(tokenizeChatMarkdown("~~strike"), "strike") === 0, "unclosed strike rendered");
    },
  },
  {
    id: "mixed-adjacent",
    name: "Mixed adjacent syntax does not move text",
    run() {
      const raw = "`code`**bold** plain`code`plain";
      assert(tokenizeChatMarkdown(raw).map((token) => token.raw).join("") === raw, "raw token stream changed");
    },
  },
  {
    id: "quote-line-start",
    name: "Quote only triggers at line start",
    run() {
      assert(count(tokenizeChatMarkdown("> quote"), "quote_line") === 1, "line-start quote missing");
      assert(count(tokenizeChatMarkdown("x > quote"), "quote_line") === 0, "middle quote rendered");
    },
  },
  {
    id: "quote-inline-code",
    name: "Inline code inside quote is safe",
    run() {
      const quote = first(tokenizeChatMarkdown("> `code`"), "quote_line");
      assert(quote && count(quote.children, "inline_code") === 1, "quote inline code missing");
    },
  },
  {
    id: "heading-block-render",
    name: "Markdown headings render as headings",
    run() {
      const html = htmlFor("## Topic\nPlain text");
      assert(count(tokenizeChatMarkdown("## Topic"), "heading") === 1, "heading token missing");
      assert(html.includes("<h2>Topic</h2>"), "h2 html missing");
      assert(!html.includes("## Topic"), "raw heading marker leaked");
    },
  },
  {
    id: "gfm-table-render",
    name: "GitHub-style pipe tables render as tables",
    run() {
      const raw = "| Name | Status |\n| --- | :---: |\n| **Test1** | ready |";
      const tokens = tokenizeChatMarkdown(raw);
      const table = first(tokens, "table");
      assert(table?.headers?.length === 2, "table headers missing");
      assert(table?.rows?.length === 1, "table row missing");
      assert(tokens.map((token) => token.raw).join("") === raw, "table raw source changed");
      const html = htmlFor(raw);
      assert(html.includes('<div class="agent-markdown-table-wrap"><table>'), "table wrapper missing");
      assert(html.includes("<th>Name</th>"), "table header missing");
      assert(html.includes('style="text-align: center"'), "alignment missing");
      assert(html.includes("<strong>Test1</strong>"), "inline markdown in table cell missing");
      assert(!html.includes("| --- |"), "raw separator leaked");
    },
  },
  {
    id: "https-link",
    name: "https linkifies",
    run() {
      assertToken("https://blablabla.com", "link", "https://blablabla.com");
    },
  },
  {
    id: "http-link",
    name: "http linkifies",
    run() {
      assertToken("http://blablabla.com", "link", "http://blablabla.com");
    },
  },
  {
    id: "bare-domain-link",
    name: "Bare domains use https href",
    run() {
      const token = first(tokenizeChatMarkdown("blablabla.com"), "link");
      assert(token?.href === "https://blablabla.com", "bare domain href wrong");
    },
  },
  {
    id: "www-domain-link",
    name: "www bare domains linkify",
    run() {
      const token = first(tokenizeChatMarkdown("www.blablabla.com"), "link");
      assert(token?.href === "https://www.blablabla.com", "www href wrong");
    },
  },
  {
    id: "subdomain-path-link",
    name: "Subdomain path query and hash linkify",
    run() {
      assertToken("sub.blablabla.com/path?x=1#top", "link", "sub.blablabla.com/path?x=1#top");
    },
  },
  {
    id: "trailing-period",
    name: "Trailing period stays outside link",
    run() {
      const tokens = tokenizeChatMarkdown("blablabla.com.");
      assert(first(tokens, "link")?.value === "blablabla.com", "period included");
      assert(tokens.at(-1)?.raw === ".", "period missing");
    },
  },
  {
    id: "trailing-paren",
    name: "Trailing parenthesis stays outside link",
    run() {
      const tokens = tokenizeChatMarkdown("(blablabla.com)");
      assert(first(tokens, "link")?.value === "blablabla.com", "paren included");
      assert(tokens[0].raw === "(", "opening paren missing");
      assert(tokens.at(-1).raw === ")", "closing paren missing");
    },
  },
  {
    id: "links-not-in-code",
    name: "Links inside inline code are not clickable",
    run() {
      assert(count(tokenizeChatMarkdown("`https://blablabla.com`"), "link") === 0, "link parsed in inline code");
    },
  },
  {
    id: "unsafe-protocols",
    name: "Unsafe protocols are not clickable",
    run() {
      for (const raw of ["javascript:alert(1)", "data:text/html,<script>", "vbscript:msgbox", "file:///etc/passwd"]) {
        assert(count(tokenizeChatMarkdown(raw), "link") === 0, `${raw} linkified`);
      }
    },
  },
  {
    id: "no-email-link",
    name: "Emails are not linkified",
    run() {
      assert(count(tokenizeChatMarkdown("person@example.com"), "link") === 0, "email linkified");
    },
  },
  {
    id: "raw-html-escaped",
    name: "Raw HTML is escaped",
    run() {
      const html = htmlFor('<img src=x onerror=alert(1)><script>alert(1)</script>');
      assert(!html.includes("<script>"), "script tag survived");
      assert(!html.includes("<img"), "image tag survived");
      assert(html.includes("&lt;script&gt;"), "script was not escaped");
    },
  },
  {
    id: "slash-root",
    name: "Slash at position zero opens command palette",
    run() {
      assert(getSlashCommandContext("/", 1, 1).active, "slash context inactive");
    },
  },
  {
    id: "slash-filter",
    name: "/g filters to /goal",
    run() {
      const context = getSlashCommandContext("/g", 2, 2);
      assert(context.active && context.query === "g", "slash query wrong");
      const filtered = filterCommands(DEFAULT_CHAT_COMMANDS, context.query);
      assert(filtered.length === 1 && filtered[0].name === "/goal", "filter wrong");
    },
  },
  {
    id: "slash-in-sentence",
    name: "Slash inside a sentence does not open",
    run() {
      assert(!getSlashCommandContext("look at /tmp/file", 10, 10).active, "sentence slash opened");
    },
  },
  {
    id: "slash-after-space",
    name: "Palette closes after command prefix",
    run() {
      assert(!getSlashCommandContext("/goal ", 6, 6).active, "slash stayed open after space");
    },
  },
  {
    id: "deterministic",
    name: "Tokenizer is deterministic",
    run() {
      const raw = "hello `code` **bold** https://example.com.";
      assert(JSON.stringify(tokenizeChatMarkdown(raw)) === JSON.stringify(tokenizeChatMarkdown(raw)), "tokenizer changed");
    },
  },
  {
    id: "fuzz-never-throws",
    name: "Fuzz strings never throw",
    run() {
      const samples = [
        "`".repeat(101),
        "*".repeat(101),
        "~".repeat(101),
        "混合 🚀 ** ` ~~ https://x.y/".repeat(30),
      ];
      for (const sample of samples) tokenizeChatMarkdown(sample);
    },
  },
  {
    id: "long-message",
    name: "Long messages remain tokenizable",
    run() {
      const raw = `${"hello example.com ".repeat(500)}\n\`code\``;
      const tokens = tokenizeChatMarkdown(raw);
      assert(tokens.length > 100, "long message collapsed unexpectedly");
    },
  },
];

export function runChatComposerTests() {
  return CHAT_COMPOSER_TEST_CASES.map((test) => {
    const startedAt = performance.now?.() || Date.now();
    try {
      test.run();
      return {
        id: test.id,
        name: test.name,
        ok: true,
        durationMs: (performance.now?.() || Date.now()) - startedAt,
      };
    } catch (error) {
      return {
        id: test.id,
        name: test.name,
        ok: false,
        error: error.message || String(error),
        durationMs: (performance.now?.() || Date.now()) - startedAt,
      };
    }
  });
}
