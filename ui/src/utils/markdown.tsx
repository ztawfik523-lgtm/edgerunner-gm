import { memo, useMemo } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { toJsxRuntime, type Components } from "hast-util-to-jsx-runtime";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import remend from "remend";
import { unified } from "unified";

// Model output is untrusted: raw HTML is dropped by remark-rehype (allowDangerousHtml
// is off), rehype-sanitize restricts tags/attributes and link protocols (no
// javascript:), and <img> is removed entirely so replies cannot load remote images.
const SANITIZE_SCHEMA = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames ?? []).filter((tag) => tag !== "img"),
};

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkRehype)
  .use(rehypeSanitize, SANITIZE_SCHEMA);

export type MarkdownComponents = Partial<Components>;

interface MarkdownProps {
  children: string;
  components?: MarkdownComponents;
  /** Close unterminated emphasis/links/code while text is still streaming in. */
  streaming?: boolean;
}

export const Markdown = memo(function Markdown({ children, components, streaming = false }: MarkdownProps) {
  return useMemo(() => {
    const source = streaming ? remend(children) : children;
    const tree = processor.runSync(processor.parse(source));
    return toJsxRuntime(tree, { Fragment, jsx, jsxs, components });
  }, [children, components, streaming]);
});
