import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Render user-supplied Markdown safely.
 * react-markdown builds React elements from the AST — no dangerouslySetInnerHTML,
 * no raw HTML allowed (default behavior), so XSS-by-uploaded-README is closed.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown-body text-zinc-800 dark:text-zinc-200 leading-7">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (props) => (
            <h1
              className="text-3xl font-medium tracking-tight mt-10 mb-4 first:mt-0"
              {...props}
            />
          ),
          h2: (props) => (
            <h2
              className="text-xl font-medium tracking-tight mt-9 mb-3 pb-1 border-b border-zinc-200 dark:border-zinc-800"
              {...props}
            />
          ),
          h3: (props) => (
            <h3
              className="text-base font-medium tracking-tight mt-6 mb-2"
              {...props}
            />
          ),
          p: (props) => <p className="my-4" {...props} />,
          ul: (props) => (
            <ul className="my-4 ml-6 list-disc space-y-1.5" {...props} />
          ),
          ol: (props) => (
            <ol className="my-4 ml-6 list-decimal space-y-1.5" {...props} />
          ),
          li: (props) => <li className="leading-7" {...props} />,
          a: ({ href, ...props }) => (
            <a
              href={href}
              className="text-fuchsia-600 dark:text-fuchsia-400 hover:underline"
              target={href?.startsWith("http") ? "_blank" : undefined}
              rel={href?.startsWith("http") ? "noreferrer" : undefined}
              {...props}
            />
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <code
                  className="block font-mono text-sm leading-relaxed"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code
                className="font-mono text-[0.875em] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800"
                {...props}
              >
                {children}
              </code>
            );
          },
          pre: (props) => (
            <pre
              className="my-5 p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 overflow-x-auto"
              {...props}
            />
          ),
          blockquote: (props) => (
            <blockquote
              className="my-4 pl-4 border-l-2 border-zinc-300 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400"
              {...props}
            />
          ),
          hr: () => <hr className="my-8 border-zinc-200 dark:border-zinc-800" />,
          table: (props) => (
            <div className="my-5 overflow-x-auto">
              <table
                className="w-full border-collapse text-sm"
                {...props}
              />
            </div>
          ),
          th: (props) => (
            <th
              className="text-left font-medium px-3 py-2 border-b border-zinc-300 dark:border-zinc-700"
              {...props}
            />
          ),
          td: (props) => (
            <td
              className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800"
              {...props}
            />
          ),
          img: (props) => (
            <img
              loading="lazy"
              className="my-5 rounded-lg border border-zinc-200 dark:border-zinc-800"
              {...props}
            />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
