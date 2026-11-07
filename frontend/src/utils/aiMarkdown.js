// AI 回答的 Markdown 渲染（9.8.1）
//
// 为什么自己写而不装 marked/markdown-it：
// 1. 只需要模型回答里出现的那几种结构（标题、列表、引用、表格、加粗），
//    完整 Markdown 解析器反而会把 HTML 原样透传，必须再叠一层 sanitizer；
// 2. 这里**先转义再加标签**，任何输出都不含模型自带的标签，v-html 是安全的；
// 3. 需要把 `[n]` 变成可点击锚点（9.8.2），自定义解析器改起来比插件链简单。

const HTML_ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch])
}

const CODE_TOKEN = '\u0000'
// 模型偶尔写成【1】，与后端 extract_used_refs 的识别口径保持一致
const CITATION = /[\[【]\s*(\d{1,2})\s*[\]】]/g
const BOLD = /\*\*([^*\n]+)\*\*/g
const ITALIC = /(^|[^*])\*([^*\n]+)\*(?!\*)/g
const INLINE_CODE = /`([^`\n]+)`/g

/**
 * 行内渲染：行内代码 → 转义 → 加粗/斜体 → 引用锚点 → 还原行内代码。
 *
 * 行内代码先摘出来（换成占位符），否则 `` `a*b*c` `` 里的星号会被当成斜体。
 */
export function renderInline(raw) {
  const codes = []
  let text = String(raw ?? '').replace(INLINE_CODE, (_, code) => {
    codes.push(code)
    return `${CODE_TOKEN}${codes.length - 1}${CODE_TOKEN}`
  })

  text = escapeHtml(text)
  text = text.replace(BOLD, '<strong>$1</strong>')
  text = text.replace(ITALIC, '$1<em>$2</em>')

  // [1] → 可点击锚点。只认 1~2 位数字，避免把 [2026] 这类年份当成引用。
  text = text.replace(
    CITATION,
    (_, index) => `<span class="cite" data-cite="${index}">${index}</span>`,
  )

  if (codes.length) {
    text = text.replace(new RegExp(`${CODE_TOKEN}(\\d+)${CODE_TOKEN}`, 'g'), (_, i) => {
      return `<code>${escapeHtml(codes[Number(i)])}</code>`
    })
  }
  return text
}

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableSeparator(line) {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(line)
}

function renderTable(rows) {
  const head = splitRow(rows[0])
  const body = rows.slice(2).map(splitRow)
  const thead = `<thead><tr>${head.map((c) => `<th>${renderInline(c)}</th>`).join('')}</tr></thead>`
  const tbody = body.length
    ? `<tbody>${body
        .map((cells) => `<tr>${cells.map((c) => `<td>${renderInline(c)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
    : ''
  return `<table>${thead}${tbody}</table>`
}

/**
 * 把模型输出的 Markdown 转成 HTML 字符串。
 *
 * 解析按行进行、状态机驱动，遇到不完整语法（流式输出的中间态）就退化成普通
 * 段落，不会吞掉后文——流式渲染时几乎每一帧都存在未闭合的 `**` 或列表。
 */
export function renderMarkdown(source) {
  if (!source) return ''
  const lines = String(source).replace(/\r\n?/g, '\n').split('\n')
  const out = []
  let paragraph = []
  let listType = null
  let inCode = false
  let codeLines = []

  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }
  const flushParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${paragraph.map(renderInline).join('<br>')}</p>`)
      paragraph = []
    }
  }
  const flush = () => {
    flushParagraph()
    closeList()
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]

    // 代码块：内部原样保留，只做转义
    if (/^\s*```/.test(line)) {
      if (inCode) {
        out.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
        codeLines = []
        inCode = false
      } else {
        flush()
        inCode = true
      }
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }

    if (!line.trim()) {
      flush()
      continue
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      const level = Math.min(heading[1].length + 1, 5)
      out.push(`<h${level}>${renderInline(heading[2].trim())}</h${level}>`)
      continue
    }

    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      flush()
      out.push('<hr>')
      continue
    }

    const quote = /^\s*>\s?(.*)$/.exec(line)
    if (quote) {
      flushParagraph()
      closeList()
      out.push(`<blockquote>${renderInline(quote[1])}</blockquote>`)
      continue
    }

    // 表格：当前行含竖线且下一行是分隔行
    if (line.includes('|') && isTableSeparator(lines[i + 1] || '')) {
      flush()
      const rows = [line, lines[i + 1]]
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(lines[i])
        i += 1
      }
      i -= 1
      out.push(renderTable(rows))
      continue
    }

    const ordered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line)
    if (ordered) {
      flushParagraph()
      if (listType !== 'ol') {
        closeList()
        out.push('<ol>')
        listType = 'ol'
      }
      out.push(`<li>${renderInline(ordered[2])}</li>`)
      continue
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line)
    if (bullet) {
      flushParagraph()
      if (listType !== 'ul') {
        closeList()
        out.push('<ul>')
        listType = 'ul'
      }
      out.push(`<li>${renderInline(bullet[1])}</li>`)
      continue
    }

    closeList()
    paragraph.push(line.trim())
  }

  if (inCode) {
    // 流式过程中代码块还没闭合：先按已到达的内容渲染，避免整段消失
    out.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
  }
  flush()
  return out.join('')
}

/** 纯文本预览（会话列表、复制降级用）。 */
export function toPlainText(source) {
  return String(source ?? '')
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[a-zA-Z]*/g, ''))
    .replace(/[*_`>#]/g, '')
    .replace(/[\[【]\s*\d{1,2}\s*[\]】]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
